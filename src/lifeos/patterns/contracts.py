"""Canonical contracts for evidence-backed personal patterns."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, cast

from lifeos.vault import VaultAccessError, validate_vault_relative_path

PATTERN_SCHEMA_VERSION = 1
PatternStatus = Literal["seed", "active", "needs-review", "archived"]
PatternConfidence = Literal["low", "medium", "high"]
EvidenceRole = Literal["supporting", "contesting", "contextual"]
OriginKind = Literal[
    "manual",
    "observation",
    "review",
    "conversation",
    "experiment",
    "goal",
    "plan",
    "agent",
]

_PATTERN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STATUSES = frozenset({"seed", "active", "needs-review", "archived"})
_CONFIDENCE = frozenset({"low", "medium", "high"})
_EVIDENCE_ROLES = frozenset({"supporting", "contesting", "contextual"})
_ORIGIN_KINDS = frozenset(
    {"manual", "observation", "review", "conversation", "experiment", "goal", "plan", "agent"}
)


class PatternError(ValueError):
    """Typed validation or artifact error for canonical personal patterns."""

    def __init__(self, code: str, message: str, data: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})


def _nonblank(value: str, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise PatternError(
            "invalid_field",
            f"{field_name} must be a non-blank string.",
            {"field": field_name},
        )
    return value


def _optional_nonblank(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        raise PatternError(
            "invalid_field",
            f"{field_name} must be a non-blank string when present.",
            {"field": field_name},
        )
    return value


def _validate_timestamp(value: str, field_name: str) -> str:
    _nonblank(value, field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PatternError(
            "invalid_timestamp",
            f"{field_name} must be an ISO 8601 timestamp.",
            {"field": field_name},
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PatternError(
            "invalid_timestamp",
            f"{field_name} must include a timezone.",
            {"field": field_name},
        )
    return value


def _timestamp_value(value: object, field_name: str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise PatternError(
                "invalid_timestamp",
                f"{field_name} must include a timezone.",
                {"field": field_name},
            )
        normalized = value.astimezone(timezone.utc).isoformat()
        return normalized.removesuffix("+00:00") + "Z"
    if type(value) is not str:
        raise PatternError(
            "invalid_timestamp",
            f"{field_name} must be an ISO 8601 timestamp.",
            {"field": field_name},
        )
    return _validate_timestamp(value, field_name)


def _validate_hash(value: str, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise PatternError(
            "invalid_hash",
            f"{field_name} must be sha256: followed by 64 lowercase hexadecimal characters.",
            {"field": field_name},
        )
    return value


def _validate_evidence_path(value: str) -> str:
    try:
        return validate_vault_relative_path(value)
    except VaultAccessError as exc:
        raise PatternError(
            "invalid_evidence_path",
            "Evidence path must be a safe vault-relative path.",
            {"path": value},
        ) from exc


def _portable_value(value: object, field_name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PatternError(
                "invalid_evaluation",
                f"{field_name} cannot contain NaN or infinite values.",
                {"field": field_name},
            )
        return value
    if isinstance(value, list):
        return [_portable_value(item, field_name) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key:
                raise PatternError(
                    "invalid_evaluation",
                    f"{field_name} keys must be non-empty strings.",
                    {"field": field_name},
                )
            normalized[key] = _portable_value(item, field_name)
        return {key: normalized[key] for key in sorted(normalized)}
    raise PatternError(
        "invalid_evaluation",
        f"{field_name} contains a non-portable value.",
        {"field": field_name},
    )


@dataclass(frozen=True, slots=True)
class PatternOrigin:
    kind: OriginKind
    source_ref: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _ORIGIN_KINDS:
            raise PatternError("invalid_origin", "Pattern origin kind is unsupported.")
        _optional_nonblank(self.source_ref, "origin.source_ref")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"kind": self.kind}
        if self.source_ref is not None:
            result["source_ref"] = self.source_ref
        return result


@dataclass(frozen=True, slots=True)
class PatternEvidence:
    path: str
    content_hash: str
    role: EvidenceRole
    source_id: str | None = None
    observation_id: str | None = None
    event_id: str | None = None

    def __post_init__(self) -> None:
        _validate_evidence_path(self.path)
        _validate_hash(self.content_hash, "evidence.content_hash")
        if self.role not in _EVIDENCE_ROLES:
            raise PatternError("invalid_evidence_role", "Pattern evidence role is unsupported.")
        _optional_nonblank(self.source_id, "evidence.source_id")
        _optional_nonblank(self.observation_id, "evidence.observation_id")
        _optional_nonblank(self.event_id, "evidence.event_id")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"path": self.path}
        if self.source_id is not None:
            result["source_id"] = self.source_id
        result["content_hash"] = self.content_hash
        result["role"] = self.role
        if self.observation_id is not None:
            result["observation_id"] = self.observation_id
        if self.event_id is not None:
            result["event_id"] = self.event_id
        return result


@dataclass(frozen=True, slots=True)
class PatternEvaluation:
    kind: str
    parameters: Mapping[str, object]

    def __post_init__(self) -> None:
        _nonblank(self.kind, "evaluation.kind")
        if not isinstance(self.parameters, Mapping):
            raise PatternError(
                "invalid_evaluation",
                "evaluation.parameters must be a mapping.",
                {"field": "evaluation.parameters"},
            )
        normalized = _portable_value(dict(self.parameters), "evaluation.parameters")
        if not isinstance(normalized, dict):
            raise AssertionError("evaluation parameters must normalize to a mapping")

    def to_dict(self) -> dict[str, object]:
        parameters = _portable_value(dict(self.parameters), "evaluation.parameters")
        assert isinstance(parameters, dict)
        return {"kind": self.kind, "parameters": parameters}


@dataclass(frozen=True, slots=True)
class PatternMetadata:
    pattern_id: str
    title: str
    description: str
    status: PatternStatus
    confidence: PatternConfidence
    review_reasons: tuple[str, ...]
    statement: str
    origin: PatternOrigin
    created_at: str
    updated_at: str
    evidence_fingerprint: str
    evidence: tuple[PatternEvidence, ...]
    last_reviewed_at: str | None = None
    review_due_at: str | None = None
    evaluation: PatternEvaluation | None = None
    schema_version: int = PATTERN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != PATTERN_SCHEMA_VERSION:
            raise PatternError("unsupported_schema", "Pattern schema version is unsupported.")
        if type(self.pattern_id) is not str or _PATTERN_ID_RE.fullmatch(self.pattern_id) is None:
            raise PatternError(
                "invalid_pattern_id",
                "Pattern ID must use lowercase letters, digits, dot, underscore, or hyphen.",
                {"pattern_id": self.pattern_id},
            )
        _nonblank(self.title, "title")
        if type(self.description) is not str:
            raise PatternError(
                "invalid_field",
                "description must be a string.",
                {"field": "description"},
            )
        if self.status not in _STATUSES:
            raise PatternError("invalid_status", "Pattern status is unsupported.")
        if self.confidence not in _CONFIDENCE:
            raise PatternError("invalid_confidence", "Pattern confidence is unsupported.")
        for reason in self.review_reasons:
            _nonblank(reason, "review_reasons")
        if len(set(self.review_reasons)) != len(self.review_reasons):
            raise PatternError("duplicate_review_reason", "Pattern review reasons must be unique.")
        _nonblank(self.statement, "statement")
        _validate_timestamp(self.created_at, "created_at")
        _validate_timestamp(self.updated_at, "updated_at")
        if self.last_reviewed_at is not None:
            _validate_timestamp(self.last_reviewed_at, "last_reviewed_at")
        if self.review_due_at is not None:
            _validate_timestamp(self.review_due_at, "review_due_at")
        _validate_hash(self.evidence_fingerprint, "evidence_fingerprint")

    def to_frontmatter(self) -> dict[str, object]:
        result: dict[str, object] = {
            "pattern_schema": self.schema_version,
            "type": "pattern",
            "id": self.pattern_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "confidence": self.confidence,
            "review_reasons": list(self.review_reasons),
            "statement": self.statement,
            "origin": self.origin.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.last_reviewed_at is not None:
            result["last_reviewed_at"] = self.last_reviewed_at
        if self.review_due_at is not None:
            result["review_due_at"] = self.review_due_at
        result["evidence_fingerprint"] = self.evidence_fingerprint
        result["evidence"] = [item.to_dict() for item in self.evidence]
        if self.evaluation is not None:
            result["evaluation"] = self.evaluation.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class PatternArtifact:
    path: str
    content_hash: str
    metadata: PatternMetadata
    body_prefix: str
    managed_summary: str
    body_suffix: str

    @property
    def human_body(self) -> str:
        """Return the exact human-owned body bytes represented as text around the managed block."""
        return self.body_prefix + self.body_suffix


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(type(key) is str for key in value):
        raise PatternError(
            "invalid_field",
            f"{field_name} must be a mapping with string keys.",
            {"field": field_name},
        )
    return value


def _string(value: object, field_name: str, *, allow_blank: bool = False) -> str:
    if type(value) is not str or (not allow_blank and not value.strip()):
        qualifier = "a string" if allow_blank else "a non-blank string"
        raise PatternError(
            "invalid_field", f"{field_name} must be {qualifier}.", {"field": field_name}
        )
    return value


def _string_list(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PatternError("invalid_field", f"{field_name} must be a list.", {"field": field_name})
    return tuple(_string(item, field_name) for item in value)


def _optional_string(data: Mapping[str, Any], field_name: str) -> str | None:
    value = data.get(field_name)
    if value is None:
        return None
    return _string(value, field_name)


def _optional_timestamp(data: Mapping[str, Any], field_name: str) -> str | None:
    value = data.get(field_name)
    if value is None:
        return None
    return _timestamp_value(value, field_name)


def _origin_from_dict(value: object) -> PatternOrigin:
    data = _mapping(value, "origin")
    kind = _string(data.get("kind"), "origin.kind")
    if kind not in _ORIGIN_KINDS:
        raise PatternError("invalid_origin", "Pattern origin kind is unsupported.", {"kind": kind})
    return PatternOrigin(
        kind=cast(OriginKind, kind),
        source_ref=_optional_string(data, "source_ref"),
    )


def _evidence_from_dict(value: object, index: int) -> PatternEvidence:
    data = _mapping(value, f"evidence[{index}]")
    role = _string(data.get("role"), f"evidence[{index}].role")
    if role not in _EVIDENCE_ROLES:
        raise PatternError(
            "invalid_evidence_role", "Pattern evidence role is unsupported.", {"role": role}
        )
    return PatternEvidence(
        path=_string(data.get("path"), f"evidence[{index}].path"),
        content_hash=_string(data.get("content_hash"), f"evidence[{index}].content_hash"),
        role=cast(EvidenceRole, role),
        source_id=_optional_string(data, "source_id"),
        observation_id=_optional_string(data, "observation_id"),
        event_id=_optional_string(data, "event_id"),
    )


def _evaluation_from_dict(value: object) -> PatternEvaluation:
    data = _mapping(value, "evaluation")
    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict) or not all(type(key) is str for key in parameters):
        raise PatternError(
            "invalid_evaluation",
            "evaluation.parameters must be a mapping with string keys.",
            {"field": "evaluation.parameters"},
        )
    return PatternEvaluation(
        kind=_string(data.get("kind"), "evaluation.kind"),
        parameters=parameters,
    )


def metadata_from_dict(data: Mapping[str, Any]) -> PatternMetadata:
    """Parse and validate recognized pattern-schema frontmatter."""
    schema = data.get("pattern_schema")
    if type(schema) is not int or schema != PATTERN_SCHEMA_VERSION:
        raise PatternError(
            "unsupported_schema",
            "Pattern schema version is unsupported.",
            {"pattern_schema": schema},
        )
    if data.get("type") != "pattern":
        raise PatternError("invalid_pattern", "pattern_schema: 1 requires type: pattern.")

    status = _string(data.get("status"), "status")
    if status not in _STATUSES:
        raise PatternError("invalid_status", "Pattern status is unsupported.", {"status": status})
    confidence = _string(data.get("confidence"), "confidence")
    if confidence not in _CONFIDENCE:
        raise PatternError(
            "invalid_confidence",
            "Pattern confidence is unsupported.",
            {"confidence": confidence},
        )
    evidence_value = data.get("evidence")
    if not isinstance(evidence_value, list):
        raise PatternError("invalid_evidence", "Pattern evidence must be a list.")
    evidence = tuple(_evidence_from_dict(item, index) for index, item in enumerate(evidence_value))
    evaluation_value = data.get("evaluation")

    return PatternMetadata(
        pattern_id=_string(data.get("id"), "id"),
        title=_string(data.get("title"), "title"),
        description=_string(data.get("description"), "description", allow_blank=True),
        status=cast(PatternStatus, status),
        confidence=cast(PatternConfidence, confidence),
        review_reasons=_string_list(data.get("review_reasons"), "review_reasons"),
        statement=_string(data.get("statement"), "statement"),
        origin=_origin_from_dict(data.get("origin")),
        created_at=_timestamp_value(data.get("created_at"), "created_at"),
        updated_at=_timestamp_value(data.get("updated_at"), "updated_at"),
        last_reviewed_at=_optional_timestamp(data, "last_reviewed_at"),
        review_due_at=_optional_timestamp(data, "review_due_at"),
        evidence_fingerprint=_string(data.get("evidence_fingerprint"), "evidence_fingerprint"),
        evidence=evidence,
        evaluation=(None if evaluation_value is None else _evaluation_from_dict(evaluation_value)),
        schema_version=schema,
    )
