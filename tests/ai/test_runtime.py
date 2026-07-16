import pytest
from pathlib import Path

from pydantic import BaseModel

import pydantic_ai
# Disable real network requests globally for safety
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False

from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402
from pydantic_ai.models.test import TestModel  # noqa: E402

from lifeos.ai.errors import (  # noqa: E402
    LifeOSAIToolError,
    LifeOSAIValidationError,
)
from lifeos.ai.runtime import (  # noqa: E402
    LifeOSAgentDeps,
    LifeOSAgentLimits,
    run_lifeos_agent_sync,
)


class MyOutput(BaseModel):
    name: str


def test_runtime_type_returns(tmp_path: Path) -> None:
    model = TestModel(custom_output_args={"name": "Alice"}, call_tools=[])
    deps = LifeOSAgentDeps(vault_root=tmp_path)
    
    result = run_lifeos_agent_sync(
        model=model,
        output_type=MyOutput,
        deps=deps,
        instructions="Say hello.",
        user_prompt="Hello",
    )
    
    assert isinstance(result, MyOutput)
    assert result.name == "Alice"


def test_runtime_input_validation(tmp_path: Path) -> None:
    model = TestModel(call_tools=[])
    deps = LifeOSAgentDeps(vault_root=tmp_path)
    
    with pytest.raises(LifeOSAIValidationError, match="Instructions cannot be empty"):
        run_lifeos_agent_sync(model=model, output_type=str, deps=deps, instructions="", user_prompt="hi")
        
    with pytest.raises(LifeOSAIValidationError, match="Instructions must not have surrounding"):
        run_lifeos_agent_sync(model=model, output_type=str, deps=deps, instructions=" hi ", user_prompt="hi")
        
    with pytest.raises(LifeOSAIValidationError, match="User prompt cannot be empty"):
        run_lifeos_agent_sync(model=model, output_type=str, deps=deps, instructions="hi", user_prompt="")

    with pytest.raises(LifeOSAIValidationError, match="Invalid dependency object"):
        run_lifeos_agent_sync(model=model, output_type=str, deps="bad", instructions="hi", user_prompt="hi") # type: ignore


def test_tool_delegation_and_registration(tmp_path: Path) -> None:
    # Setup vault
    md_file = tmp_path / "a.md"
    md_file.write_text("Hello World", encoding="utf-8")
    
    deps = LifeOSAgentDeps(vault_root=tmp_path)
    
    call_count = 0
    def simulate(messages: list[pydantic_ai.messages.ModelMessage], info: AgentInfo) -> pydantic_ai.messages.ModelMessage:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Request tool call
            return pydantic_ai.messages.ModelResponse(
                parts=[pydantic_ai.messages.ToolCallPart(tool_name="vault_read_markdown", args={"vault_path": "a.md"})]
            )
        # Check that tool result is in messages
        assert isinstance(messages[-1].parts[0], pydantic_ai.messages.ToolReturnPart)
        assert messages[-1].parts[0].content == "Hello World"
        return pydantic_ai.messages.ModelResponse(parts=[pydantic_ai.messages.TextPart("Done")])

    model = FunctionModel(simulate)
    result = run_lifeos_agent_sync(model=model, output_type=str, deps=deps, instructions="i", user_prompt="u")
    assert result == "Done"


def test_tool_retry_and_error_behavior(tmp_path: Path) -> None:
    deps = LifeOSAgentDeps(vault_root=tmp_path)
    
    call_count = 0
    def simulate(messages: list[pydantic_ai.messages.ModelMessage], info: AgentInfo) -> pydantic_ai.messages.ModelMessage:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return pydantic_ai.messages.ModelResponse(
                parts=[pydantic_ai.messages.ToolCallPart(tool_name="vault_read_markdown", args={"vault_path": "missing.md"})]
            )
        # Should get a ModelRetry return
        assert isinstance(messages[-1].parts[0], pydantic_ai.messages.RetryPromptPart)
        return pydantic_ai.messages.ModelResponse(parts=[pydantic_ai.messages.TextPart("Recovered")])
        
    model = FunctionModel(simulate)
    result = run_lifeos_agent_sync(model=model, output_type=str, deps=deps, instructions="i", user_prompt="u")
    assert result == "Recovered"

def test_fatal_tool_error_aborts_run(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    target.mkdir()
    
    deps = LifeOSAgentDeps(vault_root=tmp_path)
    
    def simulate(messages: list[pydantic_ai.messages.ModelMessage], info: AgentInfo) -> pydantic_ai.messages.ModelMessage:
        return pydantic_ai.messages.ModelResponse(
            parts=[pydantic_ai.messages.ToolCallPart(tool_name="vault_read_markdown", args={"vault_path": "a.md"})]
        )
        
    model = FunctionModel(simulate)
    
    with pytest.raises(LifeOSAIToolError):
        run_lifeos_agent_sync(model=model, output_type=str, deps=deps, instructions="i", user_prompt="u")


@pytest.mark.parametrize(
    "limits",
    [
        LifeOSAgentLimits(request_limit=True, tool_calls_limit=1),  # type: ignore[arg-type]
        LifeOSAgentLimits(request_limit=1, tool_calls_limit=False),  # type: ignore[arg-type]
        LifeOSAgentLimits(request_limit=1.5, tool_calls_limit=1),  # type: ignore[arg-type]
        LifeOSAgentLimits(request_limit=1, tool_calls_limit=2.5),  # type: ignore[arg-type]
    ],
)
def test_runtime_rejects_non_integer_limits(
    tmp_path: Path,
    limits: LifeOSAgentLimits,
) -> None:
    model = TestModel(call_tools=[])

    with pytest.raises(LifeOSAIValidationError, match="positive integers"):
        run_lifeos_agent_sync(
            model=model,
            output_type=str,
            deps=LifeOSAgentDeps(vault_root=tmp_path),
            instructions="i",
            user_prompt="u",
            limits=limits,
        )
