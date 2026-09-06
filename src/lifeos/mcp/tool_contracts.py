"""Shared FastMCP input and authoritative-output contract adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from types import GenericAlias
from typing import Any, cast, get_args, get_origin, get_type_hints

from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, create_model

_OUTPUT_MODELS: dict[tuple[type[Any], str | None], type[BaseModel]] = {}


def build_mcp_tool(
    fn: Callable[..., object],
    *,
    name: str,
    description: str,
    annotations: ToolAnnotations,
    strict_inputs: bool,
    output_type: type[object] | None = None,
    output_model_name: str | None = None,
) -> Tool:
    """Build one LifeOS MCP tool while preserving family-specific input behavior."""
    if output_type is None and output_model_name is not None:
        raise ValueError("output_model_name requires output_type")

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
        output_model = _mcp_output_model(output_type, model_name=output_model_name)
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
    output_model_name: str | None = None,
) -> dict[str, Any]:
    """Strictly validate a facade result and return its direct-call-compatible JSON mapping."""
    validated = _mcp_output_model(output_type, model_name=output_model_name).model_validate(
        result, strict=True
    )
    return validated.model_dump(mode="json")


def _mcp_output_model(
    result_type: type[Any],
    *,
    model_name: str | None = None,
) -> type[BaseModel]:
    cache_key = (result_type, model_name)
    cached = _OUTPUT_MODELS.get(cache_key)
    if cached is not None:
        return cached
    if not is_dataclass(result_type):
        raise TypeError("authoritative MCP output types must be dataclasses")

    type_hints = get_type_hints(result_type)
    model_fields: dict[str, Any] = {}
    for item in fields(result_type):
        annotation = _mcp_output_annotation(type_hints[item.name])
        if item.default is not MISSING:
            model_fields[item.name] = (annotation, item.default)
        elif item.default_factory is not MISSING:
            model_fields[item.name] = (
                annotation,
                Field(default_factory=item.default_factory),
            )
        else:
            model_fields[item.name] = annotation

    resolved_name = model_name
    if resolved_name is None:
        resolved_name = result_type.__name__
        if resolved_name.endswith("Result"):
            resolved_name = resolved_name[: -len("Result")]
        resolved_name = f"{resolved_name}MCPResult"
    model = cast(
        type[BaseModel],
        create_model(
            resolved_name,
            __config__=ConfigDict(from_attributes=True),
            **model_fields,
        ),
    )
    _OUTPUT_MODELS[cache_key] = model
    return model


def _mcp_output_annotation(annotation: Any) -> Any:
    if isinstance(annotation, type) and is_dataclass(annotation):
        dataclass_type = cast(type[Any], annotation)
        return _mcp_output_model(dataclass_type)

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is tuple and len(arguments) == 2 and arguments[1] is Ellipsis:
        return GenericAlias(tuple, (_mcp_output_annotation(arguments[0]), Ellipsis))
    if origin is list and len(arguments) == 1:
        return GenericAlias(list, (_mcp_output_annotation(arguments[0]),))
    return annotation
