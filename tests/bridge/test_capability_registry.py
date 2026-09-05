from dataclasses import replace
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient
from lifeos.capabilities import (
    CapabilityBackingReference,
    CapabilityDefinitionError,
    CapabilityEntryPoint,
    CapabilityRegistry,
    SemanticCapability,
)


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
        entry_points=(
            CapabilityEntryPoint("obsidian_view", "lifeos-today", "Open Today"),
        ),
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
            path.relative_to(bridge.daily.vault_root)
            for path in bridge.daily.vault_root.rglob("*")
        )
    )

    handshake = client.call("system.handshake", protocol="1.0")
    listing = client.call("capability.list")
    detail = client.call("capability.get", capability_id="system.capability-discovery")

    assert "capability.list" in handshake["capabilities"]
    assert "capability.get" in handshake["capabilities"]
    assert "system.capability-discovery" not in handshake["capabilities"]
    assert listing["semantic_capability_schema"] == 1
    assert [item["id"] for item in listing["capabilities"]] == ["system.capability-discovery"]
    assert detail == {
        "semantic_capability_schema": 1,
        "capability": listing["capabilities"][0],
    }
    after = tuple(
        sorted(
            path.relative_to(bridge.daily.vault_root)
            for path in bridge.daily.vault_root.rglob("*")
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
