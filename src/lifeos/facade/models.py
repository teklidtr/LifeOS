import re
from dataclasses import dataclass
from enum import Enum

from .errors import ToolValidationError

_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class ToolEffect(str, Enum):
    READ_ONLY = "read_only"
    PROPOSAL_PRODUCING = "proposal_producing"
    CONSEQUENTIAL = "consequential"


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    description: str
    effect: ToolEffect

    def __post_init__(self) -> None:
        if not self.name:
            raise ToolValidationError("name is empty")
        if self.name != self.name.strip():
            raise ToolValidationError("name has surrounding whitespace")
        if not _TOOL_NAME_PATTERN.fullmatch(self.name):
            raise ToolValidationError("name is noncanonical")

        if not self.description:
            raise ToolValidationError("description is empty")
        if self.description != self.description.strip():
            raise ToolValidationError("description has surrounding whitespace")

        if not isinstance(self.effect, ToolEffect):
            raise ToolValidationError("effect must be a ToolEffect instance")
