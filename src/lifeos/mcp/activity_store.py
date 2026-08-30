"""MCP-facing privacy projection for disposable activity records."""

from dataclasses import replace

from lifeos.runtime import ActivityRecord, ActivityStore
from lifeos.runtime.activity import _ACTIVITY_ACTOR


class MCPActivityStore(ActivityStore):
    """Retain internal activity detail while redacting non-reauthorizable instruction IDs."""

    def current_actor_id(self) -> str | None:
        """Return only the request-scoped actor bound by the trusted MCP runtime."""

        return _ACTIVITY_ACTOR.get()

    def read(self, *, limit: int = 20) -> tuple[ActivityRecord, ...]:
        return tuple(
            replace(record, instruction_ids=())
            for record in super().read(limit=limit)
        )
