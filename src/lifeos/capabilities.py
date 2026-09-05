"""Python-owned semantic capability metadata for user-facing discovery surfaces."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
import re
from typing import Literal

CapabilityVisibility = Literal["explore", "internal"]
CapabilityMaturity = Literal["stable", "beta", "experimental"]
CapabilityBackingKind = Literal["bridge_method", "workflow", "data_source"]
CapabilityEntryPointKind = Literal[
    "obsidian_command",
    "obsidian_view",
    "cli",
    "mcp_tool",
    "workflow",
]

SEMANTIC_CAPABILITY_SCHEMA_VERSION = 1

_ALLOWED_VISIBILITY = frozenset({"explore", "internal"})
_ALLOWED_MATURITY = frozenset({"stable", "beta", "experimental"})
_ALLOWED_BACKING_KINDS = frozenset({"bridge_method", "workflow", "data_source"})
_ALLOWED_ENTRY_POINT_KINDS = frozenset(
    {"obsidian_command", "obsidian_view", "cli", "mcp_tool", "workflow"}
)
_CAPABILITY_ID = re.compile(
    r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)*$"
)
_BRIDGE_METHOD = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")


class CapabilityDefinitionError(ValueError):
    """Raised when semantic capability metadata violates the registry contract."""


@dataclass(frozen=True, slots=True)
class CapabilityBackingReference:
    """Concrete LifeOS machinery that materially implements a semantic capability."""

    kind: CapabilityBackingKind
    ref: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "ref": self.ref}


@dataclass(frozen=True, slots=True)
class CapabilityEntryPoint:
    """Direct user entry point for a capability when one exists."""

    kind: CapabilityEntryPointKind
    target: str
    label: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"kind": self.kind, "target": self.target, "label": self.label}


@dataclass(frozen=True, slots=True)
class SemanticCapability:
    """Stable metadata describing one composed LifeOS capability."""

    capability_id: str
    name: str
    description: str
    category: str
    visibility: CapabilityVisibility
    maturity: CapabilityMaturity
    requirements: tuple[str, ...] = ()
    backing: tuple[CapabilityBackingReference, ...] = ()
    entry_points: tuple[CapabilityEntryPoint, ...] = ()
    example_prompts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "visibility": self.visibility,
            "maturity": self.maturity,
            "requirements": list(self.requirements),
            "backing": [item.to_dict() for item in self.backing],
            "entry_points": [item.to_dict() for item in self.entry_points],
            "example_prompts": list(self.example_prompts),
        }


class CapabilityRegistry:
    """Validated, deterministic in-process registry of semantic capabilities."""

    __slots__ = ("_by_id", "_capabilities")

    def __init__(self, definitions: Iterable[SemanticCapability]) -> None:
        capabilities = tuple(definitions)
        seen: set[str] = set()
        for capability in capabilities:
            self._validate_capability(capability)
            if capability.capability_id in seen:
                raise CapabilityDefinitionError(
                    f"Duplicate capability ID: {capability.capability_id}"
                )
            seen.add(capability.capability_id)
        self._capabilities = tuple(sorted(capabilities, key=lambda item: item.capability_id))
        self._by_id = {item.capability_id: item for item in self._capabilities}

    def list_capabilities(self) -> tuple[SemanticCapability, ...]:
        return self._capabilities

    def get(self, capability_id: str) -> SemanticCapability | None:
        return self._by_id.get(capability_id)

    def validate_bridge_methods(self, known_methods: Collection[str]) -> None:
        """Fail if any declared bridge-method backing reference is not implemented."""

        available = frozenset(known_methods)
        for capability in self._capabilities:
            for reference in capability.backing:
                if reference.kind == "bridge_method" and reference.ref not in available:
                    raise CapabilityDefinitionError(
                        f"Capability {capability.capability_id} references unknown bridge method "
                        f"{reference.ref}"
                    )

    @classmethod
    def _validate_capability(cls, capability: object) -> None:
        if not isinstance(capability, SemanticCapability):
            raise CapabilityDefinitionError(
                "Capability registry entries must be SemanticCapability instances"
            )
        if (
            not isinstance(capability.capability_id, str)
            or not _CAPABILITY_ID.fullmatch(capability.capability_id)
        ):
            raise CapabilityDefinitionError(
                f"Invalid capability ID: {capability.capability_id!r}"
            )
        cls._require_text(capability.name, "name", capability.capability_id)
        cls._require_text(capability.description, "description", capability.capability_id)
        cls._require_text(capability.category, "category", capability.capability_id)
        if (
            not isinstance(capability.visibility, str)
            or capability.visibility not in _ALLOWED_VISIBILITY
        ):
            raise CapabilityDefinitionError(
                f"Invalid visibility for {capability.capability_id}: {capability.visibility!r}"
            )
        if (
            not isinstance(capability.maturity, str)
            or capability.maturity not in _ALLOWED_MATURITY
        ):
            raise CapabilityDefinitionError(
                f"Invalid maturity for {capability.capability_id}: {capability.maturity!r}"
            )
        if not isinstance(capability.requirements, tuple):
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} requirements must be a tuple"
            )
        if not isinstance(capability.backing, tuple) or not all(
            isinstance(item, CapabilityBackingReference) for item in capability.backing
        ):
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} backing must contain backing references"
            )
        if not isinstance(capability.entry_points, tuple) or not all(
            isinstance(item, CapabilityEntryPoint) for item in capability.entry_points
        ):
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} entry_points must contain entry points"
            )
        if not isinstance(capability.example_prompts, tuple):
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} example_prompts must be a tuple"
            )
        if not capability.backing:
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} must declare implementation backing"
            )

        cls._validate_string_items(
            capability.requirements, "requirement", capability.capability_id
        )
        cls._validate_string_items(
            capability.example_prompts, "example prompt", capability.capability_id
        )

        backing_seen: set[tuple[str, str]] = set()
        for reference in capability.backing:
            if not isinstance(reference.kind, str) or reference.kind not in _ALLOWED_BACKING_KINDS:
                raise CapabilityDefinitionError(
                    f"Invalid backing kind for {capability.capability_id}: {reference.kind!r}"
                )
            cls._require_identifier(reference.ref, "backing reference", capability.capability_id)
            if reference.kind == "bridge_method" and not _BRIDGE_METHOD.fullmatch(reference.ref):
                raise CapabilityDefinitionError(
                    f"Malformed bridge method for {capability.capability_id}: {reference.ref!r}"
                )
            key = (reference.kind, reference.ref)
            if key in backing_seen:
                raise CapabilityDefinitionError(
                    f"Duplicate backing reference for {capability.capability_id}: {reference.ref}"
                )
            backing_seen.add(key)

        entry_seen: set[tuple[str, str]] = set()
        for entry_point in capability.entry_points:
            if (
                not isinstance(entry_point.kind, str)
                or entry_point.kind not in _ALLOWED_ENTRY_POINT_KINDS
            ):
                raise CapabilityDefinitionError(
                    f"Invalid entry-point kind for {capability.capability_id}: {entry_point.kind!r}"
                )
            cls._require_identifier(
                entry_point.target, "entry-point target", capability.capability_id
            )
            if entry_point.label is not None:
                cls._require_text(entry_point.label, "entry-point label", capability.capability_id)
            key = (entry_point.kind, entry_point.target)
            if key in entry_seen:
                raise CapabilityDefinitionError(
                    f"Duplicate entry point for {capability.capability_id}: {entry_point.target}"
                )
            entry_seen.add(key)

    @staticmethod
    def _require_text(value: object, field: str, capability_id: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise CapabilityDefinitionError(
                f"Capability {capability_id} has an empty {field}"
            )

    @staticmethod
    def _require_identifier(value: object, field: str, capability_id: str) -> None:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(character.isspace() or ord(character) < 32 for character in value)
        ):
            raise CapabilityDefinitionError(
                f"Capability {capability_id} has a malformed {field}: {value!r}"
            )

    @classmethod
    def _validate_string_items(
        cls, values: tuple[str, ...], field: str, capability_id: str
    ) -> None:
        seen: set[str] = set()
        for value in values:
            cls._require_text(value, field, capability_id)
            if value in seen:
                raise CapabilityDefinitionError(
                    f"Capability {capability_id} has a duplicate {field}: {value!r}"
                )
            seen.add(value)


CAPABILITY_REGISTRY = CapabilityRegistry(
    (
        SemanticCapability(
            capability_id="system.capability-discovery",
            name="Capability discovery",
            description=(
                "Provides machine-readable semantic capability metadata to first-party "
                "LifeOS discovery surfaces."
            ),
            category="System",
            visibility="internal",
            maturity="stable",
            backing=(
                CapabilityBackingReference("bridge_method", "capability.list"),
                CapabilityBackingReference("bridge_method", "capability.get"),
            ),
        ),
    )
)
