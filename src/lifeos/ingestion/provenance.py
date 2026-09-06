import re
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Mapping


class ProvenanceValidationError(ValueError):
    """Raised when lifeos_provenance is present but malformed."""

    pass


_SELECTED_ACQUISITION_ID: ContextVar[str | None] = ContextVar(
    "lifeos_provenance_selected_acquisition",
    default=None,
)


def push_provenance_acquisition_id(acquisition_id: str) -> Token[str | None]:
    if not isinstance(acquisition_id, str) or not acquisition_id.strip():
        raise ValueError("provenance acquisition_id must be a non-empty string")
    if acquisition_id != acquisition_id.strip() or not acquisition_id.startswith("acq-"):
        raise ValueError("provenance acquisition_id must be a canonical acquisition ID")
    return _SELECTED_ACQUISITION_ID.set(acquisition_id)


def reset_provenance_acquisition_id(token: Token[str | None]) -> None:
    _SELECTED_ACQUISITION_ID.reset(token)


@dataclass(frozen=True, slots=True)
class ProvenanceSource:
    path: str
    content_hash: str
    acquisition_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceGenerator:
    id: str
    version: str
    prompt_schema_version: str
    model_id: str | None


@dataclass(frozen=True, slots=True)
class LifeOSProvenance:
    schema_version: int
    sources: tuple[ProvenanceSource, ...]
    generator: ProvenanceGenerator
    created_at: str


TIMESTAMP_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
HASH_REGEX = re.compile(r"^sha256:[a-f0-9]{64}$")
ACQUISITION_ID_REGEX = re.compile(r"^acq-[a-f0-9]{24}$")


def _validate_path(path: Any) -> str:
    if not isinstance(path, str):
        raise ProvenanceValidationError("Source path must be a string")
    if not path:
        raise ProvenanceValidationError("Source path cannot be empty")

    p = PurePosixPath(path)
    if p.is_absolute():
        raise ProvenanceValidationError("Source path cannot be absolute")

    parts = p.parts
    if ".." in parts:
        raise ProvenanceValidationError("Source path cannot contain parent traversal (..)")
    if "." in parts:
        raise ProvenanceValidationError(
            "Source path cannot contain current directory traversal (.)"
        )
    if "\\" in path:
        raise ProvenanceValidationError("Source path cannot contain backslashes")
    if "\0" in path:
        raise ProvenanceValidationError("Source path cannot contain NUL characters")
    if str(p) != path:
        raise ProvenanceValidationError(f"Source path is not normalized: {path}")

    return path


def _validate_hash(hash_val: Any) -> str:
    if not isinstance(hash_val, str):
        raise ProvenanceValidationError("Content hash must be a string")
    if not HASH_REGEX.match(hash_val):
        raise ProvenanceValidationError(
            "Content hash must be in canonical form: sha256:<64 lowercase hexadecimal characters>"
        )
    return hash_val


def _validate_acquisition_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ProvenanceValidationError("acquisition_id must be a string")
    if not ACQUISITION_ID_REGEX.match(value):
        raise ProvenanceValidationError(
            "acquisition_id must match acq-<24 lowercase hexadecimal characters>"
        )
    return value


def _validate_timestamp(ts: Any) -> str:
    if not isinstance(ts, str):
        raise ProvenanceValidationError("Timestamp must be a string")
    if not TIMESTAMP_REGEX.match(ts):
        raise ProvenanceValidationError(
            "Timestamp must be strictly formatted as YYYY-MM-DDTHH:MM:SSZ"
        )

    try:
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise ProvenanceValidationError("Invalid calendar date or time in timestamp") from e

    return ts


def _validate_string_nonempty(val: Any, field_name: str) -> str:
    if not isinstance(val, str):
        raise ProvenanceValidationError(f"{field_name} must be a string")
    if not val.strip():
        raise ProvenanceValidationError(f"{field_name} must be non-empty")
    return val


def extract_provenance(frontmatter: Mapping[str, object]) -> LifeOSProvenance | None:
    """Extract and validate provenance from generic Markdown frontmatter."""
    if "lifeos_provenance" not in frontmatter:
        return None

    raw = frontmatter["lifeos_provenance"]
    if not isinstance(raw, dict):
        raise ProvenanceValidationError("lifeos_provenance must be a mapping")

    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or isinstance(schema_version, bool):
        raise ProvenanceValidationError("schema_version must be an integer")
    if schema_version != 1:
        raise ProvenanceValidationError("schema_version must be 1")

    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list):
        raise ProvenanceValidationError("sources must be a list")
    if not raw_sources:
        raise ProvenanceValidationError(
            "sources must contain at least one source for schema_version 1"
        )

    source_objs = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ProvenanceValidationError("source entry must be a mapping")

        path = raw_source.get("path")
        content_hash = raw_source.get("content_hash")
        acquisition_id = raw_source.get("acquisition_id")

        for k in raw_source:
            if k not in ("path", "content_hash", "acquisition_id"):
                raise ProvenanceValidationError(f"Unknown field in source: {k}")

        if path is None or content_hash is None:
            raise ProvenanceValidationError("source entry must contain path and content_hash")

        source_objs.append(
            ProvenanceSource(
                path=_validate_path(path),
                content_hash=_validate_hash(content_hash),
                acquisition_id=(
                    _validate_acquisition_id(acquisition_id) if acquisition_id is not None else None
                ),
            )
        )

    raw_generator = raw.get("generator")
    if not isinstance(raw_generator, dict):
        raise ProvenanceValidationError("generator must be a mapping")

    for k in raw_generator:
        if k not in ("id", "version", "prompt_schema_version", "model_id"):
            raise ProvenanceValidationError(f"Unknown field in generator: {k}")

    if (
        "id" not in raw_generator
        or "version" not in raw_generator
        or "prompt_schema_version" not in raw_generator
    ):
        raise ProvenanceValidationError(
            "generator must contain id, version, and prompt_schema_version"
        )

    gen_id = _validate_string_nonempty(raw_generator["id"], "generator id")
    gen_version = _validate_string_nonempty(raw_generator["version"], "generator version")
    gen_prompt = _validate_string_nonempty(
        raw_generator["prompt_schema_version"], "generator prompt_schema_version"
    )

    model_id = raw_generator.get("model_id")
    if model_id is not None:
        model_id = _validate_string_nonempty(model_id, "generator model_id")

    raw_created = raw.get("created_at")
    if raw_created is None:
        raise ProvenanceValidationError("created_at is required")

    created_at = _validate_timestamp(raw_created)

    for k in raw:
        if k not in ("schema_version", "sources", "generator", "created_at"):
            raise ProvenanceValidationError(f"Unknown field in lifeos_provenance: {k}")

    return LifeOSProvenance(
        schema_version=schema_version,
        sources=tuple(source_objs),
        generator=ProvenanceGenerator(
            id=gen_id,
            version=gen_version,
            prompt_schema_version=gen_prompt,
            model_id=model_id,
        ),
        created_at=created_at,
    )


def merge_provenance_sources(
    existing: tuple[ProvenanceSource, ...],
    source: ProvenanceSource,
) -> tuple[ProvenanceSource, ...]:
    """Append one accepted source snapshot without erasing provenance history.

    Exact ``(path, content_hash, acquisition_id)`` repeats are deduplicated. The
    same source snapshot with a distinct research acquisition remains distinct so
    durable synthesis can identify which query/reason selected the evidence.
    Accepted-order is preserved.
    """
    selected_acquisition = _SELECTED_ACQUISITION_ID.get()
    incoming = source
    if selected_acquisition is not None and incoming.acquisition_id is None:
        incoming = replace(incoming, acquisition_id=selected_acquisition)

    merged: list[ProvenanceSource] = []
    seen: set[tuple[str, str, str | None]] = set()
    for item in (*existing, incoming):
        key = (item.path, item.content_hash, item.acquisition_id)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return tuple(merged)


def provenance_to_frontmatter_value(provenance: LifeOSProvenance) -> dict[str, object]:
    """Convert a typed provenance model back to a deterministically ordered mapping."""
    selected_acquisition = _SELECTED_ACQUISITION_ID.get()
    sources_list = []
    last_index = len(provenance.sources) - 1
    for index, source in enumerate(provenance.sources):
        acquisition_id = source.acquisition_id
        if acquisition_id is None and selected_acquisition is not None and index == last_index:
            acquisition_id = selected_acquisition
        item: dict[str, object] = {
            "path": source.path,
            "content_hash": source.content_hash,
        }
        if acquisition_id is not None:
            item["acquisition_id"] = acquisition_id
        sources_list.append(item)

    gen_dict: dict[str, object] = {
        "id": provenance.generator.id,
        "version": provenance.generator.version,
        "prompt_schema_version": provenance.generator.prompt_schema_version,
    }

    if provenance.generator.model_id is not None:
        gen_dict["model_id"] = provenance.generator.model_id

    return {
        "schema_version": provenance.schema_version,
        "sources": sources_list,
        "generator": gen_dict,
        "created_at": provenance.created_at,
    }
