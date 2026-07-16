import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml


@dataclass(frozen=True, slots=True)
class ParseFinding:
    code: str
    severity: Literal["error", "warning"]
    path: Path
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class DurableFields:
    id: str | None = None
    type: str | None = None
    title: str | None = None
    description: str | None = None
    status: str | None = None
    confidence: str | None = None
    review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ManagedBlock:
    name: str
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True, slots=True)
class ParsedNote:
    path: Path
    durable_fields: DurableFields
    frontmatter: MappingProxyType[str, Any]
    body: str
    managed_blocks: tuple[ManagedBlock, ...]
    findings: tuple[ParseFinding, ...]


START_MARKER_RE = re.compile(r"^\s*<!--\s*lifeos:managed:start\s+([^\s>]+)\s*-->\s*$")
END_MARKER_RE = re.compile(r"^\s*<!--\s*lifeos:managed:end\s+([^\s>]+)\s*-->\s*$")
FENCED_CODE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})")


def parse_markdown_note(path: Path, *, content: str | None = None) -> ParsedNote:
    if content is None:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return ParsedNote(
            path=path,
            durable_fields=DurableFields(),
            frontmatter=MappingProxyType({}),
            body="",
            managed_blocks=(),
                findings=(ParseFinding("file-read-error", "error", path, 1, str(e)),),
            )

    lines = content.split("\n")
    if not lines:
        return ParsedNote(path, DurableFields(), MappingProxyType({}), "", (), ())

    first_line = lines[0]
    has_bom = first_line.startswith("\ufeff")
    start_str = first_line[1:] if has_bom else first_line

    yaml_lines = []
    yaml_end_idx = -1
    has_frontmatter_start = start_str == "---" or start_str == "---\r"

    findings: list[ParseFinding] = []

    if has_frontmatter_start:
        for i in range(1, len(lines)):
            if lines[i] == "---" or lines[i] == "---\r":
                yaml_end_idx = i
                break
            yaml_lines.append(lines[i])

        if yaml_end_idx == -1:
            findings.append(
                ParseFinding("frontmatter-unclosed", "error", path, 1, "Unclosed frontmatter")
            )
            body_start_idx = 0
            yaml_str = None
        else:
            yaml_str = "\n".join(yaml_lines)
            body_start_idx = yaml_end_idx + 1
    else:
        body_start_idx = 0
        yaml_str = None

    frontmatter_dict: dict[str, Any] = {}
    if yaml_str is not None:
        class StrictSafeLoader(yaml.SafeLoader):
            def construct_yaml_map(self, node: yaml.Node) -> Any:
                if not isinstance(node, yaml.MappingNode):
                    raise yaml.constructor.ConstructorError(
                        None, None, f"expected a mapping node, but found {type(node).__name__}", node.start_mark
                    )
                mapping = {}
                for key_node, value_node in node.value:
                    if getattr(key_node, "tag", None) == "tag:yaml.org,2002:merge":
                        raise yaml.constructor.ConstructorError(
                            "while constructing a mapping",
                            node.start_mark,
                            "merge keys are not supported",
                            key_node.start_mark,
                        )
                    key = self.construct_object(key_node, deep=False)
                    if key in mapping:
                        raise yaml.constructor.ConstructorError(
                            "while constructing a mapping",
                            node.start_mark,
                            f"found duplicate key '{key}'",
                            key_node.start_mark,
                        )
                    mapping[key] = self.construct_object(value_node, deep=False)
                return mapping

        StrictSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, StrictSafeLoader.construct_yaml_map
        )

        try:
            parsed_yaml = yaml.load(yaml_str, Loader=StrictSafeLoader)
            if parsed_yaml is None:
                parsed_yaml = {}
            if not isinstance(parsed_yaml, dict):
                findings.append(
                    ParseFinding(
                        "frontmatter-not-mapping", "error", path, 1, "Frontmatter is not a mapping"
                    )
                )
                body_start_idx = 0
            else:
                frontmatter_dict = parsed_yaml
        except yaml.YAMLError as e:
            err_line = (
                e.problem_mark.line + 2 if hasattr(e, "problem_mark") and e.problem_mark else 1
            )
            findings.append(
                ParseFinding("frontmatter-invalid-yaml", "error", path, err_line, str(e))
            )
            body_start_idx = 0
            frontmatter_dict = {}

    def get_str(key: str) -> str | None:
        val = frontmatter_dict.get(key)
        if val is None:
            return None
        if isinstance(val, str):
            return val
        findings.append(
            ParseFinding(
                "frontmatter-invalid-type", "warning", path, 1, f"Expected string for {key}"
            )
        )
        return None

    def get_str_list(key: str) -> tuple[str, ...]:
        val = frontmatter_dict.get(key)
        if val is None:
            return ()
        if isinstance(val, list) and all(isinstance(x, str) for x in val):
            return tuple(val)
        findings.append(
            ParseFinding(
                "frontmatter-invalid-type",
                "warning",
                path,
                1,
                f"Expected list of strings for {key}",
            )
        )
        return ()

    durable = DurableFields(
        id=get_str("id"),
        type=get_str("type"),
        title=get_str("title"),
        description=get_str("description"),
        status=get_str("status"),
        confidence=get_str("confidence"),
        review_reasons=get_str_list("review_reasons"),
    )

    body = "\n".join(lines[body_start_idx:])

    in_fenced_code = False
    fenced_char = None
    fenced_len = 0

    open_block_name = None
    open_block_start_line = -1
    open_block_content_lines: list[str] = []

    managed_blocks: list[ManagedBlock] = []
    seen_block_names: set[str] = set()

    for i in range(body_start_idx, len(lines)):
        line = lines[i]
        line_num = i + 1

        # Fenced code and markers must be checked against line without \r
        clean_line = line.rstrip('\r')

        m_fence = FENCED_CODE_RE.match(clean_line)
        if m_fence:
            marker = m_fence.group(2)
            if not in_fenced_code:
                in_fenced_code = True
                fenced_char = marker[0]
                fenced_len = len(marker)
            else:
                if marker[0] == fenced_char and len(marker) >= fenced_len:
                    in_fenced_code = False

        if in_fenced_code:
            if open_block_name:
                open_block_content_lines.append(line)
            continue

        m_start = START_MARKER_RE.match(clean_line)
        m_end = END_MARKER_RE.match(clean_line)

        if m_start:
            name = m_start.group(1)
            if open_block_name:
                findings.append(
                    ParseFinding(
                        "managed-block-nested",
                        "error",
                        path,
                        line_num,
                        f"Nested block '{name}' inside '{open_block_name}'",
                    )
                )
                open_block_content_lines.append(line)
            else:
                if name in seen_block_names:
                    findings.append(
                        ParseFinding(
                            "managed-block-duplicate-name",
                            "error",
                            path,
                            line_num,
                            f"Duplicate block name '{name}'",
                        )
                    )
                open_block_name = name
                open_block_start_line = line_num
                open_block_content_lines = []
                seen_block_names.add(name)
        elif m_end:
            name = m_end.group(1)
            if not open_block_name:
                findings.append(
                    ParseFinding(
                        "managed-block-unmatched-end",
                        "error",
                        path,
                        line_num,
                        f"Unmatched end marker for '{name}'",
                    )
                )
            elif name != open_block_name:
                findings.append(
                    ParseFinding(
                        "managed-block-name-mismatch",
                        "error",
                        path,
                        line_num,
                        f"Mismatched end marker: expected '{open_block_name}', got '{name}'",
                    )
                )
            else:
                managed_blocks.append(
                    ManagedBlock(
                        name=open_block_name,
                        start_line=open_block_start_line,
                        end_line=line_num,
                        content="\n".join(open_block_content_lines),
                    )
                )
                open_block_name = None
        else:
            if open_block_name:
                open_block_content_lines.append(line)

    if open_block_name:
        findings.append(
            ParseFinding(
                "managed-block-unmatched-start",
                "error",
                path,
                open_block_start_line,
                f"Unmatched start marker for '{open_block_name}'",
            )
        )

    return ParsedNote(
        path=path,
        durable_fields=durable,
        frontmatter=MappingProxyType(frontmatter_dict),
        body=body,
        managed_blocks=tuple(managed_blocks),
        findings=tuple(findings),
    )
