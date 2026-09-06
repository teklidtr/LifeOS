"""Bridge adapter for Python-owned semantic capability discovery."""

from __future__ import annotations

from lifeos.bridge.application import BridgeApplication as _BaseBridgeApplication
from lifeos.bridge.protocol import CAPABILITIES, ProtocolError, strict_object
from lifeos.capabilities import CAPABILITY_REGISTRY, SEMANTIC_CAPABILITY_SCHEMA_VERSION

# Keep semantic definitions honest about the low-level bridge methods they claim to compose.
CAPABILITY_REGISTRY.validate_bridge_methods(CAPABILITIES)


class BridgeApplication(_BaseBridgeApplication):
    """Add read-only semantic capability discovery to the desktop bridge."""

    def dispatch(self, method: str, params: object) -> object:
        if method == "capability.list":
            strict_object(params, allowed=set())
            return {
                "semantic_capability_schema": SEMANTIC_CAPABILITY_SCHEMA_VERSION,
                "capabilities": [
                    capability.to_dict() for capability in CAPABILITY_REGISTRY.list_capabilities()
                ],
            }
        if method == "capability.get":
            data = strict_object(
                params,
                allowed={"capability_id"},
                required={"capability_id"},
            )
            capability_id = data["capability_id"]
            if not isinstance(capability_id, str) or not capability_id.strip():
                raise ProtocolError(
                    "invalid_params",
                    "capability_id must be a non-empty string.",
                )
            capability = CAPABILITY_REGISTRY.get(capability_id)
            if capability is None:
                raise ProtocolError(
                    "capability_not_found",
                    "The requested semantic capability does not exist.",
                    {"capability_id": capability_id},
                )
            return {
                "semantic_capability_schema": SEMANTIC_CAPABILITY_SCHEMA_VERSION,
                "capability": capability.to_dict(),
            }
        return super().dispatch(method, params)
