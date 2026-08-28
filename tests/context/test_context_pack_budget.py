from __future__ import annotations

from pathlib import Path

from lifeos.context import build_context_pack
from lifeos.retrieval import RetrievalIndexService


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_context_pack_reports_real_unique_source_budget_truncation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(vault, "wiki/alpha.md", "---\ntitle: Alpha\n---\nATP evidence alpha.")
    _write(vault, "wiki/beta.md", "---\ntitle: Beta\n---\nATP evidence beta distinct.")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP evidence",
        limit=1,
    )

    assert len(pack.sources) == 1
    assert "Results were limited to the top 1 sources." in pack.omissions
