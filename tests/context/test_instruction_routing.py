from __future__ import annotations

import json
from pathlib import Path

from lifeos.context import build_context_pack, format_context_pack, serialize_context_pack


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _note(vault: Path, relative: str, *, title: str, body: str = "") -> None:
    _write(vault / relative, f"---\ntitle: {title}\n---\n{body}\n")


def _instructions(vault: Path, entries: str) -> None:
    _write(
        vault / "system/instructions.yml",
        "schema_version: 1\ninstructions:\n" + entries,
    )


def test_unlisted_instruction_source_is_ignored_and_diagnosed(tmp_path: Path) -> None:
    _note(tmp_path, "wiki/sleep.md", title="Sleep", body="Sleep evidence.")
    _instructions(
        tmp_path,
        "  - id: allowed\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 10\n"
        "    text: Allowed instruction.\n",
    )
    _write(
        tmp_path / "wiki/instructions.yml",
        "schema_version: 1\ninstructions:\n"
        "  - id: unauthorized\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 999\n"
        "    text: Do not include me.\n",
    )

    pack = build_context_pack(vault_root=tmp_path, question="sleep")

    assert [item.id for item in pack.instructions] == ["allowed"]
    diagnostic = next(item for item in pack.diagnostics if item.code == "instruction-source-not-allowed")
    assert diagnostic.source_path == "wiki/instructions.yml"


def test_malformed_typed_instruction_is_rejected_with_diagnostic(tmp_path: Path) -> None:
    _note(tmp_path, "wiki/sleep.md", title="Sleep")
    _instructions(
        tmp_path,
        "  - id: malformed\n"
        "    authority: imaginary\n"
        "    scope: global\n"
        "    priority: 1\n"
        "    text: Invalid.\n",
    )

    pack = build_context_pack(vault_root=tmp_path, question="sleep")

    assert pack.instructions == ()
    assert [item.code for item in pack.diagnostics] == ["instruction-entry-invalid"]
    assert "No validated instructions applied" in pack.omissions[0]


def test_instruction_scope_domain_path_and_note_applicability(tmp_path: Path) -> None:
    _note(tmp_path, "wiki/sleep/guide.md", title="Sleep guide", body="sleep")
    _note(tmp_path, "study/sleep.md", title="Unrelated study", body="other")
    _instructions(
        tmp_path,
        "  - id: global\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 50\n"
        "    text: Global.\n"
        "  - id: wiki-domain\n"
        "    authority: repository\n"
        "    scope: domain\n"
        "    priority: 40\n"
        "    text: Wiki domain.\n"
        "    domains: [wiki]\n"
        "  - id: study-domain\n"
        "    authority: repository\n"
        "    scope: domain\n"
        "    priority: 40\n"
        "    text: Study domain.\n"
        "    domains: [study]\n"
        "  - id: sleep-path\n"
        "    authority: scope\n"
        "    scope: path\n"
        "    priority: 30\n"
        "    text: Sleep path.\n"
        "    paths: [wiki/sleep/**]\n"
        "  - id: exact-note\n"
        "    authority: note-local\n"
        "    scope: note\n"
        "    priority: 20\n"
        "    text: Exact note.\n"
        "    paths: [wiki/sleep/guide.md]\n",
    )

    pack = build_context_pack(vault_root=tmp_path, question="sleep", limit=1)

    assert [item.id for item in pack.instructions] == [
        "global",
        "wiki-domain",
        "sleep-path",
        "exact-note",
    ]
    assert pack.instructions[1].applicable_sources == ("wiki/sleep/guide.md",)
    assert pack.instructions[2].applicability == ("path:wiki/sleep/**", "query:any")
    assert all(item.id != "study-domain" for item in pack.instructions)


def test_authority_classes_remain_distinguishable_and_stably_ordered(tmp_path: Path) -> None:
    _note(tmp_path, "wiki/sleep.md", title="Sleep")
    _instructions(
        tmp_path,
        "  - id: local\n"
        "    authority: note-local\n"
        "    scope: note\n"
        "    priority: 10\n"
        "    text: Local guidance.\n"
        "    paths: [wiki/sleep.md]\n"
        "  - id: system\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 10\n"
        "    text: System guidance.\n"
        "  - id: repository\n"
        "    authority: repository\n"
        "    scope: global\n"
        "    priority: 10\n"
        "    text: Repository guidance.\n",
    )

    pack = build_context_pack(vault_root=tmp_path, question="sleep")

    assert [(item.id, item.authority) for item in pack.instructions] == [
        ("system", "system"),
        ("repository", "repository"),
        ("local", "note-local"),
    ]


def test_query_term_applicability_is_exact_and_explained(tmp_path: Path) -> None:
    _note(tmp_path, "wiki/heart.md", title="Heart")
    _instructions(
        tmp_path,
        "  - id: art-only\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 1\n"
        "    text: Art guidance.\n"
        "    query_terms: [art]\n"
        "  - id: heart-only\n"
        "    authority: system\n"
        "    scope: global\n"
        "    priority: 1\n"
        "    text: Heart guidance.\n"
        "    query_terms: [heart]\n",
    )

    pack = build_context_pack(vault_root=tmp_path, question="heart")

    assert [item.id for item in pack.instructions] == ["heart-only"]
    assert pack.instructions[0].applicability == ("query-term:heart", "scope:global")


def test_context_pack_serialization_and_text_explain_inclusions(tmp_path: Path) -> None:
    _note(tmp_path, "wiki/sleep.md", title="Sleep", body="Sleep supports recovery.")
    _instructions(
        tmp_path,
        "  - id: evidence\n"
        "    authority: system\n"
        "    scope: domain\n"
        "    priority: 5\n"
        "    text: Prefer evidence.\n"
        "    domains: [wiki]\n"
        "    query_terms: [sleep]\n",
    )

    pack = build_context_pack(vault_root=tmp_path, question="sleep")
    payload = json.loads(serialize_context_pack(pack))
    rendered = format_context_pack(pack)

    assert payload["instructions"][0]["id"] == "evidence"
    assert payload["instructions"][0]["authority"] == "system"
    assert payload["instructions"][0]["applicable_sources"] == ["wiki/sleep.md"]
    assert payload["sources"][0]["score_evidence"]
    assert "applicability: domain:wiki, query-term:sleep" in rendered
    assert "score evidence: sleep:title" in rendered
