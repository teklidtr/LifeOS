import sys
from dataclasses import FrozenInstanceError

import pytest

from lifeos.facade import (
    ToolAuthorizationError,
    ToolConflictError,
    ToolDescriptor,
    ToolEffect,
    ToolExecutionError,
    ToolFacadeError,
    ToolNotFoundError,
    ToolUnavailableError,
    ToolValidationError,
)
from lifeos.facade import models


def test_tool_effect_values() -> None:
    assert ToolEffect.READ_ONLY == "read_only"
    assert ToolEffect.DERIVED_WRITE == "derived_write"
    assert ToolEffect.PROPOSAL_PRODUCING == "proposal_producing"
    assert ToolEffect.CONSEQUENTIAL == "consequential"


def test_tool_descriptor_frozen() -> None:
    descriptor = ToolDescriptor(
        name="test_tool",
        description="A test tool",
        effect=ToolEffect.READ_ONLY,
    )
    with pytest.raises(FrozenInstanceError):
        descriptor.name = "changed"  # type: ignore


def test_tool_descriptor_uses_slots() -> None:
    descriptor = ToolDescriptor(
        name="test_tool",
        description="A test tool",
        effect=ToolEffect.READ_ONLY,
    )
    assert not hasattr(descriptor, "__dict__")
    assert hasattr(descriptor, "__slots__")


def test_valid_descriptor_constructs() -> None:
    descriptor = ToolDescriptor(
        name="my.tool",
        description="Does something",
        effect=ToolEffect.READ_ONLY,
    )
    assert descriptor.name == "my.tool"
    assert descriptor.description == "Does something"
    assert descriptor.effect == ToolEffect.READ_ONLY


def test_descriptor_empty_name_rejected() -> None:
    with pytest.raises(ToolValidationError, match="name is empty"):
        ToolDescriptor(name="", description="valid", effect=ToolEffect.READ_ONLY)


def test_descriptor_whitespace_only_name_rejected() -> None:
    with pytest.raises(ToolValidationError, match="name has surrounding whitespace"):
        ToolDescriptor(name="   ", description="valid", effect=ToolEffect.READ_ONLY)


def test_descriptor_noncanonical_name_rejected() -> None:
    bad_names = [
        "InvalidName",       # uppercase
        "1tool",             # starts with digit
        "notes..read",       # consecutive dots
        "notes.",            # trailing dot
        ".notes",            # leading dot
        "notes-read",        # hyphen
        "notes._",           # dot then underscore without letter
        "notes.2read",       # segment starts with digit
        "notes read",        # space
    ]
    for bad in bad_names:
        with pytest.raises(ToolValidationError, match="name is noncanonical"):
            ToolDescriptor(name=bad, description="valid", effect=ToolEffect.READ_ONLY)


def test_valid_snake_case_segment_accepted() -> None:
    descriptor = ToolDescriptor(name="my_valid_tool", description="valid", effect=ToolEffect.READ_ONLY)
    assert descriptor.name == "my_valid_tool"


def test_descriptor_empty_description_rejected() -> None:
    with pytest.raises(ToolValidationError, match="description is empty"):
        ToolDescriptor(name="valid_tool", description="", effect=ToolEffect.READ_ONLY)


def test_descriptor_whitespace_only_description_rejected() -> None:
    with pytest.raises(ToolValidationError, match="description has surrounding whitespace"):
        ToolDescriptor(name="valid_tool", description="   ", effect=ToolEffect.READ_ONLY)


def test_descriptor_raw_string_effect_rejected() -> None:
    with pytest.raises(ToolValidationError, match="effect must be a ToolEffect instance"):
        ToolDescriptor(name="valid", description="valid", effect="read_only")  # type: ignore


def test_descriptor_unrelated_effect_rejected() -> None:
    with pytest.raises(ToolValidationError, match="effect must be a ToolEffect instance"):
        ToolDescriptor(name="valid", description="valid", effect=123)  # type: ignore


def test_facade_errors_inherit_base() -> None:
    errors = [
        ToolValidationError,
        ToolNotFoundError,
        ToolConflictError,
        ToolUnavailableError,
        ToolAuthorizationError,
        ToolExecutionError,
    ]
    for error_cls in errors:
        assert issubclass(error_cls, ToolFacadeError)


def test_error_classes_preserve_cause() -> None:
    cause = ValueError("Original error")
    try:
        raise ToolValidationError("Validation failed") from cause
    except ToolValidationError as e:
        assert e.__cause__ is cause


def test_no_pydantic_imports() -> None:
    import pathlib

    facade_dir = pathlib.Path(__file__).parent.parent.parent / "src" / "lifeos" / "facade"
    for py_file in facade_dir.glob("*.py"):
        content = py_file.read_text()
        assert "pydantic" not in content.lower()
        assert "openai" not in content.lower()
        assert "anthropic" not in content.lower()


def test_no_forbidden_module_imports() -> None:
    # Ensure 'sqlite3' and 'os' are not imported in models.py (or we can just check globals)
    assert "sqlite3" not in sys.modules or "sqlite3" not in dir(models)
    assert "os" not in sys.modules or "os" not in dir(models)
