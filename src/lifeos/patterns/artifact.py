"""Canonical Markdown parsing and deterministic serialization for personal patterns."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

import yaml

from lifeos.markdown.parser import ManagedBlock, parse_markdown_note
from lifeos.vault import (
    VaultAccessError,
    iter_vault_markdown,
    read_vault_markdown,
    validate_vault_relative_path,
)

from .contracts import PatternArtifact, PatternError, PatternMetadata, metadata_from_dict

_MANAGED_NAME = "personal-pattern-evidence"
_MANAGED_START = f"<!-- lifeos:managed:start {_MANAGED_NAME} -->"
_MANAGED_END = f"<!-- lifeos:managed:end {_MANAGED_NAME} -->"


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_artifact_path(relative_path: str) -> str:
    try:
        validated = validate_vault_relative_path(relative_path)
    except VaultAccessError as exc:
        raise PatternError(
            "invalid_path",
            "Pattern path must be vault-relative.",
            {"path": relative_path},
        ) from exc
    if not validated.startswith("patterns/") or not validated.casefold().endswith(".md"):
        raise PatternError(
            "invalid_path",
            "Canonical pattern artifacts must be Markdown under patterns/.",
            {"path": relative_path},
        )
    return validated


def _declares_pattern_schema(content: str) -> bool:
    lines = content.split("\n")
    if not lines or lines[0].lstrip("\ufeff").rstrip("\r") != "---":
        return False
    for line in lines[1:]:
        clean = line.rstrip("\r")
        if clean == "---":
            break
        if re.match(r"^[ \t]*pattern_schema[ \t]*:", clean):
            return True
    return False


def _managed_block(parsed_blocks: Iterable[ManagedBlock]) -> ManagedBlock:
    blocks = tuple(parsed_blocks)
    unexpected = sorted({block.name for block in blocks if block.name != _MANAGED_NAME})
    if unexpected:
        raise PatternError(
            "malformed_artifact",
            "Pattern contains unsupported managed blocks.",
            {"blocks": unexpected},
        )
    matches = tuple(block for block in blocks if block.name == _MANAGED_NAME)
    if len(matches) != 1:
        raise PatternError(
            "malformed_artifact",
            "Pattern evidence managed block must appear exactly once.",
            {"block": _MANAGED_NAME, "count": len(matches)},
        )
    return matches[0]


def _render_managed_summary(metadata: PatternMetadata) -> str:
    counts = {"supporting": 0, "contesting": 0, "contextual": 0}
    for item in metadata.evidence:
        counts[item.role] += 1
    reasons = (
        ", ".join(" ".join(reason.split()) for reason in metadata.review_reasons)
        if metadata.review_reasons
        else "none"
    )
    return "\n".join(
        [
            _MANAGED_START,
            "## Evidence summary",
            "",
            f"- Supporting: {counts['supporting']}",
            f"- Contesting: {counts['contesting']}",
            f"- Contextual: {counts['contextual']}",
            f"- Evidence fingerprint: `{metadata.evidence_fingerprint}`",
            f"- Review reasons: {reasons}",
            _MANAGED_END,
        ]
    )


def serialize_pattern(
    metadata: PatternMetadata,
    *,
    body_prefix: str = "\n",
    body_suffix: str = "\n",
) -> str:
    """Serialize one canonical pattern while preserving caller-owned body regions verbatim."""
    dumped = yaml.safe_dump(metadata.to_frontmatter(), sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{dumped}\n---{body_prefix}{_render_managed_summary(metadata)}{body_suffix}"


def parse_pattern(path: Path, relative_path: str, content: str) -> PatternArtifact | None:
    """Parse one recognized pattern; return None for ordinary Markdown without a pattern schema."""
    _validate_artifact_path(relative_path)
    parsed = parse_markdown_note(path, content=content)
    error = next((item for item in parsed.findings if item.severity == "error"), None)
    if error is not None:
        if not _declares_pattern_schema(content):
            return None
        raise PatternError(
            "malformed_artifact", error.message, {"path": relative_path, "line": error.line}
        )

    if "pattern_schema" not in parsed.frontmatter:
        return None
    metadata = metadata_from_dict(parsed.frontmatter)
    block = _managed_block(parsed.managed_blocks)
    body_prefix = parsed.body[: block.start_offset]
    body_suffix = parsed.body[block.end_offset :]
    artifact = PatternArtifact(
        path=relative_path,
        content_hash=_content_hash(content),
        metadata=metadata,
        body_prefix=body_prefix,
        managed_summary=block.content,
        body_suffix=body_suffix,
    )
    canonical = serialize_pattern(metadata, body_prefix=body_prefix, body_suffix=body_suffix)
    reparsed = parse_markdown_note(path, content=canonical)
    if any(item.severity == "error" for item in reparsed.findings):
        raise PatternError("malformed_artifact", "Pattern could not be serialized safely.")
    return artifact


class PatternArtifactService:
    """Read canonical personal patterns directly from vault Markdown."""

    def __init__(self, *, vault_root: Path) -> None:
        self.vault_root = vault_root

    def load(self, relative_path: str) -> PatternArtifact:
        _validate_artifact_path(relative_path)
        try:
            source = read_vault_markdown(self.vault_root, relative_path)
        except VaultAccessError as exc:
            raise PatternError(exc.code, str(exc), {"path": relative_path}) from exc
        artifact = parse_pattern(source.path, source.relative_path, source.content)
        if artifact is None:
            raise PatternError(
                "unsupported_artifact",
                "Markdown without a recognized pattern schema is ordinary user content.",
                {"path": relative_path},
            )
        return artifact

    def list(self) -> tuple[PatternArtifact, ...]:
        try:
            sources = iter_vault_markdown(self.vault_root, roots=("patterns",))
        except VaultAccessError as exc:
            if exc.code == "not-found":
                return ()
            raise PatternError(exc.code, str(exc)) from exc

        artifacts: list[PatternArtifact] = []
        by_id: dict[str, str] = {}
        for source in sources:
            artifact = parse_pattern(source.path, source.relative_path, source.content)
            if artifact is None:
                continue
            previous = by_id.get(artifact.metadata.pattern_id)
            if previous is not None:
                raise PatternError(
                    "duplicate_identity",
                    "Pattern identity must resolve to exactly one canonical artifact.",
                    {
                        "pattern_id": artifact.metadata.pattern_id,
                        "paths": [previous, artifact.path],
                    },
                )
            by_id[artifact.metadata.pattern_id] = artifact.path
            artifacts.append(artifact)
        return tuple(sorted(artifacts, key=lambda item: (item.metadata.pattern_id, item.path)))

    def find(self, pattern_id: str) -> PatternArtifact:
        matches = [item for item in self.list() if item.metadata.pattern_id == pattern_id]
        if not matches:
            raise PatternError(
                "not_found",
                "Pattern could not be found.",
                {"pattern_id": pattern_id},
            )
        return matches[0]
