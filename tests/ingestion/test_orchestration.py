from pathlib import Path
from unittest.mock import patch

import pytest

from lifeos.ingestion.orchestration import (
    MissingSourceError,
    ModifiedSourceError,
    SourceReadError,
    UnregisteredSourceError,
    load_registered_source,
)
from lifeos.registry import Registry
from lifeos.registry.file_tracking import FileTrackingError, hash_file_content, register_scan
from lifeos.scanner import VaultFile


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    result = Registry(tmp_path / "registry.db")
    result.initialize()
    return result


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    result = tmp_path / "vault"
    result.mkdir()
    return result


def _register(registry: Registry, vault_root: Path, source_path: str, content: bytes) -> None:
    register_scan(
        registry,
        vault_root,
        [VaultFile(Path(source_path), "markdown", len(content))],
    )


def test_registered_unchanged_source_returns_exact_bytes_and_hash(
    registry: Registry, vault_root: Path
) -> None:
    source_path = "study/test.md"
    content = b"exact raw bytes \xff\xfe"
    target = vault_root / source_path
    target.parent.mkdir()
    target.write_bytes(content)
    _register(registry, vault_root, source_path, content)

    with patch(
        "lifeos.ingestion.orchestration.Path.read_bytes", wraps=target.read_bytes
    ) as read_bytes:
        verified = load_registered_source(
            registry=registry,
            vault_root=vault_root,
            source_path=source_path,
        )

    read_bytes.assert_called_once()
    assert verified.content == content
    assert verified.source.path == source_path
    assert verified.source.content_hash == f"sha256:{hash_file_content(content)}"
    assert verified.source.tags == ()
    assert verified.source.topics == ()


def test_registered_source_exposes_only_tags_and_topics(
    registry: Registry, vault_root: Path
) -> None:
    source_path = "study/tagged.md"
    content = (
        b"---\ntags: [existing, '#nested/topic']\ntopics: [new-topic]\n"
        b"secret: hidden\n---\nBody\n"
    )
    target = vault_root / source_path
    target.parent.mkdir()
    target.write_bytes(content)
    _register(registry, vault_root, source_path, content)

    verified = load_registered_source(
        registry=registry,
        vault_root=vault_root,
        source_path=source_path,
    )

    assert verified.source.tags == ("existing", "nested/topic")
    assert verified.source.topics == ("new-topic",)


@pytest.mark.parametrize("source_path", ["/absolute.md", "../test.md", r"dir\test.md"])
def test_invalid_path_is_rejected_before_filesystem_access(
    registry: Registry, vault_root: Path, source_path: str
) -> None:
    with patch("lifeos.ingestion.orchestration.Path.read_bytes") as read_bytes:
        with pytest.raises(FileTrackingError):
            load_registered_source(
                registry=registry,
                vault_root=vault_root,
                source_path=source_path,
            )

    read_bytes.assert_not_called()


def test_unregistered_present_source_is_rejected(
    registry: Registry, vault_root: Path
) -> None:
    (vault_root / "test.md").write_bytes(b"content")

    with pytest.raises(UnregisteredSourceError):
        load_registered_source(
            registry=registry,
            vault_root=vault_root,
            source_path="test.md",
        )


def test_registered_modified_source_is_rejected(
    registry: Registry, vault_root: Path
) -> None:
    target = vault_root / "test.md"
    target.write_bytes(b"content")
    _register(registry, vault_root, "test.md", b"content")
    target.write_bytes(b"changed")

    with pytest.raises(ModifiedSourceError):
        load_registered_source(
            registry=registry,
            vault_root=vault_root,
            source_path="test.md",
        )


def test_registered_missing_source_is_rejected(
    registry: Registry, vault_root: Path
) -> None:
    target = vault_root / "test.md"
    target.write_bytes(b"content")
    _register(registry, vault_root, "test.md", b"content")
    target.unlink()

    with pytest.raises(MissingSourceError):
        load_registered_source(
            registry=registry,
            vault_root=vault_root,
            source_path="test.md",
        )


def test_unregistered_missing_source_is_rejected(
    registry: Registry, vault_root: Path
) -> None:
    with pytest.raises(UnregisteredSourceError):
        load_registered_source(
            registry=registry,
            vault_root=vault_root,
            source_path="missing.md",
        )


def test_read_failure_maps_to_source_read_error(
    registry: Registry, vault_root: Path
) -> None:
    with patch(
        "lifeos.ingestion.orchestration.Path.read_bytes",
        side_effect=PermissionError("denied"),
    ):
        with pytest.raises(SourceReadError):
            load_registered_source(
                registry=registry,
                vault_root=vault_root,
                source_path="test.md",
            )
