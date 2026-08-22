"""Allowlisted bridge dispatcher backed by typed Python services."""

from __future__ import annotations

from dataclasses import asdict
import json
from datetime import datetime
from datetime import date
from pathlib import Path
from typing import Any, Callable, cast

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
    ExplanationError,
    compare_plan_options,
    explain_plan_option,
    recompute_capacity_counterfactual,
    ConflictPlanEdit,
    CopilotProposalError,
    CopilotProposalRequest,
    create_copilot_plan_proposal,
)
from lifeos.copilot.replanning import (
    ReplanningError,
    ReplanningProposalRequest,
    ReviewEvidence,
    build_replanning_review,
    create_replanning_proposal,
    scan_replanning_triggers,
    suppress_replanning_suggestion,
)
from lifeos.facade.copilot_tools import (
    CopilotContextRequest,
    CopilotReadinessRequest,
    inspect_goal_readiness,
    preview_goal_context,
)
from lifeos.bridge.protocol import (
    CAPABILITIES,
    ENGINE_VERSION,
    PROTOCOL_VERSION,
    ProtocolError,
    strict_object,
)
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
from lifeos.reviews import (
    ReviewArtifactService,
    ReviewDecisionService,
    ReviewProgressService,
    ReviewProposalRequest,
    build_review_snapshot,
    create_review_proposal,
    list_review_history,
    open_daily_review,
    open_weekly_review,
    refresh_review_snapshot,
    preview_review_migration,
    apply_review_migration,
    rebuild_review_state,
    build_review_workflow,
    save_progress,
    save_review_note,
)
from lifeos.desktop import DesktopProposalService
from lifeos.config import FeatureFlags, LifeOSConfig
from lifeos.registry import Registry
from lifeos.status import collect_status
from lifeos.versioning import DESKTOP_RUNTIME_SCHEMA_VERSION
from lifeos.vault import VaultAccessError, read_vault_markdown
from lifeos.planning import load_plan_actions
from lifeos.scheduler import (
    BackgroundServiceInstaller,
    ScheduleConfig,
    load_schedule,
    save_schedule,
)
from lifeos.conversations import (
    ConversationError,
    ConversationProposalRequest,
    ConversationProposalService,
    KnowledgeConversationService,
)
from lifeos.retrieval import RetrievalError, RetrievalRequest
from lifeos.conversations.contracts import scope_from_dict
from lifeos.experiments import (
    ExperimentArtifactService,
    ExperimentError,
    ExperimentProposalRequest,
    ExperimentProposalService,
    analyze_experiment,
    classify_safety,
    compare_experiments,
    create_observation,
    due_windows,
    load_experiment_index,
    protocol_from_dict,
    rebuild_experiment_index,
    record_conclusion,
    save_analysis,
    apply_experiment_migration,
    audit_experiment_recovery,
    preview_experiment_context,
    preview_experiment_migration,
)
from lifeos.experiments.design import evaluate_design
from lifeos.captures import CaptureArtifactService, CaptureError
from lifeos.captures.contracts import ArtifactLink, CaptureState, CaptureType, PrivacyScope
from lifeos.captures.enrichment import CaptureEnrichmentService
from lifeos.captures.integrations import CaptureLinkService
from lifeos.captures.processing import CaptureProcessingService, MergePreview
from lifeos.captures.proposals import CaptureProposalRequest, CaptureProposalService
from lifeos.captures.storage import AttachmentStore
from lifeos.captures.privacy import preview_capture_context
from lifeos.captures.migration import apply_capture_migration, preview_capture_migration
from lifeos.captures.recovery import audit_capture_recovery
from lifeos.captures.visualization import build_capture_visualization
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


def _iso_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ProtocolError("invalid_params", f"{field} must be an ISO datetime.")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProtocolError("invalid_params", f"{field} must be an ISO datetime.") from exc
    if result.tzinfo is None:
        raise ProtocolError("invalid_params", f"{field} must include a timezone.")
    return result


def _jsonable(value: object) -> object:
    """Normalize dataclass/date-heavy service results for the JSON-RPC boundary."""
    return json.loads(json.dumps(value, default=str))


class BridgeApplication:
    def __init__(
        self,
        *,
        vault_root: Path,
        runtime_dir: Path,
        actor_id: str,
        notify: NotificationSink | None = None,
    ) -> None:
        self.actor_id = actor_id.strip()
        if not self.actor_id:
            raise ProtocolError("invalid_actor", "A local actor ID is required.")
        self.daily = DailyInteractionService(
            vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id
        )
        self.study_sessions = StudySessionService(
            vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id
        )
        self.proposals = DesktopProposalService(vault_root=vault_root, actor_id=self.actor_id)
        self.planning_sessions = PlanningSessionService(
            vault_root=vault_root, runtime_dir=runtime_dir
        )
        self.feedback_controls = FeedbackControlService(
            vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id
        )
        self.knowledge = KnowledgeConversationService(
            vault_root=vault_root, runtime_dir=runtime_dir
        )
        self.conversation_proposals = ConversationProposalService(
            vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id
        )
        self.experiments = ExperimentArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
        self.experiment_proposals = ExperimentProposalService(
            vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id
        )
        self.captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
        self.capture_store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)
        self.capture_processing = CaptureProcessingService(
            vault_root=vault_root, runtime_dir=runtime_dir
        )
        self.capture_links = CaptureLinkService(self.captures)
        self.capture_enrichment = CaptureEnrichmentService(captures=self.captures)
        self.capture_proposals = CaptureProposalService(
            vault_root=vault_root, runtime_dir=runtime_dir, actor_id=self.actor_id
        )
        self.config = LifeOSConfig(
            vault_root, runtime_dir, FeatureFlags(graphify=True, exports=True)
        )
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

    def _copilot_bundle(
        self, *, session_id: str, option_id: str, as_of: date, available_minutes: int | None = None
    ):
        snapshot = self.planning_sessions.get(session_id)
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
        option_set = generate_plan_options(
            goal=goal,
            session=session,
            readiness=snapshot.envelope.readiness,
            context=context,
            index=index,
            as_of=as_of,
        )
        option = next((item for item in option_set.options if item.option_id == option_id), None)
        if option is None:
            raise ExplanationError("selected option was not found")
        decomposition = decompose_plan_option(option=option, horizon=goal.horizon)
        capacity = check_portfolio_capacity(
            option=option,
            decomposition=decomposition,
            index=index,
            as_of=as_of,
            available_minutes=available_minutes,
        )
        return goal, index, context, option_set, option, decomposition, capacity

    def _retrieval_progress(self, progress: object) -> None:
        if self._notify is not None:
            payload = progress.to_dict() if hasattr(progress, "to_dict") else _jsonable(progress)
            self._notify(
                {
                    "jsonrpc": "2.0",
                    "method": "retrieval.index.progress",
                    "params": payload,
                    "meta": {"protocol": PROTOCOL_VERSION},
                }
            )

    def _dispatch_knowledge(self, method: str, params: object) -> object:
        try:
            if method == "retrieval.index.health":
                strict_object(params, allowed=set())
                return self.knowledge.retriever.index_service.health().to_dict()
            if method == "retrieval.index.recovery.plan":
                strict_object(params, allowed=set())
                return self.knowledge.retriever.index_service.recovery_plan().to_dict()
            if method == "retrieval.index.recover":
                strict_object(params, allowed=set())
                return self.knowledge.retriever.index_service.recover(
                    progress=self._retrieval_progress
                ).to_dict()
            if method == "retrieval.index.rebuild":
                data = strict_object(params, allowed={"resume", "batch_size"})
                resume = data.get("resume", True)
                batch_size = data.get("batch_size", 64)
                if type(resume) is not bool or type(batch_size) is not int:
                    raise ProtocolError(
                        "invalid_params",
                        "resume must be boolean and batch_size must be an integer.",
                    )
                return self.knowledge.retriever.index_service.rebuild(
                    resume=resume, batch_size=batch_size, progress=self._retrieval_progress
                ).to_dict()
            if method == "retrieval.index.sync":
                strict_object(params, allowed=set())
                return self.knowledge.retriever.index_service.incremental_sync(
                    progress=self._retrieval_progress
                ).to_dict()
            if method == "retrieval.search":
                data = strict_object(
                    params,
                    allowed={"query", "scope", "limit", "context_budget", "timeout_seconds"},
                    required={"query"},
                )
                scope_value = data.get("scope", {})
                if not isinstance(scope_value, dict):
                    raise ProtocolError("invalid_params", "scope must be an object.")
                request = RetrievalRequest(
                    query=str(data["query"]),
                    scope=scope_from_dict(scope_value),
                    limit=data.get("limit", 8),
                    context_budget=data.get("context_budget", 12000),
                    timeout_seconds=data.get("timeout_seconds", 30.0),
                )
                return self.knowledge.retriever.search(request).to_dict()
            if method == "conversation.create":
                data = strict_object(params, allowed={"title", "scope", "now"}, required={"title"})
                scope_value = data.get("scope", {})
                if not isinstance(scope_value, dict):
                    raise ProtocolError("invalid_params", "scope must be an object.")
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.knowledge.create(
                    title=str(data["title"]), scope=scope_from_dict(scope_value), now=moment
                ).to_dict()
            if method == "conversation.list":
                data = strict_object(params, allowed={"include_archived"})
                include = data.get("include_archived", True)
                if type(include) is not bool:
                    raise ProtocolError("invalid_params", "include_archived must be boolean.")
                return [
                    item.to_dict()
                    for item in self.knowledge.artifacts.list(include_archived=include)
                ]
            if method == "conversation.load":
                data = strict_object(params, allowed={"path"}, required={"path"})
                return self.knowledge.artifacts.load(str(data["path"])).to_dict()
            if method == "conversation.ask":
                data = strict_object(
                    params,
                    allowed={
                        "path",
                        "query",
                        "expected_hash",
                        "evidence_only",
                        "limit",
                        "context_budget",
                        "timeout_seconds",
                        "now",
                    },
                    required={"path", "query", "expected_hash"},
                )
                evidence_only = data.get("evidence_only", False)
                if type(evidence_only) is not bool:
                    raise ProtocolError("invalid_params", "evidence_only must be boolean.")
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.knowledge.ask(
                    str(data["path"]),
                    query=str(data["query"]),
                    expected_hash=str(data["expected_hash"]),
                    evidence_only=evidence_only,
                    limit=data.get("limit", 8),
                    context_budget=data.get("context_budget", 12000),
                    timeout_seconds=data.get("timeout_seconds", 30.0),
                    now=moment,
                ).to_dict()
            if method == "conversation.scope.update":
                data = strict_object(
                    params,
                    allowed={"path", "expected_hash", "scope", "now"},
                    required={"path", "expected_hash", "scope"},
                )
                if not isinstance(data["scope"], dict):
                    raise ProtocolError("invalid_params", "scope must be an object.")
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.knowledge.artifacts.update(
                    str(data["path"]),
                    expected_hash=str(data["expected_hash"]),
                    scope=scope_from_dict(data["scope"]),
                    now=moment,
                ).to_dict()
            if method in {"conversation.source.pin", "conversation.source.exclude"}:
                data = strict_object(
                    params,
                    allowed={"path", "source_path", "enabled", "expected_hash", "now"},
                    required={"path", "source_path", "expected_hash"},
                )
                enabled = data.get("enabled", True)
                if type(enabled) is not bool:
                    raise ProtocolError("invalid_params", "enabled must be boolean.")
                artifact = self.knowledge.artifacts.load(str(data["path"]))
                source_path = str(data["source_path"])
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                if method.endswith("pin"):
                    values = set(artifact.metadata.pinned_sources)
                    values.add(source_path) if enabled else values.discard(source_path)
                    return self.knowledge.artifacts.update(
                        artifact.relative_path,
                        expected_hash=str(data["expected_hash"]),
                        pinned_sources=tuple(sorted(values)),
                        now=moment,
                    ).to_dict()
                values = set(artifact.metadata.excluded_sources)
                values.add(source_path) if enabled else values.discard(source_path)
                return self.knowledge.artifacts.update(
                    artifact.relative_path,
                    expected_hash=str(data["expected_hash"]),
                    excluded_sources=tuple(sorted(values)),
                    now=moment,
                ).to_dict()
            if method == "conversation.branch":
                data = strict_object(
                    params,
                    allowed={"path", "turn_id", "title", "now"},
                    required={"path", "turn_id"},
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.knowledge.artifacts.branch(
                    str(data["path"]),
                    from_turn_id=str(data["turn_id"]),
                    title=str(data["title"]) if data.get("title") is not None else None,
                    now=moment,
                ).to_dict()
            if method in {"conversation.rename", "conversation.archive"}:
                allowed = {"path", "expected_hash", "now"} | (
                    {"title"} if method.endswith("rename") else set()
                )
                required = {"path", "expected_hash"} | (
                    {"title"} if method.endswith("rename") else set()
                )
                data = strict_object(params, allowed=allowed, required=required)
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                if method.endswith("rename"):
                    return self.knowledge.artifacts.rename(
                        str(data["path"]),
                        str(data["title"]),
                        expected_hash=str(data["expected_hash"]),
                        now=moment,
                    ).to_dict()
                return self.knowledge.artifacts.archive(
                    str(data["path"]), expected_hash=str(data["expected_hash"]), now=moment
                ).to_dict()
            if method == "conversation.stale.check":
                data = strict_object(params, allowed={"path"}, required={"path"})
                return [turn.to_dict() for turn in self.knowledge.stale_status(str(data["path"]))]
            if method in {"conversation.proposal.preview", "conversation.proposal.create"}:
                data = strict_object(
                    params,
                    allowed={
                        "conversation_path",
                        "turn_id",
                        "action",
                        "target_path",
                        "content",
                        "title",
                        "now",
                    },
                    required={"conversation_path", "turn_id", "action", "target_path", "content"},
                )
                moment = (
                    _iso_datetime(data.pop("now"), "now") if data.get("now") is not None else None
                )
                proposal_request = ConversationProposalRequest(**data)
                if method.endswith("preview"):
                    preview, _, _, _ = self.conversation_proposals.preview(
                        proposal_request, now=moment
                    )
                    return preview.to_dict()
                return self.conversation_proposals.publish(proposal_request, now=moment).to_dict()
        except ProtocolError:
            raise
        except (ConversationError, RetrievalError, TypeError, ValueError) as exc:
            raise ProtocolError(
                getattr(exc, "code", "knowledge_workspace_invalid"),
                getattr(exc, "message", str(exc)),
                getattr(exc, "data", None),
            ) from exc
        raise ProtocolError(
            "method_not_found",
            "The requested bridge method is not allowlisted.",
            {"method": method},
        )

    def _dispatch_capture(self, method: str, params: object) -> object:
        try:
            if method == "capture.create":
                data = strict_object(
                    params,
                    allowed={
                        "title",
                        "capture_type",
                        "description",
                        "event_at",
                        "timezone",
                        "source_entry_point",
                        "privacy_scope",
                        "sensitive",
                        "tags",
                        "now",
                    },
                    required={"title", "capture_type"},
                )
                tags = data.get("tags", [])
                if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
                    raise ProtocolError("invalid_params", "tags must be a list of strings.")
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                event_at = (
                    _iso_datetime(data["event_at"], "event_at")
                    if data.get("event_at") is not None
                    else None
                )
                return self.captures.create(
                    title=str(data["title"]),
                    capture_type=cast(CaptureType, str(data["capture_type"])),
                    description=str(data.get("description", "")),
                    event_at=event_at,
                    timezone_name=str(data.get("timezone", "UTC")),
                    source_entry_point=str(data.get("source_entry_point", "bridge")),
                    privacy_scope=cast(PrivacyScope, str(data.get("privacy_scope", "standard"))),
                    sensitive=bool(data.get("sensitive", False)),
                    tags=tuple(tags),
                    now=moment,
                ).to_dict()
            if method == "capture.read":
                data = strict_object(params, allowed={"path"}, required={"path"})
                return self.captures.load(str(data["path"])).to_dict()
            if method in {"capture.list", "capture.filter"}:
                data = strict_object(params, allowed={"capture_types", "states"})
                raw_types = data.get("capture_types")
                raw_states = data.get("states")
                for name, value in (("capture_types", raw_types), ("states", raw_states)):
                    if value is not None and (
                        not isinstance(value, list)
                        or not all(isinstance(item, str) for item in value)
                    ):
                        raise ProtocolError("invalid_params", f"{name} must be a list of strings.")
                return [
                    item.to_dict()
                    for item in self.captures.list(
                        capture_types=frozenset(raw_types) if raw_types is not None else None,
                        states=frozenset(raw_states) if raw_states is not None else None,
                    )
                ]
            if method == "capture.visualization.build":
                data = strict_object(
                    params,
                    allowed={"capture_types", "states", "start", "end", "max_points"},
                )
                raw_types = data.get("capture_types")
                raw_states = data.get("states")
                for name, value in (("capture_types", raw_types), ("states", raw_states)):
                    if value is not None and (
                        not isinstance(value, list)
                        or not all(isinstance(item, str) for item in value)
                    ):
                        raise ProtocolError("invalid_params", f"{name} must be a list of strings.")
                start = _iso_date(data["start"], "start") if data.get("start") is not None else None
                end = _iso_date(data["end"], "end") if data.get("end") is not None else None
                max_points = data.get("max_points", 500)
                if type(max_points) is not int:
                    raise ProtocolError("invalid_params", "max_points must be an integer.")
                return build_capture_visualization(
                    vault_root=self.daily.vault_root,
                    runtime_dir=self.daily.runtime_dir,
                    capture_types=frozenset(raw_types) if raw_types is not None else None,
                    states=frozenset(raw_states) if raw_states is not None else None,
                    start=start,
                    end=end,
                    max_points=max_points,
                ).to_dict()
            if method == "capture.update":
                data = strict_object(
                    params,
                    allowed={
                        "path",
                        "expected_hash",
                        "title",
                        "description",
                        "event_at",
                        "tags",
                        "location",
                        "privacy_scope",
                        "sensitive",
                        "now",
                    },
                    required={"path", "expected_hash"},
                )
                tags = data.get("tags")
                if tags is not None and (
                    not isinstance(tags, list) or not all(isinstance(item, str) for item in tags)
                ):
                    raise ProtocolError("invalid_params", "tags must be a list of strings.")
                event_at = data.get("event_at")
                if event_at is not None:
                    _iso_datetime(event_at, "event_at")
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.captures.update_user_fields(
                    str(data["path"]),
                    expected_hash=str(data["expected_hash"]),
                    title=str(data["title"]) if data.get("title") is not None else None,
                    description=str(data["description"])
                    if data.get("description") is not None
                    else None,
                    event_at=str(event_at) if event_at is not None else None,
                    tags=tuple(tags) if tags is not None else None,
                    location=str(data["location"]) if data.get("location") is not None else None,
                    privacy_scope=cast(PrivacyScope, str(data["privacy_scope"]))
                    if data.get("privacy_scope") is not None
                    else None,
                    sensitive=bool(data["sensitive"])
                    if data.get("sensitive") is not None
                    else None,
                    now=moment,
                ).to_dict()
            if method == "capture.transition":
                data = strict_object(
                    params,
                    allowed={"path", "target", "expected_hash", "reason", "now"},
                    required={"path", "target", "expected_hash"},
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.captures.transition(
                    str(data["path"]),
                    cast(CaptureState, str(data["target"])),
                    expected_hash=str(data["expected_hash"]),
                    reason=str(data.get("reason", "")),
                    now=moment,
                ).to_dict()
            if method == "capture.attachment.add":
                data = strict_object(
                    params,
                    allowed={"path", "expected_hash", "source_path", "independent_copy", "now"},
                    required={"path", "expected_hash", "source_path"},
                )
                independent = data.get("independent_copy", False)
                if type(independent) is not bool:
                    raise ProtocolError("invalid_params", "independent_copy must be boolean.")
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                capture = self.captures.load(str(data["path"]))
                if capture.content_hash != str(data["expected_hash"]):
                    raise CaptureError("stale_capture", "Capture changed before attachment import.")
                imported = self.capture_store.import_file(
                    Path(str(data["source_path"])),
                    capture_source="bridge",
                    parent_capture_id=capture.metadata.capture_id,
                    independent_copy=independent,
                    now=moment,
                )
                updated = self.capture_store.attach_to_capture(
                    capture.path, imported.reference, expected_hash=capture.content_hash, now=moment
                )
                return {"capture": updated.to_dict(), "attachment": imported.to_dict()}
            if method == "capture.attachment.remove":
                data = strict_object(
                    params,
                    allowed={"path", "expected_hash", "attachment_id", "now"},
                    required={"path", "expected_hash", "attachment_id"},
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.capture_store.remove_from_capture(
                    str(data["path"]),
                    str(data["attachment_id"]),
                    expected_hash=str(data["expected_hash"]),
                    now=moment,
                ).to_dict()
            if method == "capture.attachment.audit":
                data = strict_object(params, allowed={"attachment_id"}, required={"attachment_id"})
                return self.capture_store.audit(str(data["attachment_id"])).to_dict()
            if method == "capture.enrichment.start":
                data = strict_object(
                    params,
                    allowed={"path", "expected_hash", "now"},
                    required={"path", "expected_hash"},
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.capture_processing.start_extraction(
                    str(data["path"]), expected_hash=str(data["expected_hash"]), now=moment
                ).to_dict()
            if method == "capture.enrichment.run":
                data = strict_object(params, allowed={"job_id", "now"}, required={"job_id"})
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.capture_processing.run_extraction(
                    str(data["job_id"]), now=moment
                ).to_dict()
            if method == "capture.enrichment.cancel":
                data = strict_object(params, allowed={"job_id", "now"}, required={"job_id"})
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.capture_processing.cancel(str(data["job_id"]), now=moment).to_dict()
            if method == "capture.enrichment.retry":
                data = strict_object(params, allowed={"job_id", "now"}, required={"job_id"})
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.capture_processing.retry(str(data["job_id"]), now=moment).to_dict()
            if method == "capture.inference.decide":
                data = strict_object(
                    params,
                    allowed={
                        "path",
                        "field_name",
                        "decision",
                        "expected_hash",
                        "corrected_value",
                        "now",
                    },
                    required={"path", "field_name", "decision", "expected_hash"},
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.capture_enrichment.decide_value(
                    str(data["path"]),
                    str(data["field_name"]),
                    str(data["decision"]),
                    expected_hash=str(data["expected_hash"]),
                    corrected_value=data.get("corrected_value"),
                    now=moment,
                ).to_dict()
            if method == "capture.link":
                data = strict_object(
                    params,
                    allowed={
                        "path",
                        "expected_hash",
                        "target_path",
                        "relation",
                        "artifact_type",
                        "content_hash",
                        "now",
                    },
                    required={"path", "expected_hash", "target_path", "relation"},
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                link = ArtifactLink(
                    str(data["target_path"]),
                    str(data["relation"]),
                    str(data.get("artifact_type", "note")),
                    str(data["content_hash"]) if data.get("content_hash") is not None else None,
                )
                return self.capture_links.link(
                    str(data["path"]), link, expected_hash=str(data["expected_hash"]), now=moment
                ).to_dict()
            if method == "capture.unlink":
                data = strict_object(
                    params,
                    allowed={"path", "expected_hash", "target_path", "now"},
                    required={"path", "expected_hash", "target_path"},
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.capture_links.unlink(
                    str(data["path"]),
                    str(data["target_path"]),
                    expected_hash=str(data["expected_hash"]),
                    now=moment,
                ).to_dict()
            if method == "capture.split":
                data = strict_object(
                    params,
                    allowed={"path", "groups", "expected_hash", "now"},
                    required={"path", "groups", "expected_hash"},
                )
                groups = data["groups"]
                if not isinstance(groups, list) or not all(
                    isinstance(group, list) and all(isinstance(item, str) for item in group)
                    for group in groups
                ):
                    raise ProtocolError(
                        "invalid_params", "groups must be a list of attachment ID lists."
                    )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return [
                    item.to_dict()
                    for item in self.capture_processing.split(
                        str(data["path"]),
                        tuple(tuple(group) for group in groups),
                        expected_hash=str(data["expected_hash"]),
                        now=moment,
                    )
                ]
            if method == "capture.merge.preview":
                data = strict_object(params, allowed={"source_paths"}, required={"source_paths"})
                source_paths = data["source_paths"]
                if not isinstance(source_paths, list) or not all(
                    isinstance(item, str) for item in source_paths
                ):
                    raise ProtocolError("invalid_params", "source_paths must be a list of strings.")
                return self.capture_processing.merge_preview(tuple(source_paths)).to_dict()
            if method == "capture.merge.apply":
                data = strict_object(params, allowed={"preview", "now"}, required={"preview"})
                preview = data["preview"]
                if not isinstance(preview, dict):
                    raise ProtocolError("invalid_params", "preview must be an object.")
                normalized = dict(preview)
                for key in (
                    "source_paths",
                    "source_hashes",
                    "attachment_ids",
                    "link_paths",
                    "warnings",
                ):
                    value = normalized.get(key)
                    if not isinstance(value, (list, tuple)) or not all(
                        isinstance(item, str) for item in value
                    ):
                        raise ProtocolError(
                            "invalid_params", f"preview.{key} must be a list of strings."
                        )
                    normalized[key] = tuple(value)
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.capture_processing.apply_merge(
                    MergePreview(**normalized), now=moment
                ).to_dict()
            if method in {"capture.proposal.preview", "capture.proposal.create"}:
                data = strict_object(
                    params,
                    allowed={
                        "capture_path",
                        "action",
                        "target_path",
                        "content",
                        "create_target",
                        "attachment_ids",
                        "included_actions",
                        "excluded_actions",
                        "now",
                    },
                    required={"capture_path", "action", "target_path", "content"},
                )
                for key in ("attachment_ids", "included_actions", "excluded_actions"):
                    value = data.get(key, [])
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) for item in value
                    ):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                    data[key] = tuple(value)
                create_target = data.get("create_target", False)
                if type(create_target) is not bool:
                    raise ProtocolError("invalid_params", "create_target must be boolean.")
                moment = (
                    _iso_datetime(data.pop("now"), "now") if data.get("now") is not None else None
                )
                request = CaptureProposalRequest(**data)
                if method.endswith("preview"):
                    preview, _, _ = self.capture_proposals.preview(request, now=moment)
                    return preview.to_dict()
                return self.capture_proposals.publish(request, now=moment)
            if method == "capture.privacy.preview":
                data = strict_object(
                    params,
                    allowed={
                        "capture_path",
                        "selected_attachment_ids",
                        "selected_paths",
                        "requested_operations",
                        "external_processing_intent",
                        "allow_sensitive_capture",
                        "allowed_sensitive_roots",
                        "redact_terms",
                        "max_item_bytes",
                        "max_total_bytes",
                    },
                    required={"capture_path"},
                )
                for key in (
                    "selected_attachment_ids",
                    "selected_paths",
                    "requested_operations",
                    "allowed_sensitive_roots",
                    "redact_terms",
                ):
                    value = data.get(key, [])
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) for item in value
                    ):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                    data[key] = tuple(value)
                for key in ("external_processing_intent", "allow_sensitive_capture"):
                    value = data.get(key, False)
                    if type(value) is not bool:
                        raise ProtocolError("invalid_params", f"{key} must be boolean.")
                    data[key] = value
                return preview_capture_context(
                    vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir, **data
                ).to_dict()
            if method == "capture.rebuild":
                data = strict_object(
                    params,
                    allowed={
                        "rebuild_manifests",
                        "delete_runtime",
                        "interrupt_after",
                        "batch_size",
                    },
                )
                for key in ("rebuild_manifests", "delete_runtime"):
                    value = data.get(key, False)
                    if type(value) is not bool:
                        raise ProtocolError("invalid_params", f"{key} must be boolean.")
                    data[key] = value
                interrupt_after = data.get("interrupt_after")
                batch_size = data.get("batch_size", 64)
                if interrupt_after is not None and (
                    type(interrupt_after) is not int or interrupt_after < 1
                ):
                    raise ProtocolError(
                        "invalid_params", "interrupt_after must be a positive integer or null."
                    )
                if type(batch_size) is not int or batch_size < 1:
                    raise ProtocolError("invalid_params", "batch_size must be a positive integer.")
                return audit_capture_recovery(
                    vault_root=self.daily.vault_root,
                    runtime_dir=self.daily.runtime_dir,
                    rebuild=True,
                    **data,
                ).to_dict()
            if method == "capture.migration.preview":
                strict_object(params, allowed=set())
                return preview_capture_migration(
                    vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir
                ).to_dict()
            if method == "capture.migration.apply":
                data = strict_object(params, allowed={"expected_source_hashes"})
                hashes = data.get("expected_source_hashes", {})
                if not isinstance(hashes, dict) or not all(
                    isinstance(key, str) and isinstance(value, str) for key, value in hashes.items()
                ):
                    raise ProtocolError(
                        "invalid_params", "expected_source_hashes must be an object of strings."
                    )
                return apply_capture_migration(
                    vault_root=self.daily.vault_root,
                    runtime_dir=self.daily.runtime_dir,
                    expected_source_hashes=hashes,
                ).to_dict()
        except ProtocolError:
            raise
        except (CaptureError, TypeError, ValueError, OSError) as exc:
            raise ProtocolError(
                getattr(exc, "code", "capture_invalid"),
                getattr(exc, "message", str(exc)),
                getattr(exc, "data", None),
            ) from exc
        raise ProtocolError(
            "method_not_found",
            "The requested capture method is not allowlisted.",
            {"method": method},
        )

    def _dispatch_experiment(self, method: str, params: object) -> object:
        try:
            if method == "experiment.create":
                data = strict_object(
                    params,
                    allowed={"title", "description", "category", "protocol", "origins", "now"},
                    required={"title", "protocol"},
                )
                if not isinstance(data["protocol"], dict):
                    raise ProtocolError("invalid_params", "protocol must be an object.")
                protocol = protocol_from_dict(data["protocol"])
                origins_raw = data.get("origins", [])
                if not isinstance(origins_raw, list):
                    raise ProtocolError("invalid_params", "origins must be a list.")
                from lifeos.experiments.contracts import source_from_dict

                origins = tuple(source_from_dict(dict(item)) for item in origins_raw)
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.experiments.create(
                    title=str(data["title"]),
                    description=str(data.get("description", "")),
                    category=str(data.get("category", "other")),
                    protocol=protocol,
                    origins=origins,
                    safety=classify_safety(protocol),
                    now=moment,
                ).to_dict()
            if method == "experiment.list":
                data = strict_object(params, allowed={"states"})
                raw = data.get("states")
                if raw is not None and (
                    not isinstance(raw, list) or not all(isinstance(item, str) for item in raw)
                ):
                    raise ProtocolError("invalid_params", "states must be a list of strings.")
                states = frozenset(raw) if raw is not None else None
                return [item.to_dict() for item in self.experiments.list(states=states)]
            if method == "experiment.load":
                data = strict_object(params, allowed={"path"}, required={"path"})
                return self.experiments.load(str(data["path"])).to_dict()
            if method in {"experiment.design.evaluate", "experiment.safety.classify"}:
                data = strict_object(
                    params, allowed={"protocol", "current_experiment_id"}, required={"protocol"}
                )
                if not isinstance(data["protocol"], dict):
                    raise ProtocolError("invalid_params", "protocol must be an object.")
                protocol = protocol_from_dict(data["protocol"])
                if method.endswith("classify"):
                    return classify_safety(protocol).to_dict()
                active = self.experiments.list(
                    states=frozenset({"baseline", "scheduled", "active", "paused"})
                )
                return [
                    item.to_dict()
                    for item in evaluate_design(
                        protocol,
                        active_experiments=active,
                        current_experiment_id=str(data["current_experiment_id"])
                        if data.get("current_experiment_id")
                        else None,
                    )
                ]
            if method == "experiment.transition":
                data = strict_object(
                    params,
                    allowed={"path", "target", "expected_hash", "reason", "now"},
                    required={"path", "target", "expected_hash"},
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.experiments.transition(
                    str(data["path"]),
                    str(data["target"]),
                    expected_hash=str(data["expected_hash"]),
                    reason=str(data.get("reason", "")),
                    now=moment,
                ).to_dict()
            if method == "experiment.protocol.update":
                data = strict_object(
                    params,
                    allowed={"path", "protocol", "expected_hash", "now"},
                    required={"path", "protocol", "expected_hash"},
                )
                if not isinstance(data["protocol"], dict):
                    raise ProtocolError("invalid_params", "protocol must be an object.")
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.experiments.update_protocol(
                    str(data["path"]),
                    protocol_from_dict(data["protocol"]),
                    expected_hash=str(data["expected_hash"]),
                    now=moment,
                ).to_dict()
            if method == "experiment.amendment.add":
                data = strict_object(
                    params,
                    allowed={"path", "protocol", "reason", "changes", "expected_hash", "now"},
                    required={"path", "protocol", "reason", "changes", "expected_hash"},
                )
                if not isinstance(data["protocol"], dict) or not isinstance(data["changes"], list):
                    raise ProtocolError(
                        "invalid_params", "protocol must be an object and changes must be a list."
                    )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.experiments.amend_protocol(
                    str(data["path"]),
                    protocol_from_dict(data["protocol"]),
                    reason=str(data["reason"]),
                    changes=tuple(str(item) for item in data["changes"]),
                    expected_hash=str(data["expected_hash"]),
                    now=moment,
                ).to_dict()
            if method == "experiment.observation.record":
                data = strict_object(
                    params,
                    allowed={
                        "path",
                        "measure_id",
                        "phase_id",
                        "observed_at",
                        "state",
                        "value",
                        "note",
                        "context",
                        "source_refs",
                        "observation_id",
                        "expected_hash",
                        "now",
                    },
                    required={
                        "path",
                        "measure_id",
                        "phase_id",
                        "observed_at",
                        "state",
                        "expected_hash",
                    },
                )
                artifact = self.experiments.load(str(data["path"]))
                context = data.get("context", [])
                sources = data.get("source_refs", [])
                if not isinstance(context, list) or not isinstance(sources, list):
                    raise ProtocolError("invalid_params", "context and source_refs must be lists.")
                from lifeos.experiments.contracts import source_from_dict

                observation = create_observation(
                    artifact.metadata,
                    measure_id=str(data["measure_id"]),
                    phase_id=str(data["phase_id"]),
                    observed_at=_iso_datetime(data["observed_at"], "observed_at"),
                    state=str(data["state"]),
                    value=data.get("value"),
                    note=str(data.get("note", "")),
                    context=tuple(str(item) for item in context),
                    source_refs=tuple(source_from_dict(dict(item)) for item in sources),
                    observation_id=str(data["observation_id"])
                    if data.get("observation_id")
                    else None,
                )
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.experiments.append_observation(
                    artifact.path, observation, expected_hash=str(data["expected_hash"]), now=moment
                ).to_dict()
            if method == "experiment.schedule.due":
                data = strict_object(params, allowed={"path", "now"}, required={"path", "now"})
                artifact = self.experiments.load(str(data["path"]))
                return [
                    item.to_dict()
                    for item in due_windows(
                        artifact.metadata, now=_iso_datetime(data["now"], "now")
                    )
                ]
            if method == "experiment.analysis.run":
                data = strict_object(
                    params,
                    allowed={"path", "expected_hash", "now", "save"},
                    required={"path", "expected_hash"},
                )
                artifact = self.experiments.load(str(data["path"]))
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                save = data.get("save", True)
                if type(save) is not bool:
                    raise ProtocolError("invalid_params", "save must be boolean.")
                if not save:
                    return analyze_experiment(artifact, now=moment).to_dict()
                return save_analysis(
                    self.experiments, artifact, expected_hash=str(data["expected_hash"]), now=moment
                ).to_dict()
            if method == "experiment.conclusion.record":
                data = strict_object(
                    params,
                    allowed={
                        "path",
                        "conclusion",
                        "notes",
                        "follow_up_decisions",
                        "expected_hash",
                        "now",
                    },
                    required={"path", "conclusion", "expected_hash"},
                )
                decisions = data.get("follow_up_decisions", ())
                if not isinstance(decisions, list):
                    raise ProtocolError("invalid_params", "follow_up_decisions must be a list.")
                artifact = self.experiments.load(str(data["path"]))
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return record_conclusion(
                    self.experiments,
                    artifact,
                    conclusion=str(data["conclusion"]),
                    notes=str(data.get("notes", "")),
                    follow_up_decisions=tuple(str(item) for item in decisions),
                    expected_hash=str(data["expected_hash"]),
                    now=moment,
                ).to_dict()
            if method == "experiment.clone":
                data = strict_object(params, allowed={"path", "title", "now"}, required={"path"})
                moment = _iso_datetime(data["now"], "now") if data.get("now") is not None else None
                return self.experiments.clone(
                    str(data["path"]),
                    title=str(data["title"]) if data.get("title") else None,
                    now=moment,
                ).to_dict()
            if method == "experiment.history.rebuild":
                data = strict_object(params, allowed={"batch_size", "interrupt_after"})
                return rebuild_experiment_index(
                    vault_root=self.daily.vault_root,
                    runtime_dir=self.daily.runtime_dir,
                    batch_size=int(data.get("batch_size", 100)),
                    interrupt_after=int(data["interrupt_after"])
                    if data.get("interrupt_after") is not None
                    else None,
                ).to_dict()
            if method == "experiment.history.load":
                strict_object(params, allowed=set())
                return load_experiment_index(runtime_dir=self.daily.runtime_dir).to_dict()
            if method == "experiment.migration.preview":
                strict_object(params, allowed=set())
                return preview_experiment_migration(
                    vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir
                ).to_dict()
            if method == "experiment.migration.apply":
                data = strict_object(
                    params,
                    allowed={"expected_source_hashes", "interrupt_after"},
                    required={"expected_source_hashes"},
                )
                hashes = data["expected_source_hashes"]
                if not isinstance(hashes, dict) or not all(
                    isinstance(key, str) and isinstance(value, str) for key, value in hashes.items()
                ):
                    raise ProtocolError(
                        "invalid_params", "expected_source_hashes must map paths to hashes."
                    )
                return apply_experiment_migration(
                    vault_root=self.daily.vault_root,
                    runtime_dir=self.daily.runtime_dir,
                    expected_source_hashes=hashes,
                    interrupt_after=int(data["interrupt_after"])
                    if data.get("interrupt_after") is not None
                    else None,
                ).to_dict()
            if method == "experiment.privacy.preview":
                data = strict_object(
                    params,
                    allowed={
                        "experiment_path",
                        "selected_paths",
                        "allowed_sensitive_roots",
                        "redact_terms",
                        "max_item_bytes",
                        "max_total_bytes",
                    },
                    required={"experiment_path"},
                )
                for key in ("selected_paths", "allowed_sensitive_roots", "redact_terms"):
                    raw = data.get(key, [])
                    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                return preview_experiment_context(
                    vault_root=self.daily.vault_root,
                    runtime_dir=self.daily.runtime_dir,
                    experiment_path=str(data["experiment_path"]),
                    selected_paths=data.get("selected_paths", []),
                    allowed_sensitive_roots=data.get("allowed_sensitive_roots", []),
                    redact_terms=data.get("redact_terms", []),
                    max_item_bytes=int(data.get("max_item_bytes", 8_000)),
                    max_total_bytes=int(data.get("max_total_bytes", 24_000)),
                ).to_dict()
            if method == "experiment.recovery.audit":
                data = strict_object(params, allowed={"rebuild", "interrupt_after"})
                rebuild = data.get("rebuild", False)
                if type(rebuild) is not bool:
                    raise ProtocolError("invalid_params", "rebuild must be boolean.")
                return audit_experiment_recovery(
                    vault_root=self.daily.vault_root,
                    runtime_dir=self.daily.runtime_dir,
                    rebuild=rebuild,
                    interrupt_after=int(data["interrupt_after"])
                    if data.get("interrupt_after") is not None
                    else None,
                ).to_dict()
            if method == "experiment.compare":
                data = strict_object(
                    params, allowed={"left_id", "right_id"}, required={"left_id", "right_id"}
                )
                report = load_experiment_index(runtime_dir=self.daily.runtime_dir)
                return compare_experiments(
                    report.entries, str(data["left_id"]), str(data["right_id"])
                )
            if method in {"experiment.proposal.preview", "experiment.proposal.create"}:
                data = strict_object(
                    params,
                    allowed={
                        "experiment_path",
                        "action",
                        "target_path",
                        "content",
                        "create_target",
                        "included_actions",
                        "excluded_actions",
                        "now",
                    },
                    required={
                        "experiment_path",
                        "action",
                        "target_path",
                        "content",
                        "create_target",
                    },
                )
                for key in ("included_actions", "excluded_actions"):
                    raw = data.get(key, [])
                    if not isinstance(raw, list):
                        raise ProtocolError("invalid_params", f"{key} must be a list.")
                    data[key] = tuple(str(item) for item in raw)
                if type(data["create_target"]) is not bool:
                    raise ProtocolError("invalid_params", "create_target must be boolean.")
                moment = (
                    _iso_datetime(data.pop("now"), "now") if data.get("now") is not None else None
                )
                request = ExperimentProposalRequest(**data)
                if method.endswith("preview"):
                    preview, _, _ = self.experiment_proposals.preview(request, now=moment)
                    return preview.to_dict()
                return self.experiment_proposals.publish(request, now=moment)
        except ProtocolError:
            raise
        except (ExperimentError, TypeError, ValueError) as exc:
            raise ProtocolError(
                getattr(exc, "code", "experiment_invalid"),
                getattr(exc, "message", str(exc)),
                getattr(exc, "data", None),
            ) from exc
        raise ProtocolError(
            "method_not_found",
            "The requested experiment method is not allowlisted.",
            {"method": method},
        )

    def dispatch(self, method: str, params: object) -> object:
        if method.startswith("retrieval.") or method.startswith("conversation."):
            return self._dispatch_knowledge(method, params)
        if method.startswith("experiment."):
            return self._dispatch_experiment(method, params)
        if method.startswith("capture."):
            return self._dispatch_capture(method, params)
        if method == "copilot.replanning.scan":
            data = strict_object(params, allowed={"as_of"}, required={"as_of"})
            try:
                return [
                    item.to_dict()
                    for item in scan_replanning_triggers(
                        vault_root=self.daily.vault_root,
                        runtime_dir=self.daily.runtime_dir,
                        as_of=_iso_date(data["as_of"], "as_of"),
                    )
                ]
            except (ReplanningError, CopilotContractError, VaultAccessError) as exc:
                raise ProtocolError("copilot_replanning_invalid", str(exc)) from exc
        if method == "copilot.replanning.review":
            data = strict_object(
                params,
                allowed={"target_path", "as_of", "expected_hash", "corrections", "recent_answers"},
                required={"target_path", "as_of"},
            )

            def evidence_values(key: str) -> tuple[ReviewEvidence, ...]:
                raw = data.get(key, [])
                if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
                    raise ProtocolError(
                        "invalid_params", f"{key} must be a list of evidence objects."
                    )
                values: list[ReviewEvidence] = []
                for item in raw:
                    value = strict_object(
                        item,
                        allowed={"evidence_id", "kind", "statement", "source_ref", "observed_at"},
                        required={"evidence_id", "kind", "statement"},
                    )
                    observed = value.get("observed_at")
                    if observed is not None:
                        value["observed_at"] = _iso_date(observed, "observed_at")
                    values.append(ReviewEvidence(**value))
                return tuple(values)

            try:
                return build_replanning_review(
                    vault_root=self.daily.vault_root,
                    runtime_dir=self.daily.runtime_dir,
                    target_path=data["target_path"],
                    as_of=_iso_date(data["as_of"], "as_of"),
                    expected_hash=data.get("expected_hash"),
                    corrections=evidence_values("corrections"),
                    recent_answers=evidence_values("recent_answers"),
                ).to_dict()
            except (ReplanningError, CopilotContractError, VaultAccessError, TypeError) as exc:
                raise ProtocolError("copilot_replanning_invalid", str(exc)) from exc
        if method == "copilot.replanning.suppress":
            data = strict_object(
                params,
                allowed={"trigger_id", "evidence_fingerprint"},
                required={"trigger_id", "evidence_fingerprint"},
            )
            try:
                suppress_replanning_suggestion(
                    runtime_dir=self.daily.runtime_dir,
                    trigger_id=data["trigger_id"],
                    evidence_fingerprint=data["evidence_fingerprint"],
                )
                return {"suppressed": True, **data}
            except (ReplanningError, TypeError) as exc:
                raise ProtocolError("copilot_replanning_invalid", str(exc)) from exc
        if method == "copilot.replanning.proposal.create":
            data = strict_object(
                params,
                allowed={
                    "review_id",
                    "target_path",
                    "expected_hash",
                    "outcome",
                    "rationale",
                    "evidence_fingerprint",
                    "changes",
                },
                required={
                    "review_id",
                    "target_path",
                    "expected_hash",
                    "outcome",
                    "rationale",
                    "evidence_fingerprint",
                },
            )
            changes = data.get("changes", {})
            if not isinstance(changes, dict):
                raise ProtocolError("invalid_params", "changes must be an object.")
            try:
                result = create_replanning_proposal(
                    vault_root=self.daily.vault_root,
                    request=ReplanningProposalRequest(
                        review_id=data["review_id"],
                        target_path=data["target_path"],
                        expected_hash=data["expected_hash"],
                        outcome=data["outcome"],
                        rationale=data["rationale"],
                        evidence_fingerprint=data["evidence_fingerprint"],
                        changes=changes,
                    ),
                    actor_id=self.actor_id,
                )
                return (
                    result.to_dict()
                    if result is not None
                    else {"proposal_created": False, "outcome": "continue-unchanged"}
                )
            except (ReplanningError, TypeError) as exc:
                raise ProtocolError("copilot_replanning_invalid", str(exc)) from exc
        if method == "copilot.proposal.create":
            data = strict_object(
                params,
                allowed={
                    "session_id",
                    "option_id",
                    "as_of",
                    "expected_revision",
                    "plan_id",
                    "plan_path",
                    "plan_title",
                    "desired_outcome",
                    "included_milestone_ids",
                    "included_action_ids",
                    "milestone_edits",
                    "action_edits",
                    "goal_updates",
                    "link_goal",
                    "conflict_edits",
                },
                required={
                    "session_id",
                    "option_id",
                    "as_of",
                    "expected_revision",
                    "plan_id",
                    "plan_path",
                    "plan_title",
                    "desired_outcome",
                    "included_milestone_ids",
                    "included_action_ids",
                },
            )
            as_of = _iso_date(data["as_of"], "as_of")
            for key in ("included_milestone_ids", "included_action_ids"):
                value = data[key]
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
            for key in ("milestone_edits", "action_edits", "goal_updates"):
                value = data.get(key, {})
                if not isinstance(value, dict):
                    raise ProtocolError("invalid_params", f"{key} must be an object.")
                data[key] = value
            raw_conflicts = data.get("conflict_edits", [])
            if not isinstance(raw_conflicts, list) or not all(
                isinstance(item, dict) for item in raw_conflicts
            ):
                raise ProtocolError("invalid_params", "conflict_edits must be a list of objects.")
            try:
                conflicts = tuple(
                    ConflictPlanEdit(
                        **strict_object(
                            item,
                            allowed={"target_path", "action"},
                            required={"target_path", "action"},
                        )
                    )
                    for item in raw_conflicts
                )
                goal, index, _, _, option, decomposition, _ = self._copilot_bundle(
                    session_id=data["session_id"], option_id=data["option_id"], as_of=as_of
                )
                request = CopilotProposalRequest(
                    session_id=data["session_id"],
                    expected_session_revision=data["expected_revision"],
                    goal_path=goal.path,
                    expected_goal_hash=goal.content_hash,
                    plan_id=data["plan_id"],
                    plan_path=data["plan_path"],
                    plan_title=data["plan_title"],
                    desired_outcome=data["desired_outcome"],
                    included_milestone_ids=tuple(data["included_milestone_ids"]),
                    included_action_ids=tuple(data["included_action_ids"]),
                    milestone_edits=data["milestone_edits"],
                    action_edits=data["action_edits"],
                    goal_updates=data["goal_updates"],
                    link_goal=data.get("link_goal", True),
                    conflict_edits=conflicts,
                )
                return create_copilot_plan_proposal(
                    vault_root=self.daily.vault_root,
                    option=option,
                    decomposition=decomposition,
                    index=index,
                    request=request,
                    actor_id=self.actor_id,
                    session_service=self.planning_sessions,
                ).to_dict()
            except (
                CopilotProposalError,
                ExplanationError,
                CapacityError,
                DecompositionError,
                PlanOptionError,
                PlanningSessionError,
                SessionConflictError,
                CopilotContractError,
                PlanningContextError,
                VaultAccessError,
                TypeError,
                ProtocolError,
            ) as exc:
                if isinstance(exc, ProtocolError):
                    raise
                raise ProtocolError("copilot_proposal_invalid", str(exc)) from exc
        if method == "copilot.explain":
            data = strict_object(
                params,
                allowed={"session_id", "option_id", "as_of", "available_minutes"},
                required={"session_id", "option_id", "as_of"},
            )
            as_of = _iso_date(data["as_of"], "as_of")
            available = data.get("available_minutes")
            if available is not None and (type(available) is not int or available < 0):
                raise ProtocolError(
                    "invalid_params", "available_minutes must be non-negative or null."
                )
            try:
                _, _, context, _, option, decomposition, capacity = self._copilot_bundle(
                    session_id=data["session_id"],
                    option_id=data["option_id"],
                    as_of=as_of,
                    available_minutes=available,
                )
                return explain_plan_option(
                    option=option, decomposition=decomposition, capacity=capacity, context=context
                ).to_dict()
            except (
                ExplanationError,
                CapacityError,
                DecompositionError,
                PlanOptionError,
                PlanningSessionError,
                CopilotContractError,
                PlanningContextError,
                VaultAccessError,
            ) as exc:
                raise ProtocolError("copilot_explanation_invalid", str(exc)) from exc
        if method == "copilot.compare":
            data = strict_object(
                params,
                allowed={"session_id", "option_ids", "as_of", "available_minutes"},
                required={"session_id", "option_ids", "as_of"},
            )
            option_ids = data["option_ids"]
            if not isinstance(option_ids, list) or not all(
                isinstance(item, str) for item in option_ids
            ):
                raise ProtocolError("invalid_params", "option_ids must be a list of strings.")
            as_of = _iso_date(data["as_of"], "as_of")
            available = data.get("available_minutes")
            try:
                bundles = [
                    self._copilot_bundle(
                        session_id=data["session_id"],
                        option_id=option_id,
                        as_of=as_of,
                        available_minutes=available,
                    )
                    for option_id in option_ids
                ]
                return compare_plan_options(
                    options=tuple(bundle[4] for bundle in bundles),
                    decompositions={bundle[4].option_id: bundle[5] for bundle in bundles},
                    capacity_reports={bundle[4].option_id: bundle[6] for bundle in bundles},
                ).to_dict()
            except (
                ExplanationError,
                CapacityError,
                DecompositionError,
                PlanOptionError,
                PlanningSessionError,
                CopilotContractError,
                PlanningContextError,
                VaultAccessError,
            ) as exc:
                raise ProtocolError("copilot_comparison_invalid", str(exc)) from exc
        if method == "copilot.counterfactual":
            data = strict_object(
                params,
                allowed={
                    "session_id",
                    "option_id",
                    "as_of",
                    "before_available_minutes",
                    "available_minutes",
                },
                required={"session_id", "option_id", "as_of", "available_minutes"},
            )
            as_of = _iso_date(data["as_of"], "as_of")
            before_available = data.get("before_available_minutes")
            available = data.get("available_minutes")
            try:
                _, index, _, _, option, decomposition, before = self._copilot_bundle(
                    session_id=data["session_id"],
                    option_id=data["option_id"],
                    as_of=as_of,
                    available_minutes=before_available,
                )
                return recompute_capacity_counterfactual(
                    option=option,
                    decomposition=decomposition,
                    index=index,
                    before=before,
                    as_of=as_of,
                    available_minutes=available,
                ).to_dict()
            except (
                ExplanationError,
                CapacityError,
                DecompositionError,
                PlanOptionError,
                PlanningSessionError,
                CopilotContractError,
                PlanningContextError,
                VaultAccessError,
            ) as exc:
                raise ProtocolError("copilot_counterfactual_invalid", str(exc)) from exc
        if method == "copilot.capacity.check":
            data = strict_object(
                params,
                allowed={
                    "session_id",
                    "option_id",
                    "as_of",
                    "available_minutes",
                    "recurring_workloads",
                    "adaptive_durations",
                },
                required={"session_id", "option_id", "as_of"},
            )
            as_of = _iso_date(data["as_of"], "as_of")
            available = data.get("available_minutes")
            if available is not None and (type(available) is not int or available < 0):
                raise ProtocolError(
                    "invalid_params", "available_minutes must be non-negative or null."
                )
            raw_workloads = data.get("recurring_workloads", [])
            if not isinstance(raw_workloads, list) or not all(
                isinstance(item, dict) for item in raw_workloads
            ):
                raise ProtocolError(
                    "invalid_params", "recurring_workloads must be a list of objects."
                )
            try:
                workloads = tuple(
                    RecurringWorkload(
                        **strict_object(
                            item,
                            allowed={
                                "workload_id",
                                "title",
                                "minutes",
                                "kind",
                                "protected",
                                "source_ref",
                            },
                            required={"workload_id", "title", "minutes"},
                        )
                    )
                    for item in raw_workloads
                )
            except (TypeError, CapacityError, ProtocolError) as exc:
                raise ProtocolError("invalid_params", str(exc)) from exc
            adaptive = data.get("adaptive_durations")
            if adaptive is not None and (
                not isinstance(adaptive, dict) or not all(isinstance(key, str) for key in adaptive)
            ):
                raise ProtocolError(
                    "invalid_params", "adaptive_durations must be an object keyed by task ID."
                )
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
                options = generate_plan_options(
                    goal=goal,
                    session=session,
                    readiness=snapshot.envelope.readiness,
                    context=context,
                    index=index,
                    as_of=as_of,
                )
                option = next(
                    (item for item in options.options if item.option_id == data["option_id"]), None
                )
                if option is None:
                    raise CapacityError("selected option was not found")
                decomposition = decompose_plan_option(option=option, horizon=goal.horizon)
                return check_portfolio_capacity(
                    option=option,
                    decomposition=decomposition,
                    index=index,
                    as_of=as_of,
                    available_minutes=available,
                    recurring_workloads=workloads,
                    adaptive_durations=adaptive,
                ).to_dict()
            except (
                CapacityError,
                DecompositionError,
                PlanOptionError,
                PlanningSessionError,
                CopilotContractError,
                PlanningContextError,
                VaultAccessError,
            ) as exc:
                raise ProtocolError("copilot_capacity_invalid", str(exc)) from exc
        if method == "copilot.option.decompose":
            data = strict_object(
                params,
                allowed={"session_id", "option_id", "as_of", "existing_task_ids"},
                required={"session_id", "option_id", "as_of"},
            )
            existing = data.get("existing_task_ids", [])
            if not isinstance(existing, list) or not all(
                isinstance(item, str) for item in existing
            ):
                raise ProtocolError(
                    "invalid_params", "existing_task_ids must be a list of strings."
                )
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
                options = generate_plan_options(
                    goal=goal,
                    session=session,
                    readiness=snapshot.envelope.readiness,
                    context=context,
                    index=index,
                    as_of=as_of,
                )
                option = next(
                    (item for item in options.options if item.option_id == data["option_id"]), None
                )
                if option is None:
                    raise DecompositionError("selected option was not found")
                return decompose_plan_option(
                    option=option, horizon=goal.horizon, existing_task_ids=tuple(existing)
                ).to_dict()
            except (
                DecompositionError,
                PlanOptionError,
                PlanningSessionError,
                CopilotContractError,
                PlanningContextError,
                VaultAccessError,
            ) as exc:
                raise ProtocolError("copilot_decomposition_invalid", str(exc)) from exc
        if method == "copilot.options.generate":
            data = strict_object(
                params, allowed={"session_id", "as_of"}, required={"session_id", "as_of"}
            )
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
            except (
                PlanOptionError,
                PlanningSessionError,
                CopilotContractError,
                PlanningContextError,
                VaultAccessError,
            ) as exc:
                raise ProtocolError("copilot_options_invalid", str(exc)) from exc
        if method == "copilot.session.start":
            data = strict_object(
                params,
                allowed={
                    "goal_path",
                    "session_id",
                    "selected_context_refs",
                    "excluded_context_refs",
                },
                required={"goal_path"},
            )
            for key in ("selected_context_refs", "excluded_context_refs"):
                if key in data:
                    value = data[key]
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) for item in value
                    ):
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
                allowed={
                    "session_id",
                    "question_id",
                    "response_kind",
                    "value",
                    "expected_revision",
                },
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
            for key in (
                "include_paths",
                "exclude_paths",
                "redact_terms",
                "allowed_sensitive_roots",
            ):
                if key in data:
                    value = data[key]
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) for item in value
                    ):
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
            data = strict_object(
                params, allowed={"protocol", "client_version"}, required={"protocol"}
            )
            protocol = data["protocol"]
            if (
                not isinstance(protocol, str)
                or protocol.split(".", 1)[0] != PROTOCOL_VERSION.split(".", 1)[0]
            ):
                raise ProtocolError(
                    "protocol_mismatch",
                    "The plugin and engine protocol versions are incompatible.",
                    {"engine_protocol": PROTOCOL_VERSION},
                )
            return {
                "protocol": PROTOCOL_VERSION,
                "engine_version": ENGINE_VERSION,
                "runtime_schema": DESKTOP_RUNTIME_SCHEMA_VERSION,
                "capabilities": list(CAPABILITIES),
                "actor_id": self.actor_id,
            }
        if method == "feedback.proposal.create":
            data = strict_object(
                params,
                allowed={
                    "kind",
                    "target_path",
                    "evidence_fingerprint",
                    "evidence_event_ids",
                    "confidence",
                    "expected_effect",
                    "alternatives",
                    "task_id",
                    "changes",
                    "decomposition_titles",
                    "agent_requested",
                },
                required={
                    "kind",
                    "target_path",
                    "evidence_fingerprint",
                    "evidence_event_ids",
                    "confidence",
                    "expected_effect",
                    "alternatives",
                },
            )
            for key in ("evidence_event_ids", "alternatives", "decomposition_titles"):
                if key in data:
                    value = data[key]
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) for item in value
                    ):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                    data[key] = tuple(value)
            try:
                return asdict(
                    create_feedback_proposal(
                        vault_root=self.daily.vault_root,
                        request=FeedbackProposalRequest(**data),
                        actor_id=self.actor_id,
                    )
                )
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
            data = strict_object(
                params,
                allowed={
                    "idempotency_key",
                    "expected_hash",
                    "mode",
                    "disabled_dimensions",
                    "exclude_event_id",
                    "include_event_id",
                    "dismiss_diagnosis_id",
                    "dismiss_fingerprint",
                    "restore_diagnosis_id",
                    "reset_before",
                    "reset_reason",
                },
                required={"idempotency_key"},
            )
            if "disabled_dimensions" in data:
                value = data["disabled_dimensions"]
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ProtocolError(
                        "invalid_params", "disabled_dimensions must be a list of strings."
                    )
                data["disabled_dimensions"] = tuple(value)
            if data.get("reset_before") is not None:
                data["reset_before"] = _iso_date(data["reset_before"], "reset_before")
            return self.feedback_controls.update(PreferencesUpdate(**data)).to_dict()
        if method == "feedback.outcome.correct":
            data = strict_object(
                params,
                allowed={
                    "idempotency_key",
                    "plan_path",
                    "corrects_event_id",
                    "outcome",
                    "day",
                    "expected_hash",
                    "actual_minutes",
                    "completion_fraction",
                    "reason",
                },
                required={
                    "idempotency_key",
                    "plan_path",
                    "corrects_event_id",
                    "outcome",
                    "day",
                    "expected_hash",
                },
            )
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
                    tuple(disabled) if disabled is not None else preferences.disabled_dimensions
                ),
                dismissed_diagnosis_fingerprints=preferences.dismissed_fingerprints(),
            ).to_dict()
        if method == "feedback.explain":
            data = strict_object(
                params,
                allowed={
                    "task_id",
                    "as_of",
                    "available_minutes",
                    "energy",
                    "motivation",
                    "mode_filter",
                    "adaptive_mode",
                    "time_window",
                    "disabled_dimensions",
                },
                required={"task_id", "as_of", "available_minutes", "energy", "motivation"},
            )
            task_id = data.pop("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise ProtocolError("invalid_params", "task_id must be a non-empty string.")
            as_of = _iso_date(data.pop("as_of"), "as_of")
            disabled = data.pop("disabled_dimensions", ())
            if not isinstance(disabled, list) or not all(
                isinstance(item, str) for item in disabled
            ):
                raise ProtocolError(
                    "invalid_params", "disabled_dimensions must be a list of strings."
                )
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
                return explain_adaptive_result(
                    result=result, actions=actions, task_id=task_id
                ).to_dict()
            except KeyError as exc:
                raise ProtocolError("not_found", str(exc)) from exc
        if method == "feedback.plan":
            data = strict_object(
                params,
                allowed={
                    "as_of",
                    "available_minutes",
                    "energy",
                    "motivation",
                    "mode_filter",
                    "adaptive_mode",
                    "time_window",
                    "disabled_dimensions",
                },
                required={"as_of", "available_minutes", "energy", "motivation"},
            )
            as_of = _iso_date(data.pop("as_of"), "as_of")
            disabled = data.pop("disabled_dimensions", ())
            if not isinstance(disabled, list) or not all(
                isinstance(item, str) for item in disabled
            ):
                raise ProtocolError(
                    "invalid_params", "disabled_dimensions must be a list of strings."
                )
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
            data = strict_object(
                params,
                allowed={"as_of", "minimum_repetitions", "recency_days", "dismissed_fingerprints"},
                required={"as_of"},
            )
            as_of = _iso_date(data.pop("as_of"), "as_of")
            dismissed = data.pop("dismissed_fingerprints", ())
            if not isinstance(dismissed, list) or not all(
                isinstance(item, str) for item in dismissed
            ):
                raise ProtocolError(
                    "invalid_params", "dismissed_fingerprints must be a list of strings."
                )
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
            data = strict_object(
                params,
                allowed={
                    "task_id",
                    "current_energy",
                    "current_motivation",
                    "mode",
                    "declared_minutes",
                    "time_window",
                    "blocked",
                    "as_of",
                    "disabled_dimensions",
                },
                required={"task_id", "as_of"},
            )
            as_of = _iso_date(data.pop("as_of"), "as_of")
            disabled = data.pop("disabled_dimensions", ())
            if not isinstance(disabled, list) or not all(
                isinstance(item, str) for item in disabled
            ):
                raise ProtocolError(
                    "invalid_params", "disabled_dimensions must be a list of strings."
                )
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
            data = strict_object(
                params,
                allowed={
                    "task_id",
                    "declared_minutes",
                    "task_shape",
                    "plan_id",
                    "mode",
                    "as_of",
                    "enabled",
                },
                required={"task_id", "declared_minutes", "as_of"},
            )
            as_of = _iso_date(data.pop("as_of"), "as_of")
            _, _, _, observations = self._feedback_context(as_of)
            return calibrate_duration(observations=observations, as_of=as_of, **data).to_dict()
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
            data = strict_object(
                params,
                allowed={
                    "enabled",
                    "timezone",
                    "morning",
                    "evening",
                    "weekly_day",
                    "weekly",
                    "quiet_start",
                    "quiet_end",
                    "privacy",
                    "grace_hours",
                },
            )
            config = ScheduleConfig(**data)
            save_schedule(self.daily.vault_root, config)
            return asdict(config)
        if method == "scheduler.service.status":
            strict_object(params, allowed=set())
            return BackgroundServiceInstaller(self.daily.runtime_dir).status()
        if method == "scheduler.service.install":
            data = strict_object(params, allowed={"command"}, required={"command"})
            if not isinstance(data["command"], list) or not all(
                isinstance(item, str) for item in data["command"]
            ):
                raise ProtocolError("invalid_params", "command must be a list of strings.")
            path = BackgroundServiceInstaller(self.daily.runtime_dir).install(
                command=tuple(data["command"])
            )
            return {"installed": True, "descriptor": path.name}
        if method == "scheduler.service.uninstall":
            strict_object(params, allowed=set())
            BackgroundServiceInstaller(self.daily.runtime_dir).uninstall()
            return {"installed": False}
        if method == "proposal.list":
            try:
                strict_object(params, allowed=set())
                return [item.to_dict() for item in self.proposals.list()]
            except ValueError as exc:
                raise ProtocolError("proposal_invalid", str(exc)) from exc
        if method == "proposal.inspect":
            try:
                data = strict_object(params, allowed={"proposal_id"}, required={"proposal_id"})
                return self.proposals.inspect(data["proposal_id"]).to_dict()
            except ProtocolError:
                raise
            except ValueError as exc:
                raise ProtocolError("proposal_invalid", str(exc)) from exc
        if method == "proposal.prepare":
            try:
                data = strict_object(
                    params,
                    allowed={"proposal_id", "action"},
                    required={"proposal_id", "action"},
                )
                return asdict(self.proposals.prepare(**data))
            except ProtocolError:
                raise
            except ValueError as exc:
                raise ProtocolError("proposal_invalid", str(exc)) from exc
        if method == "proposal.execute":
            try:
                data = strict_object(
                    params,
                    allowed={"proposal_id", "action", "token", "reason"},
                    required={"proposal_id", "action", "token"},
                )
                return self.proposals.execute(**data)
            except ProtocolError:
                raise
            except ValueError as exc:
                raise ProtocolError("proposal_invalid", str(exc)) from exc
        if method == "ownership.orphans.list":
            try:
                strict_object(params, allowed=set())
                return list(self.proposals.list_orphaned_ownership())
            except ValueError as exc:
                raise ProtocolError("ownership_invalid", str(exc)) from exc
        if method == "ownership.release.proposal.create":
            try:
                data = strict_object(
                    params,
                    allowed={"target_path"},
                    required={"target_path"},
                )
                return self.proposals.create_ownership_release_proposal(
                    data["target_path"]
                )
            except ProtocolError:
                raise
            except ValueError as exc:
                raise ProtocolError("ownership_invalid", str(exc)) from exc
        if method == "system.status":
            strict_object(params, allowed=set())
            return asdict(
                collect_status(self.config, Registry(self.daily.runtime_dir / "registry.db"))
            )
        if method.startswith("review.artifact.") or method == "review.proposal.create":
            artifacts = ReviewArtifactService(
                vault_root=self.daily.vault_root,
                runtime_dir=self.daily.runtime_dir,
                actor_id=self.actor_id,
            )
            progress = ReviewProgressService(artifacts)
            decisions = ReviewDecisionService(artifacts)
            try:
                if method == "review.artifact.open":
                    data = strict_object(
                        params,
                        allowed={
                            "kind",
                            "day",
                            "timezone",
                            "now",
                            "idempotency_key",
                            "phase",
                            "refresh",
                        },
                        required={"kind", "day", "timezone", "now", "idempotency_key"},
                    )
                    kind = data["kind"]
                    if kind == "daily":
                        state = open_daily_review(
                            service=artifacts,
                            runtime_dir=self.daily.runtime_dir,
                            day=_iso_date(data["day"], "day"),
                            timezone=str(data["timezone"]),
                            now=_iso_datetime(data["now"], "now"),
                            idempotency_key=str(data["idempotency_key"]),
                            phase=str(data.get("phase", "morning")),
                            refresh=bool(data.get("refresh", True)),
                        )
                    elif kind == "weekly":
                        state = open_weekly_review(
                            service=artifacts,
                            runtime_dir=self.daily.runtime_dir,
                            day=_iso_date(data["day"], "day"),
                            timezone=str(data["timezone"]),
                            now=_iso_datetime(data["now"], "now"),
                            idempotency_key=str(data["idempotency_key"]),
                            refresh=bool(data.get("refresh", True)),
                        )
                    else:
                        raise ProtocolError("invalid_params", "kind must be daily or weekly.")
                    return _jsonable(state.to_dict())
                if method == "review.artifact.load":
                    data = strict_object(
                        params, allowed={"review_id", "path", "now"}, required={"now"}
                    )
                    if bool(data.get("review_id")) == bool(data.get("path")):
                        raise ProtocolError(
                            "invalid_params", "Provide exactly one of review_id or path."
                        )
                    artifact = (
                        artifacts.load_id(str(data["review_id"]))
                        if data.get("review_id")
                        else artifacts.load_path(str(data["path"]))
                    )
                    snapshot = build_review_snapshot(
                        vault_root=self.daily.vault_root,
                        runtime_dir=self.daily.runtime_dir,
                        kind=artifact.metadata.review_kind,
                        day=artifact.metadata.period_start,
                        generated_at=_iso_datetime(data["now"], "now"),
                    )
                    return _jsonable(
                        {"artifact": artifact.to_dict(), "snapshot": snapshot.to_dict()}
                    )
                if method == "review.artifact.refresh":
                    data = strict_object(
                        params,
                        allowed={"review_id", "expected_hash", "now", "idempotency_key"},
                        required={"review_id", "expected_hash", "now", "idempotency_key"},
                    )
                    artifact = artifacts.load_id(str(data["review_id"]))
                    if artifact.content_hash != data["expected_hash"]:
                        raise ProtocolError(
                            "stale_write",
                            "The review changed after it was opened.",
                            {"actual_hash": artifact.content_hash, "path": artifact.path},
                        )
                    updated, snapshot = refresh_review_snapshot(
                        service=artifacts,
                        artifact=artifact,
                        runtime_dir=self.daily.runtime_dir,
                        generated_at=_iso_datetime(data["now"], "now"),
                        idempotency_key=str(data["idempotency_key"]),
                    )
                    return _jsonable(
                        {"artifact": updated.to_dict(), "snapshot": snapshot.to_dict()}
                    )
                if method == "review.artifact.migration.preview":
                    strict_object(params, allowed=set())
                    return preview_review_migration(
                        vault_root=self.daily.vault_root,
                        runtime_dir=self.daily.runtime_dir,
                        actor_id=self.actor_id,
                    ).to_dict()
                if method == "review.artifact.migration.apply":
                    data = strict_object(
                        params,
                        allowed={"now", "idempotency_key", "expected_source_hashes"},
                        required={"now", "idempotency_key"},
                    )
                    expected = data.get("expected_source_hashes")
                    if expected is not None and (
                        not isinstance(expected, dict)
                        or not all(
                            isinstance(key, str) and isinstance(value, str)
                            for key, value in expected.items()
                        )
                    ):
                        raise ProtocolError(
                            "invalid_params",
                            "expected_source_hashes must be an object of path-to-hash strings.",
                        )
                    return apply_review_migration(
                        vault_root=self.daily.vault_root,
                        runtime_dir=self.daily.runtime_dir,
                        actor_id=self.actor_id,
                        now=_iso_datetime(data["now"], "now"),
                        idempotency_key=str(data["idempotency_key"]),
                        expected_source_hashes=expected,
                    ).to_dict()
                if method == "review.artifact.rebuild":
                    strict_object(params, allowed=set())
                    return rebuild_review_state(
                        vault_root=self.daily.vault_root,
                        runtime_dir=self.daily.runtime_dir,
                        actor_id=self.actor_id,
                    ).to_dict()
                if method == "review.artifact.history":
                    data = strict_object(params, allowed={"kind", "limit"})
                    kind = data.get("kind")
                    if kind is not None and kind not in {"daily", "weekly"}:
                        raise ProtocolError("invalid_params", "kind must be daily or weekly.")
                    limit = data.get("limit", 50)
                    if not isinstance(limit, int) or limit < 1 or limit > 200:
                        raise ProtocolError("invalid_params", "limit must be between 1 and 200.")
                    return _jsonable(
                        [
                            item.to_dict()
                            for item in list_review_history(service=artifacts, kind=kind)[:limit]
                        ]
                    )
                if method == "review.artifact.section":
                    data = strict_object(
                        params,
                        allowed={
                            "review_id",
                            "phase_id",
                            "section_id",
                            "action",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                        },
                        required={
                            "review_id",
                            "phase_id",
                            "section_id",
                            "action",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                        },
                    )
                    return _jsonable(
                        progress.update_section(
                            now=_iso_datetime(data.pop("now"), "now"), **data
                        ).to_dict()
                    )
                if method == "review.artifact.phase":
                    data = strict_object(
                        params,
                        allowed={
                            "review_id",
                            "phase_id",
                            "action",
                            "required_sections",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                        },
                        required={
                            "review_id",
                            "phase_id",
                            "action",
                            "required_sections",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                        },
                    )
                    required = data.pop("required_sections")
                    if not isinstance(required, list) or not all(
                        isinstance(item, str) for item in required
                    ):
                        raise ProtocolError(
                            "invalid_params", "required_sections must be a list of strings."
                        )
                    return _jsonable(
                        progress.update_phase(
                            required_sections=tuple(required),
                            now=_iso_datetime(data.pop("now"), "now"),
                            **data,
                        ).to_dict()
                    )
                if method == "review.artifact.answer":
                    data = strict_object(
                        params,
                        allowed={
                            "review_id",
                            "prompt_id",
                            "value",
                            "phase_id",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                        },
                        required={
                            "review_id",
                            "prompt_id",
                            "value",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                        },
                    )
                    return _jsonable(
                        progress.answer(now=_iso_datetime(data.pop("now"), "now"), **data).to_dict()
                    )
                if method == "review.artifact.decide":
                    data = strict_object(
                        params,
                        allowed={
                            "review_id",
                            "item_id",
                            "evidence_fingerprint",
                            "decision",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                            "note",
                            "proposal_id",
                        },
                        required={
                            "review_id",
                            "item_id",
                            "evidence_fingerprint",
                            "decision",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                        },
                    )
                    return _jsonable(
                        decisions.decide(
                            now=_iso_datetime(data.pop("now"), "now"), **data
                        ).to_dict()
                    )
                if method == "review.artifact.complete":
                    data = strict_object(
                        params,
                        allowed={"review_id", "expected_hash", "idempotency_key", "now"},
                        required={"review_id", "expected_hash", "idempotency_key", "now"},
                    )
                    return _jsonable(
                        progress.complete_review(
                            now=_iso_datetime(data.pop("now"), "now"), **data
                        ).to_dict()
                    )
                if method == "review.artifact.skip":
                    data = strict_object(
                        params,
                        allowed={"review_id", "expected_hash", "idempotency_key", "now", "note"},
                        required={"review_id", "expected_hash", "idempotency_key", "now"},
                    )
                    return _jsonable(
                        progress.skip_review(
                            now=_iso_datetime(data.pop("now"), "now"), **data
                        ).to_dict()
                    )
                if method == "review.artifact.reopen":
                    data = strict_object(
                        params,
                        allowed={
                            "review_id",
                            "expected_hash",
                            "idempotency_key",
                            "now",
                            "phase_id",
                        },
                        required={"review_id", "expected_hash", "idempotency_key", "now"},
                    )
                    return _jsonable(
                        progress.reopen_review(
                            now=_iso_datetime(data.pop("now"), "now"), **data
                        ).to_dict()
                    )
                if method == "review.proposal.create":
                    data = strict_object(
                        params,
                        allowed={
                            "review_id",
                            "item_id",
                            "evidence_fingerprint",
                            "target_path",
                            "expected_target_hash",
                            "action",
                            "value",
                            "rationale",
                            "task_id",
                            "now",
                        },
                        required={
                            "review_id",
                            "item_id",
                            "evidence_fingerprint",
                            "target_path",
                            "expected_target_hash",
                            "action",
                            "value",
                            "rationale",
                        },
                    )
                    moment = (
                        _iso_datetime(data.pop("now"), "now")
                        if data.get("now") is not None
                        else None
                    )
                    request = ReviewProposalRequest(**data)
                    return create_review_proposal(
                        vault_root=self.daily.vault_root,
                        request=request,
                        actor_id=self.actor_id,
                        now=moment,
                    ).to_dict()
            except ProtocolError:
                raise
            except (DailyInteractionError, ValueError, TypeError) as exc:
                code = getattr(exc, "code", "review_artifact_invalid")
                data = getattr(exc, "data", None)
                raise ProtocolError(code, str(exc), data) from exc
        if method == "review.build":
            data = strict_object(params, allowed={"kind", "day"}, required={"kind", "day"})
            data["day"] = _iso_date(data["day"], "day")
            return build_review_workflow(
                vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir, **data
            ).to_dict()
        if method == "review.progress":
            data = strict_object(
                params,
                allowed={"review_id", "completed_sections", "skipped_sections", "current_section"},
                required={"review_id"},
            )
            for key in ("completed_sections", "skipped_sections"):
                if key in data:
                    value = data[key]
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) for item in value
                    ):
                        raise ProtocolError("invalid_params", f"{key} must be a list of strings.")
                    data[key] = tuple(value)
            return asdict(save_progress(self.daily.runtime_dir, **data))
        if method == "review.save":
            data = strict_object(
                params,
                allowed={"kind", "day", "idempotency_key", "expected_hash"},
                required={"kind", "day", "idempotency_key"},
            )
            day_value = _iso_date(data.pop("day"), "day")
            workflow = build_review_workflow(
                vault_root=self.daily.vault_root,
                runtime_dir=self.daily.runtime_dir,
                kind=data.pop("kind"),
                day=day_value,
            )
            return save_review_note(
                vault_root=self.daily.vault_root,
                runtime_dir=self.daily.runtime_dir,
                actor_id=self.actor_id,
                workflow=workflow,
                **data,
            )
        if method == "study.plan":
            data = strict_object(
                params, allowed={"day", "minutes", "topic"}, required={"day", "minutes"}
            )
            data["day"] = _iso_date(data["day"], "day")
            return asdict(
                self.study_sessions.plan(
                    day=data["day"], minutes=data["minutes"], topic=data.get("topic")
                )
            )
        if method == "study.session.start":
            data = strict_object(
                params,
                allowed={"day", "minutes", "topic", "session_id", "now"},
                required={"day", "minutes"},
            )
            data["day"] = _iso_date(data["day"], "day")
            if data.get("now") is not None:
                data["now"] = datetime.fromisoformat(data["now"])
            return self.study_sessions.start(**data).to_dict()
        if method == "study.session.transition":
            data = strict_object(
                params,
                allowed={"session_id", "action", "now", "actual_minutes", "expected_journal_hash"},
                required={"session_id", "action"},
            )
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
            return evaluate_attention(
                vault_root=self.daily.vault_root, runtime_dir=self.daily.runtime_dir, as_of=moment
            ).to_dict()
        if method == "attention.preference":
            data = strict_object(
                params,
                allowed={
                    "item_id",
                    "snooze_until",
                    "dismiss",
                    "morning_checkin",
                    "evening_checkin",
                    "inbox_days",
                },
            )
            return asdict(save_preference(self.daily.runtime_dir, **data))  # type: ignore[arg-type]
        if method == "today.get":
            data = strict_object(
                params,
                allowed={
                    "day",
                    "available_minutes",
                    "study_minutes",
                    "energy",
                    "motivation",
                    "mode",
                    "adaptive_mode",
                },
                required={"day"},
            )
            data["day"] = _iso_date(data["day"], "day")
            dashboard = build_today_dashboard(
                vault_root=self.daily.vault_root,
                runtime_dir=self.daily.runtime_dir,
                inputs=TodayInputs(**data),
            )  # type: ignore[arg-type]
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
            raise ProtocolError(
                exc.code, exc.message, {"remediation": exc.remediation, **(exc.data or {})}
            ) from exc
        if self._notify is not None:
            self._notify(
                {
                    "jsonrpc": "2.0",
                    "method": "vault.changed",
                    "params": {"path": result["reference"]["path"]},
                    "meta": {"protocol": PROTOCOL_VERSION},
                }
            )
        return result

    def _dispatch_daily(self, method: str, params: object) -> dict[str, Any]:
        if method == "daily.capture":
            data = strict_object(
                params,
                allowed={
                    "idempotency_key",
                    "kind",
                    "title",
                    "content",
                    "target_path",
                    "plan_path",
                    "task",
                    "metadata",
                    "expected_hash",
                },
                required={"idempotency_key", "kind", "title"},
            )
            request = QuickCaptureRequest(**data)  # type: ignore[arg-type]
            return self.daily.quick_capture(request).to_dict()
        if method == "daily.checkin":
            data = strict_object(
                params,
                allowed={
                    "idempotency_key",
                    "day",
                    "period",
                    "metrics",
                    "activities",
                    "note",
                    "expected_hash",
                },
                required={"idempotency_key", "day", "period", "metrics"},
            )
            data["day"] = _iso_date(data["day"], "day")
            if "activities" in data:
                activities = data["activities"]
                if not isinstance(activities, list) or not all(
                    isinstance(item, str) for item in activities
                ):
                    raise ProtocolError("invalid_params", "activities must be a list of strings.")
                data["activities"] = tuple(activities)
            request = CheckInRequest(**data)  # type: ignore[arg-type]
            return self.daily.update_checkin(request).to_dict()
        if method == "daily.task_outcome":
            data = strict_object(
                params,
                allowed={
                    "idempotency_key",
                    "plan_path",
                    "task_id",
                    "outcome",
                    "day",
                    "expected_hash",
                    "planned_minutes",
                    "actual_minutes",
                    "energy_before",
                    "energy_after",
                    "motivation_before",
                    "difficulty",
                    "satisfaction",
                    "reason",
                    "note",
                    "deferred_until",
                    "started_at",
                    "ended_at",
                    "source_ref",
                },
                required={
                    "idempotency_key",
                    "plan_path",
                    "task_id",
                    "outcome",
                    "day",
                    "expected_hash",
                },
            )
            data["day"] = _iso_date(data["day"], "day")
            if data.get("deferred_until") is not None:
                data["deferred_until"] = _iso_date(data["deferred_until"], "deferred_until")
            request = TaskOutcomeRequest(**data)  # type: ignore[arg-type]
            return self.daily.record_task_outcome(request).to_dict()
        if method == "daily.review":
            data = strict_object(
                params,
                allowed={"idempotency_key", "kind", "day", "facts_markdown", "expected_hash"},
                required={"idempotency_key", "kind", "day", "facts_markdown"},
            )
            data["day"] = _iso_date(data["day"], "day")
            request = ReviewNoteRequest(**data)  # type: ignore[arg-type]
            return self.daily.create_review_note(request).to_dict()
        raise ProtocolError(
            "method_not_found",
            "The requested bridge method is not allowlisted.",
            {"method": method},
        )
