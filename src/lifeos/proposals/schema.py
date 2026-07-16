import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class ProposalRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProposalSchemaError(Exception):
    def __init__(self, code: str, field_path: str, message: str) -> None:
        super().__init__(f"{field_path} ({code}): {message}")
        self.code = code
        self.field_path = field_path
        self.message = message


@dataclass(frozen=True)
class ProposalMetadata:
    id: str
    schema_version: int
    patch_schema_version: int
    lifecycle_schema_version: int | None
    title: str
    description: str
    status: ProposalStatus
    risk: ProposalRisk
    created_at: str
    created_by: str
    submitted_at: str | None
    submitted_by: str | None
    review_digest: str | None
    approved_at: str | None
    approved_by: str | None
    rejected_at: str | None
    rejected_by: str | None
    rejection_reason: str | None
    applied_at: str | None
    applied_by: str | None
    related_goals: tuple[str, ...]
    related_sources: tuple[str, ...]
    extensions: Mapping[str, Any]


def _freeze_value(val: Any) -> Any:
    """Recursively freeze JSON-compatible values."""
    if isinstance(val, dict):
        return MappingProxyType({k: _freeze_value(v) for k, v in val.items()})
    if isinstance(val, list):
        return tuple(_freeze_value(v) for v in val)
    return val


def _unfreeze_value(val: Any) -> Any:
    if isinstance(val, MappingProxyType):
        return {k: _unfreeze_value(val[k]) for k in sorted(val.keys())}
    if isinstance(val, tuple):
        return [_unfreeze_value(v) for v in val]
    return val


def generate_proposal_id(
    clock_fn: Callable[[], datetime], random_suffix_fn: Callable[[], str]
) -> str:
    now = clock_fn()
    if now.tzinfo is None:
        raise ValueError("clock_fn must return a UTC datetime")
    offset = now.tzinfo.utcoffset(now)
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("clock_fn must return a UTC datetime")
    suffix = random_suffix_fn()
    if not re.match(r"^[a-f0-9]{8}$", suffix):
        raise ValueError("random_suffix_fn must return exactly 8 lowercase hexadecimal characters")

    timestamp_str = now.strftime("%Y%m%dT%H%M%SZ")
    pid = f"prop-{timestamp_str}-{suffix}"
    try:
        validate_proposal_id(pid)
    except ProposalSchemaError:
        raise ValueError(f"Generated ID '{pid}' failed validation")
    return pid


ID_REGEX = re.compile(r"^prop-\d{8}T\d{6}Z-[a-f0-9]{8}$")
TIMESTAMP_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def validate_proposal_id(value: object, *, field_path: str = "id") -> str:
    if not isinstance(value, str):
        raise ProposalSchemaError("invalid_type", field_path, "must be a string")
    if not ID_REGEX.match(value):
        raise ProposalSchemaError(
            "invalid_format", field_path, "must match ^prop-\\d{8}T\\d{6}Z-[a-f0-9]{8}$"
        )
    return value


def _validate_timestamp(val: Any, field: str, errors: list[ProposalSchemaError]) -> None:
    if not isinstance(val, str):
        errors.append(ProposalSchemaError("invalid_type", field, "must be a string"))
        return
    if not TIMESTAMP_REGEX.match(val):
        errors.append(
            ProposalSchemaError(
                "invalid_format",
                field,
                "must be an RFC 3339 UTC string with second precision and trailing Z",
            )
        )
        return
    try:
        datetime.strptime(val, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append(ProposalSchemaError("invalid_value", field, "invalid calendar date or time"))


def _validate_string(val: Any, field: str, errors: list[ProposalSchemaError]) -> None:
    if not isinstance(val, str):
        errors.append(ProposalSchemaError("invalid_type", field, "must be a string"))
        return
    if not val.strip():
        errors.append(ProposalSchemaError("empty_string", field, "must not be empty"))


def validate_metadata(data: dict[str, Any]) -> ProposalMetadata:
    errors: list[ProposalSchemaError] = []

    # 1. Unknown top-level fields
    allowed_fields = {
        "id",
        "schema_version",
        "patch_schema_version",
        "lifecycle_schema_version",
        "title",
        "description",
        "status",
        "risk",
        "created_at",
        "created_by",
        "submitted_at",
        "submitted_by",
        "review_digest",
        "approved_at",
        "approved_by",
        "rejected_at",
        "rejected_by",
        "rejection_reason",
        "applied_at",
        "applied_by",
        "related_goals",
        "related_sources",
        "extensions",
    }
    for key in sorted(data.keys()):
        if key not in allowed_fields:
            errors.append(ProposalSchemaError("unknown_field", key, "unknown top-level field"))

    # 2. Required fields
    required = [
        "id",
        "schema_version",
        "patch_schema_version",
        "title",
        "description",
        "status",
        "risk",
        "created_at",
        "created_by",
    ]
    for req in required:
        if req not in data:
            errors.append(ProposalSchemaError("missing_field", req, "required field is missing"))

    # Short circuit if missing required primitives that we need to build the model
    if any(e.code == "missing_field" for e in errors):
        raise errors[0]

    # ID
    val_id = data.get("id")
    try:
        validate_proposal_id(val_id)
    except ProposalSchemaError as e:
        errors.append(e)

    # schema_version
    sv = data.get("schema_version")
    if type(sv) is not int or isinstance(sv, bool):
        errors.append(ProposalSchemaError("invalid_type", "schema_version", "must be an integer"))
    elif sv != 1:
        errors.append(ProposalSchemaError("unsupported_version", "schema_version", "must be 1"))

    # patch_schema_version
    psv = data.get("patch_schema_version")
    if type(psv) is not int or isinstance(psv, bool):
        errors.append(
            ProposalSchemaError("invalid_type", "patch_schema_version", "must be an integer")
        )
    elif psv <= 0:
        errors.append(
            ProposalSchemaError(
                "invalid_value", "patch_schema_version", "must be a positive integer"
            )
        )

    # lifecycle_schema_version
    lsv = data.get("lifecycle_schema_version")
    if lsv is not None:
        if type(lsv) is not int or isinstance(lsv, bool):
            errors.append(ProposalSchemaError("invalid_type", "lifecycle_schema_version", "must be an integer or null"))
        elif lsv != 1:
            errors.append(ProposalSchemaError("unsupported_version", "lifecycle_schema_version", "must be 1 or null"))

    # strings
    for f in ("title", "description", "created_by"):
        _validate_string(data.get(f), f, errors)

    for f in ("submitted_by", "review_digest", "approved_by", "rejected_by", "rejection_reason", "applied_by"):
        val = data.get(f)
        if val is not None:
            _validate_string(val, f, errors)

    # status
    status_val = data.get("status")
    status_enum = None
    if isinstance(status_val, str):
        try:
            status_enum = ProposalStatus(status_val)
        except ValueError:
            errors.append(
                ProposalSchemaError("invalid_value", "status", f"invalid status: {status_val}")
            )
    else:
        errors.append(ProposalSchemaError("invalid_type", "status", "must be a string"))

    # risk
    risk_val = data.get("risk")
    risk_enum = None
    if isinstance(risk_val, str):
        try:
            risk_enum = ProposalRisk(risk_val)
        except ValueError:
            errors.append(ProposalSchemaError("invalid_value", "risk", f"invalid risk: {risk_val}"))
    else:
        errors.append(ProposalSchemaError("invalid_type", "risk", "must be a string"))

    # created_at
    _validate_timestamp(data.get("created_at"), "created_at", errors)

    # optional timestamps
    for f in ("submitted_at", "approved_at", "rejected_at", "applied_at"):
        val = data.get(f)
        if val is not None:
            _validate_timestamp(val, f, errors)

    # related lists
    related_goals = data.get("related_goals", [])
    if not isinstance(related_goals, list):
        errors.append(ProposalSchemaError("invalid_type", "related_goals", "must be a list"))
    else:
        for i, item in enumerate(related_goals):
            _validate_string(item, f"related_goals[{i}]", errors)

    related_sources = data.get("related_sources", [])
    if not isinstance(related_sources, list):
        errors.append(ProposalSchemaError("invalid_type", "related_sources", "must be a list"))
    else:
        for i, item in enumerate(related_sources):
            _validate_string(item, f"related_sources[{i}]", errors)

    # extensions
    extensions = data.get("extensions", {})
    if not isinstance(extensions, dict):
        errors.append(ProposalSchemaError("invalid_type", "extensions", "must be a dictionary"))
    else:
        for k in extensions.keys():
            if not isinstance(k, str):
                errors.append(
                    ProposalSchemaError(
                        "invalid_type", f"extensions[{k}]", "extension keys must be strings"
                    )
                )

    if errors:
        # Sort errors deterministically by field path then code
        errors.sort(key=lambda e: (e.field_path, e.code))
        raise errors[0]  # Just raise the first deterministically ordered error for simplicity

    assert status_enum is not None
    assert risk_enum is not None

    # Validate lifecycle invariants and chronologies
    submitted_at = data.get("submitted_at")
    submitted_by = data.get("submitted_by")
    review_digest = data.get("review_digest")
    approved_at = data.get("approved_at")
    approved_by = data.get("approved_by")
    rejected_at = data.get("rejected_at")
    rejected_by = data.get("rejected_by")
    rejection_reason = data.get("rejection_reason")
    applied_at = data.get("applied_at")
    applied_by = data.get("applied_by")

    # Helper function to check required/null constraints
    def _require(field: str, val: Any) -> None:
        if val is None:
            errors.append(ProposalSchemaError("lifecycle_mismatch", field, f"required for {status_enum.value} status"))

    def _forbid(field: str, val: Any) -> None:
        if val is not None:
            errors.append(ProposalSchemaError("lifecycle_mismatch", field, f"must be null for {status_enum.value} status"))

    if lsv is None:
        # Legacy lifecycle rules (pre-LIFEOS-105)
        # Note: we do not enforce that submission/rejection/review_digest are null,
        # we only enforce the previous rules exactly.
        if status_enum in (ProposalStatus.DRAFT, ProposalStatus.PENDING):
            _forbid("approved_at", approved_at)
            _forbid("rejected_at", rejected_at)
            _forbid("applied_at", applied_at)
        elif status_enum == ProposalStatus.APPROVED:
            _require("approved_at", approved_at)
            _forbid("rejected_at", rejected_at)
            _forbid("applied_at", applied_at)
        elif status_enum == ProposalStatus.REJECTED:
            _require("rejected_at", rejected_at)
            _forbid("applied_at", applied_at)
        elif status_enum == ProposalStatus.APPLIED:
            _require("approved_at", approved_at)
            _require("applied_at", applied_at)
            _forbid("rejected_at", rejected_at)

        # Legacy chronologies (only checked if present)
        times = {}
        for f in ("created_at", "approved_at", "rejected_at", "applied_at"):
            val = data.get(f)
            if val is not None:
                times[f] = val

        if "approved_at" in times and times["created_at"] > times["approved_at"]:
            errors.append(ProposalSchemaError("chronology_error", "approved_at", "must be >= created_at"))
        if "rejected_at" in times and times["created_at"] > times["rejected_at"]:
            errors.append(ProposalSchemaError("chronology_error", "rejected_at", "must be >= created_at"))
        if "applied_at" in times and times["created_at"] > times["applied_at"]:
            errors.append(ProposalSchemaError("chronology_error", "applied_at", "must be >= created_at"))
        if "approved_at" in times and "applied_at" in times and times["approved_at"] > times["applied_at"]:
            errors.append(ProposalSchemaError("chronology_error", "applied_at", "must be >= approved_at"))
        if "approved_at" in times and "rejected_at" in times and times["approved_at"] > times["rejected_at"]:
            errors.append(ProposalSchemaError("chronology_error", "rejected_at", "must be >= approved_at"))

    else:
        # Complete lifecycle contract (LIFEOS-105)
        if status_enum == ProposalStatus.DRAFT:
            _forbid("submitted_at", submitted_at)
            _forbid("submitted_by", submitted_by)
            _forbid("review_digest", review_digest)
            _forbid("approved_at", approved_at)
            _forbid("approved_by", approved_by)
            _forbid("rejected_at", rejected_at)
            _forbid("rejected_by", rejected_by)
            _forbid("rejection_reason", rejection_reason)
            _forbid("applied_at", applied_at)
            _forbid("applied_by", applied_by)
        elif status_enum == ProposalStatus.PENDING:
            _require("submitted_at", submitted_at)
            _require("submitted_by", submitted_by)
            _require("review_digest", review_digest)
            _forbid("approved_at", approved_at)
            _forbid("approved_by", approved_by)
            _forbid("rejected_at", rejected_at)
            _forbid("rejected_by", rejected_by)
            _forbid("rejection_reason", rejection_reason)
            _forbid("applied_at", applied_at)
            _forbid("applied_by", applied_by)
        elif status_enum == ProposalStatus.APPROVED:
            _require("submitted_at", submitted_at)
            _require("submitted_by", submitted_by)
            _require("review_digest", review_digest)
            _require("approved_at", approved_at)
            _require("approved_by", approved_by)
            _forbid("rejected_at", rejected_at)
            _forbid("rejected_by", rejected_by)
            _forbid("rejection_reason", rejection_reason)
            _forbid("applied_at", applied_at)
            _forbid("applied_by", applied_by)
        elif status_enum == ProposalStatus.REJECTED:
            _require("submitted_at", submitted_at)
            _require("submitted_by", submitted_by)
            _require("review_digest", review_digest)
            _require("rejected_at", rejected_at)
            _require("rejected_by", rejected_by)
            _require("rejection_reason", rejection_reason)
            _forbid("applied_at", applied_at)
            _forbid("applied_by", applied_by)

            # Approval actor and timestamp must either both be null or both be present
            if (approved_at is None) != (approved_by is None):
                errors.append(ProposalSchemaError("lifecycle_mismatch", "approved_at", "approval actor and timestamp must both be absent or both be present"))
        elif status_enum == ProposalStatus.APPLIED:
            _require("submitted_at", submitted_at)
            _require("submitted_by", submitted_by)
            _require("review_digest", review_digest)
            _require("approved_at", approved_at)
            _require("approved_by", approved_by)
            _require("applied_at", applied_at)
            _require("applied_by", applied_by)
            _forbid("rejected_at", rejected_at)
            _forbid("rejected_by", rejected_by)
            _forbid("rejection_reason", rejection_reason)

        # Chronologies explicitly checked via independent comparisons
        times = {}
        for f in ("created_at", "submitted_at", "approved_at", "rejected_at", "applied_at"):
            val = data.get(f)
            if val is not None:
                times[f] = val

        if "submitted_at" in times and times["created_at"] > times["submitted_at"]:
            errors.append(ProposalSchemaError("chronology_error", "submitted_at", "must be >= created_at"))
        if "submitted_at" in times and "approved_at" in times and times["submitted_at"] > times["approved_at"]:
            errors.append(ProposalSchemaError("chronology_error", "approved_at", "must be >= submitted_at"))
        if "submitted_at" in times and "rejected_at" in times and times["submitted_at"] > times["rejected_at"]:
            errors.append(ProposalSchemaError("chronology_error", "rejected_at", "must be >= submitted_at"))
        if "approved_at" in times and "rejected_at" in times and times["approved_at"] > times["rejected_at"]:
            errors.append(ProposalSchemaError("chronology_error", "rejected_at", "must be >= approved_at"))
        if "approved_at" in times and "applied_at" in times and times["approved_at"] > times["applied_at"]:
            errors.append(ProposalSchemaError("chronology_error", "applied_at", "must be >= approved_at"))

    if errors:
        errors.sort(key=lambda e: (e.field_path, e.code))
        raise errors[0]

    assert status_enum is not None
    assert risk_enum is not None

    return ProposalMetadata(
        id=data["id"],
        schema_version=data["schema_version"],
        patch_schema_version=data["patch_schema_version"],
        lifecycle_schema_version=lsv,
        title=data["title"],
        description=data["description"],
        status=status_enum,
        risk=risk_enum,
        created_at=data["created_at"],
        created_by=data["created_by"],
        submitted_at=submitted_at,
        submitted_by=submitted_by,
        review_digest=review_digest,
        approved_at=approved_at,
        approved_by=approved_by,
        rejected_at=rejected_at,
        rejected_by=rejected_by,
        rejection_reason=rejection_reason,
        applied_at=applied_at,
        applied_by=applied_by,
        related_goals=tuple(related_goals),
        related_sources=tuple(related_sources),
        extensions=_freeze_value(extensions),
    )


def serialize_metadata(meta: ProposalMetadata) -> dict[str, Any]:
    d = {
        "id": meta.id,
        "schema_version": meta.schema_version,
        "patch_schema_version": meta.patch_schema_version,
        "lifecycle_schema_version": meta.lifecycle_schema_version,
        "title": meta.title,
        "description": meta.description,
        "status": meta.status.value,
        "risk": meta.risk.value,
        "created_at": meta.created_at,
        "created_by": meta.created_by,
        "submitted_at": meta.submitted_at,
        "submitted_by": meta.submitted_by,
        "review_digest": meta.review_digest,
        "approved_at": meta.approved_at,
        "approved_by": meta.approved_by,
        "rejected_at": meta.rejected_at,
        "rejected_by": meta.rejected_by,
        "rejection_reason": meta.rejection_reason,
        "applied_at": meta.applied_at,
        "applied_by": meta.applied_by,
        "related_goals": list(meta.related_goals),
        "related_sources": list(meta.related_sources),
        "extensions": _unfreeze_value(meta.extensions),
    }
    # To keep identical format where possible, we might omit nulls if desired, but
    # typically YAML safe_dumper handles nulls correctly. Let's return the full dict.
    return d
