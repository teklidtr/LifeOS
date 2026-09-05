import pytest

from lifeos.bridge.protocol import CAPABILITIES
from lifeos.capabilities import (
    CAPABILITY_REGISTRY,
    CapabilityBackingReference,
    CapabilityDefinitionError,
    CapabilityRegistry,
    CapabilityVisibility,
    SemanticCapability,
)
from lifeos.capability_coverage import validate_capability_coverage


def _capability(
    *,
    capability_id: str = "example.feature",
    visibility: CapabilityVisibility = "explore",
    description: str = "A concrete LifeOS capability used by the discoverability audit.",
    bridge_method: str = "example.run",
) -> SemanticCapability:
    return SemanticCapability(
        capability_id=capability_id,
        name="Example feature",
        description=description,
        category="Example",
        visibility=visibility,
        maturity="stable",
        backing=(CapabilityBackingReference("bridge_method", bridge_method),),
    )


def test_repository_desktop_protocol_has_semantic_capability_coverage() -> None:
    validate_capability_coverage(CAPABILITY_REGISTRY, CAPABILITIES)


def test_orphan_desktop_bridge_method_fails_coverage() -> None:
    registry = CapabilityRegistry((_capability(),))

    with pytest.raises(CapabilityDefinitionError, match="orphan.run"):
        validate_capability_coverage(registry, {"example.run", "orphan.run"})


def test_semantically_covered_desktop_bridge_method_passes_coverage() -> None:
    registry = CapabilityRegistry((_capability(),))

    validate_capability_coverage(registry, {"example.run"})


def test_internal_method_with_reviewable_rationale_passes_coverage() -> None:
    registry = CapabilityRegistry(
        (
            _capability(
                capability_id="system.example-runtime",
                visibility="internal",
                description=(
                    "Low-level runtime plumbing used by first-party workflows rather than "
                    "an independently discoverable user ability."
                ),
            ),
        )
    )

    validate_capability_coverage(registry, {"example.run"})


def test_explore_prompt_only_capability_fails_registry_validation() -> None:
    prompt_only = SemanticCapability(
        capability_id="example.prompt-only",
        name="Prompt only",
        description="Teaching text without concrete LifeOS implementation backing.",
        category="Example",
        visibility="explore",
        maturity="stable",
        backing=(),
        example_prompts=("Ask a generic model to do something.",),
    )

    with pytest.raises(CapabilityDefinitionError, match="must declare implementation backing"):
        CapabilityRegistry((prompt_only,))
