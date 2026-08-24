"""Inspectable context-pack assembly."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from lifeos.context.instructions import ContextInstruction, load_instruction_report
from lifeos.context.search import (
    ContextSearchError,
    PathFilter,
    SearchResult,
    focused_search_results,
    lexical_search_report,
)
from lifeos.diagnostics import DomainDiagnostic


@dataclass(frozen=True, slots=True)
class ContextPack:
    question: str
    instructions: tuple[ContextInstruction, ...]
    sources: tuple[SearchResult, ...]
    evidence_gaps: tuple[str, ...]
    omissions: tuple[str, ...]
    diagnostics: tuple[DomainDiagnostic, ...]


def _diagnostic_key(item: DomainDiagnostic) -> tuple[str, int, str, str, str]:
    return (item.source_path, item.line, item.code, item.severity, item.message)


def build_context_pack(
    *,
    vault_root: Path,
    question: str,
    limit: int = 8,
    focus_paths: tuple[str, ...] = (),
    path_filter: PathFilter | None = None,
) -> ContextPack:
    if type(limit) is not int or limit <= 0:
        raise ContextSearchError("limit must be a positive integer")
    focused = focused_search_results(
        vault_root=vault_root,
        paths=focus_paths,
        path_filter=path_filter,
    )
    if len(focused) > limit:
        raise ContextSearchError("focus_paths cannot exceed the context source limit")
    search_report = lexical_search_report(
        vault_root=vault_root,
        query=question,
        limit=limit + len(focused) + 1,
        path_filter=path_filter,
    )
    focused_paths = {item.path for item in focused}
    lexical = tuple(item for item in search_report.results if item.path not in focused_paths)
    remaining = max(0, limit - len(focused))
    limited = len(lexical) > remaining
    sources = (*focused, *lexical[:remaining])
    instruction_report = load_instruction_report(
        vault_root=vault_root,
        question=question,
        sources=sources,
        path_filter=path_filter,
    )
    gaps: list[str] = []
    omissions: list[str] = []

    if not sources:
        gaps.append("No matching canonical Markdown sources were found.")
    else:
        roots = {source.path.split("/", 1)[0] for source in sources}
        if len(sources) == 1:
            gaps.append("Only one matching source was found.")
        if len(roots) == 1:
            gaps.append("Matching evidence comes from a single vault area.")
        if all(not source.description for source in sources):
            gaps.append("Matching sources do not provide routing descriptions.")
        if limited:
            omissions.append(f"Results were limited to the top {limit} sources.")

    if not instruction_report.allowlisted_source_present:
        omissions.append("No system/instructions.yml file was available for this context.")
    elif not instruction_report.instructions:
        omissions.append("No validated instructions applied to this context pack.")

    diagnostics = tuple(
        sorted(
            set((*search_report.diagnostics, *instruction_report.diagnostics)),
            key=_diagnostic_key,
        )
    )
    return ContextPack(
        question=question.strip(),
        instructions=instruction_report.instructions,
        sources=sources,
        evidence_gaps=tuple(gaps),
        omissions=tuple(omissions),
        diagnostics=diagnostics,
    )


def serialize_context_pack(pack: ContextPack) -> str:
    return json.dumps(asdict(pack), sort_keys=True, ensure_ascii=False, indent=2)


def format_context_pack(pack: ContextPack) -> str:
    lines = [f"Question: {pack.question}", ""]
    lines.append("Instructions")
    if pack.instructions:
        for item in pack.instructions:
            lines.append(
                f"  - [{item.id}] {item.text} "
                f"(authority {item.authority}, scope {item.scope}, priority {item.priority})"
            )
            lines.append(f"    applicability: {', '.join(item.applicability)}")
            if item.applicable_sources:
                lines.append(f"    sources: {', '.join(item.applicable_sources)}")
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Sources")
    if not pack.sources:
        lines.append("  none")
    for source in pack.sources:
        lines.append(f"  {source.path} (score {source.score})")
        evidence = ", ".join(
            f"{item.term}:{item.field} {item.match_count}×{item.weight}={item.score}"
            for item in source.score_evidence
        )
        lines.append(f"    score evidence: {evidence}")
        if source.description:
            lines.append(f"    {source.description}")
        if source.excerpt:
            lines.append(f"    {source.excerpt}")

    lines.append("")
    lines.append("Diagnostics")
    if pack.diagnostics:
        lines.extend(
            f"  - [{item.code}] {item.source_path}:{item.line} {item.message}"
            for item in pack.diagnostics
        )
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Evidence gaps")
    lines.extend(f"  - {item}" for item in pack.evidence_gaps)
    if not pack.evidence_gaps:
        lines.append("  none identified")

    lines.append("")
    lines.append("Omissions")
    lines.extend(f"  - {item}" for item in pack.omissions)
    if not pack.omissions:
        lines.append("  none")
    return "\n".join(lines)
