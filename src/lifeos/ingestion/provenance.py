import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Mapping

class ProvenanceValidationError(ValueError):
    """Raised when lifeos_provenance is present but malformed."""
    pass


@dataclass(frozen=True, slots=True)
class ProvenanceSource:
    path: str
    content_hash: str


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
        raise ProvenanceValidationError("Source path cannot contain current directory traversal (.)")
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
        raise ProvenanceValidationError("Content hash must be in canonical form: sha256:<64 lowercase hexadecimal characters>")
    return hash_val


def _validate_timestamp(ts: Any) -> str:
    if not isinstance(ts, str):
        raise ProvenanceValidationError("Timestamp must be a string")
    if not TIMESTAMP_REGEX.match(ts):
        raise ProvenanceValidationError("Timestamp must be strictly formatted as YYYY-MM-DDTHH:MM:SSZ")

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

    # Schema version
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or isinstance(schema_version, bool):
        raise ProvenanceValidationError("schema_version must be an integer")
    if schema_version != 1:
        raise ProvenanceValidationError("schema_version must be 1")

    # Sources
    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list):
        raise ProvenanceValidationError("sources must be a list")
    if len(raw_sources) != 1:
        raise ProvenanceValidationError("sources must contain exactly one source for schema_version 1")

    source_objs = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ProvenanceValidationError("source entry must be a mapping")

        path = raw_source.get("path")
        content_hash = raw_source.get("content_hash")

        # reject unknown fields in source
        for k in raw_source:
            if k not in ("path", "content_hash"):
                raise ProvenanceValidationError(f"Unknown field in source: {k}")

        if path is None or content_hash is None:
            raise ProvenanceValidationError("source entry must contain path and content_hash")

        source_objs.append(ProvenanceSource(
            path=_validate_path(path),
            content_hash=_validate_hash(content_hash)
        ))

    # Generator
    raw_generator = raw.get("generator")
    if not isinstance(raw_generator, dict):
        raise ProvenanceValidationError("generator must be a mapping")

    for k in raw_generator:
        if k not in ("id", "version", "prompt_schema_version", "model_id"):
            raise ProvenanceValidationError(f"Unknown field in generator: {k}")

    if "id" not in raw_generator or "version" not in raw_generator or "prompt_schema_version" not in raw_generator:
         raise ProvenanceValidationError("generator must contain id, version, and prompt_schema_version")

    gen_id = _validate_string_nonempty(raw_generator["id"], "generator id")
    gen_version = _validate_string_nonempty(raw_generator["version"], "generator version")
    gen_prompt = _validate_string_nonempty(raw_generator["prompt_schema_version"], "generator prompt_schema_version")

    model_id = raw_generator.get("model_id")
    if model_id is not None:
        model_id = _validate_string_nonempty(model_id, "generator model_id")

    # Created at
    raw_created = raw.get("created_at")
    if raw_created is None:
        raise ProvenanceValidationError("created_at is required")

    created_at = _validate_timestamp(raw_created)

    # Ensure no other top-level fields
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


def provenance_to_frontmatter_value(provenance: LifeOSProvenance) -> dict[str, object]:
    """
    Convert a typed provenance model back to a deterministically ordered mapping.
    This mapping can be safely embedded under 'lifeos_provenance' in a Markdown document.
    """
    sources_list = []
    for s in provenance.sources:
        sources_list.append({
            "path": s.path,
            "content_hash": s.content_hash,
        })

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
