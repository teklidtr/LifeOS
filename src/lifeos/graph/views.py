"""Disposable, deterministic relationship graph views."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from lifeos.diagnostics import (
    DomainDiagnostic,
    DiagnosticError,
    diagnostics_from_findings,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.publication import (
    FaultInjector,
    PublicationError,
    active_generation_path,
    inspect_generation_integrity,
    inspect_publication,
    publish_generation,
)
from lifeos.vault import VaultAccessError, VaultMarkdownFile, iter_vault_markdown

GraphStatus = Literal[
    "missing", "clean", "dirty", "failed", "unavailable", "unsupported"
]
_ALLOWED_VIEWS = frozenset({"knowledge", "provenance", "personal-patterns", "system"})
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_VIEW_ROOTS: dict[str, frozenset[str]] = {
    "knowledge": frozenset({"wiki", "study", "flashcards"}),
    "provenance": frozenset({"raw", "study", "wiki", "flashcards"}),
    "personal-patterns": frozenset({"journal", "patterns", "metrics", "goals", "plans", "experiments"}),
    "system": frozenset({"system", "proposals"}),
}


class GraphError(DiagnosticError):
    """Raised when graph extraction or persistence fails."""


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    path: str
    title: str
    note_type: str
    description: str


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    evidence: str
    source_path: str


@dataclass(frozen=True, slots=True)
class GraphDocument:
    schema_version: int
    view_name: str
    source_hash: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    diagnostics: tuple[DomainDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class GraphViewState:
    view_name: str
    status: GraphStatus
    source_hash: str | None
    node_count: int
    edge_count: int
    diagnostics: tuple[DomainDiagnostic, ...] = ()
    active_generation: str | None = None
    recovery_state: str = "none"
    stale_cleanup: bool = False
    integrity_state: str = "none"
    integrity_code: str = "integrity-not-inspected"


def _validate_view(view_name: str) -> None:
    if view_name not in _ALLOWED_VIEWS:
        raise GraphError(f"view_name must be one of: {', '.join(sorted(_ALLOWED_VIEWS))}")


def _selected_files(vault_root: Path, view_name: str) -> tuple[VaultMarkdownFile, ...]:
    try:
        return iter_vault_markdown(vault_root, roots=_VIEW_ROOTS[view_name])
    except VaultAccessError as exc:
        raise GraphError(str(exc)) from exc


def _hash_sources(files: tuple[VaultMarkdownFile, ...]) -> str:
    hasher = hashlib.sha256()
    for source in files:
        relative = source.relative_path.encode("utf-8")
        hasher.update(len(relative).to_bytes(4, "big"))
        hasher.update(relative)
        hasher.update(hashlib.sha256(source.content_bytes).digest())
    return hasher.hexdigest()


def _node_id(path: Path, vault_root: Path, frontmatter: dict[str, Any]) -> str:
    raw_id = frontmatter.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    return path.relative_to(vault_root).with_suffix("").as_posix()


def _relation_edges(
    *,
    node_id: str,
    source_path: str,
    relations: object,
) -> list[GraphEdge]:
    if relations is None:
        return []
    if not isinstance(relations, list):
        raise GraphError(f"{source_path}: relations must be a list")
    edges: list[GraphEdge] = []
    for relation in relations:
        if not isinstance(relation, dict):
            raise GraphError(f"{source_path}: every relation must be a mapping")
        target = relation.get("target")
        relation_type = relation.get("type")
        evidence = relation.get("evidence", "explicit")
        if not isinstance(target, str) or not target.strip():
            raise GraphError(f"{source_path}: relation target must be a non-empty string")
        if not isinstance(relation_type, str) or not relation_type.strip():
            raise GraphError(f"{source_path}: relation type must be a non-empty string")
        if evidence not in {"explicit", "derived", "inferred", "ambiguous"}:
            raise GraphError(f"{source_path}: relation evidence is invalid")
        edges.append(
            GraphEdge(
                source=node_id,
                target=target.strip(),
                relation=relation_type.strip(),
                evidence=str(evidence),
                source_path=source_path,
            )
        )
    return edges


def build_graph_document(*, vault_root: Path, view_name: str) -> GraphDocument:
    _validate_view(view_name)
    sources = _selected_files(vault_root, view_name)
    source_hash = _hash_sources(sources)
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    path_to_id: dict[str, str] = {}
    stem_targets: dict[str, set[str]] = {}
    id_to_path: dict[str, str] = {}
    parsed_notes: list[tuple[Path, str, str, dict[str, Any], str]] = []
    diagnostics: list[DomainDiagnostic] = []

    for source in sources:
        path = source.path
        parsed = parse_markdown_note(path, content=source.content)
        relative = source.relative_path
        source_diagnostics = diagnostics_from_findings(parsed.findings, vault_root=vault_root)
        if source_diagnostics:
            diagnostics.extend(source_diagnostics)
            continue
        data = dict(parsed.frontmatter)
        node_id = _node_id(path, vault_root, data)
        previous_path = id_to_path.get(node_id)
        if previous_path is not None:
            raise GraphError(
                f"duplicate graph node id {node_id!r}: {previous_path} and {relative}"
            )
        id_to_path[node_id] = relative
        path_to_id[path.with_suffix("").relative_to(vault_root).as_posix()] = node_id
        stem_targets.setdefault(path.stem, set()).add(node_id)
        title = parsed.durable_fields.title or path.stem.replace("-", " ")
        note_type = parsed.durable_fields.type or "note"
        description = parsed.durable_fields.description or ""
        nodes.append(GraphNode(node_id, relative, title, note_type, description))
        parsed_notes.append((path, relative, node_id, data, parsed.body))

    for stem, targets in stem_targets.items():
        if len(targets) == 1:
            path_to_id[stem] = next(iter(targets))

    node_ids = {node.id for node in nodes}
    for _path, relative, node_id, data, body in parsed_notes:
        for raw_target in _WIKILINK_RE.findall(body):
            canonical_target = raw_target.strip().replace("\\", "/")
            target = path_to_id.get(canonical_target, canonical_target)
            if target == node_id:
                continue
            edges.append(GraphEdge(node_id, target, "wikilink", "explicit", relative))
        edges.extend(
            _relation_edges(
                node_id=node_id,
                source_path=relative,
                relations=data.get("relations"),
            )
        )

    nodes.sort(key=lambda node: (node.id, node.path))
    edges = [edge for edge in edges if edge.target in node_ids or edge.relation != "wikilink"]
    edges.sort(key=lambda edge: (edge.source, edge.target, edge.relation, edge.source_path))
    deduped_edges = tuple(dict.fromkeys(edges))
    return GraphDocument(
        1,
        view_name,
        source_hash,
        tuple(nodes),
        deduped_edges,
        tuple(sorted(set(diagnostics), key=lambda item: (item.source_path, item.line, item.code))),
    )


def _serialize(document: GraphDocument) -> bytes:
    return (
        json.dumps(asdict(document), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def build_graph_view(
    *,
    vault_root: Path,
    runtime_dir: Path,
    view_name: str,
    _fault_injector: FaultInjector | None = None,
) -> GraphViewState:
    document = build_graph_document(vault_root=vault_root, view_name=view_name)
    generation_state = GraphViewState(
        view_name=view_name,
        status="clean",
        source_hash=document.source_hash,
        node_count=len(document.nodes),
        edge_count=len(document.edges),
        diagnostics=document.diagnostics,
    )
    root = runtime_dir / "graphify" / view_name
    try:
        inspection = publish_generation(
            root=root,
            files={
                "graph.json": _serialize(document),
                "state.json": (
                    json.dumps(asdict(generation_state), sort_keys=True, indent=2) + "\n"
                ).encode("utf-8"),
            },
            fault_injector=_fault_injector,
        )
    except PublicationError as exc:
        raise GraphError(str(exc)) from exc
    return GraphViewState(
        view_name=view_name,
        status="clean",
        source_hash=document.source_hash,
        node_count=len(document.nodes),
        edge_count=len(document.edges),
        diagnostics=document.diagnostics,
        active_generation=inspection.active_generation,
        recovery_state=inspection.recovery_state,
        stale_cleanup=inspection.stale_cleanup,
    )


def graph_view_status(
    *,
    vault_root: Path,
    runtime_dir: Path,
    view_name: str,
) -> GraphViewState:
    _validate_view(view_name)
    root = runtime_dir / "graphify" / view_name
    inspection = inspect_publication(root)
    if inspection.recovery_state == "corrupt":
        return GraphViewState(
            view_name,
            "failed",
            None,
            0,
            0,
            (),
            inspection.active_generation,
            inspection.recovery_state,
            inspection.stale_cleanup,
        )
    try:
        generation = active_generation_path(root)
    except PublicationError:
        return GraphViewState(
            view_name,
            "failed",
            None,
            0,
            0,
            (),
            inspection.active_generation,
            inspection.recovery_state,
            inspection.stale_cleanup,
        )
    if generation is None and (root / "state.json").exists():
        return GraphViewState(
            view_name,
            "failed",
            None,
            0,
            0,
            (),
            None,
            inspection.recovery_state,
            inspection.stale_cleanup,
        )
    if generation is None:
        return GraphViewState(
            view_name,
            "missing",
            None,
            0,
            0,
            (),
            None,
            inspection.recovery_state,
            inspection.stale_cleanup,
        )
    integrity = inspect_generation_integrity(generation)
    if integrity.state in {"corrupt", "unavailable", "unsupported"}:
        integrity_status: GraphStatus = (
            "failed" if integrity.state == "corrupt" else integrity.state
        )
        return GraphViewState(
            view_name=view_name,
            status=integrity_status,
            source_hash=None,
            node_count=0,
            edge_count=0,
            active_generation=inspection.active_generation,
            recovery_state=inspection.recovery_state,
            stale_cleanup=inspection.stale_cleanup,
            integrity_state=integrity.state,
            integrity_code=integrity.code,
        )
    state_path = generation / "state.json"
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return GraphViewState(view_name, "failed", None, 0, 0)
    if not isinstance(raw, dict):
        return GraphViewState(view_name, "failed", None, 0, 0)
    if raw.get("view_name") != view_name or raw.get("status") != "clean":
        return GraphViewState(view_name, "failed", None, 0, 0)
    try:
        recorded_hash = raw["source_hash"]
        node_count = raw["node_count"]
        edge_count = raw["edge_count"]
        raw_diagnostics = raw.get("diagnostics", [])
    except (KeyError, TypeError):
        return GraphViewState(view_name, "failed", None, 0, 0)
    if not isinstance(recorded_hash, str) or re.fullmatch(r"[0-9a-f]{64}", recorded_hash) is None:
        return GraphViewState(view_name, "failed", None, 0, 0)
    if (
        type(node_count) is not int
        or node_count < 0
        or type(edge_count) is not int
        or edge_count < 0
        or not isinstance(raw_diagnostics, list)
    ):
        return GraphViewState(view_name, "failed", None, 0, 0)
    diagnostics: list[DomainDiagnostic] = []
    for item in raw_diagnostics:
        if not isinstance(item, dict):
            return GraphViewState(view_name, "failed", None, 0, 0)
        code = item.get("code")
        severity = item.get("severity")
        source_path = item.get("source_path")
        line = item.get("line")
        message = item.get("message")
        if (
            not isinstance(code, str)
            or severity not in {"error", "warning"}
            or not isinstance(source_path, str)
            or type(line) is not int
            or not isinstance(message, str)
        ):
            return GraphViewState(view_name, "failed", None, 0, 0)
        diagnostics.append(
            DomainDiagnostic(code, severity, source_path, line, message)
        )
    current_hash = _hash_sources(_selected_files(vault_root, view_name))
    status: GraphStatus = "clean" if recorded_hash == current_hash else "dirty"
    return GraphViewState(
        view_name,
        status,
        recorded_hash,
        node_count,
        edge_count,
        tuple(diagnostics),
        inspection.active_generation,
        inspection.recovery_state,
        inspection.stale_cleanup,
        integrity.state,
        integrity.code,
    )


def serialize_graph_state(state: GraphViewState) -> str:
    return json.dumps(asdict(state), sort_keys=True, indent=2)


def format_graph_state(state: GraphViewState) -> str:
    return (
        f"Graph view {state.view_name}: {state.status}\n"
        f"Nodes: {state.node_count}\n"
        f"Edges: {state.edge_count}\n"
        f"Diagnostics: {len(state.diagnostics)}\n"
        f"Active generation: {state.active_generation or 'none'}\n"
        f"Recovery: {state.recovery_state}\n"
        f"Stale cleanup: {'yes' if state.stale_cleanup else 'no'}\n"
        f"Integrity: {state.integrity_state} [{state.integrity_code}]"
    )
