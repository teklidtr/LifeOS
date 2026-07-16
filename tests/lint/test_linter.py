import json
from pathlib import Path
from unittest.mock import patch

from lifeos.lint.linter import LintFinding, lint_vault
from lifeos.scanner import VaultFile


def test_no_findings_for_valid_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    # Valid note
    note = vault / "note.md"
    note.write_text(
        "---\nid: valid-id\nstatus: seed\nconfidence: medium\n---\nBody", encoding="utf-8"
    )

    files = [VaultFile(Path("note.md"), ".md", note.stat().st_size)]
    res = lint_vault(vault, files, None)

    assert not res.findings
    assert res.error_count == 0
    assert res.warning_count == 0
    assert res.suggestion_count == 0


def test_existing_parser_findings_surfaced(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note = vault / "note.md"
    note.write_text("---\nstatus: seed\n---", encoding="utf-8")

    files = [VaultFile(Path("note.md"), ".md", note.stat().st_size)]
    res = lint_vault(vault, files, None)

    # Should have a frontmatter-invalid-yaml finding because we used `---` at the end without closing properly maybe? Wait, no, `---` matches frontmatter start and end. If content is just `---\nstatus: seed\n---`, it is valid YAML. Let's make an explicitly invalid one:
    note.write_text("---\nbad_yaml: [\n---\n", encoding="utf-8")

    res = lint_vault(vault, files, None)
    assert any(f.code == "frontmatter-invalid-yaml" for f in res.findings)
    assert any(f.severity == "error" for f in res.findings)


def test_duplicate_stable_ids(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note1 = vault / "note1.md"
    note1.write_text("---\nid: dup\n---\n", encoding="utf-8")

    note2 = vault / "note2.md"
    note2.write_text("---\nid: dup\n---\n", encoding="utf-8")

    note3 = vault / "note3.md"
    note3.write_text("---\nid:  \n---\n", encoding="utf-8")  # Empty shouldn't trigger duplicate

    files = [
        VaultFile(Path("note1.md"), ".md", 0),
        VaultFile(Path("note2.md"), ".md", 0),
        VaultFile(Path("note3.md"), ".md", 0),
    ]

    res = lint_vault(vault, files, None)
    dup_findings = [f for f in res.findings if f.code == "durable-id-duplicate"]

    assert len(dup_findings) == 2
    paths = {str(f.path) for f in dup_findings}
    assert paths == {"note1.md", "note2.md"}

    assert "note2.md" in dup_findings[0].message
    assert "note1.md" in dup_findings[1].message


def test_same_id_in_same_file_not_duplicate(tmp_path: Path) -> None:
    # Our parser currently only returns one ID per file from frontmatter
    # So duplicate IDs within the same file is impossible with this parser,
    # but we can simulate passing the same VaultFile if we wanted, though
    # id_to_paths uses a set of paths, which protects against it.
    vault = tmp_path / "vault"
    vault.mkdir()

    note1 = vault / "note1.md"
    note1.write_text("---\nid: my-id\n---\n", encoding="utf-8")

    # Intentionally duplicate VaultFile to ensure set prevents duplicates
    files = [
        VaultFile(Path("note1.md"), ".md", 0),
        VaultFile(Path("note1.md"), ".md", 0),
    ]

    res = lint_vault(vault, files, None)
    assert not any(f.code == "durable-id-duplicate" for f in res.findings)


def test_invalid_status_and_confidence(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note1 = vault / "note1.md"
    note1.write_text("---\nstatus: stale\nconfidence: very-high\n---\n", encoding="utf-8")

    files = [VaultFile(Path("note1.md"), ".md", 0)]
    res = lint_vault(vault, files, None)

    assert any(f.code == "status-invalid" for f in res.findings)
    assert any(f.code == "confidence-invalid" for f in res.findings)

    # They should be errors
    status_finding = next(f for f in res.findings if f.code == "status-invalid")
    assert status_finding.severity == "error"


def test_deterministic_ordering(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note1 = vault / "z.md"
    note1.write_text("---\nbad: [\n---\n", encoding="utf-8")  # Will have YAML error

    note2 = vault / "a.md"
    note2.write_text("---\nbad: [\n---\n", encoding="utf-8")  # Will have YAML error

    files = [
        VaultFile(Path("z.md"), ".md", 0),
        VaultFile(Path("a.md"), ".md", 0),
    ]

    res = lint_vault(vault, files, None)

    paths = [str(f.path) for f in res.findings]
    assert paths == ["a.md", "z.md"]  # 'a' sorts before 'z'


def test_unreadable_file_does_not_crash(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note1 = vault / "note1.md"
    note1.write_text("Hello")

    note2 = vault / "note2.md"
    note2.write_text("Hello")

    files = [
        VaultFile(Path("note1.md"), ".md", 0),
        VaultFile(Path("note2.md"), ".md", 0),
    ]

    original_read = Path.read_text

    def failing_read(self, *args, **kwargs):
        if "note1.md" in str(self):
            raise OSError("Permission denied")
        return original_read(self, *args, **kwargs)

    with patch("pathlib.Path.read_text", new=failing_read):
        res = lint_vault(vault, files, None)

    assert any(f.code == "markdown-read-error" and str(f.path) == "note1.md" for f in res.findings)
    assert not any(str(f.path) == "note2.md" for f in res.findings)  # note2 had no errors


def test_ownership_hash_mismatch_and_missing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    target = vault / "gen.md"
    target.write_text("modified", encoding="utf-8")

    manifest_path = vault / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "owned_files": {
                    "gen.md": {
                        "generator_id": "gen1",
                        "generator_version": "1",
                        "content_hash": "a" * 64,
                        "created_at": "1",
                        "updated_at": "1",
                    },
                    "missing.md": {
                        "generator_id": "gen1",
                        "generator_version": "1",
                        "content_hash": "b" * 64,
                        "created_at": "1",
                        "updated_at": "1",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    res = lint_vault(vault, [], manifest_path)

    assert any(f.code == "ownership-hash-mismatch" for f in res.findings)
    assert any(f.code == "ownership-file-missing" for f in res.findings)


def test_ownership_manifest_malformed_no_crash(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    manifest_path = vault / "manifest.json"
    manifest_path.write_text("{bad json", encoding="utf-8")

    res = lint_vault(vault, [], manifest_path)

    assert any(f.code == "ownership-manifest-invalid" for f in res.findings)
    assert res.error_count == 1


def test_linting_is_read_only(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note = vault / "note.md"
    note.write_text("---\nstatus: seed\n---\n", encoding="utf-8")

    manifest_path = vault / "manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "owned_files": {}}), encoding="utf-8")

    files = [VaultFile(Path("note.md"), ".md", note.stat().st_size)]

    mtime_note = note.stat().st_mtime
    mtime_manifest = manifest_path.stat().st_mtime

    res1 = lint_vault(vault, files, manifest_path)
    res2 = lint_vault(vault, files, manifest_path)

    # Results are identical
    assert res1 == res2

    # Files are untouched
    assert note.stat().st_mtime == mtime_note
    assert manifest_path.stat().st_mtime == mtime_manifest


def test_summary_counts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note1 = vault / "note1.md"
    # Will trigger 2 warnings: invalid type for status and confidence
    note1.write_text("---\nstatus: []\nconfidence: {}\n---\n", encoding="utf-8")

    note2 = vault / "note2.md"
    # Will trigger 1 error: invalid status
    note2.write_text("---\nstatus: bad\n---\n", encoding="utf-8")

    files = [
        VaultFile(Path("note1.md"), ".md", 0),
        VaultFile(Path("note2.md"), ".md", 0),
    ]

    res = lint_vault(vault, files, None)

    assert res.error_count == 1
    assert res.warning_count == 2
    assert res.suggestion_count == 0
    assert len(res.findings) == 3


def test_parser_findings_retain_exact_properties(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note = vault / "note.md"
    note.write_text("---\nbad_yaml: [\n---\n", encoding="utf-8")

    files = [VaultFile(Path("note.md"), ".md", 0)]
    res = lint_vault(vault, files, None)

    f = next(x for x in res.findings if x.code == "frontmatter-invalid-yaml")
    assert f.severity == "error"
    assert f.line == 2  # According to parser
    assert f.path == Path("note.md")


def test_non_string_ids_do_not_participate(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note1 = vault / "n1.md"
    note1.write_text("---\nid: 123\n---\n", encoding="utf-8")  # int, invalid type
    note2 = vault / "n2.md"
    note2.write_text("---\nid: 123\n---\n", encoding="utf-8")

    files = [VaultFile(Path("n1.md"), ".md", 0), VaultFile(Path("n2.md"), ".md", 0)]
    res = lint_vault(vault, files, None)

    # Should only produce invalid type warnings, not durable-id-duplicate
    assert not any(f.code == "durable-id-duplicate" for f in res.findings)
    assert sum(1 for f in res.findings if f.code == "frontmatter-invalid-type") == 2


def test_invalid_types_do_not_duplicate_status_confidence(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note = vault / "n.md"
    note.write_text("---\nstatus: []\nconfidence: {}\n---\n", encoding="utf-8")

    files = [VaultFile(Path("n.md"), ".md", 0)]
    res = lint_vault(vault, files, None)

    assert not any(f.code == "status-invalid" for f in res.findings)
    assert not any(f.code == "confidence-invalid" for f in res.findings)

    type_findings = [f for f in res.findings if f.code == "frontmatter-invalid-type"]
    assert len(type_findings) == 2


def test_multiple_independent_findings(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    note = vault / "n.md"
    # Invalid type for id, invalid value for status
    note.write_text("---\nid: []\nstatus: bad\n---\n", encoding="utf-8")

    files = [VaultFile(Path("n.md"), ".md", 0)]
    res = lint_vault(vault, files, None)

    assert len(res.findings) == 2
    codes = {f.code for f in res.findings}
    assert codes == {"frontmatter-invalid-type", "status-invalid"}


def test_missing_manifest_is_valid_empty(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    manifest_path = vault / "missing.json"

    res = lint_vault(vault, [], manifest_path)
    assert not res.findings


def test_manifest_none_skips_lint(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    # This shouldn't do anything because files is empty, but manifest is None so it's a pass
    res = lint_vault(vault, [], None)
    assert not res.findings


def test_non_markdown_ignored(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    pdf = vault / "doc.pdf"
    pdf.write_text("fake pdf data")
    img = vault / "pic.png"
    img.write_text("fake png data")

    files = [
        VaultFile(Path("doc.pdf"), ".pdf", 0),
        VaultFile(Path("pic.png"), ".png", 0),
    ]

    # If parser is called, it would error on binary
    res = lint_vault(vault, files, None)
    assert not res.findings


def test_full_deterministic_sort(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    f1 = vault / "a.md"
    f2 = vault / "b.md"
    f1.write_text("", encoding="utf-8")
    f2.write_text("", encoding="utf-8")

    # To test sort order: path -> line (inf for None) -> severity -> code -> message
    findings_unordered = [
        LintFinding(Path("b.md"), "codeA", "error", "msg2", None),
        LintFinding(Path("a.md"), "codeB", "error", "msg1", 10),
        LintFinding(Path("a.md"), "codeC", "error", "msg3", 5),
        LintFinding(Path("a.md"), "codeB", "warning", "msg4", 10),
        LintFinding(Path("a.md"), "codeB", "error", "msg0", 10),
        LintFinding(Path("a.md"), "codeA", "error", "msg9", None),
    ]

    from lifeos.lint.linter import _sort_key

    sorted_findings = sorted(findings_unordered, key=_sort_key)

    expected = [
        # a.md line 5
        LintFinding(Path("a.md"), "codeC", "error", "msg3", 5),
        # a.md line 10
        LintFinding(Path("a.md"), "codeB", "error", "msg0", 10),
        LintFinding(Path("a.md"), "codeB", "error", "msg1", 10),
        LintFinding(Path("a.md"), "codeB", "warning", "msg4", 10),
        # a.md line None
        LintFinding(Path("a.md"), "codeA", "error", "msg9", None),
        # b.md line None
        LintFinding(Path("b.md"), "codeA", "error", "msg2", None),
    ]

    assert sorted_findings == expected
