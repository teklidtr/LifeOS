"""MCP-facing privacy projection for disposable activity records."""

from dataclasses import replace

from lifeos.runtime import ActivityRecord, ActivityStore


class MCPActivityStore(ActivityStore):
    """Retain internal activity detail while redacting non-reauthorizable instruction IDs."""

    def read(self, *, limit: int = 20) -> tuple[ActivityRecord, ...]:
        return tuple(
            replace(record, instruction_ids=())
            for record in super().read(limit=limit)
        )
