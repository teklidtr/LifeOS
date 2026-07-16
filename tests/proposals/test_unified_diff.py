import pytest
from lifeos.proposals.unified_diff import apply_diff, DiffError


def test_basic_apply():
    target = "line 1\nline 2\nline 3\n"
    patch = "@@ -1,3 +1,3 @@\n line 1\n-line 2\n+new line 2\n line 3\n"
    res = apply_diff(target, patch)
    assert res == "line 1\nnew line 2\nline 3\n"


def test_reject_headers():
    target = "line 1\n"
    patch = "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n line 1\n"
    with pytest.raises(DiffError, match="File headers"):
        apply_diff(target, patch)


def test_omitted_count_means_one():
    target = "line 1\n"
    patch = "@@ -1 +1 @@\n-line 1\n+new line\n"
    res = apply_diff(target, patch)
    assert res == "new line\n"


def test_zero_count_insertion():
    target = "line 1\n"
    patch = "@@ -1,0 +1 @@\n+new line\n"
    res = apply_diff(target, patch)
    assert res == "new line\nline 1\n"


def test_zero_count_deletion():
    target = "line 1\n"
    patch = "@@ -1 +1,0 @@\n-line 1\n"
    res = apply_diff(target, patch)
    assert res == ""


def test_strict_markers():
    target = "line 1\n"
    patch = "@@ -1 +1 @@\n*line 1\n"
    with pytest.raises(DiffError, match="Invalid hunk line marker"):
        apply_diff(target, patch)


def test_malformed_counts():
    target = "line 1\nline 2\n"
    # declared 1 removed, but actually removes 2
    patch = "@@ -1 +1 @@\n-line 1\n-line 2\n+new line\n"
    with pytest.raises(DiffError, match="declared old count"):
        apply_diff(target, patch)


def test_overlapping_hunks():
    target = "line 1\nline 2\n"
    patch = "@@ -1,2 +1,2 @@\n-line 1\n+new 1\n line 2\n@@ -2,1 +2,1 @@\n-line 2\n+new 2\n"
    with pytest.raises(DiffError, match="Hunks are overlapping"):
        apply_diff(target, patch)


def test_trailing_whitespace_significant():
    target = "line 1 \n"
    patch = "@@ -1 +1 @@\n-line 1\n+new line\n"
    with pytest.raises(DiffError, match="Context mismatch"):
        apply_diff(target, patch)


def test_crlf_target():
    target = "line 1\r\nline 2\r\n"
    patch = "@@ -1,2 +1,2 @@\n line 1\n-line 2\n+new line\n"
    res = apply_diff(target, patch)
    assert res == "line 1\r\nnew line\r\n"


def test_mixed_line_endings_rejected():
    target = "line 1\nline 2\r\n"
    patch = "@@ -1,2 +1,2 @@\n line 1\n line 2\n"
    with pytest.raises(DiffError, match="Mixed line endings"):
        apply_diff(target, patch)


def test_diff_text_uses_lf():
    target = "line 1\n"
    patch = "@@ -1 +1 @@\r\n-line 1\r\n+new line\r\n"
    with pytest.raises(DiffError, match="LF line endings"):
        apply_diff(target, patch)


def test_no_newline_at_eof():
    target = "line 1\nline 2"
    patch = "@@ -1,2 +1,2 @@\n line 1\n-line 2\n\\ No newline at end of file\n+new line 2\n\\ No newline at end of file\n"
    res = apply_diff(target, patch)
    assert res == "line 1\nnew line 2"

    patch_with_nl = "@@ -1,2 +1,2 @@\n line 1\n-line 2\n\\ No newline at end of file\n+new line 2\n"
    res2 = apply_diff(target, patch_with_nl)
    assert res2 == "line 1\nnew line 2\n"


def test_no_newline_at_eof_target_mismatch():
    target = "line 1\nline 2\n"
    patch = "@@ -1,2 +1,2 @@\n line 1\n-line 2\n\\ No newline at end of file\n+new line 2\n\\ No newline at end of file\n"
    with pytest.raises(DiffError, match="Marker says no final newline but target has one"):
        apply_diff(target, patch)


def test_strict_utf8():
    with pytest.raises(DiffError, match="Target text must be strict UTF-8"):
        apply_diff("line \udcff", "")


def test_out_of_bounds_hunk():
    target = "line 1\n"
    patch = "@@ -2 +2 @@\n-line 2\n+line 3\n"
    with pytest.raises(DiffError, match="Hunk extends beyond target file length"):
        apply_diff(target, patch)


def test_zero_count_insertion_can_append_at_end():
    target = "line 1\n"
    patch = "@@ -2,0 +2 @@\n+line 2\n"

    assert apply_diff(target, patch) == "line 1\nline 2\n"


def test_zero_count_insertion_rejects_out_of_bounds_position():
    target = "line 1\n"
    patch = "@@ -99,0 +99 @@\n+new line\n"

    with pytest.raises(DiffError, match="insertion point is beyond"):
        apply_diff(target, patch)
