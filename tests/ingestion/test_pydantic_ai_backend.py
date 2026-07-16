import json
import pytest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError

import pydantic_ai
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False

from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402
from pydantic_ai.models.test import TestModel  # noqa: E402

from lifeos.ai.errors import (  # noqa: E402
    LifeOSAIModelError,
    LifeOSAIToolError,
    LifeOSAIValidationError,
)
from lifeos.ingestion.backend import (  # noqa: E402
    AnalysisBackend,
    AnalysisBackendError,
    AnalysisRequest,
    SourceSnapshot,
)
from lifeos.ingestion.pydantic_ai_backend import (  # noqa: E402
    ADAPTER_VERSION,
    GENERATOR_ID,
    PROMPT_SCHEMA_VERSION,
    PydanticAIAnalysisBackend,
    _WikiAnalysisOutput,
)


@pytest.fixture
def dummy_request() -> AnalysisRequest:
    return AnalysisRequest(
        source=SourceSnapshot(
            path="source.md",
            content_hash="sha256:abc",
        ),
        markdown_body="some text",
    )


def test_protocol_compatibility(tmp_path: Path) -> None:
    # Prove static compatibility using a typed assignment
    backend: AnalysisBackend = PydanticAIAnalysisBackend(
        model=TestModel(),
        vault_root=tmp_path,
        model_id=None,
    )
    assert backend is not None


def test_pydantic_ai_backend_happy_path(tmp_path: Path, dummy_request: AnalysisRequest) -> None:
    # Use TestModel with custom output
    model = TestModel(
        custom_output_args={"title": "My Title", "body": "My Body"},
        call_tools=[],
    )
    backend = PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id="gpt-4")

    result = backend.analyze(dummy_request)

    assert result.draft.title == "My Title"
    assert result.draft.body == "My Body"

    assert result.generator.id == GENERATOR_ID
    assert result.generator.version == ADAPTER_VERSION
    assert result.generator.prompt_schema_version == PROMPT_SCHEMA_VERSION
    assert result.generator.model_id == "gpt-4"


def test_model_id_validation_in_constructor(tmp_path: Path) -> None:
    model = TestModel()

    # Valid
    PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id=None)
    PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id="gpt-4")
    PydanticAIAnalysisBackend(model=model, vault_root=tmp_path)

    # Invalid
    with pytest.raises(ValueError, match="empty or whitespace"):
        PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id="")
    with pytest.raises(ValueError, match="empty or whitespace"):
        PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id="  ")
    with pytest.raises(ValueError, match="surrounding whitespace"):
        PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id=" gpt-4 ")


def test_function_model_exact_prompt_and_tool_call(tmp_path: Path, dummy_request: AnalysisRequest) -> None:
    md_file = tmp_path / "reference.md"
    md_file.write_text("Reference content")

    call_count = 0

    def simulate(messages: list[pydantic_ai.messages.ModelMessage], info: AgentInfo) -> pydantic_ai.messages.ModelMessage:
        nonlocal call_count
        call_count += 1

        # Check user prompt
        # messages[0] is ModelRequest, parts[0] is SystemPromptPart, parts[1] is UserPromptPart
        user_prompt_part = messages[0].parts[1]
        assert isinstance(user_prompt_part, pydantic_ai.messages.UserPromptPart)
        if isinstance(user_prompt_part.content, str):
            payload = json.loads(user_prompt_part.content)
            assert payload["source_path"] == "source.md"
            assert payload["content_hash"] == "sha256:abc"
            assert payload["markdown_body"] == "some text"

            # Verify exact deterministic serialization
            expected_json = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            assert user_prompt_part.content == expected_json

        if call_count == 1:
            return pydantic_ai.messages.ModelResponse(
                parts=[pydantic_ai.messages.ToolCallPart(tool_name="vault_read_markdown", args={"vault_path": "reference.md"})]
            )

        # Check tool result
        tool_return = messages[-1].parts[0]
        assert isinstance(tool_return, pydantic_ai.messages.ToolReturnPart)
        assert tool_return.content == "Reference content"

        # Return final valid output
        return pydantic_ai.messages.ModelResponse(
            parts=[
                pydantic_ai.messages.ToolCallPart(
                    tool_name="final_result",
                    args={"title": "Exact Title", "body": "Exact Body"}
                )
            ]
        )

    model = FunctionModel(simulate)
    backend = PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id=None)

    result = backend.analyze(dummy_request)
    assert result.draft.title == "Exact Title"
    assert result.draft.body == "Exact Body"


def test_malformed_output_raises_analysis_backend_error(tmp_path: Path, dummy_request: AnalysisRequest) -> None:
    def simulate(messages: list[pydantic_ai.messages.ModelMessage], info: AgentInfo) -> pydantic_ai.messages.ModelMessage:
        return pydantic_ai.messages.ModelResponse(
            parts=[
                pydantic_ai.messages.ToolCallPart(
                    tool_name="final_result",
                    args={"title": "   ", "body": "Exact Body"} # Invalid title
                )
            ]
        )

    model = FunctionModel(simulate)
    backend = PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id=None)

    with pytest.raises(AnalysisBackendError, match="AI analysis failed"):
        backend.analyze(dummy_request)


@patch("lifeos.ingestion.pydantic_ai_backend.run_lifeos_agent_sync")
def test_core_ai_errors_translated(mock_run: patch, tmp_path: Path, dummy_request: AnalysisRequest) -> None:
    backend = PydanticAIAnalysisBackend(model=TestModel(), vault_root=tmp_path, model_id=None)

    mock_run.side_effect = LifeOSAIValidationError("validation")
    with pytest.raises(AnalysisBackendError) as exc_info:
        backend.analyze(dummy_request)
    assert isinstance(exc_info.value.__cause__, LifeOSAIValidationError)

    mock_run.side_effect = LifeOSAIToolError("tool error")
    with pytest.raises(AnalysisBackendError) as exc_info:
        backend.analyze(dummy_request)
    assert isinstance(exc_info.value.__cause__, LifeOSAIToolError)

    mock_run.side_effect = LifeOSAIModelError("model error")
    with pytest.raises(AnalysisBackendError) as exc_info:
        backend.analyze(dummy_request)
    assert isinstance(exc_info.value.__cause__, LifeOSAIModelError)


def test_arbitrary_programming_errors_propagate(tmp_path: Path, dummy_request: AnalysisRequest) -> None:
    # If the user prompt building fails due to some bizarre object, it propagates
    with pytest.raises(AttributeError):
        # We can't easily break json.dumps without mocking, but we can pass a bad request type
        backend = PydanticAIAnalysisBackend(model=TestModel(), vault_root=tmp_path, model_id=None)
        backend.analyze(None) # type: ignore


def test_no_side_effects(tmp_path: Path, dummy_request: AnalysisRequest) -> None:
    # Set up some files
    file1 = tmp_path / "1.txt"
    file1.write_bytes(b"content")

    model = TestModel(custom_output_args={"title": "T", "body": "B"}, call_tools=[])
    backend = PydanticAIAnalysisBackend(model=model, vault_root=tmp_path, model_id=None)

    backend.analyze(dummy_request)

    # Assert no files changed
    assert file1.read_bytes() == b"content"
    # Assert no new files created in vault_root
    assert list(tmp_path.iterdir()) == [file1]


def test_wiki_analysis_output_validation() -> None:
    # Valid
    _WikiAnalysisOutput(title="A", body="B")

    # Empty title
    with pytest.raises(ValidationError):
        _WikiAnalysisOutput(title="", body="B")

    # Surrounding whitespace in title
    with pytest.raises(ValidationError, match="surrounding whitespace"):
        _WikiAnalysisOutput(title=" A ", body="B")

    # Empty body
    with pytest.raises(ValidationError):
        _WikiAnalysisOutput(title="A", body="   ")
