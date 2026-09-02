from pathlib import Path

import pytest

from lifeos.markdown.parser import parse_markdown_note, replace_managed_block, splice_managed_block


def test_valid_frontmatter(tmp_path: Path) -> None:
    file = tmp_path / "valid.md"
    file.write_text("---\ntitle: Hello\n---\nBody text")

    result = parse_markdown_note(file)
    assert not result.findings
    assert result.frontmatter["title"] == "Hello"
    assert result.durable_fields.title == "Hello"


def test_no_frontmatter(tmp_path: Path) -> None:
    file = tmp_path / "no_fm.md"
    file.write_text("Just body")

    result = parse_markdown_note(file)
    assert not result.findings
    assert not result.frontmatter
    assert result.body == "Just body"


def test_unknown_fields_preserved(tmp_path: Path) -> None:
    file = tmp_path / "unknown.md"
    file.write_text("---\nunknown_field: 42\ntitle: test\n---\nbody")

    result = parse_markdown_note(file)
    assert result.frontmatter["unknown_field"] == 42
    assert result.durable_fields.title == "test"


def test_empty_frontmatter(tmp_path: Path) -> None:
    file = tmp_path / "empty.md"
    file.write_text("---\n---\nbody")

    result = parse_markdown_note(file)
    assert not result.findings
    assert not result.frontmatter
    assert result.body == "body"


def test_malformed_yaml(tmp_path: Path) -> None:
    file = tmp_path / "malformed.md"
    file.write_text("---\nbad yaml: [unclosed\n---\nbody")

    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "frontmatter-invalid-yaml"
    assert result.findings[0].severity == "error"
    assert result.body == "---\nbad yaml: [unclosed\n---\nbody"


def test_known_fields_extracted(tmp_path: Path) -> None:
    file = tmp_path / "known.md"
    file.write_text(
        "---\n"
        "id: '123'\n"
        "type: doc\n"
        "title: t\n"
        "description: d\n"
        "status: active\n"
        "confidence: high\n"
        "review_reasons: [a, b]\n"
        "---\n"
    )
    result = parse_markdown_note(file)
    d = result.durable_fields
    assert d.id == "123"
    assert d.type == "doc"
    assert d.title == "t"
    assert d.description == "d"
    assert d.status == "active"
    assert d.confidence == "high"
    assert d.review_reasons == ("a", "b")


def test_frontmatter_body_separation(tmp_path: Path) -> None:
    file = tmp_path / "sep.md"
    file.write_text("---\na: 1\n---\nline1\nline2")

    result = parse_markdown_note(file)
    assert result.body == "line1\nline2"


def test_valid_managed_block(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    original = "a\n<!-- lifeos:managed:start m1 -->\nb\n<!-- lifeos:managed:end m1 -->\nc"
    file.write_text(original)

    result = parse_markdown_note(file)
    assert len(result.managed_blocks) == 1
    block = result.managed_blocks[0]
    assert block.name == "m1"
    assert block.content == "b"
    assert result.body[block.start_offset : block.end_offset] == (
        "<!-- lifeos:managed:start m1 -->\nb\n<!-- lifeos:managed:end m1 -->"
    )
    assert splice_managed_block(result.body, block, "replacement") == "a\nreplacement\nc"
    assert replace_managed_block(result.body, block, "new\n", content_only=True) == (
        "a\n<!-- lifeos:managed:start m1 -->\nnew\n<!-- lifeos:managed:end m1 -->\nc"
    )


@pytest.mark.parametrize("content_only", [False, True])
@pytest.mark.parametrize(
    "replacement",
    [
        "<!--lifeos:managed:end m1 -->\n~~~markdown\n",
        "~~~markdown\nUnclosed example\n",
        "<!-- lifeos:managed:start nested -->\nnested\n<!-- lifeos:managed:end nested -->\n",
    ],
    ids=["early-end-hides-real-end", "unclosed-fence", "nested-marker"],
)
def test_managed_replacement_keeps_the_complete_structural_boundary(
    tmp_path: Path, replacement: str, content_only: bool
) -> None:
    start = "<!-- lifeos:managed:start m1 -->\n"
    end = "<!-- lifeos:managed:end m1 -->"
    body = "Human prefix\n" + start + "old\n" + end + "\nHuman suffix\n"
    parsed = parse_markdown_note(tmp_path / "block.md", content=body)
    if not content_only:
        replacement = start + replacement + end

    with pytest.raises(ValueError, match="complete managed block"):
        replace_managed_block(
            parsed.body, parsed.managed_blocks[0], replacement, content_only=content_only
        )


def test_unmatched_start_marker(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    file.write_text("<!-- lifeos:managed:start m1 -->\nb")

    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "managed-block-unmatched-start"
    assert result.findings[0].line == 1


def test_unmatched_end_marker(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    file.write_text("<!-- lifeos:managed:end m1 -->")

    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "managed-block-unmatched-end"
    assert result.findings[0].line == 1


def test_nested_managed_blocks(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    file.write_text(
        "<!-- lifeos:managed:start m1 -->\n"
        "<!-- lifeos:managed:start m2 -->\n"
        "<!-- lifeos:managed:end m1 -->"
    )
    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "managed-block-nested"
    assert result.findings[0].line == 2


def test_duplicate_block_names(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    file.write_text(
        "<!-- lifeos:managed:start m1 -->\n"
        "<!-- lifeos:managed:end m1 -->\n"
        "<!-- lifeos:managed:start m1 -->\n"
        "<!-- lifeos:managed:end m1 -->"
    )
    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "managed-block-duplicate-name"
    assert result.findings[0].line == 3


def test_mismatched_block_names(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    file.write_text("<!-- lifeos:managed:start m1 -->\n<!-- lifeos:managed:end m2 -->")
    result = parse_markdown_note(file)
    assert len(result.findings) == 2
    codes = {f.code for f in result.findings}
    assert "managed-block-name-mismatch" in codes
    assert "managed-block-unmatched-start" in codes


def test_findings_line_numbers(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    file.write_text(
        "---\na: 1\n---\n\n<!-- lifeos:managed:start m1 -->\n<!-- lifeos:managed:end m2 -->"
    )
    result = parse_markdown_note(file)
    # The end marker is at line 6
    mismatch = [f for f in result.findings if f.code == "managed-block-name-mismatch"][0]
    assert mismatch.line == 6


def test_parsing_does_not_modify_file(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    content = "---\na: 1\n---\nbody"
    file.write_text(content)
    mtime = file.stat().st_mtime_ns

    parse_markdown_note(file)

    assert file.read_text() == content
    assert file.stat().st_mtime_ns == mtime


def test_unreadable_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = tmp_path / "block.md"
    file.write_text("test")
    original_read_text = Path.read_text

    def deny_target(path: Path, *args, **kwargs) -> str:
        if path == file:
            raise PermissionError("denied by test")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_target)

    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "file-read-error"
    assert "denied by test" in result.findings[0].message


def test_deterministic_parsing(tmp_path: Path) -> None:
    file = tmp_path / "block.md"
    file.write_text(
        "---\na: 1\n---\n<!-- lifeos:managed:start m1 -->\n<!-- lifeos:managed:end m1 -->"
    )

    r1 = parse_markdown_note(file)
    r2 = parse_markdown_note(file)

    assert r1 == r2


def test_unclosed_frontmatter(tmp_path: Path) -> None:
    file = tmp_path / "unclosed.md"
    file.write_text("---\na: 1\nbody")
    result = parse_markdown_note(file)

    assert len(result.findings) == 1
    assert result.findings[0].code == "frontmatter-unclosed"
    assert result.findings[0].severity == "error"
    assert result.body == "---\na: 1\nbody"


def test_frontmatter_not_mapping(tmp_path: Path) -> None:
    file = tmp_path / "not_mapping.md"
    file.write_text("---\n- item1\n- item2\n---\nbody")
    result = parse_markdown_note(file)

    assert len(result.findings) == 1
    assert result.findings[0].code == "frontmatter-not-mapping"
    assert result.findings[0].severity == "error"
    assert result.body == "---\n- item1\n- item2\n---\nbody"


def test_invalid_type_known_field(tmp_path: Path) -> None:
    file = tmp_path / "invalid_type.md"
    file.write_text("---\nid: 123\nreview_reasons: string-not-list\n---\nbody")
    result = parse_markdown_note(file)

    assert len(result.findings) == 2
    assert result.findings[0].code == "frontmatter-invalid-type"
    assert result.durable_fields.review_reasons == ()
    assert result.durable_fields.id is None


def test_fenced_code_blocks(tmp_path: Path) -> None:
    file = tmp_path / "fenced.md"
    file.write_text("```md\n<!-- lifeos:managed:start m1 -->\n```")
    result = parse_markdown_note(file)
    assert not result.findings
    assert not result.managed_blocks


@pytest.mark.parametrize(
    "example",
    [
        (
            "```md\n"
            "```not-a-closing-fence\n"
            "<!-- lifeos:managed:start m1 -->\n"
            "example\n"
            "<!-- lifeos:managed:end m1 -->\n"
            "```\n"
        ),
        (
            "~~~md\n"
            "~~~not-a-closing-fence\n"
            "<!-- lifeos:managed:start m1 -->\n"
            "example\n"
            "<!-- lifeos:managed:end m1 -->\n"
            "~~~\n"
        ),
        (
            "````md\n"
            "```\n"
            "<!-- lifeos:managed:start m1 -->\n"
            "example\n"
            "<!-- lifeos:managed:end m1 -->\n"
            "````\n"
        ),
        (
            "```md\n"
            "    ```\n"
            "<!-- lifeos:managed:start m1 -->\n"
            "example\n"
            "<!-- lifeos:managed:end m1 -->\n"
            "```\n"
        ),
        (
            "```md\n"
            "\t```\n"
            "<!-- lifeos:managed:start m1 -->\n"
            "example\n"
            "<!-- lifeos:managed:end m1 -->\n"
            "```\n"
        ),
        (
            "    <!-- lifeos:managed:start m1 -->\n"
            "    example\n"
            "    <!-- lifeos:managed:end m1 -->\n"
        ),
        (
            "\t<!-- lifeos:managed:start m1 -->\n"
            "\texample\n"
            "\t<!-- lifeos:managed:end m1 -->\n"
        ),
        (
            "- example\n"
            "  <!-- lifeos:managed:start m1 -->\n"
            "  nested text\n"
            "  <!-- lifeos:managed:end m1 -->\n"
        ),
        (
            "> <!-- lifeos:managed:start m1 -->\n"
            "> quoted text\n"
            "> <!-- lifeos:managed:end m1 -->\n"
        ),
    ],
    ids=[
        "backtick-false-closer",
        "tilde-false-closer",
        "shorter-backtick-run",
        "four-space-indented-closer",
        "tab-indented-closer",
        "indented-code",
        "tab-indented-code",
        "list-nested",
        "block-quoted",
    ],
)
def test_managed_marker_examples_in_non_structural_markdown_are_ignored(
    tmp_path: Path,
    example: str,
) -> None:
    file = tmp_path / "marker-example.md"
    file.write_text(example, encoding="utf-8")

    result = parse_markdown_note(file)

    assert not result.findings
    assert not result.managed_blocks


def test_fence_open_and_close_grammar_controls_marker_visibility(tmp_path: Path) -> None:
    file = tmp_path / "fence-grammar.md"
    file.write_text(
        "```language`invalid-opener\n"
        "<!-- lifeos:managed:start visible-before -->\n"
        "value\n"
        "<!-- lifeos:managed:end visible-before -->\n"
        "```md\n"
        "<!-- lifeos:managed:start hidden -->\n"
        "example\n"
        "<!-- lifeos:managed:end hidden -->\n"
        "``` \t\n"
        "<!-- lifeos:managed:start visible-after -->\n"
        "value\n"
        "<!-- lifeos:managed:end visible-after -->\n",
        encoding="utf-8",
    )

    result = parse_markdown_note(file)

    assert not result.findings
    assert [block.name for block in result.managed_blocks] == [
        "visible-before",
        "visible-after",
    ]


def test_malformed_markers(tmp_path: Path) -> None:
    file = tmp_path / "malformed.md"
    file.write_text(
        "<!-- lifeos:managed:start -->\n"
        "<!-- lifeos:managed:start m1 m2 -->\n"
        "<!-- lifeos:managed:start m1\n"
        "-->\n"
    )
    result = parse_markdown_note(file)
    assert not result.managed_blocks
    assert not result.findings


def test_duplicate_top_level_yaml_keys(tmp_path: Path) -> None:
    file = tmp_path / "dup.md"
    file.write_text("---\nstatus: pending\nstatus: approved\n---\nbody")
    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "frontmatter-invalid-yaml"
    assert result.findings[0].severity == "error"
    assert "found duplicate key 'status'" in result.findings[0].message


def test_duplicate_nested_yaml_keys(tmp_path: Path) -> None:
    file = tmp_path / "dup_nested.md"
    file.write_text("---\nextensions:\n  score: 1\n  score: 2\n---\nbody")
    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "frontmatter-invalid-yaml"
    assert result.findings[0].severity == "error"
    assert "found duplicate key 'score'" in result.findings[0].message


def test_yaml_merge_keys_rejected(tmp_path: Path) -> None:
    file = tmp_path / "merge.md"
    file.write_text("---\ndefaults: &defaults\n  status: pending\n<<: *defaults\n---\nbody")
    result = parse_markdown_note(file)
    assert len(result.findings) == 1
    assert result.findings[0].code == "frontmatter-invalid-yaml"
    assert result.findings[0].severity == "error"
    assert "merge keys are not supported" in result.findings[0].message


def test_strict_loader_does_not_alter_global_safeloader() -> None:
    import yaml

    # The standard PyYAML safe_load parses duplicates by overwriting them
    res = yaml.safe_load("a: 1\na: 2\n")
    assert res == {"a": 2}
