from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.graph import GraphError, build_graph_document, build_graph_view, graph_view_status


def _write_note(vault: Path, relative: str, content: str) -> None:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_knowledge_graph_extracts_stable_nodes_and_links(tmp_path: Path) -> None:
    _write_note(
        tmp_path,
        "wiki/energy.md",
        "---\nid: concept-energy\ntype: concept\ntitle: Energy\ndescription: Cellular energy.\n---\n"
        "See [[wiki/atp]].\n",
    )
    _write_note(
        tmp_path,
        "wiki/atp.md",
        "---\nid: concept-atp\ntype: concept\ntitle: ATP\nrelations:\n"
        "  - target: concept-energy\n    type: supports\n    evidence: explicit\n---\n",
    )
    _write_note(tmp_path, "journal/day.md", "Journal text [[wiki/energy]].\n")

    document = build_graph_document(vault_root=tmp_path, view_name="knowledge")

    assert [node.id for node in document.nodes] == ["concept-atp", "concept-energy"]
    assert [(edge.source, edge.target, edge.relation) for edge in document.edges] == [
        ("concept-atp", "concept-energy", "supports"),
        ("concept-energy", "concept-atp", "wikilink"),
    ]
    assert all(not node.path.startswith("journal/") for node in document.nodes)


def test_graph_views_are_separate(tmp_path: Path) -> None:
    _write_note(tmp_path, "wiki/concept.md", "---\nid: concept\n---\n")
    _write_note(tmp_path, "patterns/pattern.md", "---\nid: pattern\n---\n")

    knowledge = build_graph_document(vault_root=tmp_path, view_name="knowledge")
    personal = build_graph_document(vault_root=tmp_path, view_name="personal-patterns")

    assert [node.id for node in knowledge.nodes] == ["concept"]
    assert [node.id for node in personal.nodes] == ["pattern"]


def test_graph_status_becomes_dirty_after_source_change(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write_note(vault, "wiki/concept.md", "---\nid: concept\n---\nInitial.\n")

    built = build_graph_view(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    assert built.status == "clean"
    assert (
        graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge").status
        == "clean"
    )

    (vault / "wiki" / "concept.md").write_text(
        "---\nid: concept\n---\nChanged.\n", encoding="utf-8"
    )

    assert (
        graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge").status
        == "dirty"
    )


def test_graph_output_is_deterministic_json(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write_note(vault, "wiki/a.md", "---\nid: a\n---\n")

    first_state = build_graph_view(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    assert first_state.active_generation is not None
    first = (
        runtime
        / "graphify"
        / "knowledge"
        / "generations"
        / first_state.active_generation
        / "graph.json"
    ).read_bytes()
    second_state = build_graph_view(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    assert second_state.active_generation == first_state.active_generation
    second = (
        runtime
        / "graphify"
        / "knowledge"
        / "generations"
        / second_state.active_generation
        / "graph.json"
    ).read_bytes()

    assert first == second
    assert json.loads(first)["view_name"] == "knowledge"


def test_invalid_view_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GraphError, match="view_name"):
        build_graph_document(vault_root=tmp_path, view_name="combined")


def test_duplicate_graph_node_ids_are_rejected(tmp_path: Path) -> None:
    _write_note(tmp_path, "wiki/one.md", "---\nid: shared-id\n---\nOne.\n")
    _write_note(tmp_path, "wiki/two.md", "---\nid: shared-id\n---\nTwo.\n")

    with pytest.raises(GraphError, match="duplicate graph node id"):
        build_graph_document(vault_root=tmp_path, view_name="knowledge")


def test_ambiguous_basename_wikilinks_are_not_resolved_arbitrarily(tmp_path: Path) -> None:
    _write_note(tmp_path, "wiki/one/topic.md", "---\nid: topic-one\n---\nOne.\n")
    _write_note(tmp_path, "study/two/topic.md", "---\nid: topic-two\n---\nTwo.\n")
    _write_note(
        tmp_path,
        "wiki/source.md",
        "---\nid: source\n---\nAmbiguous [[topic]], exact [[wiki/one/topic]].\n",
    )

    document = build_graph_document(vault_root=tmp_path, view_name="knowledge")

    assert [(edge.source, edge.target) for edge in document.edges] == [("source", "topic-one")]


@pytest.mark.parametrize(
    "state",
    [
        {"source_hash": 123, "node_count": 1, "edge_count": 0},
        {"source_hash": "not-a-hash", "node_count": 1, "edge_count": 0},
        {"source_hash": "0" * 64, "node_count": True, "edge_count": 0},
        {"source_hash": "0" * 64, "node_count": -1, "edge_count": 0},
        {"source_hash": "0" * 64, "node_count": 1, "edge_count": "0"},
    ],
)
def test_graph_status_rejects_corrupt_state_schema(
    tmp_path: Path,
    state: dict[str, object],
) -> None:
    runtime = tmp_path / ".lifeos"
    state_path = runtime / "graphify" / "knowledge" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = graph_view_status(
        vault_root=tmp_path,
        runtime_dir=runtime,
        view_name="knowledge",
    )

    assert result.status == "failed"
    assert result.source_hash is None
    assert result.node_count == 0
    assert result.edge_count == 0
