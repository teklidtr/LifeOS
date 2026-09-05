"""Bridge compatibility adapter for explicit personal-pattern desktop workflows."""

from __future__ import annotations

from lifeos.bridge.capability_application import BridgeApplication as _BaseBridgeApplication
from lifeos.bridge.personal_model_workspace import PersonalModelWorkspaceBridge
from lifeos.bridge.protocol import ProtocolError
from lifeos.reviews.pattern_integration import (
    push_pattern_review_attention,
    reset_pattern_review_attention,
)


class BridgeApplication(_BaseBridgeApplication):
    """Add bounded Phase 17 transport fields without widening the generic dispatcher.

    Review attention remains request-local. Personal Model workspace calls delegate
    to the existing deterministic pattern read model and proposal services; the
    TypeScript client receives presentation data but owns no pattern semantics.
    """

    def dispatch(self, method: str, params: object) -> object:
        if method.startswith("personal-model."):
            return PersonalModelWorkspaceBridge(
                vault_root=self.daily.vault_root,
                runtime_dir=self.daily.runtime_dir,
                actor_id=self.actor_id,
            ).dispatch(method, params)

        if method not in {"review.artifact.open", "review.artifact.refresh"} or not isinstance(
            params, dict
        ):
            return super().dispatch(method, params)

        data = dict(params)
        urgent = self._pattern_ids(data.pop("urgent_pattern_ids", None), "urgent_pattern_ids")
        pinned = self._pattern_ids(data.pop("pinned_pattern_ids", None), "pinned_pattern_ids")
        if method == "review.artifact.open" and data.get("kind") != "daily" and (urgent or pinned):
            raise ProtocolError(
                "invalid_params",
                "Explicit pattern attention is supported only for daily reviews.",
            )
        token = push_pattern_review_attention(
            urgent_pattern_ids=urgent,
            pinned_pattern_ids=pinned,
        )
        try:
            return super().dispatch(method, data)
        finally:
            reset_pattern_review_attention(token)

    @staticmethod
    def _pattern_ids(value: object, field: str) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ProtocolError("invalid_params", f"{field} must be a list of non-empty strings.")
        return tuple(dict.fromkeys(item.strip() for item in value))
