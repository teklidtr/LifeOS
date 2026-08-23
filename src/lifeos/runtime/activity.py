"""Privacy-bounded MCP activity tracing in disposable runtime state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    timestamp: str
    tool: str
    focus_paths: tuple[str, ...] = ()
    instruction_ids: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    proposal_id: str | None = None
    target_paths: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    operation_count: int | None = None


class ActivityStore:
    """Append/read bounded routing metadata without canonical content bodies."""

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir).resolve(strict=False)
        self.path = self.runtime_dir / "activity" / "mcp.jsonl"

    @staticmethod
    def _clean_paths(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(item) for item in values if str(item)))

    def append(
        self,
        *,
        tool: str,
        focus_paths: tuple[str, ...] | list[str] = (),
        instruction_ids: tuple[str, ...] | list[str] = (),
        source_paths: tuple[str, ...] | list[str] = (),
        proposal_id: str | None = None,
        target_paths: tuple[str, ...] | list[str] = (),
        changed_paths: tuple[str, ...] | list[str] = (),
        operation_count: int | None = None,
        now: datetime | None = None,
    ) -> ActivityRecord:
        if not tool or tool.isspace():
            raise ValueError("tool must be non-empty")
        timestamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        record = ActivityRecord(
            timestamp=timestamp,
            tool=tool,
            focus_paths=self._clean_paths(focus_paths),
            instruction_ids=self._clean_paths(instruction_ids),
            source_paths=self._clean_paths(source_paths),
            proposal_id=proposal_id,
            target_paths=self._clean_paths(target_paths),
            changed_paths=self._clean_paths(changed_paths),
            operation_count=operation_count,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True, ensure_ascii=False) + "\n")
        return record

    def read(self, *, limit: int = 20) -> tuple[ActivityRecord, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if not self.path.exists():
            return ()
        records: list[ActivityRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                raw: Any = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                records.append(
                    ActivityRecord(
                        timestamp=str(raw["timestamp"]),
                        tool=str(raw["tool"]),
                        focus_paths=tuple(raw.get("focus_paths", ())),
                        instruction_ids=tuple(raw.get("instruction_ids", ())),
                        source_paths=tuple(raw.get("source_paths", ())),
                        proposal_id=raw.get("proposal_id"),
                        target_paths=tuple(raw.get("target_paths", ())),
                        changed_paths=tuple(raw.get("changed_paths", ())),
                        operation_count=raw.get("operation_count"),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(records[-limit:])
