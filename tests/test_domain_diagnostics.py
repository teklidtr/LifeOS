from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.cli import main
from lifeos.context import build_context_pack, format_context_pack
from lifeos.exports import ExportError, build_export, serialize_export_result
from lifeos.graph import build_graph_document
from lifeos.observation import ObservationError, load_observations
from lifeos.planning import PlanningError, load_plan_actions
from lifeos.study import StudyError, load_flashcards


def _invalid_yaml(vault: Path, relative: str) -> Path:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\ntitle: [broken\n---\nbody\n", encoding="utf-8")
    return path


def test_context_skips_malformed_source_and_reports_diagnostic(tmp_path: Path) -> None:
    _invalid_yaml(tmp_path, "wiki/bad.md")
    good = tmp_path / "wiki" / "good.md"
    good.write_text("---\ntitle: Energy\n---\nEnergy evidence.\n", encoding="utf-8")

    pack = build_context_pack(vault_root=tmp_path, question="energy")

    assert [item.path for item in pack.sources] == ["wiki/good.md"]
    assert [item.code for item in pack.diagnostics] == ["frontmatter-invalid-yaml"]
    assert pack.diagnostics[0].source_path == "wiki/bad.md"
    text = format_context_pack(pack)
    assert "wiki/bad.md" in text
    assert str(tmp_path) not in text


@pytest.mark.parametrize(
    ("relative", "loader", "error_type"),
    [
        ("flashcards/bad.md", load_flashcards, StudyError),
        ("plans/bad.md", load_plan_actions, PlanningError),
        ("journal/bad.md", load_observations, ObservationError),
    ],
)
def test_strict_domain_loaders_abort_on_parser_findings(
    tmp_path: Path,
    relative: str,
    loader: object,
    error_type: type[Exception],
) -> None:
    _invalid_yaml(tmp_path, relative)

    with pytest.raises(error_type) as exc_info:
        loader(tmp_path)  # type: ignore[operator]

    diagnostic = exc_info.value.diagnostic  # type: ignore[attr-defined]
    assert diagnostic.code == "frontmatter-invalid-yaml"
    assert diagnostic.source_path == relative
    assert str(tmp_path) not in str(exc_info.value)


def test_graph_omits_malformed_note_and_persists_diagnostic(tmp_path: Path) -> None:
    _invalid_yaml(tmp_path, "wiki/bad.md")
    (tmp_path / "wiki" / "good.md").write_text("---\nid: good\n---\n", encoding="utf-8")

    document = build_graph_document(vault_root=tmp_path, view_name="knowledge")

    assert [node.id for node in document.nodes] == ["good"]
    assert document.diagnostics[0].source_path == "wiki/bad.md"
    assert document.diagnostics[0].code == "frontmatter-invalid-yaml"


def test_public_export_fails_closed_on_malformed_privacy_metadata(tmp_path: Path) -> None:
    _invalid_yaml(tmp_path, "wiki/bad.md")

    with pytest.raises(ExportError) as exc_info:
        build_export(
            vault_root=tmp_path,
            runtime_dir=tmp_path / ".lifeos",
            kind="public-wiki",
        )

    assert exc_info.value.diagnostic is not None
    assert exc_info.value.diagnostic.code == "frontmatter-invalid-yaml"
    assert not (tmp_path / ".lifeos" / "exports" / "public-wiki").exists()


def test_non_public_export_skips_malformed_source_and_reports_omission(tmp_path: Path) -> None:
    _invalid_yaml(tmp_path, "study/bad.md")
    good = tmp_path / "study" / "good.md"
    good.write_text("Good.\n", encoding="utf-8")

    result = build_export(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        kind="study-bundle",
    )

    assert result.file_count == 1
    assert result.diagnostics[0].source_path == "study/bad.md"
    payload = json.loads(serialize_export_result(result))
    assert payload["diagnostics"][0]["code"] == "frontmatter-invalid-yaml"


def test_invalid_durable_metadata_type_is_not_silently_reinterpreted(tmp_path: Path) -> None:
    cards = tmp_path / "flashcards"
    cards.mkdir()
    (cards / "bad.md").write_text(
        "---\n"
        "type: [flashcard]\n"
        "id: card-1\n"
        "topic: Biology\n"
        "question: Q\n"
        "answer: A\n"
        "due: 2026-07-01\n"
        "---\n",
        encoding="utf-8",
    )

    with pytest.raises(StudyError) as exc_info:
        load_flashcards(tmp_path)

    assert exc_info.value.diagnostic is not None
    assert exc_info.value.diagnostic.code == "frontmatter-invalid-type"


def test_json_cli_error_exposes_stable_diagnostic_without_host_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _invalid_yaml(vault, "plans/bad.md")
    (tmp_path / "lifeos.yml").write_text(f"vault_root: {vault}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(
        [
            "plan",
            "today",
            "--energy",
            "medium",
            "--motivation",
            "medium",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["error"] == "domain-diagnostic"
    assert payload["diagnostic"]["code"] == "frontmatter-invalid-yaml"
    assert payload["diagnostic"]["source_path"] == "plans/bad.md"
    assert str(tmp_path) not in captured.out


def test_diagnostics_are_deduplicated_and_deterministically_ordered(tmp_path: Path) -> None:
    _invalid_yaml(tmp_path, "wiki/z.md")
    _invalid_yaml(tmp_path, "wiki/a.md")

    pack = build_context_pack(vault_root=tmp_path, question="anything")

    assert [item.source_path for item in pack.diagnostics] == ["wiki/a.md", "wiki/z.md"]
    assert len(pack.diagnostics) == len(set(pack.diagnostics))
