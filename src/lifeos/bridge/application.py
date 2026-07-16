"""Allowlisted bridge dispatcher backed by typed Python services."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from datetime import date
from pathlib import Path
from typing import Any, Callable

from lifeos.attention import evaluate_attention, save_preference
from lifeos.copilot import (
    CopilotContractError,
    PlanningContextError,
    PlanningSessionError,
    PlanningSessionService,
    PlanOptionError,
    build_copilot_index,
    decompose_plan_option,
    DecompositionError,
    build_planning_context,
    generate_plan_options,
    parse_goal_note,
    SessionConflictError,
    inspect_copilot_note,
    CapacityError,
    RecurringWorkload,
    check_portfolio_capacity,
)
from lifeos.facade.copilot_tools import (
    CopilotContextRequest,
    CopilotReadinessRequest,
    inspect_goal_readiness,
    preview_goal_context,
)
from lifeos.bridge.protocol import CAPABILITIES, ENGINE_VERSION, PROTOCOL_VERSION, ProtocolError, strict_object
from lifeos.daily import (
    CheckInRequest,
    DailyInteractionError,
    DailyInteractionService,
    QuickCaptureRequest,
    ReviewNoteRequest,
    TaskOutcomeRequest,
)

from lifeos.daily.today import TodayInputs, build_today_dashboard
from lifeos.study import StudySessionService
from lifeos.reviews import build_review_workflow, save_progress, save_review_note
from lifeos.desktop import DesktopProposalService
from lifeos.config import FeatureFlags, LifeOSConfig
from lifeos.registry import Registry
from lifeos.status import collect_status
from lifeos.versioning import DESKTOP_RUNTIME_SCHEMA_VERSION
from lifeos.vault import VaultAccessError, read_vault_markdown
from lifeos.planning import load_plan_actions
from lifeos.scheduler import BackgroundServiceInstaller, ScheduleConfig, load_schedule, save_schedule
from lifeos.feedback import (
    FeedbackControlService,
    FeedbackProposalRequest,
    OutcomeCorrection,
    PreferencesUpdate,
    ReplayContext,
    apply_preferences,
    build_adaptive_menu,
    calibrate_duration,
    create_feedback_proposal,
    diagnose_repeated_avoidance,
    explain_adaptive_result,
    rebuild_evidence_dataset,
    replay_history,
    summarize_capacity_fit,
)

NotificationSink = Callable[[dict[str, Any]], None]


def _iso_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ProtocolError("invalid_params", f"{field} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProtocolError("invalid_params", f"{field} must be an ISO date.") from exc


class BridgeApplication:
    def __init__(self, *, vault_root: Path, runtime_dir: Path, actor_id: str, notify: NotificationSink | None = None) -> None:
        self.actor_id = actor_id.strip()
        if not self.actor_id:
            raise ProtocolError("invalid_actor", "A local actor ID is required.")
        self.daily = DailyInteractionService(vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id)
        self.study_sessions = StudySessionService(vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id)
        self.proposals = DesktopProposalService(vault_root=vault_root, actor_id=self.actor_id)
        self.planning_sessions = PlanningSessionService(
            vault_root=vault_root, runtime_dir=runtime_dir
        )
        self.feedback_controls = FeedbackControlService(vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id)
        self.config = LifeOSConfig(vault_root, runtime_dir, FeatureFlags(graphify=True, exports=True))
        self._notify = notify
        self._cancelled: set[str] = set()
        self.shutdown_requested = False

    def _feedback_context(self, as_of: date):
        preferences = self.feedback_controls.load()
        dataset, status = rebuild_evidence_dataset(
            self.daily.vault_root,
            self.daily.runtime_dir,
            as_of=as_of,
            excluded_event_ids=preferences.excluded_event_ids,
        )
        observations = apply_preferences(dataset.observations, preferences)
        return preferences, dataset, status, observations

    def dispatch(self, method: str, params: object) -> object:
        if method == "copilot.capacity.check":
            data = strict_object(
                params,
                allowed={"session_id", "option_id", "as_of", "available_minutes", "recurring_workloads", "adaptive_durations"},
                required={"session_id", "option_id", "as_of"},
            )
            as_of = _iso_date(data["as_of"], "as_of")
            available = data.get("available_minutes")
            if available is not None and (type(available) is not int or available < 0):
                raise ProtocolError("invalid_params", "available_minutes must be non-negative or null.")
            raw_workloads = data.get("recurring_workloads", [])
            if not isinstance(raw_workloads, list) or not all(isinstance(item, dict) for item in raw_workloads):
                raise ProtocolError("invalid_params", "recurring_workloads must be a list of objects.")
            try:
                workloads = tuple(RecurringWorkload(**strict_object(
                    item,
                    allowed={"workload_id", "title", "minutes", "kind", "protected", "source_ref"},
                    required={"workload_id", "title", "minutes"},
                )) for item in raw_workloads)
            except (TypeError, CapacityError, ProtocolError) as exc:
                raise ProtocolError("invalid_params", str(exc)) from exc
            adaptive = data.get("adaptive_durations")
            if adaptive is not None and (not isinstance(adaptive, dict) or not all(isinstance(key, str) for key in adaptive)):
                raise ProtocolError("invalid_params", "adaptive_durations must be an object keyed by task ID.")
            try:
                snapshot = self.planning_sessions.get(data["session_id"])
                session = snapshot.envelope.session
                source = read_vault_markdown(self.daily.vault_root, session.goal_ref)
                goal = parse_goal_note(path=session.goal_ref, content=source.content)
                index = build_copilot_index(self.daily.vault_root)
                context = build_planning_context(
                    vault_root=self.daily.vault_root, goal=goal, index=index,
                    include_paths=session.selected_context_refs, exclude_paths=session.excluded_context_refs,
                )
                options = generate_plan_options(
                    goal=goal, session=session, readiness=snapshot.envelope.readiness,
                    context=context, index=index, as_of=as_of,
                )
                option = next((item for item in options.options if item.option_id == data["option_id"]), None)
                if option is None:
                    raise CapacityError("selected option was not found")
                decomposition = decompose_plan_option(option=option, horizon=goal.horizon)
                return check_portfolio_capacity(
                    option=option, decomposition=decomposition, index=index, as_of=as_of,
                    available_minutes=available, recurring_workloads=workloads,
                    adaptive_durations=adaptive,
                ).to_dict()
            except (
                CapacityError, DecompositionError, PlanOptionError, PlanningSessionError,
                CopilotContractError, PlanningContextError, VaultAccessError
            ) as exc:
                raise ProtocolError("copilot_capacity_invalid", str(exc)) from exc
        if method == "copilot.option.decompose":
            data = strict_object(
                params,
                allowed={"session_id", "option_id", "as_of", "existing_task_ids"},
                required={"session_id", "option_id", "as_of"},
            )
            existing = data.get("existing_task_ids", [])
            if not isinstance(existing, list) or not all(isinstance(item, str) for item in existing):
                raise ProtocolError("invalid_params", "existing_task_ids must be a list of strings.")
            as_of = _iso_date(data["as_of"], "as_of")
            try:
                snapshot = self.planning_sessions.get(data["session_id"])
                session = snapshot.envelope.session
                source = read_vault_markdown(self.daily.vault_root, session.goal_ref)
                goal = parse_goal_note(path=session.goal_ref, content=source.content)
                index = build_copilot_index(self.daily.vault_root)
                context = build_planning_context(
                    vault_root=self.daily.vault_root, goal=goal, index=index,
                    include_paths=session.selected_context_refs, exclude_paths=session.excluded_context_refs,
                )
                options = generate_plan_options(
                    goal=goal, session=session, readiness=snapshot.envelope.readiness,
                    context=context, index=index, as_of=as_of,
                )
                option = next((item for item in options.options if item.option_id == data["option_id"]), None)
                if option is None:
                    raise DecompositionError("selected option was not found")
                return decompose_plan_option(
                    option=option, horizon=goal.horizon, existing_task_ids=tuple(existing)
                ).to_dict()
            except (
                DecompositionError, PlanOptionError, PlanningSessionError, CopilotContractError,
                PlanningContextError, VaultAccessError
            ) as exc:
                raise ProtocolError("copilot_decomposition_invalid", str(exc)) from exc
        if method == "copilot.options.generate":
            data = strict_object(params, allowed={"session_id", "as_of"}, required={"session_id", "as_of"})
            as_of = _iso_date(data["as_of"], "as_of")
            try:
                snapshot = self.planning_sessions.get(data["session_id"])
                session = snapshot.envelope.session
                source = read_vault_markdown(self.daily.vault_root, session.goal_ref)
                goal = parse_goal_note(path=session.goal_ref, content=source.content)
                index = build_copilot_index(self.daily.vault_root)
                context = build_planning_context(
                    vault_root=self.daily.vault_root,
                    goal=goal,
                    index=index,
                    include_paths=session.selected_context_refs,
                    exclude_paths=session.excluded_context_refs,
                )
                return generate_plan_options(
                    goal=goal,
                    session=session,
                    readiness=snapshot.envelope.readiness,
                    context=context,
                    index=index,
                    as_of=as_of,
                ).to_dict()
            except (PlanOptionError, PlanningSessionError, CopilotContractError, PlanningContextError, VaultAccessError) as exc:
                raise ProtocolError("copilot_options_invalid", str(exc)) from exc
        if method == "copilot.session.start":
            data = strict_object(
                params,
                allowed={"goal_path", "session_id", "selected_context_refs", "excluded_context_refs"},
                required={"goal_path"},
            )
            for key in ("selected_context_refs", "excluded_context_refs"):
                if key in data:
                    value = data[key]
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                    data[key] = tuple(value)
            try:
                return self.planning_sessions.start(**data).to_dict()
            except (PlanningSessionError, CopilotContractError) as exc:
                raise ProtocolError("copilot_session_invalid", str(exc)) from exc
        if method == "copilot.session.get":
            data = strict_object(params, allowed={"session_id"}, required={"session_id"})
            try:
                return self.planning_sessions.get(data["session_id"]).to_dict()
            except PlanningSessionError as exc:
                raise ProtocolError("copilot_session_invalid", str(exc)) from exc
        if method == "copilot.session.answer":
            data = strict_object(
                params,
                allowed={"session_id", "question_id", "response_kind", "value", "expected_revision"},
                required={"session_id", "question_id", "response_kind", "expected_revision"},
            )
            try:
                return self.planning_sessions.answer(**data).to_dict()
            except SessionConflictError as exc:
                raise ProtocolError("copilot_session_stale", str(exc)) from exc
            except (PlanningSessionError, CopilotContractError) as exc:
                raise ProtocolError("copilot_session_invalid", str(exc)) from exc
        if method == "copilot.session.close":
            data = strict_object(
                params,
                allowed={"session_id", "outcome", "label", "rationale", "expected_revision"},
                required={"session_id", "outcome", "label", "expected_revision"},
            )
            try:
                return self.planning_sessions.close(**data).to_dict()
            except SessionConflictError as exc:
                raise ProtocolError("copilot_session_stale", str(exc)) from exc
            except (PlanningSessionError, CopilotContractError) as exc:
                raise ProtocolError("copilot_session_invalid", str(exc)) from exc
        if method == "copilot.goal.readiness":
            data = strict_object(params, allowed={"goal_path"}, required={"goal_path"})
            try:
                return inspect_goal_readiness(
                    vault_root=self.daily.vault_root,
                    request=CopilotReadinessRequest(goal_path=data["goal_path"]),
                ).to_dict()
            except (CopilotContractError, VaultAccessError) as exc:
                raise ProtocolError("copilot_readiness_invalid", str(exc)) from exc
        if method == "copilot.context.preview":
            data = strict_object(
                params,
                allowed={
                    "goal_path",
                    "include_paths",
                    "exclude_paths",
                    "redact_terms",
                    "allowed_sensitive_roots",
                    "max_total_bytes",
                    "max_item_bytes",
                },
                required={"goal_path"},
            )
            for key in ("include_paths", "exclude_paths", "redact_terms", "allowed_sensitive_roots"):
                if key in data:
                    value = data[key]
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                    data[key] = tuple(value)
            try:
                return preview_goal_context(
                    vault_root=self.daily.vault_root, request=CopilotContextRequest(**data)
                ).to_dict()
            except (CopilotContractError, PlanningContextError, VaultAccessError) as exc:
                raise ProtocolError("copilot_context_invalid", str(exc)) from exc
        if method == "copilot.note.inspect":
            data = strict_object(params, allowed={"path"}, required={"path"})
            path = data["path"]
            if not isinstance(path, str) or not path.strip():
                raise ProtocolError("invalid_params", "path must be a non-empty string.")
            try:
                return inspect_copilot_note(self.daily.vault_root, path)
            except CopilotContractError as exc:
                raise ProtocolError("copilot_contract_invalid", str(exc)) from exc
        if method == "system.handshake":
            data = strict_object(params, allowed={"protocol", "client_version"}, required={"protocol"})
            protocol = data["protocol"]
            if not isinstance(protocol, str) or protocol.split(".", 1)[0] != PROTOCOL_VERSION.split(".", 1)[0]:
                raise ProtocolError("protocol_mismatch", "The plugin and engine protocol versions are incompatible.", {"engine_protocol": PROTOCOL_VERSION})
            return {
                "protocol": PROTOCOL_VERSION,
                "engine_version": ENGINE_VERSION,
                "runtime_schema": DESKTOP_RUNTIME_SCHEMA_VERSION,
                "capabilities": list(CAPABILITIES),
                "actor_id": self.actor_id,
            }
        if method == "feedback.proposal.create":
            data = strict_object(params, allowed={"kind", "target_path", "evidence_fingerprint", "evidence_event_ids", "confidence", "expected_effect", "alternatives", "task_id", "changes", "decomposition_titles", "agent_requested"}, required={"kind", "target_path", "evidence_fingerprint", "evidence_event_ids", "confidence", "expected_effect", "alternatives"})
            for key in ("evidence_event_ids", "alternatives", "decomposition_titles"):
                if key in data:
                    value = data[key]
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                    data[key] = tuple(value)
            try:
                return asdict(create_feedback_proposal(vault_root=self.daily.vault_root, request=FeedbackProposalRequest(**data), actor_id=self.actor_id))
            except ValueError as exc:
                raise ProtocolError("feedback_proposal_invalid", str(exc)) from exc
        if method == "feedback.preferences.get":
            strict_object(params, allowed=set())
            return self.feedback_controls.load().to_dict()
        if method == "feedback.preferences.migrate":
            data = strict_object(params, allowed={"dry_run"})
            dry_run = data.get("dry_run", True)
            if not isinstance(dry_run, bool):
                raise ProtocolError("invalid_params", "dry_run must be true or false.")
            return self.feedback_controls.migrate(dry_run=dry_run).to_dict()
        if method == "feedback.preferences.update":
            data = strict_object(params, allowed={"idempotency_key", "expected_hash", "mode", "disabled_dimensions", "exclude_event_id", "include_event_id", "dismiss_diagnosis_id", "dismiss_fingerprint", "restore_diagnosis_id", "reset_before", "reset_reason"}, required={"idempotency_key"})
            if "disabled_dimensions" in data:
                value = data["disabled_dimensions"]
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ProtocolError("invalid_params", "disabled_dimensions must be a list of strings.")
                data["disabled_dimensions"] = tuple(value)
            if data.get("reset_before") is not None:
                data["reset_before"] = _iso_date(data["reset_before"], "reset_before")
            return self.feedback_controls.update(PreferencesUpdate(**data)).to_dict()
        if method == "feedback.outcome.correct":
            data = strict_object(params, allowed={"idempotency_key", "plan_path", "corrects_event_id", "outcome", "day", "expected_hash", "actual_minutes", "completion_fraction", "reason"}, required={"idempotency_key", "plan_path", "corrects_event_id", "outcome", "day", "expected_hash"})
            data["day"] = _iso_date(data["day"], "day")
            return self.feedback_controls.correct_outcome(OutcomeCorrection(**data))
        if method == "feedback.reset":
            strict_object(params, allowed=set())
            return {"removed": self.feedback_controls.reset_derived()}
        if method == "feedback.replay":
            data = strict_object(
                params,
                allowed={"contexts", "mode", "disabled_dimensions"},
                required={"contexts"},
            )
            raw_contexts = data.pop("contexts")
            if not isinstance(raw_contexts, list):
                raise ProtocolError("invalid_params", "contexts must be a list.")
            contexts = []
            for raw in raw_contexts:
                context = strict_object(
                    raw,
                    allowed={
                        "day",
                        "available_minutes",
                        "energy",
                        "motivation",
                        "mode_filter",
                        "time_window",
                    },
                    required={"day"},
                )
                context["day"] = _iso_date(context["day"], "day")
                contexts.append(ReplayContext(**context))
            disabled = data.pop("disabled_dimensions", None)
            if disabled is not None and (
                not isinstance(disabled, list)
                or not all(isinstance(item, str) for item in disabled)
            ):
                raise ProtocolError(
                    "invalid_params", "disabled_dimensions must be a list of strings."
                )
            as_of = max((item.day for item in contexts), default=date.today())
            preferences, _, _, observations = self._feedback_context(as_of)
            return replay_history(
                actions=load_plan_actions(self.daily.vault_root),
                observations=observations,
                contexts=contexts,
                mode=data.get("mode", preferences.mode),
                disabled_dimensions=(
                    tuple(disabled)
                    if disabled is not None
                    else preferences.disabled_dimensions
                ),
                dismissed_diagnosis_fingerprints=preferences.dismissed_fingerprints(),
            ).to_dict()
        if method == "feedback.explain":
            data = strict_object(params, allowed={"task_id", "as_of", "available_minutes", "energy", "motivation", "mode_filter", "adaptive_mode", "time_window", "disabled_dimensions"}, required={"task_id", "as_of", "available_minutes", "energy", "motivation"})
            task_id = data.pop("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise ProtocolError("invalid_params", "task_id must be a non-empty string.")
            as_of = _iso_date(data.pop("as_of"), "as_of")
            disabled = data.pop("disabled_dimensions", ())
            if not isinstance(disabled, list) or not all(isinstance(item, str) for item in disabled):
                raise ProtocolError("invalid_params", "disabled_dimensions must be a list of strings.")
            actions = load_plan_actions(self.daily.vault_root)
            preferences, _, _, observations = self._feedback_context(as_of)
            if not disabled:
                disabled = preferences.disabled_dimensions
            data.setdefault("adaptive_mode", preferences.mode)
            result = build_adaptive_menu(
                actions=actions,
                observations=observations,
                as_of=as_of,
                disabled_dimensions=tuple(disabled),
                dismissed_diagnosis_fingerprints=preferences.dismissed_fingerprints(),
                **data,
            )
            try:
                return explain_adaptive_result(result=result, actions=actions, task_id=task_id).to_dict()
            except KeyError as exc:
                raise ProtocolError("not_found", str(exc)) from exc
        if method == "feedback.plan":
            data = strict_object(params, allowed={"as_of", "available_minutes", "energy", "motivation", "mode_filter", "adaptive_mode", "time_window", "disabled_dimensions"}, required={"as_of", "available_minutes", "energy", "motivation"})
            as_of = _iso_date(data.pop("as_of"), "as_of")
            disabled = data.pop("disabled_dimensions", ())
            if not isinstance(disabled, list) or not all(isinstance(item, str) for item in disabled):
                raise ProtocolError("invalid_params", "disabled_dimensions must be a list of strings.")
            preferences, _, _, observations = self._feedback_context(as_of)
            if not disabled:
                disabled = preferences.disabled_dimensions
            data.setdefault("adaptive_mode", preferences.mode)
            return build_adaptive_menu(
                actions=load_plan_actions(self.daily.vault_root),
                observations=observations,
                as_of=as_of,
                disabled_dimensions=tuple(disabled),
                dismissed_diagnosis_fingerprints=preferences.dismissed_fingerprints(),
                **data,
            ).to_dict()
        if method == "feedback.avoidance":
            data = strict_object(params, allowed={"as_of", "minimum_repetitions", "recency_days", "dismissed_fingerprints"}, required={"as_of"})
            as_of = _iso_date(data.pop("as_of"), "as_of")
            dismissed = data.pop("dismissed_fingerprints", ())
            if not isinstance(dismissed, list) or not all(isinstance(item, str) for item in dismissed):
                raise ProtocolError("invalid_params", "dismissed_fingerprints must be a list of strings.")
            preferences, _, _, observations = self._feedback_context(as_of)
            if not dismissed:
                dismissed = preferences.dismissed_fingerprints()
            return [
                item.to_dict()
                for item in diagnose_repeated_avoidance(
                    observations=observations,
                    as_of=as_of,
                    dismissed_fingerprints=tuple(dismissed),
                    **data,
                )
            ]
        if method == "feedback.capacity":
            data = strict_object(params, allowed={"task_id", "current_energy", "current_motivation", "mode", "declared_minutes", "time_window", "blocked", "as_of", "disabled_dimensions"}, required={"task_id", "as_of"})
            as_of = _iso_date(data.pop("as_of"), "as_of")
            disabled = data.pop("disabled_dimensions", ())
            if not isinstance(disabled, list) or not all(isinstance(item, str) for item in disabled):
                raise ProtocolError("invalid_params", "disabled_dimensions must be a list of strings.")
            preferences, _, _, observations = self._feedback_context(as_of)
            if not disabled:
                disabled = preferences.disabled_dimensions
            return summarize_capacity_fit(
                observations=observations,
                as_of=as_of,
                disabled_dimensions=tuple(disabled),
                **data,
            ).to_dict()
        if method == "feedback.duration":
            data = strict_object(params, allowed={"task_id", "declared_minutes", "task_shape", "plan_id", "mode", "as_of", "enabled"}, required={"task_id", "declared_minutes", "as_of"})
            as_of = _iso_date(data.pop("as_of"), "as_of")
            _, _, _, observations = self._feedback_context(as_of)
            return calibrate_duration(
                observations=observations, as_of=as_of, **data
            ).to_dict()
        if method in {"feedback.dataset.status", "feedback.dataset.rebuild"}:
            data = strict_object(params, allowed={"as_of"})
            as_of = _iso_date(data["as_of"], "as_of") if "as_of" in data else date.today()
            preferences, dataset, status, observations = self._feedback_context(as_of)
            payload = dataset.to_dict()
            payload["observations"] = tuple(item.to_dict() for item in observations)
            payload["preferences"] = preferences.to_dict()
            return {"status": status.to_dict(), "dataset": payload}
        if method == "scheduler.config.get":
            strict_object(params, allowed=set())
            return asdict(load_schedule(self.daily.vault_root))
        if method == "scheduler.config.set":
            data = strict_object(params, allowed={"enabled", "timezone", "morning", "evening", "weekly_day", "weekly", "quiet_start", "quiet_end", "privacy", "grace_hours"})
            config = ScheduleConfig(**data)
            save_schedule(self.daily.vault_root, config)
            return asdict(config)
        if method == "scheduler.service.status":
            strict_object(params, allowed=set())
            return BackgroundServiceInstaller(self.daily.runtime_dir).status()
        if method == "scheduler.service.install":
            data = strict_object(params, allowed={"command"}, required={"command"})
            if not isinstance(data["command"], list) or not all(isinstance(item, str) for item in data["command"]):
                raise ProtocolError("invalid_params", "command must be a list of strings.")
            path = BackgroundServiceInstaller(self.daily.runtime_dir).install(command=tuple(data["command"]))
            return {"installed": True, "descriptor": path.name}
        if method == "scheduler.service.uninstall":
            strict_object(params, allowed=set())
            BackgroundServiceInstaller(self.daily.runtime_dir).uninstall()
            return {"installed": False}
        if method == "proposal.list":
            strict_object(params, allowed=set())
            return [item.to_dict() for item in self.proposals.list()]
        if method == "proposal.inspect":
            data = strict_object(params, allowed={"proposal_id"}, required={"proposal_id"})
            return self.proposals.inspect(data["proposal_id"]).to_dict()
        if method == "proposal.prepare":
            data = strict_object(params, allowed={"proposal_id", "action"}, required={"proposal_id", "action"})
            return asdict(self.proposals.prepare(**data))
        if method == "proposal.execute":
            data = strict_object(params, allowed={"proposal_id", "action", "token", "reason"}, required={"proposal_id", "action", "token"})
            return self.proposals.execute(**data)
        if method == "system.status":
            strict_object(params, allowed=set())
            return asdict(collect_status(self.config, Registry(self.daily.runtime_dir / "registry.db")))
        if method == "review.build":
            data = strict_object(params, allowed={"kind", "day"}, required={"kind", "day"})
            data["day"] = _iso_date(data["day"], "day")
            return build_review_workflow(vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir, **data).to_dict()
        if method == "review.progress":
            data = strict_object(params, allowed={"review_id", "completed_sections", "skipped_sections", "current_section"}, required={"review_id"})
            for key in ("completed_sections", "skipped_sections"):
                if key in data:
                    value = data[key]
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                    data[key] = tuple(value)
            return asdict(save_progress(self.daily.runtime_dir, **data))
        if method == "review.save":
            data = strict_object(params, allowed={"kind", "day", "idempotency_key", "expected_hash"}, required={"kind", "day", "idempotency_key"})
            day_value = _iso_date(data.pop("day"), "day")
            workflow = build_review_workflow(vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir, kind=data.pop("kind"), day=day_value)
            return save_review_note(vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir, actor_id=self.actor_id, workflow=workflow, **data)
        if method == "study.plan":
            data = strict_object(params, allowed={"day", "minutes", "topic"}, required={"day", "minutes"})
            data["day"] = _iso_date(data["day"], "day")
            return asdict(self.study_sessions.plan(day=data["day"], minutes=data["minutes"], topic=data.get("topic")))
        if method == "study.session.start":
            data = strict_object(params, allowed={"day", "minutes", "topic", "session_id", "now"}, required={"day", "minutes"})
            data["day"] = _iso_date(data["day"], "day")
            if data.get("now") is not None:
                data["now"] = datetime.fromisoformat(data["now"])
            return self.study_sessions.start(**data).to_dict()
        if method == "study.session.transition":
            data = strict_object(params, allowed={"session_id", "action", "now", "actual_minutes", "expected_journal_hash"}, required={"session_id", "action"})
            if data.get("now") is not None:
                data["now"] = datetime.fromisoformat(data["now"])
            return self.study_sessions.transition(**data).to_dict()
        if method == "study.session.open":
            strict_object(params, allowed=set())
            return [item.to_dict() for item in self.study_sessions.list_open()]
        if method == "attention.evaluate":
            data = strict_object(params, allowed={"as_of"}, required={"as_of"})
            if not isinstance(data["as_of"], str):
                raise ProtocolError("invalid_params", "as_of must be an ISO datetime.")
            try:
                moment = datetime.fromisoformat(data["as_of"])
            except ValueError as exc:
                raise ProtocolError("invalid_params", "as_of must be an ISO datetime.") from exc
            return evaluate_attention(vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir, as_of=moment).to_dict()
        if method == "attention.preference":
            data = strict_object(params, allowed={"item_id", "snooze_until", "dismiss", "morning_checkin", "evening_checkin", "inbox_days"})
            return asdict(save_preference(self.daily.runtime_dir, **data))  # type: ignore[arg-type]
        if method == "today.get":
            data = strict_object(params, allowed={"day", "available_minutes", "study_minutes", "energy", "motivation", "mode", "adaptive_mode"}, required={"day"})
            data["day"] = _iso_date(data["day"], "day")
            dashboard = build_today_dashboard(vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir, inputs=TodayInputs(**data))  # type: ignore[arg-type]
            return dashboard.to_dict()
        if method == "system.health":
            strict_object(params, allowed=set())
            return {
                "status": "healthy",
                "protocol": PROTOCOL_VERSION,
                "engine_version": ENGINE_VERSION,
                "runtime_schema": DESKTOP_RUNTIME_SCHEMA_VERSION,
            }
        if method == "system.shutdown":
            strict_object(params, allowed=set())
            self.shutdown_requested = True
            return {"accepted": True}
        if method == "request.cancel":
            data = strict_object(params, allowed={"request_id"}, required={"request_id"})
            request_id = data["request_id"]
            if not isinstance(request_id, str) or not request_id:
                raise ProtocolError("invalid_params", "request_id must be a non-empty string.")
            self._cancelled.add(request_id)
            return {"cancelled": request_id}
        try:
            result = self._dispatch_daily(method, params)
        except DailyInteractionError as exc:
            raise ProtocolError(exc.code, exc.message, {"remediation": exc.remediation, **(exc.data or {})}) from exc
        if self._notify is not None:
            self._notify({"jsonrpc": "2.0", "method": "vault.changed", "params": {"path": result["reference"]["path"]}, "meta": {"protocol": PROTOCOL_VERSION}})
        return result

    def _dispatch_daily(self, method: str, params: object) -> dict[str, Any]:
        if method == "daily.capture":
            data = strict_object(params, allowed={"idempotency_key", "kind", "title", "content", "target_path", "plan_path", "task", "metadata", "expected_hash"}, required={"idempotency_key", "kind", "title"})
            request = QuickCaptureRequest(**data)  # type: ignore[arg-type]
            return self.daily.quick_capture(request).to_dict()
        if method == "daily.checkin":
            data = strict_object(params, allowed={"idempotency_key", "day", "period", "metrics", "activities", "note", "expected_hash"}, required={"idempotency_key", "day", "period", "metrics"})
            data["day"] = _iso_date(data["day"], "day")
            if "activities" in data:
                activities = data["activities"]
                if not isinstance(activities, list) or not all(isinstance(item, str) for item in activities):
                    raise ProtocolError("invalid_params", "activities must be a list of strings.")
                data["activities"] = tuple(activities)
            request = CheckInRequest(**data)  # type: ignore[arg-type]
            return self.daily.update_checkin(request).to_dict()
        if method == "daily.task_outcome":
            data = strict_object(params, allowed={"idempotency_key", "plan_path", "task_id", "outcome", "day", "expected_hash", "planned_minutes", "actual_minutes", "energy_before", "energy_after", "motivation_before", "difficulty", "satisfaction", "reason", "note", "deferred_until", "started_at", "ended_at", "source_ref"}, required={"idempotency_key", "plan_path", "task_id", "outcome", "day", "expected_hash"})
            data["day"] = _iso_date(data["day"], "day")
            if data.get("deferred_until") is not None:
                data["deferred_until"] = _iso_date(data["deferred_until"], "deferred_until")
            request = TaskOutcomeRequest(**data)  # type: ignore[arg-type]
            return self.daily.record_task_outcome(request).to_dict()
        if method == "daily.review":
            data = strict_object(params, allowed={"idempotency_key", "kind", "day", "facts_markdown", "expected_hash"}, required={"idempotency_key", "kind", "day", "facts_markdown"})
            data["day"] = _iso_date(data["day"], "day")
            request = ReviewNoteRequest(**data)  # type: ignore[arg-type]
            return self.daily.create_review_note(request).to_dict()
        raise ProtocolError("method_not_found", "The requested bridge method is not allowlisted.", {"method": method})
