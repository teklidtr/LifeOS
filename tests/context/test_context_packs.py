from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.context import (
    ContextSearchError,
    build_context_pack,
    lexical_search,
    serialize_context_pack,
)


def _write_note(
    vault_root: Path,
    relative: str,
    *,
    title: str,
    description: str,
    body: str,
) -> None:
    path = vault_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"title: {title}\n"
        f"description: {description}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_lexical_search_is_weighted_and_deterministic(tmp_path: Path) -> None:
    _write_note(
        tmp_path,
        "wiki/energy.md",
        title="Energy regulation",
        description="How sleep supports energy.",
        body="Sleep and meal timing both affect perceived energy.",
    )
    _write_note(
        tmp_path,
        "journal/day.md",
        title="Daily note",
        description="A short log.",
        body="Energy was good after sleep.",
    )

    results = lexical_search(vault_root=tmp_path, query="sleep energy")

    assert [result.path for result in results] == ["wiki/energy.md", "journal/day.md"]
    assert results[0].score > results[1].score
    assert results[0].matched_terms == ("sleep", "energy")
    assert "Sleep" in results[0].excerpt


def test_search_excludes_runtime_and_hidden_directories(tmp_path: Path) -> None:
    _write_note(
        tmp_path,
        ".lifeos/private.md",
        title="Secret energy",
        description="Should be excluded.",
        body="energy",
    )
    _write_note(
        tmp_path,
        "wiki/public.md",
        title="Public energy",
        description="Included.",
        body="energy",
    )

    results = lexical_search(vault_root=tmp_path, query="energy")

    assert [result.path for result in results] == ["wiki/public.md"]


def test_context_pack_reports_instructions_gaps_and_limit(tmp_path: Path) -> None:
    _write_note(
        tmp_path,
        "wiki/one.md",
        title="Sleep",
        description="Sleep evidence.",
        body="Sleep supports recovery.",
    )
    _write_note(
        tmp_path,
        "wiki/two.md",
        title="Sleep timing",
        description="Timing evidence.",
        body="Sleep timing matters.",
    )
    instructions = tmp_path / "system" / "instructions.yml"
    instructions.parent.mkdir()
    instructions.write_text(
        "schema_version: 1\n"
        "instructions:\n"
        "  - id: prefer-direct-sources\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 100\n"
        "    text: Prefer direct sources\n",
        encoding="utf-8",
    )

    pack = build_context_pack(vault_root=tmp_path, question="sleep", limit=1)

    assert pack.sources[0].path == "wiki/one.md"
    assert "Results were limited to the top 1 sources." in pack.omissions
    assert "Only one matching source was found." in pack.evidence_gaps
    assert [item.id for item in pack.instructions] == ["prefer-direct-sources"]
    assert pack.instructions[0].authority == "system"
    assert pack.instructions[0].applicability == ("query:any", "scope:global")

    payload = json.loads(serialize_context_pack(pack))
    assert payload["question"] == "sleep"
    assert payload["sources"][0]["path"] == "wiki/one.md"


def test_context_pack_reports_no_evidence(tmp_path: Path) -> None:
    pack = build_context_pack(vault_root=tmp_path, question="nonexistent")

    assert pack.sources == ()
    assert pack.evidence_gaps == ("No matching canonical Markdown sources were found.",)
    assert "No system/instructions.yml file was present." in pack.omissions


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_empty_query(tmp_path: Path, query: str) -> None:
    with pytest.raises(ContextSearchError, match="non-empty"):
        lexical_search(vault_root=tmp_path, query=query)


def test_context_pack_does_not_claim_omissions_when_all_results_fit(tmp_path: Path) -> None:
    _write_note(
        tmp_path,
        "wiki/one.md",
        title="Sleep",
        description="Sleep evidence.",
        body="Sleep supports recovery.",
    )
    _write_note(
        tmp_path,
        "wiki/two.md",
        title="Sleep timing",
        description="Timing evidence.",
        body="Sleep timing matters.",
    )

    pack = build_context_pack(vault_root=tmp_path, question="sleep", limit=2)

    assert len(pack.sources) == 2
    assert "Results were limited to the top 2 sources." not in pack.omissions


def test_context_pack_focus_path_is_included_without_lexical_match(tmp_path: Path) -> None:
    _write_note(
        tmp_path,
        "study/driving-licence/intersections.md",
        title="Intersections",
        description="Priority rules.",
        body="Uncontrolled junction priority and emergency vehicles.",
    )
    _write_note(
        tmp_path,
        "goals/pass-driving-licence.md",
        title="Pass driving licence",
        description="Prepare for the Turkish driving licence exam.",
        body="Exam preparation goal.",
    )
    instructions = tmp_path / "system" / "instructions.yml"
    instructions.parent.mkdir(exist_ok=True)
    instructions.write_text(
        "schema_version: 1\n"
        "instructions:\n"
        "  - id: driving-exam\n"
        "    authority: system\n"
        "    scope: path\n"
        "    priority: 100\n"
        "    text: Prioritize exam-relevant distinctions.\n"
        "    paths: [study/driving-licence/**]\n",
        encoding="utf-8",
    )

    pack = build_context_pack(
        vault_root=tmp_path,
        question="What should I remember for the exam?",
        focus_paths=("study/driving-licence/intersections.md",),
    )

    assert pack.sources[0].path == "study/driving-licence/intersections.md"
    assert "goals/pass-driving-licence.md" in {item.path for item in pack.sources}
    assert [item.id for item in pack.instructions] == ["driving-exam"]
    assert pack.instructions[0].applicable_sources == (
        "study/driving-licence/intersections.md",
    )
