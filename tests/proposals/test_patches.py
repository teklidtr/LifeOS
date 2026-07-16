from dataclasses import FrozenInstanceError
import pytest

from lifeos.proposals.patches import (
    PatchDocument,
    ReplaceManagedBlock,
    CreateGeneratedFile,
    ReplaceGeneratedFile,
    CreateFile,
    PatchHumanFile,
    PatchSchemaError,
    validate_patch_document,
    serialize_patch_document,
    serialize_patch_json_bytes,
)

BASE_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def test_valid_empty_patch_document() -> None:
    data = {"schema_version": 1, "proposal_id": "prop-20260712T184129Z-a1b2c3d4", "operations": []}
    doc = validate_patch_document(data)
    assert doc.schema_version == 1
    assert doc.proposal_id == "prop-20260712T184129Z-a1b2c3d4"
    assert doc.operations == ()


def test_valid_operations() -> None:
    data = {
        "schema_version": 1,
        "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
        "operations": [
            {
                "id": "op-1",
                "op": "replace_managed_block",
                "target_path": "wiki/test.md",
                "base_hash": BASE_HASH,
                "block_name": "evidence",
                "new_content": "some text",
            },
            {
                "id": "op-2",
                "op": "create_generated_file",
                "target_path": "dashboards/test.md",
                "expected_target_state": "absent",
                "generator_id": "test.gen",
                "new_content": "new text",
            },
            {
                "id": "op-3",
                "op": "replace_generated_file",
                "target_path": "dashboards/existing.md",
                "base_hash": BASE_HASH,
                "expected_generator_id": "test.gen",
                "new_content": "updated text",
            },
            {
                "id": "op-4",
                "op": "create_file",
                "target_path": "wiki/new.md",
                "expected_target_state": "absent",
                "new_content": "new human text",
            },
            {
                "id": "op-5",
                "op": "patch_human_file",
                "target_path": "wiki/patch.md",
                "base_hash": BASE_HASH,
                "unified_diff": "diff data",
            },
        ],
    }
    doc = validate_patch_document(data)
    assert len(doc.operations) == 5
    assert isinstance(doc.operations[0], ReplaceManagedBlock)
    assert isinstance(doc.operations[1], CreateGeneratedFile)
    assert isinstance(doc.operations[2], ReplaceGeneratedFile)
    assert isinstance(doc.operations[3], CreateFile)
    assert isinstance(doc.operations[4], PatchHumanFile)


def test_invalid_schema_version() -> None:
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(
            {"schema_version": 3, "proposal_id": "prop-20260712T184129Z-a1b2c3d4", "operations": []}
        )
    assert exc.value.code == "unsupported_version"


def test_boolean_trap() -> None:
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(
            {
                "schema_version": True,
                "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
                "operations": [],
            }
        )
    assert exc.value.code == "invalid_type"


def test_invalid_proposal_id() -> None:
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document({"schema_version": 1, "proposal_id": "invalid", "operations": []})
    assert exc.value.code == "invalid_format"


def test_malformed_hashes() -> None:
    data = {
        "schema_version": 1,
        "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
        "operations": [
            {
                "id": "op-1",
                "op": "replace_managed_block",
                "target_path": "a.md",
                "base_hash": "invalid-hash",
                "block_name": "b",
                "new_content": "c",
            }
        ],
    }
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(data)
    assert exc.value.code == "invalid_format"


def test_target_path_safety() -> None:
    def make_doc(path: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
            "operations": [
                {
                    "id": "op-1",
                    "op": "create_file",
                    "target_path": path,
                    "expected_target_state": "absent",
                    "new_content": "c",
                }
            ],
        }

    # Absolute
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("/test"))
    # Traversal
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("test/../a"))
    # Current dir
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("./test"))
    # Empty part
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("test//a"))
    # Trailing slash
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("test/"))
    # Backslash
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("test\\a"))
    # Null byte
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("test\0a"))
    # Reserved namespaces
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc(".lifeos/config"))
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc(".git/HEAD"))
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("proposals/p1"))
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc(".lifeos"))
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc(".git"))
    with pytest.raises(PatchSchemaError):
        validate_patch_document(make_doc("proposals"))

    # Similarly named safe paths
    validate_patch_document(make_doc(".lifeos-notes/example.md"))
    validate_patch_document(make_doc(".github/workflows.md"))
    validate_patch_document(make_doc("proposals-archive/example.md"))


def test_replace_managed_block_must_target_md() -> None:
    data = {
        "schema_version": 1,
        "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
        "operations": [
            {
                "id": "op-1",
                "op": "replace_managed_block",
                "target_path": "a.txt",
                "base_hash": BASE_HASH,
                "block_name": "b",
                "new_content": "c",
            }
        ],
    }
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(data)
    assert exc.value.code == "invalid_target"


def test_missing_and_unknown_fields() -> None:
    # Unknown root field
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(
            {
                "schema_version": 1,
                "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
                "operations": [],
                "bad": 1,
            }
        )
    assert exc.value.code == "unknown_field"

    # Missing root field
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document({"schema_version": 1, "operations": []})
    assert exc.value.code == "invalid_type"


def test_invalid_and_duplicate_op_ids() -> None:
    def make_ops(ops: list[dict[str, object]]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
            "operations": ops,
        }

    # Invalid
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(
            make_ops(
                [
                    {
                        "id": "INVALID",
                        "op": "create_file",
                        "target_path": "a.md",
                        "expected_target_state": "absent",
                        "new_content": "c",
                    }
                ]
            )
        )
    assert exc.value.code == "invalid_format"

    # Duplicate
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(
            make_ops(
                [
                    {
                        "id": "op-1",
                        "op": "create_file",
                        "target_path": "a.md",
                        "expected_target_state": "absent",
                        "new_content": "c",
                    },
                    {
                        "id": "op-1",
                        "op": "create_file",
                        "target_path": "b.md",
                        "expected_target_state": "absent",
                        "new_content": "c",
                    },
                ]
            )
        )
    assert exc.value.code == "duplicate_id"


def test_duplicate_targets() -> None:
    data = {
        "schema_version": 1,
        "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
        "operations": [
            {
                "id": "op-1",
                "op": "create_file",
                "target_path": "a.md",
                "expected_target_state": "absent",
                "new_content": "c",
            },
            {
                "id": "op-2",
                "op": "create_file",
                "target_path": "a.md",
                "expected_target_state": "absent",
                "new_content": "c",
            },
        ],
    }
    with pytest.raises(PatchSchemaError) as exc:
        validate_patch_document(data)
    assert exc.value.code == "duplicate_target"


def test_deep_immutability() -> None:
    data: dict[str, object] = {
        "schema_version": 1,
        "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
        "operations": [
            {
                "id": "op-1",
                "op": "create_file",
                "target_path": "a.md",
                "expected_target_state": "absent",
                "new_content": "c",
            }
        ],
    }
    doc = validate_patch_document(data)
    with pytest.raises(FrozenInstanceError):
        doc.schema_version = 2  # type: ignore

    with pytest.raises(TypeError):
        doc.operations[0] = None  # type: ignore

    ops_list = data["operations"]
    if isinstance(ops_list, list):
        ops_list.append(
            {
                "id": "op-2",
                "op": "create_file",
                "target_path": "b.md",
                "expected_target_state": "absent",
                "new_content": "c",
            }
        )
    assert len(doc.operations) == 1


def test_deterministic_serialization() -> None:
    data = {
        "schema_version": 1,
        "proposal_id": "prop-20260712T184129Z-a1b2c3d4",
        "operations": [
            {
                "id": "op-1",
                "op": "create_file",
                "target_path": "a.md",
                "expected_target_state": "absent",
                "new_content": "c",
            },
            {
                "id": "op-2",
                "op": "create_file",
                "target_path": "b.md",
                "expected_target_state": "absent",
                "new_content": "c",
            },
        ],
    }
    doc = validate_patch_document(data)
    serialized = serialize_patch_document(doc)

    # Must preserve array order exactly
    assert serialized["operations"][0]["id"] == "op-1"
    assert serialized["operations"][1]["id"] == "op-2"

    b = serialize_patch_json_bytes(doc)
    # Output ends with exactly one serializer-added LF
    assert b.endswith(b"\n")
    assert not b.endswith(b"\n\n")


def test_error_ordering() -> None:
    # Malformed documents with differently ordered input mappings
    data1 = {"schema_version": "bad", "proposal_id": "bad", "operations": []}
    data2 = {"operations": [], "proposal_id": "bad", "schema_version": "bad"}

    with pytest.raises(PatchSchemaError) as exc1:
        validate_patch_document(data1)

    with pytest.raises(PatchSchemaError) as exc2:
        validate_patch_document(data2)

    errs1 = exc1.value.errors
    errs2 = exc2.value.errors

    assert len(errs1) == len(errs2)
    for e1, e2 in zip(errs1, errs2):
        assert e1.field_path == e2.field_path
        assert e1.code == e2.code
        assert e1.message == e2.message


def test_public_constructor_safety() -> None:
    # Verify public construction enforces local invariants
    with pytest.raises(ValueError):
        ReplaceManagedBlock(
            id="invalid ID",
            target_path="a.md",
            base_hash=BASE_HASH,
            block_name="b",
            new_content="c",
        )
    with pytest.raises(ValueError):
        ReplaceManagedBlock(
            id="op-1", target_path="/a.md", base_hash=BASE_HASH, block_name="b", new_content="c"
        )
    with pytest.raises(ValueError):
        ReplaceManagedBlock(
            id="op-1", target_path="a.txt", base_hash=BASE_HASH, block_name="b", new_content="c"
        )
    with pytest.raises(ValueError):
        CreateGeneratedFile(
            id="op-1",
            target_path="a.md",
            expected_target_state="present",
            generator_id="b",
            new_content="c",
        )  # type: ignore
    with pytest.raises(ValueError):
        PatchDocument(schema_version=2, proposal_id="prop-20260712T184129Z-a1b2c3d4", operations=())
