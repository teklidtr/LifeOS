import os
from pathlib import Path

import pytest

from lifeos.scanner import ScannerError, scan_vault


def test_missing_vault_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ScannerError, match="Vault root does not exist"):
        scan_vault(missing)


def test_invalid_vault_root(tmp_path: Path) -> None:
    invalid = tmp_path / "file.txt"
    invalid.write_text("not a dir")
    with pytest.raises(ScannerError, match="Vault root is not a directory"):
        scan_vault(invalid)


def test_scan_discovers_supported_files(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("content")
    (tmp_path / "image.png").write_bytes(b"img")
    (tmp_path / "doc.pdf").write_bytes(b"pdf")

    # unsupported
    (tmp_path / "data.csv").write_text("1,2,3")

    results = scan_vault(tmp_path)

    paths = [r.path for r in results]
    assert paths == [
        Path("doc.pdf"),
        Path("image.png"),
        Path("note.md"),
    ]

    note = next(r for r in results if r.path == Path("note.md"))
    assert note.file_type == ".md"
    assert note.size_bytes == 7


def test_scan_ignores_directories(tmp_path: Path) -> None:
    lifeos = tmp_path / ".lifeos"
    lifeos.mkdir()
    (lifeos / "ignored.md").write_text("ignored")

    git = tmp_path / ".git"
    git.mkdir()
    (git / "ignored.md").write_text("ignored")

    results = scan_vault(tmp_path)
    assert len(results) == 0


def test_scan_ignores_workspace_files(tmp_path: Path) -> None:
    obsidian = tmp_path / ".obsidian"
    obsidian.mkdir()
    (obsidian / "workspace.json").write_text("{}")
    (obsidian / "workspace-mobile.json").write_text("{}")
    (obsidian / "valid.md").write_text("should be found")

    results = scan_vault(tmp_path)
    paths = [r.path for r in results]
    assert paths == [Path(".obsidian/valid.md")]


def test_scan_skips_symlinks(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "note.md").write_text("real")

    sym_dir = tmp_path / "sym"
    os.symlink(real_dir, sym_dir)

    sym_file = tmp_path / "sym.md"
    os.symlink(real_dir / "note.md", sym_file)

    results = scan_vault(tmp_path)
    paths = [r.path for r in results]
    # Should only find the real note.md
    assert paths == [Path("real/note.md")]


def test_deterministic_sorting(tmp_path: Path) -> None:
    # Create files in non-alphabetical order
    names = ["c.md", "a.md", "z.md", "b.md"]
    for name in names:
        (tmp_path / name).write_text("test")

    results = scan_vault(tmp_path)
    paths = [r.path.name for r in results]
    assert paths == ["a.md", "b.md", "c.md", "z.md"]


def test_repeated_scans(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("test")
    (tmp_path / "b.md").write_text("test")

    results1 = scan_vault(tmp_path)
    results2 = scan_vault(tmp_path)

    assert results1 == results2


def test_scan_nested_folders(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "deep"
    nested.mkdir(parents=True)
    (nested / "deep.md").write_text("deep")

    results = scan_vault(tmp_path)
    assert len(results) == 1
    assert results[0].path == Path("nested/deep/deep.md")


def test_symlink_loop_does_not_hang(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()

    # Create a loop: a/link_to_b -> b, b/link_to_a -> a
    os.symlink(dir_b, dir_a / "link_to_b")
    os.symlink(dir_a, dir_b / "link_to_a")

    # If the scanner follows symlinks, it will hang. We expect it to finish instantly.
    results = scan_vault(tmp_path)
    assert len(results) == 0


def test_external_symlinks_cannot_escape_vault(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    external_dir = tmp_path_factory.mktemp("external")
    (external_dir / "external.md").write_text("external")

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    os.symlink(external_dir, vault_dir / "external_link")

    results = scan_vault(vault_dir)
    assert len(results) == 0


def test_does_not_modify_files(tmp_path: Path) -> None:
    file_path = tmp_path / "test.md"
    file_path.write_text("test")
    mtime = file_path.stat().st_mtime

    scan_vault(tmp_path)

    assert file_path.stat().st_mtime == mtime
    assert file_path.read_text() == "test"
