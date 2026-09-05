"""Deterministic coverage audit for desktop protocol capability discoverability."""

from __future__ import annotations

from collections.abc import Collection

from lifeos.capabilities import CapabilityDefinitionError, CapabilityRegistry


def validate_capability_coverage(
    registry: CapabilityRegistry,
    protocol_methods: Collection[str],
) -> None:
    """Require every desktop bridge method to have reviewed semantic ownership.

    Registry construction already requires non-empty descriptions and concrete backing.
    For ``visibility="internal"`` entries, that description is the reviewable rationale for
    keeping the grouped bridge behavior out of Explore.
    """

    methods = frozenset(protocol_methods)
    registry.validate_bridge_methods(methods)

    covered_methods = {
        reference.ref
        for capability in registry.list_capabilities()
        for reference in capability.backing
        if reference.kind == "bridge_method"
    }
    orphaned_methods = sorted(methods - covered_methods)
    if orphaned_methods:
        joined = ", ".join(orphaned_methods)
        raise CapabilityDefinitionError(
            f"Desktop bridge methods missing semantic capability coverage: {joined}"
        )
