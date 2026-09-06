from dataclasses import replace
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient
from lifeos.bridge.protocol import CAPABILITIES
from lifeos.capabilities import (
    CAPABILITY_REGISTRY,
    CapabilityBackingReference,
    CapabilityDefinitionError,
    CapabilityEntryPoint,
    CapabilityRegistry,
    SemanticCapability,
)

_EXPLORE_CAPABILITY_IDS = {
    "capture.rich-capture",
    "change.proposal-review",
    "experiments.personal-experiments",
    "knowledge.conversations",
    "knowledge.evidence-grounded-research",
    "knowledge.graph-views",
    "knowledge.semantic-retrieval",
    "knowledge.vault-exploration",
    "knowledge.wiki-evolution",
    "observation.pattern-analysis",
    "personal-model.evidence-backed-reflection",
    "planning.adaptive-feedback",
    "planning.goal-to-plan",
    "planning.today",
    "reflection.reviews",
    "sharing.purpose-specific-exports",
    "study.learning-evolution",
    "study.review-sessions",
    "system.health-diagnostics",
    "system.home-node-service",
    "system.vault-setup",
}

_INTERNAL_CAPABILITY_IDS = {
    "capture.maintenance",
    "experiments.maintenance",
    "knowledge.ingestion-compatibility",
    "knowledge.retrieval-maintenance",
    "personal-model.maintenance",
    "planning.feedback-maintenance",
    "reflection.review-maintenance",
    "system.capability-discovery",
    "system.desktop-runtime",
    "system.registry-maintenance",
    "system.scheduler-runtime",
}


def _capability(capability_id: str = "planning.today") -> SemanticCapability:
    return SemanticCapability(
        capability_id=capability_id,
        name="Plan today",
        description="Builds a bounded LifeOS today menu from canonical planning data.",
        category="Planning",
        visibility="explore",
        maturity="stable",
        requirements=("A configured LifeOS vault",),
        backing=(CapabilityBackingReference("bridge_method", "today.get"),),
        entry_points=(CapabilityEntryPoint("obsidian_view", "lifeos-today", "Open Today"),),
        example_prompts=("What should I focus on today in LifeOS?",),
    )


def test_registry_serializes_stable_shape_in_deterministic_id_order() -> None:
    registry = CapabilityRegistry((_capability("zeta.feature"), _capability("alpha.feature")))

    serialized = [item.to_dict() for item in registry.list_capabilities()]

    assert [item["id"] for item in serialized] == ["alpha.feature", "zeta.feature"]
    assert serialized[0] == {
        "id": "alpha.feature",
        "name": "Plan today",
        "description": "Builds a bounded LifeOS today menu from canonical planning data.",
        "category": "Planning",
        "visibility": "explore",
        "maturity": "stable",
        "requirements": ["A configured LifeOS vault"],
        "backing": [{"kind": "bridge_method", "ref": "today.get"}],
        "entry_points": [
            {"kind": "obsidian_view", "target": "lifeos-today", "label": "Open Today"}
        ],
        "example_prompts": ["What should I focus on today in LifeOS?"],
    }


def test_registry_rejects_duplicate_ids_and_invalid_enums() -> None:
    capability = _capability()
    with pytest.raises(CapabilityDefinitionError, match="Duplicate capability ID"):
        CapabilityRegistry((capability, capability))

    with pytest.raises(CapabilityDefinitionError, match="Invalid visibility"):
        CapabilityRegistry((replace(capability, visibility="hidden"),))  # type: ignore[arg-type]

    with pytest.raises(CapabilityDefinitionError, match="Invalid maturity"):
        CapabilityRegistry((replace(capability, maturity="preview"),))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("name", "empty name"),
        ("description", "empty description"),
        ("category", "empty category"),
    ),
)
def test_registry_rejects_missing_required_metadata(field: str, message: str) -> None:
    capability = _capability()

    with pytest.raises(CapabilityDefinitionError, match=message):
        CapabilityRegistry((replace(capability, **{field: "   "}),))


def test_registry_rejects_malformed_runtime_shapes_deterministically() -> None:
    capability = _capability()

    with pytest.raises(CapabilityDefinitionError, match="requirements must be a tuple"):
        CapabilityRegistry(
            (replace(capability, requirements=["configured"]),)  # type: ignore[arg-type]
        )

    with pytest.raises(CapabilityDefinitionError, match="backing must contain backing references"):
        CapabilityRegistry((replace(capability, backing=("today.get",)),))  # type: ignore[arg-type]


def test_registry_requires_concrete_valid_backing_not_only_example_prompts() -> None:
    capability = _capability()
    with pytest.raises(CapabilityDefinitionError, match="must declare implementation backing"):
        CapabilityRegistry((replace(capability, backing=()),))

    malformed = replace(
        capability,
        backing=(CapabilityBackingReference("bridge_method", "today get"),),
    )
    with pytest.raises(CapabilityDefinitionError, match="malformed backing reference"):
        CapabilityRegistry((malformed,))


def test_registry_can_validate_bridge_references_against_protocol_methods() -> None:
    registry = CapabilityRegistry((_capability(),))
    registry.validate_bridge_methods({"today.get", "system.health"})

    with pytest.raises(CapabilityDefinitionError, match="unknown bridge method today.get"):
        registry.validate_bridge_methods({"system.health"})


def test_baseline_inventory_covers_audited_feature_families_and_bridge_methods() -> None:
    capabilities = CAPABILITY_REGISTRY.list_capabilities()
    ids = [capability.capability_id for capability in capabilities]
    explore = {
        capability.capability_id: capability
        for capability in capabilities
        if capability.visibility == "explore"
    }
    internal = {
        capability.capability_id: capability
        for capability in capabilities
        if capability.visibility == "internal"
    }

    assert len(ids) == len(set(ids))
    assert set(explore) == _EXPLORE_CAPABILITY_IDS
    assert set(internal) == _INTERNAL_CAPABILITY_IDS
    CAPABILITY_REGISTRY.validate_bridge_methods(CAPABILITIES)

    bridge_owners: dict[str, SemanticCapability] = {}
    for capability in capabilities:
        for reference in capability.backing:
            if reference.kind != "bridge_method":
                continue
            assert reference.ref not in bridge_owners
            bridge_owners[reference.ref] = capability

    # Keep the audited baseline inventory shape reviewable. Future protocol additions are
    # enforced by tests/project/test_capability_discoverability.py.
    assert len(bridge_owners) == 148
    assert bridge_owners["today.get"].visibility == "explore"
    assert bridge_owners["capture.enrichment.run"].visibility == "explore"
    assert bridge_owners["retrieval.index.rebuild"].visibility == "internal"
    assert bridge_owners["review.artifact.migration.apply"].visibility == "internal"

    for capability in explore.values():
        assert capability.name.strip()
        assert capability.description.strip()
        assert capability.category.strip()
        assert capability.maturity in {"stable", "beta", "experimental"}
        assert capability.backing

    graph_requirements = explore["knowledge.graph-views"].requirements
    export_requirements = explore["sharing.purpose-specific-exports"].requirements
    home_node_requirements = explore["system.home-node-service"].requirements
    assert any("features.graphify" in requirement for requirement in graph_requirements)
    assert any("features.exports" in requirement for requirement in export_requirements)
    assert any("configuration" in requirement.lower() for requirement in home_node_requirements)
    assert any("--actor-id" in requirement for requirement in home_node_requirements)
    assert any(
        "LIFEOS_SERVICE_TOKEN" in requirement and "LIFEOS_SERVICE_TOKEN_FILE" in requirement
        for requirement in home_node_requirements
    )


def _bridge(tmp_path: Path) -> BridgeApplication:
    vault = tmp_path / "vault"
    vault.mkdir()
    return BridgeApplication(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        actor_id="tester",
    )


def test_bridge_lists_and_gets_semantic_capabilities_without_repurposing_handshake(
    tmp_path: Path,
) -> None:
    bridge = _bridge(tmp_path)
    client = ReferenceBridgeClient(bridge)
    before = tuple(
        sorted(
            path.relative_to(bridge.daily.vault_root) for path in bridge.daily.vault_root.rglob("*")
        )
    )

    handshake = client.call("system.handshake", protocol="1.0")
    listing = client.call("capability.list")
    detail = client.call("capability.get", capability_id="system.capability-discovery")

    assert "capability.list" in handshake["capabilities"]
    assert "capability.get" in handshake["capabilities"]
    assert "system.capability-discovery" not in handshake["capabilities"]
    assert listing["semantic_capability_schema"] == 1
    capability_items = listing["capabilities"]
    listed_ids = [item["id"] for item in capability_items]
    assert listed_ids == sorted(listed_ids)
    assert _EXPLORE_CAPABILITY_IDS <= set(listed_ids)
    discovery = next(
        item for item in capability_items if item["id"] == "system.capability-discovery"
    )
    assert detail == {
        "semantic_capability_schema": 1,
        "capability": discovery,
    }
    after = tuple(
        sorted(
            path.relative_to(bridge.daily.vault_root) for path in bridge.daily.vault_root.rglob("*")
        )
    )
    assert after == before


def test_bridge_rejects_unknown_capability_and_unexpected_list_params(tmp_path: Path) -> None:
    client = ReferenceBridgeClient(_bridge(tmp_path))

    with pytest.raises(ProtocolError) as missing:
        client.call("capability.get", capability_id="missing.capability")
    assert missing.value.code == "capability_not_found"
    assert missing.value.data == {"capability_id": "missing.capability"}

    with pytest.raises(ProtocolError) as extra:
        client.call("capability.list", visibility="explore")
    assert extra.value.code == "extra_fields"
