"""Shared FastMCP input and authoritative-output contract adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from functools import lru_cache
from typing import Any, cast, get_args, get_origin, get_type_hints

from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, create_model


def build_mcp_tool(
    fn: Callable[..., object],
    *,
    name: str,
    description: str,
    annotations: ToolAnnotations,
    strict_inputs: bool,
    output_type: type[object] | None = None,
) -> Tool:
    """Build one LifeOS MCP tool while preserving family-specific input behavior."""
    tool = Tool.from_function(
        fn,
        name=name,
        description=description,
        annotations=annotations,
        structured_output=False if output_type is not None else None,
    )
    base_model = tool.fn_metadata.arg_model
    model_config = (
        ConfigDict(arbitrary_types_allowed=True, extra="forbid", strict=True)
        if strict_inputs
        else ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    )
    input_model = cast(
        type[BaseModel],
        type(
            f"Strict{base_model.__name__}",
            (base_model,),
            {"model_config": model_config},
        ),
    )
    input_model.model_rebuild()

    metadata_updates: dict[str, object] = {"arg_model": input_model}
    if output_type is not None:
        output_model = _mcp_output_model(output_type)
        metadata_updates.update(
            output_model=output_model,
            output_schema=output_model.model_json_schema(),
            wrap_output=False,
        )

    metadata = tool.fn_metadata.model_copy(update=metadata_updates)
    return tool.model_copy(
        update={
            "fn_metadata": metadata,
            "parameters": input_model.model_json_schema(by_alias=True),
        }
    )


def serialize_authoritative_output(
    result: object,
    *,
    output_type: type[object],
) -> dict[str, Any]:
    """Validate a facade result deeply and return its direct-call-compatible JSON mapping."""
    validated = _mcp_output_model(output_type).model_validate(result)
    return cast(dict[str, Any], validated.model_dump(mode="json"))


@lru_cache(maxsize=None)
def _mcp_output_model(result_type: type[object]) -> type[BaseModel]:
    if not is_dataclass(result_type):
        raise TypeError("authoritative MCP output types must be dataclasses")

    type_hints = get_type_hints(result_type)
    model_fields: dict[str, Any] = {}
    for item in fields(result_type):
        annotation = _mcp_output_annotation(type_hints[item.name])
        if item.default is not MISSING:
            model_fields[item.name] = (annotation, item.default)
        elif item.default_factory is not MISSING:
            default_factory = cast(Callable[[], Any], item.default_factory)
            model_fields[item.name] = (
                annotation,
                Field(default_factory=default_factory),
            )
        else:
            model_fields[item.name] = annotation

    name = result_type.__name__
    if name.endswith("Result"):
        name = name[: -len("Result")]
    return create_model(
        f"{name}MCPResult",
        __config__=ConfigDict(from_attributes=True),
        **model_fields,
    )


def _mcp_output_annotation(annotation: Any) -> Any:
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _mcp_output_model(cast(type[object], annotation))

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is tuple and len(arguments) == 2 and arguments[1] is Ellipsis:
        return tuple[_mcp_output_annotation(arguments[0]), ...]
    if origin is list and len(arguments) == 1:
        return list[_mcp_output_annotation(arguments[0])]
    return annotation
