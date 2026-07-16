from pathlib import Path
from unittest.mock import patch

import pytest

from lifeos.registry import Registry
from lifeos.registry.file_tracking import FileTrackingError, register_scan
from lifeos.scanner import VaultFile
from lifeos.ingestion.provenance import ProvenanceGenerator
from lifeos.ingestion.backend import (
    AnalysisBackendError,
    AnalysisRequest,
    AnalysisResult,
    WikiPageDraft,
)
from lifeos.registry.file_tracking import hash_file_content
from lifeos.ingestion.orchestration import (
    load_registered_source,
    analyze_registered_source,
    MissingSourceError,
    ModifiedSourceError,
    SourceDecodeError,
    SourceParseError,
    SourceReadError,
    UnregisteredSourceError,
)


class FakeAnalysisBackend:
    def __init__(
        self, result: AnalysisResult | None = None, error: Exception | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[AnalysisRequest] = []

    def analyze(self, request: AnalysisRequest, /) -> AnalysisResult:
        self.requests.append(request)
        if self.error:
            raise self.error
        if self.result is None:
            raise RuntimeError("Fake backend misconfigured")
        return self.result


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    db_path = tmp_path / "registry.db"
    reg = Registry(db_path)
    reg.initialize()
    return reg


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def fake_result() -> AnalysisResult:
    return AnalysisResult(
        draft=WikiPageDraft(title="Test", body="Test Body"),
        generator=ProvenanceGenerator(
            id="test", version="1", prompt_schema_version="1", model_id=None
        ),
    )


def test_valid_registered_unchanged_source_succeeds(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    content = "---\ntitle: abc\n---\nBody text!"
    target_file.write_bytes(content.encode("utf-8"))

    register_scan(
        registry,
        vault_root,
        [VaultFile(Path(source_path), "markdown", len(content.encode("utf-8")))],
    )

    backend = FakeAnalysisBackend(result=fake_result)

    with patch(
        "lifeos.ingestion.orchestration.Path.read_bytes", wraps=target_file.read_bytes
    ) as mock_read:
        with patch("lifeos.markdown.parser.Path.read_text") as mock_parser_read:
            analyzed = analyze_registered_source(
                registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
            )

            assert analyzed.analysis == fake_result
            assert len(backend.requests) == 1
            request = backend.requests[0]

            assert request.source.path == source_path
            assert request.source.content_hash.startswith("sha256:")

            assert request.markdown_body == "Body text!"

            mock_read.assert_called_once()
            mock_parser_read.assert_not_called()


def test_absolute_path_rejected_before_filesystem_access(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    backend = FakeAnalysisBackend(result=fake_result)
    with patch("lifeos.ingestion.orchestration.Path.read_bytes") as mock_read:
        with pytest.raises(FileTrackingError):
            analyze_registered_source(
                registry=registry,
                vault_root=vault_root,
                source_path="/absolute.md",
                backend=backend,
            )
        mock_read.assert_not_called()


def test_parent_traversal_rejected_before_filesystem_access(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    backend = FakeAnalysisBackend(result=fake_result)
    with patch("lifeos.ingestion.orchestration.Path.read_bytes") as mock_read:
        with pytest.raises(FileTrackingError):
            analyze_registered_source(
                registry=registry, vault_root=vault_root, source_path="../test.md", backend=backend
            )
        mock_read.assert_not_called()


def test_backslash_path_rejected_before_filesystem_access(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    backend = FakeAnalysisBackend(result=fake_result)
    with patch("lifeos.ingestion.orchestration.Path.read_bytes") as mock_read:
        with pytest.raises(FileTrackingError):
            analyze_registered_source(
                registry=registry,
                vault_root=vault_root,
                source_path=r"dir\test.md",
                backend=backend,
            )
        mock_read.assert_not_called()


def test_unregistered_present_source_rejected(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    target_file.write_bytes(b"content")

    backend = FakeAnalysisBackend(result=fake_result)
    with pytest.raises(UnregisteredSourceError):
        analyze_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
        )


def test_registered_modified_source_rejected(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    target_file.write_bytes(b"content")
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(b"content"))])

    target_file.write_bytes(b"new content")

    backend = FakeAnalysisBackend(result=fake_result)
    with pytest.raises(ModifiedSourceError):
        analyze_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
        )


def test_registered_missing_source_rejected(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    target_file.write_bytes(b"content")
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(b"content"))])

    target_file.unlink()

    backend = FakeAnalysisBackend(result=fake_result)
    with pytest.raises(MissingSourceError):
        analyze_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
        )


def test_unregistered_missing_source_rejected(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    backend = FakeAnalysisBackend(result=fake_result)
    with pytest.raises(UnregisteredSourceError):
        analyze_registered_source(
            registry=registry, vault_root=vault_root, source_path="missing.md", backend=backend
        )


def test_permission_failure_becomes_source_read_error(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    target_file.write_bytes(b"content")

    backend = FakeAnalysisBackend(result=fake_result)
    with patch(
        "lifeos.ingestion.orchestration.Path.read_bytes", side_effect=PermissionError("denied")
    ):
        with pytest.raises(SourceReadError):
            analyze_registered_source(
                registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
            )


def test_invalid_utf8_becomes_source_decode_error(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    target_file.write_bytes(b"\xff\xfe")
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", 2)])

    backend = FakeAnalysisBackend(result=fake_result)
    with pytest.raises(SourceDecodeError):
        analyze_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
        )


def test_malformed_markdown_becomes_source_parse_error(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    target_file.write_bytes(b"content")
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(b"content"))])

    backend = FakeAnalysisBackend(result=fake_result)
    with patch(
        "lifeos.ingestion.orchestration.parse_markdown_note", side_effect=ValueError("parse error")
    ):
        with pytest.raises(SourceParseError):
            analyze_registered_source(
                registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
            )


def test_file_changed_after_initial_read_does_not_alter_request_snapshot(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"original content"
    target_file.write_bytes(content)
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])

    class MutatingBackend:
        def analyze(self, request: AnalysisRequest, /) -> AnalysisResult:
            target_file.write_bytes(b"mutated content")
            return fake_result

    backend = MutatingBackend()

    with patch("lifeos.ingestion.orchestration.parse_markdown_note") as mock_parse:
        mock_parse.return_value.body = "original content"

        analyzed = analyze_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
        )
    assert analyzed.analysis == fake_result
    assert target_file.read_bytes() == b"mutated content"


def test_analysis_backend_error_propagates_unchanged(registry: Registry, vault_root: Path) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    target_file.write_bytes(b"content")
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(b"content"))])

    backend = FakeAnalysisBackend(error=AnalysisBackendError("API limit"))
    with pytest.raises(AnalysisBackendError, match="API limit"):
        analyze_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
        )


def test_arbitrary_backend_programming_error_is_not_relabeled(
    registry: Registry, vault_root: Path
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    target_file.write_bytes(b"content")
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(b"content"))])

    backend = FakeAnalysisBackend(error=ValueError("backend logic bug"))
    with pytest.raises(ValueError, match="backend logic bug"):
        analyze_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
        )




def test_load_registered_source_reads_bytes_once_and_returns_exact_content(
    registry: Registry, vault_root: Path
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"exact raw bytes \xff\xfe"
    target_file.write_bytes(content)

    register_scan(
        registry,
        vault_root,
        [VaultFile(Path(source_path), "markdown", len(content))],
    )

    with patch(
        "lifeos.ingestion.orchestration.Path.read_bytes", wraps=target_file.read_bytes
    ) as mock_read:
        verified = load_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path
        )
        mock_read.assert_called_once()
        assert verified.content == content
        expected_hash = hash_file_content(content)
        assert verified.source.content_hash == f"sha256:{expected_hash}"

def test_load_registered_source_does_not_decode_or_parse_markdown(
    registry: Registry, vault_root: Path
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"content"
    target_file.write_bytes(content)
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])

    with patch("lifeos.ingestion.orchestration.parse_markdown_note") as mock_parse:
        load_registered_source(
            registry=registry, vault_root=vault_root, source_path=source_path
        )
        mock_parse.assert_not_called()

def test_analyze_registered_source_does_not_reopen_source(
    registry: Registry, vault_root: Path, fake_result: AnalysisResult
) -> None:
    source_path = "test.md"
    target_file = vault_root / source_path
    content = b"content"
    target_file.write_bytes(content)
    register_scan(registry, vault_root, [VaultFile(Path(source_path), "markdown", len(content))])
    
    class FakeTrackingBackend:
        requests: list[AnalysisRequest]
        def __init__(self, result: AnalysisResult):
            self.result = result
            self.requests = []
        def analyze(self, request: AnalysisRequest, /) -> AnalysisResult:
            self.requests.append(request)
            return self.result

    backend = FakeTrackingBackend(result=fake_result)

    with patch("lifeos.ingestion.orchestration.Path.read_bytes", wraps=target_file.read_bytes) as mock_read:
        with patch("lifeos.ingestion.orchestration.parse_markdown_note") as mock_parse:
            mock_parse.return_value.body = "mock body"
            analyzed = analyze_registered_source(
                registry=registry, vault_root=vault_root, source_path=source_path, backend=backend
            )
            mock_read.assert_called_once()
            mock_parse.assert_called_once_with(target_file, content="content")
            
            expected_hash = "sha256:" + hash_file_content(content)
            assert analyzed.source == backend.requests[0].source
            assert analyzed.source.content_hash == expected_hash
