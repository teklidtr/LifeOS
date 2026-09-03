import re
from dataclasses import dataclass
from typing import List, Tuple


class DiffError(Exception):
    """Raised when a unified diff fails to parse or apply cleanly."""

    pass


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[str]


def _parse_hunk_header(line: str) -> Tuple[int, int, int, int]:
    m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@$", line)
    if not m:
        raise DiffError(f"Malformed hunk header: {line}")

    old_start = int(m.group(1))
    old_count = int(m.group(2)) if m.group(2) is not None else 1
    new_start = int(m.group(3))
    new_count = int(m.group(4)) if m.group(4) is not None else 1

    return old_start, old_count, new_start, new_count


def _parse_diff(diff_text: str) -> List[Hunk]:
    if not diff_text:
        return []

    lines = diff_text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    hunks = []
    current_hunk = None

    for line in lines:
        if "\r" in line:
            allowed_data_cr = (
                current_hunk is not None
                and line.endswith("\r")
                and line.startswith((" ", "-", "+"))
                and "\r" not in line[:-1]
            )
            if not allowed_data_cr:
                raise DiffError("Diff text must use LF line endings")

        if line.startswith("@@"):
            if current_hunk:
                hunks.append(current_hunk)
            old_start, old_count, new_start, new_count = _parse_hunk_header(line)
            current_hunk = Hunk(old_start, old_count, new_start, new_count, [])
        elif current_hunk is not None:
            if line.startswith((" ", "-", "+", "\\ No newline at end of file")):
                current_hunk.lines.append(line)
            else:
                raise DiffError(f"Invalid hunk line marker: {line!r}")
        elif line.startswith("---") or line.startswith("+++"):
            raise DiffError("File headers --- and +++ are rejected")
        else:
            raise DiffError(f"Unexpected line outside hunk: {line!r}")

    if current_hunk:
        hunks.append(current_hunk)

    return hunks


def _detect_line_ending(text: str) -> str:
    has_crlf = "\r\n" in text
    stripped = text.replace("\r\n", "")
    has_lf_only = "\n" in stripped
    has_cr_only = "\r" in stripped

    if has_crlf and (has_lf_only or has_cr_only):
        raise DiffError("Mixed line endings in target text")
    if has_lf_only and has_cr_only:
        raise DiffError("Mixed line endings in target text")

    if has_crlf:
        return "\r\n"
    return "\n"


def _mixed_line_endings(text: str) -> tuple[bool, bool]:
    has_crlf = "\r\n" in text
    stripped = text.replace("\r\n", "")
    return "\r" in stripped, has_crlf and "\n" in stripped


def _split_lines_preserve_endings(text: str) -> Tuple[List[str], str]:
    if not text:
        return [], "\n"

    newline = _detect_line_ending(text)

    lines = text.split(newline)
    # the last element is empty if text ends with newline
    return lines, newline


def apply_diff(target_text: str, diff_text: str) -> str:
    try:
        target_text.encode("utf-8")
    except UnicodeEncodeError:
        raise DiffError("Target text must be strict UTF-8")

    hunks = _parse_diff(diff_text)
    if not hunks:
        return target_text

    has_bare_cr, has_mixed_lf_crlf = _mixed_line_endings(target_text)
    if has_bare_cr:
        raise DiffError("Mixed line endings in target text")
    diff_preserves_crlf = any(
        line.endswith("\r")
        for hunk in hunks
        for line in hunk.lines
        if line.startswith((" ", "-", "+"))
    )
    target_has_mixed_line_endings = has_mixed_lf_crlf
    if target_has_mixed_line_endings or diff_preserves_crlf:
        target_lines = target_text.split("\n")
        newline = "\n"
    else:
        target_lines, newline = _split_lines_preserve_endings(target_text)

    target_has_final_newline = target_text.endswith(newline) if target_text else False
    if target_lines and target_lines[-1] == "":
        target_lines.pop()
        target_has_final_newline = True

    result_lines = list(target_lines)
    result_has_final_newline = target_has_final_newline

    offset = 0
    last_old_end = 0

    for hunk in hunks:
        if hunk.old_start < last_old_end:
            raise DiffError("Hunks are overlapping or out of order")

        old_idx = hunk.old_start - 1 if hunk.old_start > 0 else 0
        if hunk.old_count == 0:
            if old_idx > len(target_lines) or (
                old_idx == len(target_lines) and hunk.old_start != len(target_lines) + 1
            ):
                raise DiffError("Hunk insertion point is beyond target file length")

        parsed_old_count = 0
        parsed_new_count = 0

        for i, line in enumerate(hunk.lines):
            if line == "\\ No newline at end of file":
                continue

            prefix = line[0]
            content = line[1:]

            if prefix in (" ", "-"):
                parsed_old_count += 1
                if old_idx >= len(target_lines):
                    raise DiffError("Hunk extends beyond target file length")
                if target_lines[old_idx] != content:
                    if target_has_mixed_line_endings:
                        raise DiffError("Mixed line endings in target text")
                    raise DiffError(f"Context mismatch at target line {old_idx + 1}")
                old_idx += 1

            if prefix in (" ", "+"):
                parsed_new_count += 1

        if parsed_old_count != hunk.old_count:
            raise DiffError(
                f"Hunk declared old count {hunk.old_count} but parsed {parsed_old_count}"
            )
        if parsed_new_count != hunk.new_count:
            raise DiffError(
                f"Hunk declared new count {hunk.new_count} but parsed {parsed_new_count}"
            )

        last_old_end = hunk.old_start + hunk.old_count

        # Apply hunk
        apply_idx = hunk.old_start - 1 + offset if hunk.old_start > 0 else offset
        del result_lines[apply_idx : apply_idx + hunk.old_count]

        insert_idx = apply_idx
        for line in hunk.lines:
            if line == "\\ No newline at end of file":
                continue
            prefix = line[0]
            content = line[1:]
            if prefix in (" ", "+"):
                result_lines.insert(insert_idx, content)
                insert_idx += 1

        # Adjust offset
        offset += hunk.new_count - hunk.old_count

        # Check no newline markers
        idx = 0
        while idx < len(hunk.lines):
            line = hunk.lines[idx]
            if line.startswith("-"):
                if (
                    idx + 1 < len(hunk.lines)
                    and hunk.lines[idx + 1] == "\\ No newline at end of file"
                ):
                    if target_has_final_newline and (
                        hunk.old_start + hunk.old_count - 1 == len(target_lines)
                    ):
                        raise DiffError("Marker says no final newline but target has one")
            elif line.startswith("+"):
                if (
                    idx + 1 < len(hunk.lines)
                    and hunk.lines[idx + 1] == "\\ No newline at end of file"
                ):
                    if hunk.old_start + hunk.old_count - 1 >= len(target_lines):
                        result_has_final_newline = False
            idx += 1

    if hunks:
        last_hunk = hunks[-1]
        touches_end = last_hunk.old_start + last_hunk.old_count - 1 >= len(target_lines)
        if touches_end:
            has_no_newline_marker = False
            for line in reversed(last_hunk.lines):
                if line == "\\ No newline at end of file":
                    has_no_newline_marker = True
                    break
                if line.startswith("+") or line.startswith(" "):
                    break

            if has_no_newline_marker or not diff_text.endswith("\n"):
                result_has_final_newline = False
            else:
                result_has_final_newline = True

    if not result_lines:
        return ""

    res = newline.join(result_lines)
    if result_has_final_newline:
        res += newline

    return res
