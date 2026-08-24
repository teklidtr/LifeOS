"""Typed, allowlisted instruction loading and context applicability."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

import yaml

from lifeos.context.search import (
    ContextSearchExecutionError,
    PathFilter,
    SearchResult,
    lexical_terms,
)
from lifeos.diagnostics import DomainDiagnostic
from lifeos.vault import VaultAccessError, read_vault_text
from lifeos.vault_paths import iter_vault_text_paths

InstructionAuthority = Literal["system", "repository", "scope", "note-local"]
InstructionScope = Literal["global", "domain", "path", "note"]
_ALLOWED_AUTHORITIES = frozenset({"system", "repository", "scope", "note-local"})
_ALLOWED_SCOPES = frozenset({"global", "domain", "path", "note"})
_AUTHORITY_ORDER: dict[str, int] = {
    "system": 0,
    "repository": 1,
    "scope": 2,
    "note-local": 3,
}
_ALLOWED_SOURCE = "system/instructions.yml"
_ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_INSTRUCTION_MARKER_RE = re.compile(r"(?m)^\s*instructions\s*:")
_ALLOWED_ITEM_KEYS = frozenset(
    {
        "id",
        "authority",
        "scope",
        "priority",
        "text",
        "domains",
        "paths",
        "query_terms",
    }
)


@dataclass(frozen=True, slots=True)
class ContextInstruction:
    """A validated instruction plus inspectable applicability evidence."""

    id: str
    authority: InstructionAuthority
    scope: InstructionScope
    priority: int
    text: str
    domains: tuple[str, ...]
    paths: tuple[str, ...]
    query_terms: tuple[str, ...]
    source_path: str
    applicable_sources: tuple[str, ...] = ()
    applicability: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InstructionReport:
    instructions: tuple[ContextInstruction, ...]
    diagnostics: tuple[DomainDiagnostic, ...]
    allowlisted_source_present: bool


def _diagnostic(code: str, source_path: str, message: str) -> DomainDiagnostic:
    return DomainDiagnostic(
        code=code,
        severity="warning" if code == "instruction-source-not-allowed" else "error",
        source_path=source_path,
        line=1,
        message=" ".join(message.split())[:300],
    )


def _string_list(raw: object, *, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(type(item) is not str or not item.strip() for item in raw):
        raise ValueError(f"{field} must be a list of non-empty strings")
    values = tuple(item.strip() for item in raw)
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must not contain duplicates")
    return values


def _validate_domain(domain: str) -> None:
    if "/" in domain or "\\" in domain or "\x00" in domain or domain in {".", ".."}:
        raise ValueError("domains must contain top-level vault names")


def _validate_path_pattern(pattern: str) -> None:
    if pattern.startswith("/") or "\\" in pattern or "\x00" in pattern:
        raise ValueError("paths must be relative POSIX patterns")
    parts = pattern.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("paths must stay within the vault")


def _parse_instruction(raw: object, *, source_path: str) -> ContextInstruction:
    if not isinstance(raw, dict):
        raise ValueError("instruction entry must be an object")
    unknown = set(raw) - _ALLOWED_ITEM_KEYS
    if unknown:
        raise ValueError(f"instruction entry has unsupported fields: {', '.join(sorted(unknown))}")

    stable_id = raw.get("id")
    authority = raw.get("authority")
    scope = raw.get("scope")
    priority = raw.get("priority")
    text = raw.get("text")
    if type(stable_id) is not str or _ID_RE.fullmatch(stable_id) is None:
        raise ValueError("id must be a stable lowercase identifier")
    if authority not in _ALLOWED_AUTHORITIES:
        raise ValueError("authority must be system, repository, scope, or note-local")
    if scope not in _ALLOWED_SCOPES:
        raise ValueError("scope must be global, domain, path, or note")
    if type(priority) is not int or not (-1000 <= priority <= 1000):
        raise ValueError("priority must be an integer from -1000 through 1000")
    if type(text) is not str or not text.strip():
        raise ValueError("text must be a non-empty string")

    domains = _string_list(raw.get("domains"), field="domains")
    paths = _string_list(raw.get("paths"), field="paths")
    query_terms = _string_list(raw.get("query_terms"), field="query_terms")
    for domain in domains:
        _validate_domain(domain)
    for pattern in paths:
        _validate_path_pattern(pattern)
    normalized_query_terms = tuple(
        dict.fromkeys(term for value in query_terms for term in lexical_terms(value))
    )
    if query_terms and not normalized_query_terms:
        raise ValueError("query_terms must contain searchable tokens")

    if scope == "global" and (domains or paths):
        raise ValueError("global instructions cannot declare domains or paths")
    if scope == "domain" and (not domains or paths):
        raise ValueError("domain instructions must declare domains only")
    if scope in {"path", "note"} and (not paths or domains):
        raise ValueError(f"{scope} instructions must declare paths only")
    if scope == "note" and (
        len(paths) != 1 or any(character in paths[0] for character in {"*", "?", "["})
    ):
        raise ValueError("note instructions must declare one exact path")
    if authority == "note-local" and scope != "note":
        raise ValueError("note-local authority requires note scope")
    if authority == "scope" and scope == "global":
        raise ValueError("scope authority cannot declare global scope")

    return ContextInstruction(
        id=stable_id,
        authority=cast(InstructionAuthority, authority),
        scope=cast(InstructionScope, scope),
        priority=priority,
        text=text.strip(),
        domains=domains,
        paths=paths,
        query_terms=normalized_query_terms,
        source_path=source_path,
    )


def _glob_matches(path: str, pattern: str) -> bool:
    pieces: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                pieces.append(".*")
                index += 2
                continue
            pieces.append("[^/]*")
        elif character == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(character))
        index += 1
    pieces.append("$")
    return re.fullmatch("".join(pieces), path) is not None


def _source_matches(
    instruction: ContextInstruction,
    sources: tuple[SearchResult, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if instruction.scope == "global":
        return tuple(source.path for source in sources), ("scope:global",)

    matched_sources: list[str] = []
    reasons: set[str] = set()
    for source in sources:
        root = source.path.split("/", 1)[0]
        domain_matches = [domain for domain in instruction.domains if root == domain]
        path_matches = [pattern for pattern in instruction.paths if _glob_matches(source.path, pattern)]
        if domain_matches or path_matches:
            matched_sources.append(source.path)
            reasons.update(f"domain:{domain}" for domain in domain_matches)
            reasons.update(f"path:{pattern}" for pattern in path_matches)
    return tuple(sorted(set(matched_sources))), tuple(sorted(reasons))


def _apply_instruction(
    instruction: ContextInstruction,
    *,
    question_terms: frozenset[str],
    sources: tuple[SearchResult, ...],
) -> ContextInstruction | None:
    query_matches = tuple(term for term in instruction.query_terms if term in question_terms)
    if instruction.query_terms and not query_matches:
        return None

    matched_sources, source_reasons = _source_matches(instruction, sources)
    if instruction.scope != "global" and not matched_sources:
        return None

    reasons = [*source_reasons]
    reasons.extend(f"query-term:{term}" for term in query_matches)
    if not instruction.query_terms:
        reasons.append("query:any")
    return replace(
        instruction,
        applicable_sources=matched_sources,
        applicability=tuple(sorted(set(reasons))),
    )


def _unauthorized_source_diagnostics(
    vault_root: Path,
    *,
    path_filter: PathFilter | None,
) -> tuple[DomainDiagnostic, ...]:
    try:
        paths = iter_vault_text_paths(
            vault_root,
            suffixes=(".yml", ".yaml"),
            path_filter=path_filter,
        )
    except VaultAccessError as exc:
        raise ContextSearchExecutionError(str(exc)) from exc
    diagnostics: list[DomainDiagnostic] = []
    for relative_path in paths:
        if relative_path == _ALLOWED_SOURCE:
            continue
        try:
            source = read_vault_text(vault_root, relative_path)
        except VaultAccessError as exc:
            raise ContextSearchExecutionError(str(exc)) from exc
        basename = source.relative_path.rsplit("/", 1)[-1].casefold()
        if "instruction" in basename or _INSTRUCTION_MARKER_RE.search(source.content):
            diagnostics.append(
                _diagnostic(
                    "instruction-source-not-allowed",
                    source.relative_path,
                    "Instruction-like content was ignored because the source is not allowlisted.",
                )
            )
    return tuple(diagnostics)


def load_instruction_report(
    *,
    vault_root: Path,
    question: str,
    sources: tuple[SearchResult, ...],
    path_filter: PathFilter | None = None,
) -> InstructionReport:
    """Load validated instructions from the one authoritative source."""
    diagnostics = list(
        _unauthorized_source_diagnostics(vault_root, path_filter=path_filter)
    )
    if path_filter is not None and not path_filter(_ALLOWED_SOURCE):
        return InstructionReport((), tuple(diagnostics), False)
    try:
        source = read_vault_text(vault_root, _ALLOWED_SOURCE)
    except VaultAccessError as exc:
        if exc.code == "not-found":
            return InstructionReport((), tuple(diagnostics), False)
        raise ContextSearchExecutionError(str(exc)) from exc

    try:
        document: object = yaml.safe_load(source.content)
    except yaml.YAMLError:
        diagnostics.append(
            _diagnostic(
                "instruction-schema-invalid",
                _ALLOWED_SOURCE,
                "Instruction YAML could not be parsed.",
            )
        )
        return InstructionReport((), tuple(sorted(diagnostics, key=_diagnostic_key)), True)

    if not isinstance(document, dict):
        diagnostics.append(
            _diagnostic(
                "instruction-schema-invalid",
                _ALLOWED_SOURCE,
                "Instruction document must be an object.",
            )
        )
        return InstructionReport((), tuple(sorted(diagnostics, key=_diagnostic_key)), True)
    if set(document) - {"schema_version", "instructions"}:
        diagnostics.append(
            _diagnostic(
                "instruction-schema-invalid",
                _ALLOWED_SOURCE,
                "Instruction document contains unsupported fields.",
            )
        )
        return InstructionReport((), tuple(sorted(diagnostics, key=_diagnostic_key)), True)
    if type(document.get("schema_version")) is not int or document.get("schema_version") != 1:
        diagnostics.append(
            _diagnostic(
                "instruction-schema-invalid",
                _ALLOWED_SOURCE,
                "Instruction schema_version must be 1.",
            )
        )
        return InstructionReport((), tuple(sorted(diagnostics, key=_diagnostic_key)), True)
    raw_instructions = document.get("instructions")
    if not isinstance(raw_instructions, list):
        diagnostics.append(
            _diagnostic(
                "instruction-schema-invalid",
                _ALLOWED_SOURCE,
                "instructions must be a list.",
            )
        )
        return InstructionReport((), tuple(sorted(diagnostics, key=_diagnostic_key)), True)

    parsed: list[ContextInstruction] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_instructions):
        try:
            instruction = _parse_instruction(raw, source_path=_ALLOWED_SOURCE)
        except ValueError as exc:
            diagnostics.append(
                _diagnostic(
                    "instruction-entry-invalid",
                    _ALLOWED_SOURCE,
                    f"Instruction entry {index + 1} is invalid: {exc}",
                )
            )
            continue
        if instruction.id in seen:
            diagnostics.append(
                _diagnostic(
                    "instruction-duplicate-id",
                    _ALLOWED_SOURCE,
                    f"Instruction ID is duplicated: {instruction.id}",
                )
            )
            continue
        seen.add(instruction.id)
        parsed.append(instruction)

    question_terms = frozenset(lexical_terms(question))
    applicable = tuple(
        item
        for instruction in parsed
        if (item := _apply_instruction(
            instruction,
            question_terms=question_terms,
            sources=sources,
        ))
        is not None
    )
    ordered = tuple(
        sorted(
            applicable,
            key=lambda item: (
                -item.priority,
                _AUTHORITY_ORDER[item.authority],
                item.id,
            ),
        )
    )
    return InstructionReport(
        ordered,
        tuple(sorted(set(diagnostics), key=_diagnostic_key)),
        True,
    )


def _diagnostic_key(item: DomainDiagnostic) -> tuple[str, int, str, str, str]:
    return (item.source_path, item.line, item.code, item.severity, item.message)
