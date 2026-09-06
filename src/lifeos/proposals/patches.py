import json
import posixpath
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Union

from .schema import ProposalSchemaError, validate_proposal_id


class PatchSchemaError(Exception):
    def __init__(
        self,
        code: str,
        field_path: str,
        message: str,
        errors: list["PatchSchemaError"] | None = None,
    ) -> None:
        super().__init__(f"{field_path} ({code}): {message}")
        self.code = code
        self.field_path = field_path
        self.message = message
        self.errors = errors or [self]


OP_ID_REGEX = re.compile(r"^op-[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
IDENTIFIER_REGEX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
HASH_REGEX = re.compile(r"^sha256:[a-f0-9]{64}$")


def _validate_path_syntax(val: Any) -> None:
    if not isinstance(val, str) or not val:
        raise ValueError("path must be a non-empty string")
    if "\0" in val or "\\" in val or "//" in val:
        raise ValueError("path contains invalid characters or duplicate separators")
    if val.startswith("/") or val.startswith("./") or val.endswith("/"):
        raise ValueError("path must be relative without leading ./ or trailing /")
    parts = val.split("/")
    if "" in parts or "." in parts or ".." in parts:
        raise ValueError("path contains empty, ., or .. components")
    if val != posixpath.normpath(val):
        raise ValueError("path is not normalized")
    if val.strip() != val:
        raise ValueError("path has leading or trailing whitespace")
    first_part = parts[0]
    if first_part in (".lifeos", ".git", "proposals"):
        raise ValueError(f"path targets reserved namespace {first_part}")


def _validate_hash_syntax(val: Any) -> None:
    if not isinstance(val, str) or not HASH_REGEX.match(val):
        raise ValueError("hash must match ^sha256:[a-f0-9]{64}$")


def _validate_id_syntax(val: Any) -> None:
    if not isinstance(val, str) or not OP_ID_REGEX.match(val):
        raise ValueError("invalid operation id")


def _validate_identifier_syntax(val: Any) -> None:
    if not isinstance(val, str) or not IDENTIFIER_REGEX.match(val):
        raise ValueError("invalid identifier")


def _validate_string_syntax(val: Any) -> None:
    if not isinstance(val, str) or not val:
        raise ValueError("must be a non-empty string")


def _validate_generator_version(val: Any) -> None:
    if type(val) is not str:
        raise ValueError("must be exactly str")
    if not (1 <= len(val) <= 64):
        raise ValueError("length must be between 1 and 64 characters")
    if val != val.strip():
        raise ValueError("must not have leading or trailing whitespace")
    if "\0" in val or "\r" in val or "\n" in val:
        raise ValueError("must not contain NUL, CR, or LF")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in val):
        raise ValueError("must not contain ASCII control characters")


@dataclass(frozen=True)
class ReplaceManagedBlock:
    id: str
    target_path: str
    base_hash: str
    block_name: str
    new_content: str
    op: Literal["replace_managed_block"] = "replace_managed_block"

    def __post_init__(self) -> None:
        _validate_id_syntax(self.id)
        _validate_path_syntax(self.target_path)
        if not self.target_path.endswith(".md"):
            raise ValueError("target_path must be .md")
        _validate_hash_syntax(self.base_hash)
        _validate_identifier_syntax(self.block_name)
        _validate_string_syntax(self.new_content)


@dataclass(frozen=True)
class CreateGeneratedFile:
    id: str
    target_path: str
    expected_target_state: Literal["absent"]
    generator_id: str
    new_content: str
    op: Literal["create_generated_file"] = "create_generated_file"

    def __post_init__(self) -> None:
        _validate_id_syntax(self.id)
        _validate_path_syntax(self.target_path)
        if self.expected_target_state != "absent":
            raise ValueError("expected_target_state must be 'absent'")
        _validate_identifier_syntax(self.generator_id)
        _validate_string_syntax(self.new_content)


@dataclass(frozen=True)
class ReplaceGeneratedFile:
    id: str
    target_path: str
    base_hash: str
    expected_generator_id: str
    new_content: str
    op: Literal["replace_generated_file"] = "replace_generated_file"

    def __post_init__(self) -> None:
        _validate_id_syntax(self.id)
        _validate_path_syntax(self.target_path)
        _validate_hash_syntax(self.base_hash)
        _validate_identifier_syntax(self.expected_generator_id)
        _validate_string_syntax(self.new_content)


@dataclass(frozen=True)
class CreateFile:
    id: str
    target_path: str
    expected_target_state: Literal["absent"]
    new_content: str
    op: Literal["create_file"] = "create_file"

    def __post_init__(self) -> None:
        _validate_id_syntax(self.id)
        _validate_path_syntax(self.target_path)
        if self.expected_target_state != "absent":
            raise ValueError("expected_target_state must be 'absent'")
        _validate_string_syntax(self.new_content)


@dataclass(frozen=True)
class PatchHumanFile:
    id: str
    target_path: str
    base_hash: str
    unified_diff: str
    op: Literal["patch_human_file"] = "patch_human_file"

    def __post_init__(self) -> None:
        _validate_id_syntax(self.id)
        _validate_path_syntax(self.target_path)
        _validate_hash_syntax(self.base_hash)
        _validate_string_syntax(self.unified_diff)


@dataclass(frozen=True)
class CreateGeneratedFileV2:
    id: str
    target_path: str
    expected_target_state: Literal["absent"]
    generator_id: str
    generator_version: str
    new_content: str
    op: Literal["create_generated_file"] = "create_generated_file"

    def __post_init__(self) -> None:
        _validate_id_syntax(self.id)
        _validate_path_syntax(self.target_path)
        if self.expected_target_state != "absent":
            raise ValueError("expected_target_state must be 'absent'")
        _validate_identifier_syntax(self.generator_id)
        _validate_generator_version(self.generator_version)
        _validate_string_syntax(self.new_content)


@dataclass(frozen=True)
class ReplaceGeneratedFileV2:
    id: str
    target_path: str
    base_hash: str
    expected_generator_id: str
    generator_version: str
    new_content: str
    op: Literal["replace_generated_file"] = "replace_generated_file"

    def __post_init__(self) -> None:
        _validate_id_syntax(self.id)
        _validate_path_syntax(self.target_path)
        _validate_hash_syntax(self.base_hash)
        _validate_identifier_syntax(self.expected_generator_id)
        _validate_generator_version(self.generator_version)
        _validate_string_syntax(self.new_content)


@dataclass(frozen=True)
class ReleaseGeneratedOwnershipV2:
    id: str
    target_path: str
    expected_content_hash: str
    expected_generator_id: str
    expected_generator_version: str
    expected_created_at: str
    expected_updated_at: str
    op: Literal["release_generated_ownership"] = "release_generated_ownership"

    def __post_init__(self) -> None:
        _validate_id_syntax(self.id)
        _validate_path_syntax(self.target_path)
        _validate_hash_syntax(self.expected_content_hash)
        _validate_identifier_syntax(self.expected_generator_id)
        _validate_generator_version(self.expected_generator_version)
        _validate_string_syntax(self.expected_created_at)
        _validate_string_syntax(self.expected_updated_at)


PatchOperationV1 = Union[
    ReplaceManagedBlock,
    CreateGeneratedFile,
    ReplaceGeneratedFile,
    CreateFile,
    PatchHumanFile,
]

PatchOperationV2 = Union[
    ReplaceManagedBlock,
    CreateGeneratedFileV2,
    ReplaceGeneratedFileV2,
    ReleaseGeneratedOwnershipV2,
    CreateFile,
    PatchHumanFile,
]

PatchOperation = Union[PatchOperationV1, PatchOperationV2]


@dataclass(frozen=True)
class PatchDocument:
    schema_version: int
    proposal_id: str
    operations: tuple[PatchOperationV1, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or isinstance(self.schema_version, bool):
            raise ValueError("schema_version must be an int")
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        try:
            validate_proposal_id(self.proposal_id, field_path="proposal_id")
        except ProposalSchemaError:
            raise ValueError("invalid proposal_id")
        if not isinstance(self.operations, tuple):
            raise ValueError("operations must be a tuple")
        op_ids = set()
        targets = set()
        for op in self.operations:
            if not isinstance(
                op,
                (
                    ReplaceManagedBlock,
                    CreateGeneratedFile,
                    ReplaceGeneratedFile,
                    CreateFile,
                    PatchHumanFile,
                ),
            ):
                raise ValueError("operation is not a valid v1 operation model")
            if op.id in op_ids:
                raise ValueError("duplicate operation id")
            if op.target_path in targets:
                raise ValueError("duplicate target path")
            op_ids.add(op.id)
            targets.add(op.target_path)


@dataclass(frozen=True)
class PatchDocumentV2:
    schema_version: int
    proposal_id: str
    operations: tuple[PatchOperationV2, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or isinstance(self.schema_version, bool):
            raise ValueError("schema_version must be an int")
        if self.schema_version != 2:
            raise ValueError("schema_version must be 2")
        try:
            validate_proposal_id(self.proposal_id, field_path="proposal_id")
        except ProposalSchemaError:
            raise ValueError("invalid proposal_id")
        if not isinstance(self.operations, tuple):
            raise ValueError("operations must be a tuple")
        op_ids = set()
        targets = set()
        for op in self.operations:
            if not isinstance(
                op,
                (
                    ReplaceManagedBlock,
                    CreateGeneratedFileV2,
                    ReplaceGeneratedFileV2,
                    ReleaseGeneratedOwnershipV2,
                    CreateFile,
                    PatchHumanFile,
                ),
            ):
                raise ValueError("operation is not a valid v2 operation model")
            if op.id in op_ids:
                raise ValueError("duplicate operation id")
            if op.target_path in targets:
                raise ValueError("duplicate target path")
            op_ids.add(op.id)
            targets.add(op.target_path)


AnyPatchDocument = Union[PatchDocument, PatchDocumentV2]


def _validate_path(val: Any, field_path: str, errors: list[PatchSchemaError]) -> str | None:
    if not isinstance(val, str):
        errors.append(PatchSchemaError("invalid_type", field_path, "must be a string"))
        return None
    if not val:
        errors.append(PatchSchemaError("empty_path", field_path, "path must not be empty"))
        return None
    if "\0" in val:
        errors.append(PatchSchemaError("invalid_characters", field_path, "path contains NUL byte"))
        return None
    if "\\" in val:
        errors.append(PatchSchemaError("invalid_separators", field_path, "path contains backslash"))
        return None
    if val.startswith("/"):
        errors.append(PatchSchemaError("absolute_path", field_path, "path must be relative"))
        return None
    if val.startswith("./") or val.endswith("/"):
        errors.append(
            PatchSchemaError(
                "invalid_format", field_path, "path must not have leading ./ or trailing /"
            )
        )
        return None
    if "//" in val:
        errors.append(
            PatchSchemaError("duplicate_separators", field_path, "path contains duplicate /")
        )
        return None

    parts = val.split("/")
    if "" in parts or "." in parts or ".." in parts:
        errors.append(
            PatchSchemaError(
                "invalid_components", field_path, "path contains empty, ., or .. components"
            )
        )
        return None
    if val != posixpath.normpath(val):
        errors.append(PatchSchemaError("not_normalized", field_path, "path is not normalized"))
        return None
    if val.strip() != val:
        errors.append(
            PatchSchemaError(
                "invalid_format", field_path, "path has leading or trailing whitespace"
            )
        )
        return None

    first_part = parts[0]
    if first_part in (".lifeos", ".git", "proposals"):
        errors.append(
            PatchSchemaError(
                "reserved_path", field_path, f"path targets reserved namespace {first_part}"
            )
        )
        return None

    return val


def _validate_hash(val: Any, field_path: str, errors: list[PatchSchemaError]) -> None:
    if not isinstance(val, str):
        errors.append(PatchSchemaError("invalid_type", field_path, "must be a string"))
    elif not HASH_REGEX.match(val):
        errors.append(
            PatchSchemaError("invalid_format", field_path, "must match ^sha256:[a-f0-9]{64}$")
        )


def _validate_identifier(val: Any, field_path: str, errors: list[PatchSchemaError]) -> None:
    if not isinstance(val, str):
        errors.append(PatchSchemaError("invalid_type", field_path, "must be a string"))
    elif not IDENTIFIER_REGEX.match(val):
        errors.append(PatchSchemaError("invalid_format", field_path, "must match identifier regex"))


def _validate_string(val: Any, field_path: str, errors: list[PatchSchemaError]) -> None:
    if not isinstance(val, str):
        errors.append(PatchSchemaError("invalid_type", field_path, "must be a string"))
    elif not val:
        errors.append(PatchSchemaError("empty_string", field_path, "must be a non-empty string"))


def _validate_generator_version_schema(
    val: Any, field_path: str, errors: list[PatchSchemaError]
) -> None:
    if type(val) is not str:
        errors.append(PatchSchemaError("invalid_type", field_path, "must be exactly str"))
        return
    if not (1 <= len(val) <= 64):
        errors.append(
            PatchSchemaError(
                "invalid_format", field_path, "length must be between 1 and 64 characters"
            )
        )
    elif val != val.strip():
        errors.append(
            PatchSchemaError(
                "invalid_format", field_path, "must not have leading or trailing whitespace"
            )
        )
    elif "\0" in val or "\r" in val or "\n" in val:
        errors.append(
            PatchSchemaError("invalid_format", field_path, "must not contain NUL, CR, or LF")
        )
    elif any(ord(c) < 0x20 or ord(c) == 0x7F for c in val):
        errors.append(
            PatchSchemaError(
                "invalid_format", field_path, "must not contain ASCII control characters"
            )
        )


def validate_patch_document(data: Mapping[str, object]) -> AnyPatchDocument:
    errors: list[PatchSchemaError] = []

    if not isinstance(data, dict):
        raise PatchSchemaError("invalid_type", "$", "document must be a JSON object")

    allowed_fields = {"schema_version", "proposal_id", "operations"}
    for k in data:
        if k not in allowed_fields:
            errors.append(PatchSchemaError("unknown_field", str(k), "unknown top-level field"))

    sv = data.get("schema_version")
    if type(sv) is not int or isinstance(sv, bool):
        errors.append(PatchSchemaError("invalid_type", "schema_version", "must be an integer"))
        sv = 1  # Fallback to avoid breaking downstream loop logic
    elif sv not in (1, 2):
        errors.append(PatchSchemaError("unsupported_version", "schema_version", "must be 1 or 2"))

    pid = data.get("proposal_id")
    try:
        validate_proposal_id(pid, field_path="proposal_id")
    except ProposalSchemaError as e:
        errors.append(PatchSchemaError(e.code, e.field_path, e.message))

    ops_data = data.get("operations")
    validated_ops: list[PatchOperation] = []
    seen_op_ids: set[str] = set()
    seen_targets: set[str] = set()

    if not isinstance(ops_data, list):
        errors.append(PatchSchemaError("invalid_type", "operations", "must be a list"))
    else:
        for idx, op_data in enumerate(ops_data):
            op_path = f"operations[{idx}]"
            if not isinstance(op_data, dict):
                errors.append(PatchSchemaError("invalid_type", op_path, "must be an object"))
                continue

            op_type = op_data.get("op")
            if not isinstance(op_type, str):
                errors.append(PatchSchemaError("invalid_type", f"{op_path}.op", "must be a string"))
                continue

            op_id = op_data.get("id")
            if not isinstance(op_id, str):
                errors.append(PatchSchemaError("invalid_type", f"{op_path}.id", "must be a string"))
            elif not OP_ID_REGEX.match(op_id):
                errors.append(
                    PatchSchemaError("invalid_format", f"{op_path}.id", "invalid operation ID")
                )
            elif op_id in seen_op_ids:
                errors.append(
                    PatchSchemaError("duplicate_id", f"{op_path}.id", "operation ID must be unique")
                )
            if isinstance(op_id, str):
                seen_op_ids.add(op_id)

            target = op_data.get("target_path")
            valid_target = _validate_path(target, f"{op_path}.target_path", errors)
            if valid_target:
                if valid_target in seen_targets:
                    errors.append(
                        PatchSchemaError(
                            "duplicate_target",
                            f"{op_path}.target_path",
                            "target path must be unique",
                        )
                    )
                seen_targets.add(valid_target)

            if op_type == "replace_managed_block":
                allowed_op_fields = {
                    "id",
                    "op",
                    "target_path",
                    "base_hash",
                    "block_name",
                    "new_content",
                }
                if valid_target and not valid_target.endswith(".md"):
                    errors.append(
                        PatchSchemaError(
                            "invalid_target",
                            f"{op_path}.target_path",
                            "replace_managed_block requires .md file",
                        )
                    )
                _validate_hash(op_data.get("base_hash"), f"{op_path}.base_hash", errors)
                _validate_identifier(op_data.get("block_name"), f"{op_path}.block_name", errors)
                _validate_string(op_data.get("new_content"), f"{op_path}.new_content", errors)

            elif op_type == "create_generated_file":
                if sv == 1:
                    allowed_op_fields = {
                        "id",
                        "op",
                        "target_path",
                        "expected_target_state",
                        "generator_id",
                        "new_content",
                    }
                else:
                    allowed_op_fields = {
                        "id",
                        "op",
                        "target_path",
                        "expected_target_state",
                        "generator_id",
                        "generator_version",
                        "new_content",
                    }
                if op_data.get("expected_target_state") != "absent":
                    errors.append(
                        PatchSchemaError(
                            "invalid_value", f"{op_path}.expected_target_state", "must be 'absent'"
                        )
                    )
                _validate_identifier(op_data.get("generator_id"), f"{op_path}.generator_id", errors)
                if sv == 2:
                    _validate_generator_version_schema(
                        op_data.get("generator_version"), f"{op_path}.generator_version", errors
                    )
                _validate_string(op_data.get("new_content"), f"{op_path}.new_content", errors)

            elif op_type == "replace_generated_file":
                if sv == 1:
                    allowed_op_fields = {
                        "id",
                        "op",
                        "target_path",
                        "base_hash",
                        "expected_generator_id",
                        "new_content",
                    }
                else:
                    allowed_op_fields = {
                        "id",
                        "op",
                        "target_path",
                        "base_hash",
                        "expected_generator_id",
                        "generator_version",
                        "new_content",
                    }
                _validate_hash(op_data.get("base_hash"), f"{op_path}.base_hash", errors)
                _validate_identifier(
                    op_data.get("expected_generator_id"), f"{op_path}.expected_generator_id", errors
                )
                if sv == 2:
                    _validate_generator_version_schema(
                        op_data.get("generator_version"), f"{op_path}.generator_version", errors
                    )
                _validate_string(op_data.get("new_content"), f"{op_path}.new_content", errors)

            elif op_type == "create_file":
                allowed_op_fields = {
                    "id",
                    "op",
                    "target_path",
                    "expected_target_state",
                    "new_content",
                }
                if op_data.get("expected_target_state") != "absent":
                    errors.append(
                        PatchSchemaError(
                            "invalid_value", f"{op_path}.expected_target_state", "must be 'absent'"
                        )
                    )
                _validate_string(op_data.get("new_content"), f"{op_path}.new_content", errors)

            elif op_type == "patch_human_file":
                allowed_op_fields = {"id", "op", "target_path", "base_hash", "unified_diff"}
                _validate_hash(op_data.get("base_hash"), f"{op_path}.base_hash", errors)
                _validate_string(op_data.get("unified_diff"), f"{op_path}.unified_diff", errors)
            elif op_type == "release_generated_ownership":
                allowed_op_fields = {
                    "id",
                    "op",
                    "target_path",
                    "expected_content_hash",
                    "expected_generator_id",
                    "expected_generator_version",
                    "expected_created_at",
                    "expected_updated_at",
                }
                if sv != 2:
                    errors.append(
                        PatchSchemaError(
                            "unsupported_operation_version",
                            f"{op_path}.op",
                            "release_generated_ownership requires schema version 2",
                        )
                    )
                _validate_hash(
                    op_data.get("expected_content_hash"),
                    f"{op_path}.expected_content_hash",
                    errors,
                )
                _validate_identifier(
                    op_data.get("expected_generator_id"),
                    f"{op_path}.expected_generator_id",
                    errors,
                )
                _validate_generator_version_schema(
                    op_data.get("expected_generator_version"),
                    f"{op_path}.expected_generator_version",
                    errors,
                )
                _validate_string(
                    op_data.get("expected_created_at"),
                    f"{op_path}.expected_created_at",
                    errors,
                )
                _validate_string(
                    op_data.get("expected_updated_at"),
                    f"{op_path}.expected_updated_at",
                    errors,
                )
            else:
                errors.append(
                    PatchSchemaError("unknown_operation", f"{op_path}.op", "unknown operation type")
                )
                continue

            for k in op_data:
                if k not in allowed_op_fields:
                    errors.append(
                        PatchSchemaError(
                            "unknown_field", f"{op_path}.{k}", "unknown operation field"
                        )
                    )

            if any(e.field_path.startswith(op_path) for e in errors):
                continue

            if op_type == "replace_managed_block":
                validated_ops.append(
                    ReplaceManagedBlock(
                        id=str(op_id),
                        target_path=str(target),
                        base_hash=str(op_data["base_hash"]),
                        block_name=str(op_data["block_name"]),
                        new_content=str(op_data["new_content"]),
                    )
                )
            elif op_type == "create_generated_file":
                if sv == 1:
                    validated_ops.append(
                        CreateGeneratedFile(
                            id=str(op_id),
                            target_path=str(target),
                            expected_target_state="absent",
                            generator_id=str(op_data["generator_id"]),
                            new_content=str(op_data["new_content"]),
                        )
                    )
                else:
                    validated_ops.append(
                        CreateGeneratedFileV2(
                            id=str(op_id),
                            target_path=str(target),
                            expected_target_state="absent",
                            generator_id=str(op_data["generator_id"]),
                            generator_version=str(op_data["generator_version"]),
                            new_content=str(op_data["new_content"]),
                        )
                    )
            elif op_type == "replace_generated_file":
                if sv == 1:
                    validated_ops.append(
                        ReplaceGeneratedFile(
                            id=str(op_id),
                            target_path=str(target),
                            base_hash=str(op_data["base_hash"]),
                            expected_generator_id=str(op_data["expected_generator_id"]),
                            new_content=str(op_data["new_content"]),
                        )
                    )
                else:
                    validated_ops.append(
                        ReplaceGeneratedFileV2(
                            id=str(op_id),
                            target_path=str(target),
                            base_hash=str(op_data["base_hash"]),
                            expected_generator_id=str(op_data["expected_generator_id"]),
                            generator_version=str(op_data["generator_version"]),
                            new_content=str(op_data["new_content"]),
                        )
                    )
            elif op_type == "create_file":
                validated_ops.append(
                    CreateFile(
                        id=str(op_id),
                        target_path=str(target),
                        expected_target_state="absent",
                        new_content=str(op_data["new_content"]),
                    )
                )
            elif op_type == "patch_human_file":
                validated_ops.append(
                    PatchHumanFile(
                        id=str(op_id),
                        target_path=str(target),
                        base_hash=str(op_data["base_hash"]),
                        unified_diff=str(op_data["unified_diff"]),
                    )
                )
            elif op_type == "release_generated_ownership":
                validated_ops.append(
                    ReleaseGeneratedOwnershipV2(
                        id=str(op_id),
                        target_path=str(target),
                        expected_content_hash=str(op_data["expected_content_hash"]),
                        expected_generator_id=str(op_data["expected_generator_id"]),
                        expected_generator_version=str(op_data["expected_generator_version"]),
                        expected_created_at=str(op_data["expected_created_at"]),
                        expected_updated_at=str(op_data["expected_updated_at"]),
                    )
                )

    if errors:
        errors.sort(key=lambda e: (e.field_path, e.code, e.message))
        first_error = errors[0]
        first_error.errors = errors
        raise first_error

    if sv == 2:
        return PatchDocumentV2(
            schema_version=2,
            proposal_id=str(data["proposal_id"]),
            operations=tuple(validated_ops),  # type: ignore
        )

    return PatchDocument(
        schema_version=1,
        proposal_id=str(data["proposal_id"]),
        operations=tuple(validated_ops),  # type: ignore
    )


def _serialize_op(op: PatchOperation) -> dict[str, Any]:
    if isinstance(op, ReplaceManagedBlock):
        return {
            "id": op.id,
            "op": op.op,
            "target_path": op.target_path,
            "base_hash": op.base_hash,
            "block_name": op.block_name,
            "new_content": op.new_content,
        }
    elif isinstance(op, CreateGeneratedFile):
        return {
            "id": op.id,
            "op": op.op,
            "target_path": op.target_path,
            "expected_target_state": op.expected_target_state,
            "generator_id": op.generator_id,
            "new_content": op.new_content,
        }
    elif isinstance(op, ReplaceGeneratedFile):
        return {
            "id": op.id,
            "op": op.op,
            "target_path": op.target_path,
            "base_hash": op.base_hash,
            "expected_generator_id": op.expected_generator_id,
            "new_content": op.new_content,
        }
    elif isinstance(op, CreateGeneratedFileV2):
        return {
            "id": op.id,
            "op": op.op,
            "target_path": op.target_path,
            "expected_target_state": op.expected_target_state,
            "generator_id": op.generator_id,
            "generator_version": op.generator_version,
            "new_content": op.new_content,
        }
    elif isinstance(op, ReplaceGeneratedFileV2):
        return {
            "id": op.id,
            "op": op.op,
            "target_path": op.target_path,
            "base_hash": op.base_hash,
            "expected_generator_id": op.expected_generator_id,
            "generator_version": op.generator_version,
            "new_content": op.new_content,
        }
    elif isinstance(op, ReleaseGeneratedOwnershipV2):
        return {
            "id": op.id,
            "op": op.op,
            "target_path": op.target_path,
            "expected_content_hash": op.expected_content_hash,
            "expected_generator_id": op.expected_generator_id,
            "expected_generator_version": op.expected_generator_version,
            "expected_created_at": op.expected_created_at,
            "expected_updated_at": op.expected_updated_at,
        }
    elif isinstance(op, CreateFile):
        return {
            "id": op.id,
            "op": op.op,
            "target_path": op.target_path,
            "expected_target_state": op.expected_target_state,
            "new_content": op.new_content,
        }
    elif isinstance(op, PatchHumanFile):
        return {
            "id": op.id,
            "op": op.op,
            "target_path": op.target_path,
            "base_hash": op.base_hash,
            "unified_diff": op.unified_diff,
        }
    raise AssertionError("Unreachable")


def serialize_patch_document(document: AnyPatchDocument) -> dict[str, Any]:
    return {
        "schema_version": document.schema_version,
        "proposal_id": document.proposal_id,
        "operations": [_serialize_op(op) for op in document.operations],
    }


def serialize_patch_json_bytes(document: AnyPatchDocument) -> bytes:
    dict_repr = serialize_patch_document(document)
    return (
        json.dumps(
            dict_repr,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
