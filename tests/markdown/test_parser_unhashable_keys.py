from pathlib import Path

import pytest

from lifeos.markdown.parser import DurableFields, parse_markdown_note


@pytest.mark.parametrize(
    ("yaml_body", "expected_line"),
    [
        ("? [left, right]\n: value", 2),
        ("? {left: right}\n: value", 2),
        ("outer:\n  ? [left, right]\n  : value", 3),
        ("outer:\n  ? {left: right}\n  : value", 3),
    ],
    ids=["sequence-key", "mapping-key", "nested-sequence-key", "nested-mapping-key"],
)
def test_unhashable_frontmatter_keys_are_invalid_yaml_findings(
    tmp_path: Path,
    yaml_body: str,
    expected_line: int,
) -> None:
    path = tmp_path / "malformed.md"
    content = f"---\n{yaml_body}\n---\nHuman body"
    path.write_text(content, encoding="utf-8")

    result = parse_markdown_note(path)

    assert result.durable_fields == DurableFields()
    assert not result.frontmatter
    assert result.body == content
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.code == "frontmatter-invalid-yaml"
    assert finding.severity == "error"
    assert finding.line == expected_line
    assert "found unhashable key" in finding.message
