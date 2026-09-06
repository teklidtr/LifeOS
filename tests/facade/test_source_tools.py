from __future__ import annotations

from pathlib import Path

import pytest

import lifeos.captures.storage as capture_storage
from lifeos.captures.contracts import CaptureError
from lifeos.facade import (
    SOURCE_EXTRACT_DESCRIPTOR,
    SOURCE_IMPORT_DESCRIPTOR,
    SOURCE_INSPECT_DESCRIPTOR,
    SourceExtractRequest,
    SourceImportRequest,
    SourceInspectRequest,
    ToolAuthorizationError,
    ToolConflictError,
    ToolEffect,
    ToolNotFoundError,
    ToolValidationError,
    extract_source,
    import_source,
    inspect_source,
)


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    return vault, runtime


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("resume.pdf", b"%PDF-1.4\nfixture"),
        ("salary.tsv", b"year\tamount\n2025\t100\n"),
        ("assets.xml", b"<assets><cash>10</cash></assets>"),
        ("archive.weird", b"\x00\x01\x02fixture"),
    ],
)
def test_generic_import_preserves_distinct_file_types_without_path_leak(
    tmp_path: Path,
    filename: str,
    content: bytes,
) -> None:
    vault, runtime = _roots(tmp_path)
    source = tmp_path / "incoming" / filename
    source.parent.mkdir()
    source.write_bytes(content)

    result = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(source_path=str(source)),
    )

    assert result.details.original_filename == filename
    assert result.details.byte_size == len(content)
    assert result.details.integrity_status == "ok"
    assert result.details.extraction_status == "not-requested"
    assert result.details.source.capture_path.startswith("captures/")
    assert result.details.source.attachment_id.startswith("att-")
    serialized = repr(result.to_dict())
    assert str(source) not in serialized
    assert "attachments/originals/" not in serialized
    assert "attachments/manifests/" not in serialized
    assert all(str(source) not in path.read_text() for path in vault.rglob("*.md"))


def test_descriptors_classify_source_effects() -> None:
    assert SOURCE_IMPORT_DESCRIPTOR.name == "source.import"
    assert SOURCE_IMPORT_DESCRIPTOR.effect is ToolEffect.CANONICAL_CAPTURE
    assert SOURCE_INSPECT_DESCRIPTOR.name == "source.inspect"
    assert SOURCE_INSPECT_DESCRIPTOR.effect is ToolEffect.READ_ONLY
    assert SOURCE_EXTRACT_DESCRIPTOR.name == "source.extract"
    assert SOURCE_EXTRACT_DESCRIPTOR.effect is ToolEffect.DERIVED_WRITE


def test_duplicate_reuses_source_identity_and_same_name_new_bytes_stay_distinct(
    tmp_path: Path,
) -> None:
    vault, runtime = _roots(tmp_path)
    first_path = tmp_path / "first" / "history.tsv"
    second_path = tmp_path / "second" / "history.tsv"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_text("year\tvalue\n2025\t1\n")
    second_path.write_text("year\tvalue\n2025\t2\n")

    first = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(str(first_path)),
    )
    duplicate = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(str(first_path)),
    )
    changed = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(str(second_path)),
    )

    assert duplicate.duplicate and duplicate.reused_original
    assert duplicate.details.source.attachment_id == first.details.source.attachment_id
    assert duplicate.details.content_hash == first.details.content_hash
    assert changed.details.source.attachment_id != first.details.source.attachment_id
    assert changed.details.content_hash != first.details.content_hash


def test_inspect_reports_integrity_privacy_and_processing_without_content(tmp_path: Path) -> None:
    vault, runtime = _roots(tmp_path)
    source = tmp_path / "private.txt"
    source.write_text("private body")
    imported = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(
            str(source),
            privacy_scope="private",
            sensitive=True,
        ),
    )

    details = inspect_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceInspectRequest(imported.details.source),
    )

    assert details.integrity_status == "ok"
    assert details.extraction_status == "not-requested"
    assert details.privacy_scope == "private"
    assert details.sensitive is True
    assert "text" not in details.to_dict()


def test_text_extraction_is_derived_reused_and_bounded(tmp_path: Path) -> None:
    vault, runtime = _roots(tmp_path)
    source = tmp_path / "notes.txt"
    source.write_text("alpha βeta gamma")
    imported = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(str(source)),
    )

    extracted = extract_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceExtractRequest(imported.details.source, max_text_bytes=8),
    )
    repeated = extract_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceExtractRequest(imported.details.source, max_text_bytes=8),
    )

    assert extracted.status == "completed"
    assert extracted.method == "utf8-text"
    assert extracted.truncated is True
    assert len(extracted.text.encode("utf-8")) <= 8
    assert repeated.text == extracted.text
    assert repeated.details.extraction_status == "completed"
    assert (
        runtime / "captures" / "extracted" / f"{imported.details.source.attachment_id}.json"
    ).exists()


def test_unsupported_extraction_remains_explicit_and_preserves_source(tmp_path: Path) -> None:
    vault, runtime = _roots(tmp_path)
    source = tmp_path / "opaque.bin"
    source.write_bytes(b"\x00\x01\x02")
    imported = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(str(source)),
    )

    result = extract_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceExtractRequest(imported.details.source),
    )

    assert result.status == "unavailable"
    assert result.method == "none"
    assert result.text == ""
    assert result.details.integrity_status == "ok"


def test_protected_content_requires_explicit_local_scope(tmp_path: Path) -> None:
    vault, runtime = _roots(tmp_path)
    source = tmp_path / "protected.txt"
    source.write_text("secret local text")
    imported = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(
            str(source),
            privacy_scope="protected",
            sensitive=True,
        ),
    )

    with pytest.raises(ToolAuthorizationError):
        extract_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceExtractRequest(imported.details.source),
        )

    allowed = extract_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceExtractRequest(imported.details.source, allow_protected=True),
    )
    assert allowed.text == "secret local text"


def test_external_protected_disclosure_uses_two_key_policy_and_is_bounded(tmp_path: Path) -> None:
    vault, runtime = _roots(tmp_path)
    source = tmp_path / "protected.txt"
    source.write_text("secret external text")
    imported = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(
            str(source),
            privacy_scope="protected",
            sensitive=True,
        ),
    )
    system = vault / "system"
    system.mkdir()
    policy = system / "retrieval-policy.yml"
    policy.write_text(
        "schema_version: 1\n"
        "protected_prefixes: [captures, attachments]\n"
        "external_allowed_prefixes: []\n"
    )

    with pytest.raises(ToolAuthorizationError):
        extract_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceExtractRequest(
                imported.details.source,
                mode="external",
                allow_protected=True,
            ),
        )

    policy.write_text(
        "schema_version: 1\n"
        "protected_prefixes: [captures, attachments]\n"
        "external_allowed_prefixes: [captures, attachments]\n"
    )
    with pytest.raises(ToolAuthorizationError):
        extract_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceExtractRequest(imported.details.source, mode="external"),
        )

    allowed = extract_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceExtractRequest(
            imported.details.source,
            mode="external",
            allow_protected=True,
            max_text_bytes=6,
        ),
    )
    assert allowed.text == "secret"
    assert allowed.truncated is True


def test_local_extraction_obeys_canonical_exclusion_policy(tmp_path: Path) -> None:
    vault, runtime = _roots(tmp_path)
    source = tmp_path / "excluded.txt"
    source.write_text("must stay excluded")
    imported = import_source(
        vault_root=vault,
        runtime_dir=runtime,
        request=SourceImportRequest(str(source)),
    )
    system = vault / "system"
    system.mkdir()
    (system / "retrieval-policy.yml").write_text(
        "schema_version: 1\n"
        "excluded_prefixes: [attachments/originals]\n"
        "protected_prefixes: []\n"
        "external_allowed_prefixes: []\n"
    )

    with pytest.raises(ToolAuthorizationError):
        extract_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceExtractRequest(imported.details.source),
        )


@pytest.mark.parametrize("bad_path", ["relative/file.txt", "", " ../file.txt"])
def test_import_request_rejects_unsafe_non_absolute_paths(bad_path: str) -> None:
    with pytest.raises(ValueError, match="absolute local path"):
        SourceImportRequest(bad_path)


def test_import_rejects_missing_symlink_and_non_regular_without_leaking_host_path(
    tmp_path: Path,
) -> None:
    vault, runtime = _roots(tmp_path)
    missing = tmp_path / "outside" / "missing.txt"
    with pytest.raises(ToolNotFoundError) as missing_error:
        import_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceImportRequest(str(missing)),
        )
    assert str(missing) not in str(missing_error.value)

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ToolValidationError):
        import_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceImportRequest(str(directory)),
        )

    target = tmp_path / "target.txt"
    target.write_text("target")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(ToolNotFoundError):
        import_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceImportRequest(str(link)),
        )


def test_changed_source_error_remains_conflict_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, runtime = _roots(tmp_path)
    source = tmp_path / "changing.txt"
    source.write_text("changing")

    def changed(_path: Path) -> tuple[str, int, int]:
        raise CaptureError("file_changed", f"changed at {source}")

    monkeypatch.setattr(capture_storage, "_hash_path", changed)

    with pytest.raises(ToolConflictError) as error:
        import_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceImportRequest(str(source)),
        )
    assert str(source) not in str(error.value)
