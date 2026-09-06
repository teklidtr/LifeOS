import pytest
import json

from lifeos.proposals.patches import (
    PatchDocument,
    PatchDocumentV2,
    ReplaceManagedBlock,
    CreateGeneratedFile,
    ReplaceGeneratedFile,
    CreateFile,
    PatchHumanFile,
    CreateGeneratedFileV2,
    ReplaceGeneratedFileV2,
    ReleaseGeneratedOwnershipV2,
    serialize_patch_json_bytes,
    validate_patch_document,
    PatchSchemaError,
)

GOLDEN_V1_BYTES = b'{"operations":[{"base_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000000","block_name":"block-1","id":"op-1","new_content":"content 1","op":"replace_managed_block","target_path":"target.md"},{"expected_target_state":"absent","generator_id":"generator-1","id":"op-2","new_content":"content 2","op":"create_generated_file","target_path":"gen1.txt"},{"base_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000000","expected_generator_id":"generator-2","id":"op-3","new_content":"content 3","op":"replace_generated_file","target_path":"gen2.txt"},{"expected_target_state":"absent","id":"op-4","new_content":"content 4","op":"create_file","target_path":"file.txt"},{"base_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000000","id":"op-5","op":"patch_human_file","target_path":"human.txt","unified_diff":"diff 5"}],"proposal_id":"prop-20260713T090000Z-01234567","schema_version":1}\n'


def test_v1_golden_bytes() -> None:
    doc = PatchDocument(
        schema_version=1,
        proposal_id="prop-20260713T090000Z-01234567",
        operations=(
            ReplaceManagedBlock("op-1", "target.md", "sha256:" + "0" * 64, "block-1", "content 1"),
            CreateGeneratedFile("op-2", "gen1.txt", "absent", "generator-1", "content 2"),
            ReplaceGeneratedFile(
                "op-3", "gen2.txt", "sha256:" + "0" * 64, "generator-2", "content 3"
            ),
            CreateFile("op-4", "file.txt", "absent", "content 4"),
            PatchHumanFile("op-5", "human.txt", "sha256:" + "0" * 64, "diff 5"),
        ),
    )
    assert serialize_patch_json_bytes(doc) == GOLDEN_V1_BYTES

    # Also test parse then serialize preserves exact bytes
    parsed = validate_patch_document(json.loads(GOLDEN_V1_BYTES))
    assert serialize_patch_json_bytes(parsed) == GOLDEN_V1_BYTES


def test_v2_construction() -> None:
    doc = PatchDocumentV2(
        schema_version=2,
        proposal_id="prop-20260713T090000Z-01234567",
        operations=(
            CreateGeneratedFileV2(
                "op-1", "gen1.txt", "absent", "generator-1", "v1.0.0", "content 2"
            ),
            ReplaceGeneratedFileV2(
                "op-2", "gen2.txt", "sha256:" + "0" * 64, "generator-2", "v2.0.0", "content 3"
            ),
            ReplaceManagedBlock("op-3", "target.md", "sha256:" + "0" * 64, "block-1", "content 1"),
            CreateFile("op-4", "file.txt", "absent", "content 4"),
            PatchHumanFile("op-5", "human.txt", "sha256:" + "0" * 64, "diff 5"),
        ),
    )
    b = serialize_patch_json_bytes(doc)
    parsed = validate_patch_document(json.loads(b))
    assert isinstance(parsed, PatchDocumentV2)
    assert parsed.operations[0].generator_version == "v1.0.0"  # type: ignore


def test_v2_release_generated_ownership_round_trip_and_v1_rejection() -> None:
    operation = ReleaseGeneratedOwnershipV2(
        "op-release",
        "wiki/missing.md",
        "sha256:" + "a" * 64,
        "lifeos.test",
        "1",
        "2026-08-22T10:00:00Z",
        "2026-08-22T11:00:00Z",
    )
    document = PatchDocumentV2(
        2,
        "prop-20260713T090000Z-01234567",
        (operation,),
    )

    serialized = serialize_patch_json_bytes(document)
    parsed = validate_patch_document(json.loads(serialized))

    assert parsed == document
    invalid_v1 = json.loads(serialized)
    invalid_v1["schema_version"] = 1
    with pytest.raises(PatchSchemaError) as error:
        validate_patch_document(invalid_v1)
    assert error.value.code == "unsupported_operation_version"


def test_v2_invalid_generator_version() -> None:
    # non-string values
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", 123, "content 2")  # type: ignore
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", True, "content 2")  # type: ignore
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", False, "content 2")  # type: ignore

    # empty string
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", "", "content 2")

    # whitespace-only string
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", "   ", "content 2")

    # leading / trailing whitespace
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", " v1", "content 2")
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", "v1 ", "content 2")

    # more than 64 characters
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", "a" * 65, "content 2")

    # NUL, CR, LF, ASCII control characters
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", "v\0", "content 2")
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", "v\r", "content 2")
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", "v\n", "content 2")
    with pytest.raises(ValueError):
        CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "generator-1", "v\x1b", "content 2")

    # test for ReplaceGeneratedFileV2 as well
    with pytest.raises(ValueError):
        ReplaceGeneratedFileV2(
            "op-1", "gen1.txt", "sha256:" + "0" * 64, "generator-1", "", "content 2"
        )


def test_v2_validation() -> None:
    valid_data = {
        "schema_version": 2,
        "proposal_id": "prop-20260713T090000Z-01234567",
        "operations": [
            {
                "id": "op-1",
                "op": "create_generated_file",
                "target_path": "gen1.txt",
                "expected_target_state": "absent",
                "generator_id": "generator-1",
                "generator_version": "v1.0.0",
                "new_content": "content 2",
            }
        ],
    }
    doc = validate_patch_document(valid_data)
    assert isinstance(doc, PatchDocumentV2)

    invalid_data = {
        "schema_version": 2,
        "proposal_id": "prop-20260713T090000Z-01234567",
        "operations": [
            {
                "id": "op-1",
                "op": "create_generated_file",
                "target_path": "gen1.txt",
                "expected_target_state": "absent",
                "generator_id": "generator-1",
                # missing generator_version
                "new_content": "content 2",
            }
        ],
    }
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(invalid_data)
    assert exc.value.code == "invalid_type"


def test_v2_cross_version_rejection() -> None:
    # PatchDocument version 1 containing CreateGeneratedFileV2
    with pytest.raises(ValueError):
        PatchDocument(
            schema_version=1,
            proposal_id="prop-20260713T090000Z-01234567",
            operations=(
                CreateGeneratedFileV2(
                    "op-1", "gen1.txt", "absent", "generator-1", "v1.0", "content 2"
                ),
            ),  # type: ignore
        )

    # PatchDocument version 1 containing ReplaceGeneratedFileV2
    with pytest.raises(ValueError):
        PatchDocument(
            schema_version=1,
            proposal_id="prop-20260713T090000Z-01234567",
            operations=(
                ReplaceGeneratedFileV2(
                    "op-1", "gen1.txt", "sha256:" + "0" * 64, "generator-1", "v1.0", "content 2"
                ),
            ),  # type: ignore
        )

    # PatchDocumentV2 containing CreateGeneratedFile
    with pytest.raises(ValueError):
        PatchDocumentV2(
            schema_version=2,
            proposal_id="prop-20260713T090000Z-01234567",
            operations=(
                CreateGeneratedFile("op-1", "gen1.txt", "absent", "generator-1", "content 2"),
            ),  # type: ignore
        )

    # PatchDocumentV2 containing ReplaceGeneratedFile
    with pytest.raises(ValueError):
        PatchDocumentV2(
            schema_version=2,
            proposal_id="prop-20260713T090000Z-01234567",
            operations=(
                ReplaceGeneratedFile(
                    "op-1", "gen1.txt", "sha256:" + "0" * 64, "generator-1", "content 2"
                ),
            ),  # type: ignore
        )


def test_v2_duplicate_rejection() -> None:
    # duplicate IDs
    with pytest.raises(ValueError):
        PatchDocumentV2(
            schema_version=2,
            proposal_id="prop-20260713T090000Z-01234567",
            operations=(
                CreateGeneratedFileV2(
                    "op-1", "gen1.txt", "absent", "generator-1", "v1.0.0", "content 2"
                ),
                CreateGeneratedFileV2(
                    "op-1", "gen2.txt", "absent", "generator-1", "v1.0.0", "content 2"
                ),
            ),
        )
    # duplicate targets
    with pytest.raises(ValueError):
        PatchDocumentV2(
            schema_version=2,
            proposal_id="prop-20260713T090000Z-01234567",
            operations=(
                CreateGeneratedFileV2(
                    "op-1", "gen1.txt", "absent", "generator-1", "v1.0.0", "content 2"
                ),
                ReplaceGeneratedFileV2(
                    "op-2", "gen1.txt", "sha256:" + "0" * 64, "generator-1", "v1.0.0", "content 3"
                ),
            ),
        )


def test_v1_rejects_generator_version() -> None:
    invalid_data = {
        "schema_version": 1,
        "proposal_id": "prop-20260713T090000Z-01234567",
        "operations": [
            {
                "id": "op-1",
                "op": "create_generated_file",
                "target_path": "gen1.txt",
                "expected_target_state": "absent",
                "generator_id": "generator-1",
                "generator_version": "v1.0.0",  # unknown field for v1
                "new_content": "content 2",
            }
        ],
    }
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(invalid_data)
    assert exc.value.code == "unknown_field"


def test_v2_rejects_generator_id_in_replacement() -> None:
    invalid_data = {
        "schema_version": 2,
        "proposal_id": "prop-20260713T090000Z-01234567",
        "operations": [
            {
                "id": "op-1",
                "op": "replace_generated_file",
                "target_path": "gen1.txt",
                "base_hash": "sha256:" + "0" * 64,
                "expected_generator_id": "generator-1",
                "generator_id": "generator-1",  # unknown field for replace
                "generator_version": "v1.0.0",
                "new_content": "content 2",
            }
        ],
    }
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(invalid_data)
    assert exc.value.code == "unknown_field"


GOLDEN_V2_BYTES = b'{"operations":[{"expected_target_state":"absent","generator_id":"generator-1","generator_version":"v1.0.0","id":"op-1","new_content":"content 2","op":"create_generated_file","target_path":"gen1.txt"},{"base_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000000","expected_generator_id":"generator-2","generator_version":"v2.0.0","id":"op-2","new_content":"content 3","op":"replace_generated_file","target_path":"gen2.txt"}],"proposal_id":"prop-20260713T090000Z-01234567","schema_version":2}\n'


def test_v2_golden_bytes() -> None:
    doc = PatchDocumentV2(
        schema_version=2,
        proposal_id="prop-20260713T090000Z-01234567",
        operations=(
            CreateGeneratedFileV2(
                "op-1", "gen1.txt", "absent", "generator-1", "v1.0.0", "content 2"
            ),
            ReplaceGeneratedFileV2(
                "op-2", "gen2.txt", "sha256:" + "0" * 64, "generator-2", "v2.0.0", "content 3"
            ),
        ),
    )
    b = serialize_patch_json_bytes(doc)
    assert b == GOLDEN_V2_BYTES
    # Verify exactly one trailing LF
    assert b.endswith(b"}\n")
    assert not b.endswith(b"}\n\n")
