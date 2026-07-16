from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import AgentRunError, ModelRetry, UnexpectedModelBehavior, UserError
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from lifeos.ai.errors import (
    LifeOSAIModelError,
    LifeOSAIToolError,
    LifeOSAIValidationError,
)
from lifeos.facade.errors import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolUnavailableError,
    ToolValidationError,
)
from lifeos.facade.read_only import ReadMarkdownRequest, read_markdown


@dataclass(frozen=True, slots=True)
class LifeOSAgentDeps:
    vault_root: Path


@dataclass(frozen=True, slots=True)
class LifeOSAgentLimits:
    request_limit: int = 8
    tool_calls_limit: int = 8


OutputT = TypeVar("OutputT")


def _vault_read_markdown(ctx: RunContext[LifeOSAgentDeps], vault_path: str) -> str:
    """Read the Markdown body of a vault-relative file."""
    req = ReadMarkdownRequest(vault_path=vault_path)
    try:
        result = read_markdown(vault_root=ctx.deps.vault_root, request=req)
        return result.markdown_body
    except ToolValidationError as e:
        raise ModelRetry(f"Validation error: {e}") from e
    except ToolNotFoundError as e:
        raise ModelRetry(f"File not found: {e}") from e
    except (ToolExecutionError, ToolUnavailableError) as e:
        # Abort the run immediately using UserError, wrapping our LifeOSAIToolError
        tool_err = LifeOSAIToolError("Tool execution aborted due to unrecoverable error.")
        tool_err.__cause__ = e
        raise UserError("Tool execution aborted") from tool_err


def run_lifeos_agent_sync(
    *,
    model: Model,
    output_type: type[OutputT],
    deps: LifeOSAgentDeps,
    instructions: str,
    user_prompt: str,
    limits: LifeOSAgentLimits | None = None,
) -> OutputT:
    if not isinstance(instructions, str) or not instructions.strip():
        raise LifeOSAIValidationError("Instructions cannot be empty or whitespace.")
    if instructions != instructions.strip():
        raise LifeOSAIValidationError("Instructions must not have surrounding whitespace.")

    if not isinstance(user_prompt, str) or not user_prompt.strip():
        raise LifeOSAIValidationError("User prompt cannot be empty or whitespace.")
    if user_prompt != user_prompt.strip():
        raise LifeOSAIValidationError("User prompt must not have surrounding whitespace.")

    if not isinstance(deps, LifeOSAgentDeps):
        raise LifeOSAIValidationError("Invalid dependency object.")

    if limits is None:
        limits = LifeOSAgentLimits()
    else:
        if not isinstance(limits, LifeOSAgentLimits):
            raise LifeOSAIValidationError("Invalid limits object.")
        if (
            type(limits.request_limit) is not int
            or limits.request_limit <= 0
            or type(limits.tool_calls_limit) is not int
            or limits.tool_calls_limit <= 0
        ):
            raise LifeOSAIValidationError("Limits must be positive integers.")

    usage_limits = UsageLimits(
        request_limit=limits.request_limit,
        tool_calls_limit=limits.tool_calls_limit,
    )

    agent = Agent(
        model=model,
        output_type=output_type,
        deps_type=LifeOSAgentDeps,
        system_prompt=instructions,
        retries=limits.request_limit,
    )
    
    agent.tool(name="vault_read_markdown")(_vault_read_markdown)

    try:
        result = agent.run_sync(
            user_prompt,
            deps=deps,
            usage_limits=usage_limits,
        )
        return result.output
    except AgentRunError as e:
        if isinstance(e.__cause__, LifeOSAIToolError):
            raise e.__cause__
        raise LifeOSAIModelError("AI model execution failed.") from e
    except UnexpectedModelBehavior as e:
        if isinstance(e.__cause__, LifeOSAIToolError):
            raise e.__cause__
        raise LifeOSAIModelError("AI model exhibited unexpected behavior.") from e
    except ValidationError as e:
        raise LifeOSAIValidationError("AI model returned invalid output structure.") from e
    except UserError as e:
        if isinstance(e.__cause__, LifeOSAIToolError):
            raise e.__cause__
        raise
