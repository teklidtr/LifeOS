"""Purpose-specific, disposable LifeOS exports."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote

from lifeos.diagnostics import (
    DomainDiagnostic,
    DiagnosticError,
    diagnostic_error_message,
    diagnostics_from_findings,
)
from lifeos.markdown.parser import ParsedNote, parse_markdown_note
from lifeos.publication import (
    FaultInjector,
    PublicationError,
    active_generation_path,
    inspect_generation_integrity,
    inspect_publication,
    publish_generation,
)
from lifeos.vault import VaultAccessError, VaultMarkdownFile, iter_vault_markdown

ExportKind = Literal["public-wiki", "study-bundle", "trusted-agent", "personal-review"]
ExportStatus = Literal[
    "missing", "ready", "stale", "failed", "unavailable", "unsupported"
]
_ALLOWED_KINDS = frozenset({"public-wiki", "study-bundle", "trusted-agent", "personal-review"})
_EXPORT_ROOTS: dict[str, frozenset[str]] = {
    "public-wiki": frozenset({"wiki"}),
    "study-bundle": frozenset({"study", "wiki", "flashcards"}),
    "trusted-agent": frozenset({"system", "goals", "plans", "wiki", "study", "patterns"}),
    "personal-review": frozenset({"journal", "metrics", "patterns", "goals", "plans", "reviews"}),
}
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")
_RENDERING_POLICY_VERSION = "portable-wikilinks-v2"


class ExportError(DiagnosticError):
    """Raised when an export cannot be selected or written safely."""


@dataclass(frozen=True, slots=True)
class ExportedFile:
    source_path: str
    output_path: str
    source_hash: str
    rendered_hash: str
    source_size: int
    rendered_size: int


@dataclass(frozen=True, slots=True)
class ExportManifest:
    schema_version: int
    kind: ExportKind
    rendering_policy_version: str
    source_hash: str
    file_count: int
    files: tuple[ExportedFile, ...]
    diagnostics: tuple[DomainDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportResult:
    kind: ExportKind
    output_dir: str
    file_count: int
    source_hash: str
    rendering_policy_version: str
    diagnostics: tuple[DomainDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportPublicationState:
    kind: ExportKind
    status: ExportStatus
    active_generation: str | None
    recovery_state: str
    stale_cleanup: bool
    file_count: int
    source_hash: str | None
    diagnostics: tuple[DomainDiagnostic, ...] = ()
    integrity_state: str = "none"
    integrity_code: str = "integrity-not-inspected"


@dataclass(frozen=True, slots=True)
class _PreparedExport:
    manifest: ExportManifest
    files_to_publish: dict[str, bytes]


@dataclass(frozen=True, slots=True)
class _Selection:
    included: tuple[tuple[VaultMarkdownFile, ParsedNote], ...]
    all_paths: frozenset[str]
    private_paths: frozenset[str]
    excluded_paths: frozenset[str]
    diagnostics: tuple[DomainDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class _LinkIndex:
    outputs: dict[str, str]
    aliases: dict[str, tuple[str, ...]]
    all_paths: frozenset[str]
    private_paths: frozenset[str]
    excluded_paths: frozenset[str]


def _validate_kind(kind: str) -> ExportKind:
    if kind not in _ALLOWED_KINDS:
        raise ExportError(f"kind must be one of: {', '.join(sorted(_ALLOWED_KINDS))}")
    return cast(ExportKind, kind)


def _canonical_key(relative_path: str) -> str:
    return relative_path[:-3] if relative_path.endswith(".md") else relative_path


def _selection(vault_root: Path, kind: ExportKind) -> _Selection:
    try:
        sources = iter_vault_markdown(vault_root)
    except VaultAccessError as exc:
        raise ExportError(str(exc)) from exc

    selected_roots = _EXPORT_ROOTS[kind]
    included: list[tuple[VaultMarkdownFile, ParsedNote]] = []
    all_paths = frozenset(
        _canonical_key(source.relative_path)
        for source in sources
        if source.relative_path.split("/", 1)[0] in selected_roots
    )
    private_paths: set[str] = set()
    excluded_paths: set[str] = set()
    diagnostics: list[DomainDiagnostic] = []

    for source in sources:
        key = _canonical_key(source.relative_path)
        root_name = source.relative_path.split("/", 1)[0]
        if root_name not in selected_roots:
            excluded_paths.add(key)
            continue

        parsed = parse_markdown_note(source.path, content=source.content)
        source_diagnostics = diagnostics_from_findings(parsed.findings, vault_root=vault_root)
        if source_diagnostics:
            if kind == "public-wiki":
                first = source_diagnostics[0]
                raise ExportError(diagnostic_error_message(first), diagnostic=first)
            diagnostics.extend(source_diagnostics)
            excluded_paths.add(key)
            continue

        if kind == "public-wiki":
            visibility = parsed.frontmatter.get("visibility")
            if visibility is not None and not isinstance(visibility, str):
                raise ExportError(f"{source.relative_path}: visibility must be a string")
            if isinstance(visibility, str) and visibility.strip().casefold() == "private":
                private_paths.add(key)
                continue
            status = parsed.durable_fields.status
            if isinstance(status, str) and status.strip().casefold() == "archived":
                excluded_paths.add(key)
                continue

        included.append((source, parsed))

    ordered_diagnostics = tuple(
        sorted(set(diagnostics), key=lambda item: (item.source_path, item.line, item.code))
    )
    return _Selection(
        included=tuple(included),
        all_paths=all_paths,
        private_paths=frozenset(private_paths),
        excluded_paths=frozenset(excluded_paths),
        diagnostics=ordered_diagnostics,
    )


def _build_link_index(selection: _Selection) -> _LinkIndex:
    outputs = {
        _canonical_key(source.relative_path): source.relative_path
        for source, _parsed in selection.included
    }
    alias_sets: dict[str, set[str]] = {}
    for key in selection.all_paths:
        alias_sets.setdefault(_basename(key), set()).add(key)
    aliases = {
        alias: tuple(sorted(paths))
        for alias, paths in sorted(alias_sets.items())
    }
    return _LinkIndex(
        outputs=outputs,
        aliases=aliases,
        all_paths=selection.all_paths,
        private_paths=selection.private_paths,
        excluded_paths=selection.excluded_paths,
    )


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _normalize_target(target: str) -> str:
    normalized = target.strip().replace("\\", "/")
    if normalized.endswith(".md"):
        normalized = normalized[:-3]
    return normalized.lstrip("/")


def _relative_candidate(source_key: str, target: str) -> str | None:
    source_dir = posixpath.dirname(source_key)
    candidate = posixpath.normpath(posixpath.join(source_dir, target))
    if candidate == ".." or candidate.startswith("../"):
        return None
    return candidate


def _resolve_target(
    *,
    source_key: str,
    raw_target: str,
    index: _LinkIndex,
) -> tuple[str | None, str]:
    target = _normalize_target(raw_target)
    candidates = [target]
    relative = _relative_candidate(source_key, target)
    if relative is not None and relative not in candidates:
        candidates.append(relative)

    for candidate in candidates:
        if candidate in index.outputs:
            return index.outputs[candidate], "resolved"
        if candidate in index.private_paths:
            return None, "private"
        if candidate in index.excluded_paths or candidate in index.all_paths:
            return None, "out-of-bundle"

    alias = _basename(target)
    alias_targets = index.aliases.get(alias, ())
    if len(alias_targets) > 1:
        return None, "ambiguous"
    if len(alias_targets) == 1:
        candidate = alias_targets[0]
        if candidate in index.outputs:
            return index.outputs[candidate], "resolved"
        if candidate in index.private_paths:
            return None, "private"
        return None, "out-of-bundle"
    return None, "unresolved"


def _heading_anchor(fragment: str) -> str:
    normalized = unicodedata.normalize("NFKC", fragment).casefold().strip()
    if normalized.startswith("^"):
        return quote(normalized, safe="-._~")
    characters = [
        character
        for character in normalized
        if character.isalnum() or character in {" ", "-", "_"}
    ]
    slug = re.sub(r"[\s_-]+", "-", "".join(characters)).strip("-")
    return quote(slug, safe="-._~")


def _diagnostic(
    *,
    code: str,
    source_path: str,
    line: int,
    raw_target: str,
) -> DomainDiagnostic:
    messages = {
        "private": "Link target is excluded from this public export.",
        "ambiguous": f"Wikilink target is ambiguous: {raw_target}",
        "out-of-bundle": f"Wikilink target is outside this export bundle: {raw_target}",
        "unresolved": f"Wikilink target could not be resolved: {raw_target}",
    }
    return DomainDiagnostic(
        code=f"export-link-{code}",
        severity="warning",
        source_path=source_path,
        line=line,
        message=messages[code],
    )


def _portable_markdown(
    *,
    source_path: str,
    content: str,
    index: _LinkIndex,
) -> tuple[str, tuple[DomainDiagnostic, ...]]:
    source_key = _canonical_key(source_path)
    diagnostics: list[DomainDiagnostic] = []

    def replace(match: re.Match[str]) -> str:
        raw_target = match.group(1).strip()
        fragment = match.group(2)
        label = match.group(3) or fragment or _basename(raw_target).replace("-", " ")
        output_path, resolution = _resolve_target(
            source_key=source_key,
            raw_target=raw_target,
            index=index,
        )
        if output_path is None:
            diagnostics.append(
                _diagnostic(
                    code=resolution,
                    source_path=source_path,
                    line=content.count("\n", 0, match.start()) + 1,
                    raw_target=raw_target,
                )
            )
            return label.replace("]", "\\]")
        relative_link = posixpath.relpath(output_path, start=posixpath.dirname(source_path) or ".")
        encoded = quote(relative_link, safe="/.-_~")
        if fragment:
            encoded += "#" + _heading_anchor(fragment)
        escaped_label = label.replace("]", "\\]")
        return f"[{escaped_label}]({encoded})"

    rendered = _WIKILINK_RE.sub(replace, content)
    ordered = tuple(
        sorted(
            set(diagnostics),
            key=lambda item: (item.source_path, item.line, item.code, item.message),
        )
    )
    return rendered, ordered


def _render_source(
    *,
    source: VaultMarkdownFile,
    kind: ExportKind,
    index: _LinkIndex,
) -> tuple[bytes, tuple[DomainDiagnostic, ...]]:
    if kind not in {"public-wiki", "study-bundle"}:
        return source.content_bytes, ()
    rendered, diagnostics = _portable_markdown(
        source_path=source.relative_path,
        content=source.content,
        index=index,
    )
    return rendered.encode("utf-8"), diagnostics


def _aggregate_source_hash(files: tuple[ExportedFile, ...]) -> str:
    hasher = hashlib.sha256()
    for item in files:
        hasher.update(item.source_path.encode("utf-8"))
        hasher.update(bytes.fromhex(item.source_hash))
    return hasher.hexdigest()


def _prepare_export(*, vault_root: Path, kind: ExportKind) -> _PreparedExport:
    selection = _selection(vault_root, kind)
    index = _build_link_index(selection)
    exported: list[ExportedFile] = []
    files_to_publish: dict[str, bytes] = {}
    diagnostics = list(selection.diagnostics)

    for source, _parsed in selection.included:
        rendered, link_diagnostics = _render_source(
            source=source,
            kind=kind,
            index=index,
        )
        diagnostics.extend(link_diagnostics)
        files_to_publish[source.relative_path] = rendered
        exported.append(
            ExportedFile(
                source_path=source.relative_path,
                output_path=source.relative_path,
                source_hash=hashlib.sha256(source.content_bytes).hexdigest(),
                rendered_hash=hashlib.sha256(rendered).hexdigest(),
                source_size=len(source.content_bytes),
                rendered_size=len(rendered),
            )
        )

    files = tuple(exported)
    ordered_diagnostics = tuple(
        sorted(
            set(diagnostics),
            key=lambda item: (item.source_path, item.line, item.code, item.message),
        )
    )
    manifest = ExportManifest(
        schema_version=2,
        kind=kind,
        rendering_policy_version=_RENDERING_POLICY_VERSION,
        source_hash=_aggregate_source_hash(files),
        file_count=len(files),
        files=files,
        diagnostics=ordered_diagnostics,
    )
    return _PreparedExport(manifest=manifest, files_to_publish=files_to_publish)


def build_export(
    *,
    vault_root: Path,
    runtime_dir: Path,
    kind: str,
    _fault_injector: FaultInjector | None = None,
) -> ExportResult:
    export_kind = _validate_kind(kind)
    prepared = _prepare_export(vault_root=vault_root, kind=export_kind)
    manifest = prepared.manifest
    files_to_publish = dict(prepared.files_to_publish)
    files_to_publish["manifest.json"] = (
        json.dumps(asdict(manifest), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    root = runtime_dir / "exports" / export_kind
    try:
        publish_generation(
            root=root,
            files=files_to_publish,
            fault_injector=_fault_injector,
        )
        active = active_generation_path(root)
    except PublicationError as exc:
        raise ExportError(str(exc)) from exc
    if active is None:
        raise ExportError("published export generation is unavailable")

    return ExportResult(
        kind=export_kind,
        output_dir=active.relative_to(runtime_dir).as_posix(),
        file_count=manifest.file_count,
        source_hash=manifest.source_hash,
        rendering_policy_version=manifest.rendering_policy_version,
        diagnostics=manifest.diagnostics,
    )

def _require_str(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise ExportError(f"manifest {key} is invalid")
    return value


def _require_non_negative_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if type(value) is not int or value < 0:
        raise ExportError(f"manifest {key} is invalid")
    return value


def _require_sha256(raw: dict[str, object], key: str) -> str:
    value = _require_str(raw, key)
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ExportError(f"manifest {key} is invalid")
    return value


def _load_export_manifest(
    path: Path, *, enforce_current_policy: bool
) -> ExportManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportError("export manifest is unreadable") from exc
    if not isinstance(raw, dict):
        raise ExportError("export manifest must be an object")
    version = raw.get("schema_version")
    if version == 1:
        raise ExportError("manifest schema version 1 must be rebuilt as version 2")
    if version != 2:
        raise ExportError("export manifest schema version is unsupported")
    kind = _validate_kind(_require_str(raw, "kind"))
    policy = _require_str(raw, "rendering_policy_version")
    if enforce_current_policy and policy != _RENDERING_POLICY_VERSION:
        raise ExportError("export manifest rendering policy is unsupported")
    source_hash = _require_sha256(raw, "source_hash")
    file_count = raw.get("file_count")
    raw_files = raw.get("files")
    raw_diagnostics = raw.get("diagnostics", [])
    if type(file_count) is not int or file_count < 0 or not isinstance(raw_files, list):
        raise ExportError("export manifest file inventory is invalid")
    files: list[ExportedFile] = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise ExportError("export manifest file entry is invalid")
        files.append(
            ExportedFile(
                source_path=_require_str(item, "source_path"),
                output_path=_require_str(item, "output_path"),
                source_hash=_require_sha256(item, "source_hash"),
                rendered_hash=_require_sha256(item, "rendered_hash"),
                source_size=_require_non_negative_int(item, "source_size"),
                rendered_size=_require_non_negative_int(item, "rendered_size"),
            )
        )
    if len(files) != file_count:
        raise ExportError("export manifest file count is inconsistent")
    if not isinstance(raw_diagnostics, list):
        raise ExportError("export manifest diagnostics are invalid")
    diagnostics: list[DomainDiagnostic] = []
    for item in raw_diagnostics:
        if not isinstance(item, dict):
            raise ExportError("export manifest diagnostic is invalid")
        severity = item.get("severity")
        line = item.get("line")
        if severity not in {"error", "warning"} or type(line) is not int:
            raise ExportError("export manifest diagnostic fields are invalid")
        diagnostics.append(
            DomainDiagnostic(
                code=_require_str(item, "code"),
                severity=cast(Literal["error", "warning"], severity),
                source_path=_require_str(item, "source_path"),
                line=line,
                message=_require_str(item, "message"),
            )
        )
    return ExportManifest(
        2,
        kind,
        policy,
        source_hash,
        file_count,
        tuple(files),
        tuple(diagnostics),
    )


def load_export_manifest(path: Path) -> ExportManifest:
    return _load_export_manifest(path, enforce_current_policy=True)


def _freshness_failure_diagnostics(error: ExportError) -> tuple[DomainDiagnostic, ...]:
    if error.diagnostic is not None:
        return (error.diagnostic,)
    return (
        DomainDiagnostic(
            code="export-freshness-unavailable",
            severity="error",
            source_path="",
            line=0,
            message="Current canonical export selection could not be inspected.",
        ),
    )


def export_status(
    *,
    vault_root: Path,
    runtime_dir: Path,
    kind: str,
) -> ExportPublicationState:
    export_kind = _validate_kind(kind)
    root = runtime_dir / "exports" / export_kind
    inspection = inspect_publication(root)
    if inspection.recovery_state == "corrupt":
        return ExportPublicationState(
            export_kind,
            "failed",
            inspection.active_generation,
            inspection.recovery_state,
            inspection.stale_cleanup,
            0,
            None,
        )
    try:
        active = active_generation_path(root)
    except PublicationError:
        active = None
    if active is None:
        status: ExportStatus = "failed" if inspection.active_generation else "missing"
        return ExportPublicationState(
            export_kind,
            status,
            inspection.active_generation,
            inspection.recovery_state,
            inspection.stale_cleanup,
            0,
            None,
        )
    integrity = inspect_generation_integrity(active)
    if integrity.state in {"corrupt", "unavailable", "unsupported"}:
        integrity_status: ExportStatus = (
            "failed" if integrity.state == "corrupt" else integrity.state
        )
        return ExportPublicationState(
            export_kind,
            integrity_status,
            inspection.active_generation,
            inspection.recovery_state,
            inspection.stale_cleanup,
            0,
            None,
            (),
            integrity.state,
            integrity.code,
        )
    try:
        manifest = _load_export_manifest(
            active / "manifest.json", enforce_current_policy=False
        )
    except ExportError:
        return ExportPublicationState(
            export_kind,
            "failed",
            inspection.active_generation,
            inspection.recovery_state,
            inspection.stale_cleanup,
            0,
            None,
        )
    if manifest.kind != export_kind:
        return ExportPublicationState(
            export_kind,
            "failed",
            inspection.active_generation,
            inspection.recovery_state,
            inspection.stale_cleanup,
            0,
            None,
        )
    try:
        current = _prepare_export(vault_root=vault_root, kind=export_kind).manifest
    except ExportError as exc:
        return ExportPublicationState(
            export_kind,
            "failed",
            inspection.active_generation,
            inspection.recovery_state,
            inspection.stale_cleanup,
            manifest.file_count,
            manifest.source_hash,
            _freshness_failure_diagnostics(exc),
        )
    status = "ready" if manifest == current else "stale"
    return ExportPublicationState(
        export_kind,
        status,
        inspection.active_generation,
        inspection.recovery_state,
        inspection.stale_cleanup,
        manifest.file_count,
        manifest.source_hash,
        current.diagnostics,
        integrity.state,
        integrity.code,
    )

def serialize_export_result(result: ExportResult) -> str:
    return json.dumps(asdict(result), sort_keys=True, indent=2)


def format_export_result(result: ExportResult) -> str:
    return (
        f"Built {result.kind} export\n"
        f"Output: {result.output_dir}\n"
        f"Files: {result.file_count}\n"
        f"Source hash: {result.source_hash}\n"
        f"Rendering policy: {result.rendering_policy_version}\n"
        f"Diagnostics: {len(result.diagnostics)}"
    )


def serialize_export_status(state: ExportPublicationState) -> str:
    return json.dumps(asdict(state), sort_keys=True, indent=2)


def format_export_status(state: ExportPublicationState) -> str:
    return (
        f"Export {state.kind}: {state.status}\n"
        f"Active generation: {state.active_generation or 'none'}\n"
        f"Recovery: {state.recovery_state}\n"
        f"Stale cleanup: {'yes' if state.stale_cleanup else 'no'}\n"
        f"Integrity: {state.integrity_state} [{state.integrity_code}]\n"
        f"Files: {state.file_count}"
    )
