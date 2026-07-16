"""Recoverable guided clarification sessions for goal-to-plan planning."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, cast

from lifeos.vault import VaultAccessError, read_vault_markdown

from .contracts import (
    CopilotContractError,
    PlanningAnswer,
    PlanningDecision,
    PlanningSession,
    ResponseKind,
    build_copilot_index,
    content_hash,
    parse_goal_note,
)
from .readiness import GoalReadinessReport, evaluate_goal_readiness

QuestionCategory = Literal[
    "purpose",
    "desired-change",
    "horizon",
    "constraints",
    "non-goals",
    "success-evidence",
    "uncertainty",
    "tradeoffs",
    "current-commitments",
]
QuestionSource = Literal["deterministic", "agent-suggestion"]
SessionOutcome = Literal[
    "ready-to-plan",
    "experiment",
    "park",
    "continue-reflecting",
    "link-existing-plan",
    "abandon",
]

_ALLOWED_OUTCOMES: tuple[SessionOutcome, ...] = (
    "ready-to-plan",
    "experiment",
    "park",
    "continue-reflecting",
    "link-existing-plan",
    "abandon",
)
_REQUIRED_QUESTION_IDS = ("purpose", "desired-change", "horizon")
_OPTIONAL_QUESTION_IDS = (
    "constraints",
    "non-goals",
    "success-evidence",
    "uncertainty",
    "tradeoffs",
    "current-commitments",
)
_UNSAFE_QUESTION_RE = re.compile(
    r"\b(diagnos(?:e|is)|disorder|trauma|lazy|failure|real motive|subconscious)\b",
    re.IGNORECASE,
)


class PlanningSessionError(ValueError):
    pass


class SessionConflictError(PlanningSessionError):
    pass


@dataclass(frozen=True, slots=True)
class ClarificationQuestion:
    question_id: str
    category: QuestionCategory
    prompt: str
    required: bool
    source: QuestionSource
    reason: str

    def __post_init__(self) -> None:
        if not self.question_id or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", self.question_id):
            raise PlanningSessionError("question_id is invalid")
        if self.category not in {
            "purpose",
            "desired-change",
            "horizon",
            "constraints",
            "non-goals",
            "success-evidence",
            "uncertainty",
            "tradeoffs",
            "current-commitments",
        }:
            raise PlanningSessionError("question category is invalid")
        if not self.prompt.strip() or self.prompt != self.prompt.strip() or len(self.prompt) > 240:
            raise PlanningSessionError("question prompt must be a trimmed string up to 240 characters")
        if _UNSAFE_QUESTION_RE.search(self.prompt):
            raise PlanningSessionError("question prompt crosses the coaching safety boundary")
        if not self.reason.strip():
            raise PlanningSessionError("question reason is required")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QuestionSuggestion:
    question_id: str
    category: QuestionCategory
    prompt: str
    reason: str


class ClarificationQuestionAdapter(Protocol):
    """Provider-neutral boundary for one optional visible question."""

    def suggest_question(
        self,
        *,
        goal_title: str,
        visible_answers: tuple[PlanningAnswer, ...],
        unresolved_categories: tuple[QuestionCategory, ...],
    ) -> QuestionSuggestion | None: ...


@dataclass(frozen=True, slots=True)
class SessionEnvelope:
    session: PlanningSession
    readiness: GoalReadinessReport
    question_history: tuple[ClarificationQuestion, ...]
    current_question: ClarificationQuestion | None
    adapter_diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "session": self.session.to_dict(),
            "readiness": self.readiness.to_dict(),
            "question_history": [item.to_dict() for item in self.question_history],
            "current_question": self.current_question.to_dict() if self.current_question else None,
            "adapter_diagnostics": list(self.adapter_diagnostics),
        }


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    envelope: SessionEnvelope
    source_stale: bool
    allowed_outcomes: tuple[SessionOutcome, ...]
    recommended_outcomes: tuple[SessionOutcome, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            **self.envelope.to_dict(),
            "source_stale": self.source_stale,
            "allowed_outcomes": list(self.allowed_outcomes),
            "recommended_outcomes": list(self.recommended_outcomes),
        }


class PlanningSessionService:
    def __init__(
        self,
        *,
        vault_root: Path,
        runtime_dir: Path,
        adapter: ClarificationQuestionAdapter | None = None,
    ) -> None:
        self.vault_root = vault_root.resolve()
        self.runtime_dir = runtime_dir.resolve()
        self.sessions_dir = self.runtime_dir / "planning-sessions"
        self.adapter = adapter

    def start(
        self,
        *,
        goal_path: str,
        session_id: str | None = None,
        selected_context_refs: tuple[str, ...] = (),
        excluded_context_refs: tuple[str, ...] = (),
    ) -> SessionSnapshot:
        source = self._read_goal(goal_path)
        goal = parse_goal_note(path=goal_path, content=source)
        index = build_copilot_index(self.vault_root)
        readiness = evaluate_goal_readiness(goal, index=index)
        sid = session_id or f"session-{uuid.uuid4().hex}"
        if self._path(sid).exists() or self._temporary_path(sid).exists():
            raise SessionConflictError(f"planning session already exists: {sid}")
        session = PlanningSession(
            schema_version=1,
            session_id=sid,
            goal_ref=goal_path,
            goal_hash=goal.content_hash,
            status="ready" if readiness.path in {"plan", "link-existing-plan"} else "clarifying",
            selected_context_refs=selected_context_refs,
            excluded_context_refs=excluded_context_refs,
        )
        question, diagnostics = self._next_question(
            goal_title=goal.title,
            goal=goal,
            readiness=readiness,
            answers=session.answers,
            history=(),
        )
        envelope = SessionEnvelope(
            session=session,
            readiness=readiness,
            question_history=(() if question is None else (question,)),
            current_question=question,
            adapter_diagnostics=diagnostics,
        )
        self._save(envelope)
        return self._snapshot(envelope)

    def get(self, session_id: str) -> SessionSnapshot:
        envelope = self._load(session_id)
        return self._snapshot(envelope)

    def answer(
        self,
        *,
        session_id: str,
        question_id: str,
        response_kind: ResponseKind,
        value: str | None = None,
        expected_revision: int,
    ) -> SessionSnapshot:
        envelope = self._load(session_id)
        session = envelope.session
        if session.source_revision != expected_revision:
            raise SessionConflictError(
                f"session revision is stale: expected {expected_revision}, current {session.source_revision}"
            )
        question = envelope.current_question
        if question is None or question.question_id != question_id:
            raise PlanningSessionError("question is not the current visible question")
        answer = PlanningAnswer(question_id=question_id, response_kind=response_kind, value=value)
        answers = tuple(item for item in session.answers if item.question_id != question_id) + (answer,)
        source = self._read_goal(session.goal_ref)
        goal = parse_goal_note(path=session.goal_ref, content=source)
        readiness = evaluate_goal_readiness(goal, index=build_copilot_index(self.vault_root))
        next_question, diagnostics = self._next_question(
            goal_title=goal.title,
            goal=goal,
            readiness=readiness,
            answers=answers,
            history=envelope.question_history,
        )
        all_required_answered = _required_questions_answered(goal, answers)
        updated_session = PlanningSession(
            schema_version=session.schema_version,
            session_id=session.session_id,
            goal_ref=session.goal_ref,
            goal_hash=session.goal_hash,
            status="ready" if all_required_answered and next_question is None else "clarifying",
            answers=answers,
            selected_context_refs=session.selected_context_refs,
            excluded_context_refs=session.excluded_context_refs,
            decisions=session.decisions,
            selected_option_id=session.selected_option_id,
            proposal_ids=session.proposal_ids,
            source_revision=session.source_revision + 1,
        )
        history = envelope.question_history
        if next_question is not None and all(
            item.question_id != next_question.question_id for item in history
        ):
            history = (*history, next_question)
        updated = SessionEnvelope(
            session=updated_session,
            readiness=readiness,
            question_history=history,
            current_question=next_question,
            adapter_diagnostics=(*envelope.adapter_diagnostics, *diagnostics),
        )
        self._save(updated)
        return self._snapshot(updated)

    def close(
        self,
        *,
        session_id: str,
        outcome: SessionOutcome,
        label: str,
        rationale: str | None = None,
        expected_revision: int,
    ) -> SessionSnapshot:
        if outcome not in _ALLOWED_OUTCOMES:
            raise PlanningSessionError("unsupported session outcome")
        envelope = self._load(session_id)
        session = envelope.session
        if session.source_revision != expected_revision:
            raise SessionConflictError(
                f"session revision is stale: expected {expected_revision}, current {session.source_revision}"
            )
        if outcome == "ready-to-plan" and not _answers_support_plan(envelope):
            raise PlanningSessionError("required clarification remains unresolved")
        decision = PlanningDecision(
            decision_id=f"decision-{session.source_revision + 1}",
            kind=cast(Any, outcome),
            label=label,
            rationale=rationale,
        )
        status_by_outcome = {
            "ready-to-plan": "ready",
            "experiment": "closed",
            "park": "parked",
            "continue-reflecting": "closed",
            "link-existing-plan": "closed",
            "abandon": "abandoned",
        }
        updated_session = PlanningSession(
            schema_version=session.schema_version,
            session_id=session.session_id,
            goal_ref=session.goal_ref,
            goal_hash=session.goal_hash,
            status=cast(Any, status_by_outcome[outcome]),
            answers=session.answers,
            selected_context_refs=session.selected_context_refs,
            excluded_context_refs=session.excluded_context_refs,
            decisions=(*session.decisions, decision),
            selected_option_id=session.selected_option_id,
            proposal_ids=session.proposal_ids,
            source_revision=session.source_revision + 1,
        )
        updated = SessionEnvelope(
            session=updated_session,
            readiness=envelope.readiness,
            question_history=envelope.question_history,
            current_question=None,
            adapter_diagnostics=envelope.adapter_diagnostics,
        )
        self._save(updated)
        return self._snapshot(updated)

    def _next_question(
        self,
        *,
        goal_title: str,
        goal: Any,
        readiness: GoalReadinessReport,
        answers: tuple[PlanningAnswer, ...],
        history: tuple[ClarificationQuestion, ...],
    ) -> tuple[ClarificationQuestion | None, tuple[str, ...]]:
        seen = {item.question_id for item in history}
        answered = {item.question_id for item in answers}
        templates = _deterministic_questions(goal)
        for question_id in _REQUIRED_QUESTION_IDS:
            if (
                question_id not in answered
                and question_id not in seen
                and question_id in templates
                and templates[question_id].required
            ):
                return templates[question_id], ()
        unresolved = tuple(
            cast(QuestionCategory, item)
            for item in _OPTIONAL_QUESTION_IDS
            if item not in answered and item not in seen
        )
        diagnostics: list[str] = []
        if self.adapter is not None and _required_questions_answered(goal, answers):
            try:
                suggestion = self.adapter.suggest_question(
                    goal_title=goal_title,
                    visible_answers=answers,
                    unresolved_categories=unresolved,
                )
                if suggestion is not None:
                    question = ClarificationQuestion(
                        question_id=suggestion.question_id,
                        category=suggestion.category,
                        prompt=suggestion.prompt,
                        required=False,
                        source="agent-suggestion",
                        reason=suggestion.reason,
                    )
                    if question.question_id in seen or question.question_id in answered:
                        raise PlanningSessionError("adapter repeated a previous question")
                    if question.category not in unresolved and unresolved:
                        raise PlanningSessionError("adapter question is not relevant to unresolved scope")
                    return question, ()
            except Exception as exc:
                diagnostics.append(f"adapter-fallback: {exc}")
        for question_id in _OPTIONAL_QUESTION_IDS:
            if question_id not in answered and question_id not in seen and question_id in templates:
                return templates[question_id], tuple(diagnostics)
        return None, tuple(diagnostics)

    def _snapshot(self, envelope: SessionEnvelope) -> SessionSnapshot:
        try:
            current = self._read_goal(envelope.session.goal_ref)
            stale = content_hash(current) != envelope.session.goal_hash
        except (PlanningSessionError, CopilotContractError):
            stale = True
        recommended = _recommended_outcomes(envelope)
        return SessionSnapshot(
            envelope=envelope,
            source_stale=stale,
            allowed_outcomes=_ALLOWED_OUTCOMES,
            recommended_outcomes=recommended,
        )

    def _read_goal(self, goal_path: str) -> str:
        try:
            return read_vault_markdown(self.vault_root, goal_path).content
        except VaultAccessError as exc:
            raise PlanningSessionError(str(exc)) from exc

    def _path(self, session_id: str) -> Path:
        _validate_session_id(session_id)
        return self.sessions_dir / f"{session_id}.json"

    def _temporary_path(self, session_id: str) -> Path:
        return self.sessions_dir / f".{session_id}.json.tmp"

    def _save(self, envelope: SessionEnvelope) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        target = self._path(envelope.session.session_id)
        temporary = self._temporary_path(envelope.session.session_id)
        payload = json.dumps(envelope.to_dict(), sort_keys=True, ensure_ascii=False, indent=2)
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)

    def _load(self, session_id: str) -> SessionEnvelope:
        target = self._path(session_id)
        temporary = self._temporary_path(session_id)
        if not target.exists() and temporary.exists():
            try:
                self._parse_envelope(json.loads(temporary.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, PlanningSessionError, CopilotContractError):
                temporary.unlink(missing_ok=True)
            else:
                os.replace(temporary, target)
        if not target.exists():
            raise PlanningSessionError(f"planning session not found: {session_id}")
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlanningSessionError("planning session file is unreadable") from exc
        return self._parse_envelope(data)

    def _parse_envelope(self, data: object) -> SessionEnvelope:
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise PlanningSessionError("unsupported planning session envelope")
        session_data = data.get("session")
        if not isinstance(session_data, dict):
            raise PlanningSessionError("planning session payload is missing")
        session = PlanningSession.from_dict(session_data)
        readiness = _readiness_from_dict(data.get("readiness"))
        history = tuple(_question_from_dict(item) for item in _dict_list(data.get("question_history")))
        current_raw = data.get("current_question")
        current = _question_from_dict(current_raw) if isinstance(current_raw, dict) else None
        diagnostics_raw = data.get("adapter_diagnostics", [])
        if not isinstance(diagnostics_raw, list) or not all(
            isinstance(item, str) for item in diagnostics_raw
        ):
            raise PlanningSessionError("adapter diagnostics must be visible strings")
        return SessionEnvelope(
            session=session,
            readiness=readiness,
            question_history=history,
            current_question=current,
            adapter_diagnostics=tuple(diagnostics_raw),
        )


def _deterministic_questions(goal: Any) -> dict[str, ClarificationQuestion]:
    return {
        "purpose": ClarificationQuestion(
            "purpose",
            "purpose",
            "What makes this direction worth attention now?",
            goal.why is None,
            "deterministic",
            "A visible purpose helps distinguish a direction from a passing capture.",
        ),
        "desired-change": ClarificationQuestion(
            "desired-change",
            "desired-change",
            "What observable change would make the next planning period worthwhile?",
            goal.desired_change is None,
            "deterministic",
            "A desired change is needed before comparing plan strategies.",
        ),
        "horizon": ClarificationQuestion(
            "horizon",
            "horizon",
            "What broad horizon fits this direction: weeks, months, a year, or open-ended?",
            goal.horizon is None,
            "deterministic",
            "The horizon bounds detail without inventing a deadline.",
        ),
        "constraints": ClarificationQuestion(
            "constraints",
            "constraints",
            "Which limits or protected activities should every option respect?",
            False,
            "deterministic",
            "Constraints protect rest, hobbies, relationships, and existing commitments.",
        ),
        "non-goals": ClarificationQuestion(
            "non-goals",
            "non-goals",
            "What should this plan explicitly avoid trying to accomplish?",
            False,
            "deterministic",
            "A non-goal prevents scope from quietly expanding.",
        ),
        "success-evidence": ClarificationQuestion(
            "success-evidence",
            "success-evidence",
            "What visible evidence would tell you the next phase worked?",
            False,
            "deterministic",
            "Success evidence makes later review possible without a hidden score.",
        ),
        "current-commitments": ClarificationQuestion(
            "current-commitments",
            "current-commitments",
            "Which current commitments must remain intact while considering this goal?",
            False,
            "deterministic",
            "Existing life commitments are constraints, not expendable slack.",
        ),
    }


def _required_questions_answered(goal: Any, answers: tuple[PlanningAnswer, ...]) -> bool:
    by_id = {item.question_id: item for item in answers}
    known = {
        "purpose": goal.why is not None,
        "desired-change": goal.desired_change is not None,
        "horizon": goal.horizon is not None,
    }
    for question_id in _REQUIRED_QUESTION_IDS:
        if known[question_id]:
            continue
        answer = by_id.get(question_id)
        if answer is None or answer.response_kind != "answered":
            return False
    return True


def _answers_support_plan(envelope: SessionEnvelope) -> bool:
    if envelope.readiness.path in {"plan", "link-existing-plan"}:
        return True
    answered = {item.question_id for item in envelope.session.answers if item.response_kind == "answered"}
    return set(_REQUIRED_QUESTION_IDS) <= answered


def _recommended_outcomes(envelope: SessionEnvelope) -> tuple[SessionOutcome, ...]:
    if envelope.readiness.path == "decline":
        return ("abandon", "continue-reflecting")
    if envelope.readiness.path == "link-existing-plan":
        return ("link-existing-plan", "ready-to-plan", "park")
    if _answers_support_plan(envelope):
        return ("ready-to-plan", "experiment", "park")
    if envelope.current_question is None:
        return ("continue-reflecting", "experiment", "park", "abandon")
    return ("continue-reflecting", "park", "abandon")


def _question_from_dict(data: Mapping[str, Any]) -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id=_required_str(data, "question_id"),
        category=cast(QuestionCategory, _required_str(data, "category")),
        prompt=_required_str(data, "prompt"),
        required=_required_bool(data, "required"),
        source=cast(QuestionSource, _required_str(data, "source")),
        reason=_required_str(data, "reason"),
    )


def _readiness_from_dict(data: object) -> GoalReadinessReport:
    if not isinstance(data, dict):
        raise PlanningSessionError("readiness payload is missing")
    from .readiness import ReadinessFinding

    findings = tuple(
        ReadinessFinding(
            code=_required_str(item, "code"),
            category=cast(Any, _required_str(item, "category")),
            field=_required_str(item, "field"),
            message=_required_str(item, "message"),
            required=_required_bool(item, "required"),
        )
        for item in _dict_list(data.get("findings"))
    )
    return GoalReadinessReport(
        goal_id=_required_str(data, "goal_id"),
        source_path=_required_str(data, "source_path"),
        source_hash=_required_str(data, "source_hash"),
        ready=_required_bool(data, "ready"),
        path=cast(Any, _required_str(data, "path")),
        findings=findings,
        active_plan_ids=tuple(_string_list(data.get("active_plan_ids"))),
        missing_fields=tuple(_string_list(data.get("missing_fields"))),
    )


def _dict_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PlanningSessionError("expected a list of mappings")
    return cast(list[Mapping[str, Any]], value)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PlanningSessionError("expected a list of strings")
    return cast(list[str], value)


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanningSessionError(f"{key} must be a visible non-empty string")
    return value


def _required_bool(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if type(value) is not bool:
        raise PlanningSessionError(f"{key} must be boolean")
    return value


def _validate_session_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"session-[a-z0-9][a-z0-9._-]{1,127}", value):
        raise PlanningSessionError("session_id is invalid")
