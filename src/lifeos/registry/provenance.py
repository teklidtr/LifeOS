"""Provenance indexing and queries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lifeos.ingestion.provenance import ProvenanceValidationError, extract_provenance
from lifeos.markdown.parser import parse_markdown_note
from lifeos.registry._registry import Registry
from lifeos.registry._registry import RegistryError
from lifeos.scanner.git import GitScannerError, git_tracked_markdown_paths

__all__ = [
    "ProvenanceIndexError",
    "ProvenanceSourceSummary",
    "DerivedProvenanceSummary",
    "ProvenanceDocumentRow",
    "ProvenanceSourceRow",
    "refresh_provenance_index",
    "get_provenance_for_derived",
    "list_derived_for_source",
]


class ProvenanceIndexError(RuntimeError):
    """Raised when canonical provenance is malformed or invalid."""

    pass


@dataclass(frozen=True, slots=True)
class ProvenanceDocumentRow:
    derived_path: str
    schema_version: int
    generator_id: str
    generator_version: str
    prompt_schema_version: str
    model_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class ProvenanceSourceRow:
    derived_path: str
    source_index: int
    source_path: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class ProvenanceSourceSummary:
    path: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class DerivedProvenanceSummary:
    derived_path: str
    sources: tuple[ProvenanceSourceSummary, ...]
    schema_version: int
    generator_id: str
    generator_version: str
    prompt_schema_version: str
    model_id: str | None
    created_at: str


def _validate_string(val: Any, name: str) -> str:
    if not isinstance(val, str):
        raise ValueError(f"{name} must be a string")
    return val


def _validate_provenance_frontmatter(
    derived_path: str, prov: Any
) -> tuple[ProvenanceDocumentRow, tuple[ProvenanceSourceRow, ...]]:
    if not isinstance(prov, dict):
        raise ValueError("lifeos_provenance must be a dictionary")

    # Canonical ingestion provenance stores generator metadata as a nested mapping.
    # The older flat shape remains readable for registry compatibility, while new
    # generated Markdown goes through the stricter shared provenance parser.
    if "generator" in prov:
        try:
            typed = extract_provenance({"lifeos_provenance": prov})
        except ProvenanceValidationError as e:
            raise ProvenanceIndexError(f"Malformed provenance in {derived_path}: {e}") from e
        if typed is None:
            raise ProvenanceIndexError(f"Malformed provenance in {derived_path}: missing block")

        doc_row = ProvenanceDocumentRow(
            derived_path=derived_path,
            schema_version=typed.schema_version,
            generator_id=typed.generator.id,
            generator_version=typed.generator.version,
            prompt_schema_version=typed.generator.prompt_schema_version,
            model_id=typed.generator.model_id,
            created_at=typed.created_at,
        )
        canonical_source_rows = tuple(
            ProvenanceSourceRow(
                derived_path=derived_path,
                source_index=index,
                source_path=source.path,
                source_hash=source.content_hash,
            )
            for index, source in enumerate(typed.sources)
        )
        return doc_row, canonical_source_rows

    try:
        schema_version = prov.get("schema_version")
        if type(schema_version) is not int:
            raise ValueError("schema_version must be an integer")
        if schema_version != 1:
            raise ValueError("Unsupported schema_version")

        generator_id = _validate_string(prov.get("generator_id"), "generator_id")
        generator_version = _validate_string(prov.get("generator_version"), "generator_version")
        prompt_schema_version = _validate_string(
            prov.get("prompt_schema_version"), "prompt_schema_version"
        )

        model_id = prov.get("model_id")
        if model_id is not None:
            _validate_string(model_id, "model_id")

        created_at = _validate_string(prov.get("created_at"), "created_at")

        sources_list = prov.get("sources")
        if not isinstance(sources_list, list):
            raise ValueError("sources must be a list")
        if not sources_list:
            raise ValueError("sources must not be empty")

        doc_row = ProvenanceDocumentRow(
            derived_path=derived_path,
            schema_version=schema_version,
            generator_id=generator_id,
            generator_version=generator_version,
            prompt_schema_version=prompt_schema_version,
            model_id=model_id,
            created_at=created_at,
        )

        source_rows: list[ProvenanceSourceRow] = []
        for i, src in enumerate(sources_list):
            if not isinstance(src, dict):
                raise ValueError(f"sources[{i}] must be a dictionary")
            path = _validate_string(src.get("path"), f"sources[{i}].path")
            content_hash = _validate_string(src.get("content_hash"), f"sources[{i}].content_hash")
            source_rows.append(
                ProvenanceSourceRow(
                    derived_path=derived_path,
                    source_index=i,
                    source_path=path,
                    source_hash=content_hash,
                )
            )

        return doc_row, tuple(source_rows)

    except ValueError as e:
        raise ProvenanceIndexError(f"Malformed provenance in {derived_path}: {e}") from e


def refresh_provenance_index(registry: Registry, vault_root: Path) -> int:
    """Refresh the provenance index from Git-tracked canonical files."""
    try:
        candidate_paths = git_tracked_markdown_paths(vault_root)
    except GitScannerError as e:
        raise ProvenanceIndexError(f"Failed to discover tracked files: {e}") from e

    doc_rows: list[ProvenanceDocumentRow] = []
    source_rows: list[ProvenanceSourceRow] = []

    for rel_path in candidate_paths:
        abs_path = vault_root / rel_path
        if not abs_path.exists():
            raise ProvenanceIndexError(f"Tracked file missing from working tree: {rel_path}")

        parsed = parse_markdown_note(abs_path)
        prov = parsed.frontmatter.get("lifeos_provenance")
        if prov is None:
            continue

        doc, sources = _validate_provenance_frontmatter(rel_path.as_posix(), prov)
        doc_rows.append(doc)
        source_rows.extend(sources)

    doc_rows.sort(key=lambda x: x.derived_path)
    source_rows.sort(key=lambda x: (x.derived_path, x.source_index))

    with registry.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM provenance_sources")
            conn.execute("DELETE FROM provenance_documents")

            conn.executemany(
                """
                INSERT INTO provenance_documents (
                    derived_path, schema_version, generator_id, generator_version,
                    prompt_schema_version, model_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.derived_path,
                        r.schema_version,
                        r.generator_id,
                        r.generator_version,
                        r.prompt_schema_version,
                        r.model_id,
                        r.created_at,
                    )
                    for r in doc_rows
                ],
            )

            conn.executemany(
                """
                INSERT INTO provenance_sources (
                    derived_path, source_index, source_path, source_hash
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (r.derived_path, r.source_index, r.source_path, r.source_hash)
                    for r in source_rows
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return len(doc_rows)


def get_provenance_for_derived(
    registry: Registry,
    derived_path: str,
) -> DerivedProvenanceSummary | None:
    if not derived_path or derived_path.startswith("/") or ".." in derived_path.split("/"):
        raise RegistryError("Invalid vault path")

    with registry.connect_read_only() as conn:
        doc_cursor = conn.execute(
            """
            SELECT schema_version, generator_id, generator_version, prompt_schema_version, model_id, created_at
            FROM provenance_documents
            WHERE derived_path = ?
            """,
            (derived_path,),
        )
        doc_row = doc_cursor.fetchone()
        if not doc_row:
            return None

        src_cursor = conn.execute(
            """
            SELECT source_path, source_hash
            FROM provenance_sources
            WHERE derived_path = ?
            ORDER BY source_index ASC
            """,
            (derived_path,),
        )
        sources = tuple(
            ProvenanceSourceSummary(path=row[0], content_hash=row[1]) for row in src_cursor.fetchall()
        )

        return DerivedProvenanceSummary(
            derived_path=derived_path,
            sources=sources,
            schema_version=doc_row[0],
            generator_id=doc_row[1],
            generator_version=doc_row[2],
            prompt_schema_version=doc_row[3],
            model_id=doc_row[4],
            created_at=doc_row[5],
        )


def list_derived_for_source(
    registry: Registry,
    source_path: str,
) -> tuple[DerivedProvenanceSummary, ...]:
    if not source_path or source_path.startswith("/") or ".." in source_path.split("/"):
        raise RegistryError("Invalid vault path")

    with registry.connect_read_only() as conn:
        cursor = conn.execute(
            """
            SELECT DISTINCT derived_path
            FROM provenance_sources
            WHERE source_path = ?
            ORDER BY derived_path ASC
            """,
            (source_path,),
        )
        derived_paths = [row[0] for row in cursor.fetchall()]

    if not derived_paths:
        return ()

    results = []
    for dp in derived_paths:
        summary = get_provenance_for_derived(registry, dp)
        if summary:
            results.append(summary)

    return tuple(results)
