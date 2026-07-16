"""Versioned, strict JSON-RPC protocol for the local desktop bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lifeos.versioning import DESKTOP_PROTOCOL_VERSION, PYTHON_PACKAGE_VERSION

PROTOCOL_VERSION = DESKTOP_PROTOCOL_VERSION
ENGINE_VERSION = PYTHON_PACKAGE_VERSION
CAPABILITIES = (
    "system.health",
    "copilot.note.inspect",
    "copilot.goal.readiness",
    "copilot.context.preview",
    "copilot.session.start",
    "copilot.session.get",
    "copilot.session.answer",
    "copilot.session.close",
    "copilot.options.generate",
    "copilot.option.decompose",
    "copilot.capacity.check",
    "copilot.explain",
    "copilot.compare",
    "copilot.counterfactual",
    "copilot.proposal.create",
    "copilot.replanning.scan",
    "copilot.replanning.review",
    "copilot.replanning.suppress",
    "copilot.replanning.proposal.create",
    "today.get",
    "scheduler.config.get",
    "scheduler.config.set",
    "scheduler.service.status",
    "scheduler.service.install",
    "scheduler.service.uninstall",
    "proposal.list",
    "proposal.inspect",
    "proposal.prepare",
    "proposal.execute",
    "system.status",
    "review.build",
    "review.progress",
    "review.save",
    "study.plan",
    "study.session.start",
    "study.session.transition",
    "study.session.open",
    "attention.evaluate",
    "attention.preference",
    "daily.capture",
    "daily.checkin",
    "daily.task_outcome",
    "daily.review",
    "feedback.dataset.status",
    "feedback.dataset.rebuild",
    "feedback.duration",
    "feedback.capacity",
    "feedback.avoidance",
    "feedback.plan",
    "feedback.explain",
    "feedback.preferences.get",
    "feedback.preferences.update",
    "feedback.preferences.migrate",
    "feedback.outcome.correct",
    "feedback.reset",
    "feedback.proposal.create",
    "feedback.replay",
    "request.cancel",
)


@dataclass(frozen=True, slots=True)
class ProtocolError(Exception):
    code: str
    message: str
    data: dict[str, Any] | None = None


def strict_object(value: object, *, allowed: set[str], required: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProtocolError("invalid_request", "Expected a JSON object.")
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        raise ProtocolError("extra_fields", "Unexpected fields were provided.", {"fields": unknown})
    if missing:
        raise ProtocolError("missing_fields", "Required fields are missing.", {"fields": missing})
    return value


def success_frame(request_id: str | int | None, result: object) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result, "meta": {"protocol": PROTOCOL_VERSION}}


def error_frame(request_id: str | int | None, error: ProtocolError) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": error.code, "message": error.message, "data": error.data or {}},
        "meta": {"protocol": PROTOCOL_VERSION},
    }
