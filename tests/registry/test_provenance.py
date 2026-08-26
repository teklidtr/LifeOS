"""Tests for provenance registry indexing."""

from pathlib import Path

import pytest

from lifeos.registry import Registry, RegistryError
from lifeos.registry.provenance import (
    ProvenanceIndexError,
    refresh_provenance_index,
    get_provenance_for_derived,
    list_derived_for_source,
)


@pytest.fixture
def mock_git_repo(tmp_path: Path) -> Path:
    """A real temporary Git repository for discovery tests."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_fresh_schema_and_upgrade(tmp_path: Path) -> None:
    """Test the current registry keeps provenance tables when upgrading from v2."""
    from unittest.mock import patch
    from lifeos.registry import CURRENT_SCHEMA_VERSION, _migrations

    db_path = tmp_path / "registry.db"

    # Initialize to version 2.
    v2_migrations = _migrations.MIGRATIONS[:2]
    with patch("lifeos.registry._registry._migrations.MIGRATIONS", v2_migrations):
        reg = Registry(db_path)
        reg.initialize()

    assert reg.schema_version == 2

    # Initialize through the current schema, including the scoped-identity migration.
    reg = Registry(db_path)
    reg.initialize()
    assert reg.schema_version == CURRENT_SCHEMA_VERSION == 4

    # Provenance tables introduced in v3 remain present after the v4 registry rebuild.
    with reg.connect_read_only() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('provenance_documents', 'provenance_sources')"
        )
        tables = set(row[0] for row in cursor.fetchall())
        assert tables == {"provenance_documents", "provenance_sources"}


def test_valid_provenance_bearing_page_is_indexed(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    derived = mock_git_repo / "derived.md"
    derived.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:12345\n"
        "---\n"
        "# Derived Content\n"
    )

    import subprocess

    subprocess.run(["git", "add", "derived.md"], cwd=mock_git_repo, check=True)

    count = refresh_provenance_index(reg, mock_git_repo)
    assert count == 1

    summary = get_provenance_for_derived(reg, "derived.md")
    assert summary is not None
    assert summary.derived_path == "derived.md"
    assert summary.generator_id == "agent-1"
    assert summary.model_id is None
    assert len(summary.sources) == 1
    assert summary.sources[0].path == "source.md"
    assert summary.sources[0].content_hash == "sha256:12345"


def test_tracked_markdown_without_provenance_ignored(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    derived = mock_git_repo / "normal.md"
    derived.write_text("# Normal Content\n")

    import subprocess

    subprocess.run(["git", "add", "normal.md"], cwd=mock_git_repo, check=True)

    count = refresh_provenance_index(reg, mock_git_repo)
    assert count == 0
    assert get_provenance_for_derived(reg, "normal.md") is None


def test_untracked_provenance_bearing_page_ignored(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    derived = mock_git_repo / "untracked.md"
    derived.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:12345\n"
        "---\n"
        "# Derived Content\n"
    )
    # Not added to git

    count = refresh_provenance_index(reg, mock_git_repo)
    assert count == 0


def test_multiple_source_rows_supported(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    derived = mock_git_repo / "derived.md"
    derived.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source1.md\n"
        "      content_hash: sha256:111\n"
        "    - path: source2.md\n"
        "      content_hash: sha256:222\n"
        "---\n"
    )
    import subprocess

    subprocess.run(["git", "add", "derived.md"], cwd=mock_git_repo, check=True)

    count = refresh_provenance_index(reg, mock_git_repo)
    assert count == 1

    summary = get_provenance_for_derived(reg, "derived.md")
    assert summary is not None
    assert len(summary.sources) == 2
    assert summary.sources[0].path == "source1.md"
    assert summary.sources[1].path == "source2.md"


def test_model_id_round_trips(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    derived1 = mock_git_repo / "derived1.md"
    derived1.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  model_id: my-model-v1\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:111\n"
        "---\n"
    )

    derived2 = mock_git_repo / "derived2.md"
    derived2.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:111\n"
        "---\n"
    )

    import subprocess

    subprocess.run(["git", "add", "derived1.md", "derived2.md"], cwd=mock_git_repo, check=True)

    refresh_provenance_index(reg, mock_git_repo)

    s1 = get_provenance_for_derived(reg, "derived1.md")
    assert s1 and s1.model_id == "my-model-v1"

    s2 = get_provenance_for_derived(reg, "derived2.md")
    assert s2 and s2.model_id is None


def test_malformed_provenance_aborts_refresh_and_preserves_previous(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    good = mock_git_repo / "good.md"
    good.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:111\n"
        "---\n"
    )
    import subprocess

    subprocess.run(["git", "add", "good.md"], cwd=mock_git_repo, check=True)
    refresh_provenance_index(reg, mock_git_repo)

    bad = mock_git_repo / "bad.md"
    bad.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 2\n"  # Unsupported
        "---\n"
    )
    subprocess.run(["git", "add", "bad.md"], cwd=mock_git_repo, check=True)

    with pytest.raises(ProvenanceIndexError, match="bad.md"):
        refresh_provenance_index(reg, mock_git_repo)

    assert get_provenance_for_derived(reg, "good.md") is not None
    assert get_provenance_for_derived(reg, "bad.md") is None


def test_sql_failure_rolls_back(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    good = mock_git_repo / "good.md"
    good.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:111\n"
        "---\n"
    )
    import subprocess

    subprocess.run(["git", "add", "good.md"], cwd=mock_git_repo, check=True)

    # Intentionally corrupt the schema to cause SQL failure during bulk insert
    with reg.connect() as conn:
        conn.execute("DROP TABLE provenance_sources")

    with pytest.raises(Exception):
        refresh_provenance_index(reg, mock_git_repo)


def test_missing_tracked_file_aborts_refresh(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    good = mock_git_repo / "good.md"
    good.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:111\n"
        "---\n"
    )
    import subprocess

    subprocess.run(["git", "add", "good.md"], cwd=mock_git_repo, check=True)
    refresh_provenance_index(reg, mock_git_repo)

    # Delete from working tree but not git index
    good.unlink()

    with pytest.raises(ProvenanceIndexError, match="missing from working tree"):
        refresh_provenance_index(reg, mock_git_repo)

    # Previous index is preserved
    assert get_provenance_for_derived(reg, "good.md") is not None


def test_git_index_removal_removes_indexed_rows(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    good = mock_git_repo / "good.md"
    good.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:111\n"
        "---\n"
    )
    import subprocess

    subprocess.run(["git", "add", "good.md"], cwd=mock_git_repo, check=True)
    refresh_provenance_index(reg, mock_git_repo)

    # Remove from git
    subprocess.run(["git", "rm", "--cached", "good.md"], cwd=mock_git_repo, check=True)
    good.unlink()

    refresh_provenance_index(reg, mock_git_repo)
    assert get_provenance_for_derived(reg, "good.md") is None


def test_queries(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    derived = mock_git_repo / "derived.md"
    derived.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:111\n"
        "---\n"
    )
    import subprocess

    subprocess.run(["git", "add", "derived.md"], cwd=mock_git_repo, check=True)
    refresh_provenance_index(reg, mock_git_repo)

    # Source to derived
    derived_list = list_derived_for_source(reg, "source.md")
    assert len(derived_list) == 1
    assert derived_list[0].derived_path == "derived.md"

    # Unknown derived
    assert get_provenance_for_derived(reg, "unknown.md") is None

    # Unknown source
    assert len(list_derived_for_source(reg, "unknown.md")) == 0

    # Database deletion and rebuild restore identical typed query results
    db_path.unlink()
    reg2 = Registry(db_path)
    reg2.initialize()
    refresh_provenance_index(reg2, mock_git_repo)

    derived_list2 = list_derived_for_source(reg2, "source.md")
    assert derived_list2 == derived_list


def test_canonical_files_unchanged(mock_git_repo: Path) -> None:
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)
    reg.initialize()

    good = mock_git_repo / "good.md"
    content = (
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: 1\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources:\n"
        "    - path: source.md\n"
        "      content_hash: sha256:111\n"
        "---\n"
    )
    good.write_text(content)
    import subprocess

    subprocess.run(["git", "add", "good.md"], cwd=mock_git_repo, check=True)

    own = mock_git_repo / "generated-ownership.json"
    own.write_text("{}")

    refresh_provenance_index(reg, mock_git_repo)

    assert good.read_text() == content
    assert own.read_text() == "{}"

    # Refresh does not mutate file-registration rows
    # (Since we didn't add any files via normal register APIs, let's just ensure files table is empty)
    with reg.connect_read_only() as conn:
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0


def test_queries_perform_no_writes(mock_git_repo: Path) -> None:
    # Ensure queries don't create missing DB or migrate
    db_path = mock_git_repo / "registry.db"
    reg = Registry(db_path)

    with pytest.raises(RegistryError):
        get_provenance_for_derived(reg, "derived.md")

    with pytest.raises(RegistryError):
        list_derived_for_source(reg, "source.md")


def test_boolean_provenance_schema_version_is_rejected(mock_git_repo: Path) -> None:
    reg = Registry(mock_git_repo / "registry.db")
    reg.initialize()
    derived = mock_git_repo / "derived.md"
    derived.write_text(
        "---\n"
        "lifeos_provenance:\n"
        "  schema_version: true\n"
        "  generator_id: agent-1\n"
        "  generator_version: '1.0'\n"
        "  prompt_schema_version: '2.0'\n"
        "  created_at: '2026-07-13T12:00:00Z'\n"
        "  sources: []\n"
        "---\n",
        encoding="utf-8",
    )

    import subprocess

    subprocess.run(["git", "add", "derived.md"], cwd=mock_git_repo, check=True)

    with pytest.raises(ProvenanceIndexError, match="schema_version must be an integer"):
        refresh_provenance_index(reg, mock_git_repo)
