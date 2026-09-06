from __future__ import annotations

import json
from pathlib import Path

from lifeos.graph import build_graph_view, graph_view_status
from lifeos.publication import active_generation_path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_graph_status_rejects_cross_view_state(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = tmp_path / "runtime"
    _write(vault_root / "wiki" / "note.md", "---\nid: note\ntitle: Note\n---\nbody\n")
    build_graph_view(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        view_name="knowledge",
    )
    active = active_generation_path(runtime_dir / "graphify" / "knowledge")
    assert active is not None
    state_path = active / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["view_name"] = "system"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert (
        graph_view_status(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            view_name="knowledge",
        ).status
        == "failed"
    )
