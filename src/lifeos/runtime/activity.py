"""Privacy-bounded MCP activity tracing in disposable runtime state."""

from __future__ import annotations

import json
import logging
import os
import stat
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)
_ACTIVITY_ACTOR: ContextVar[str | None] = ContextVar("lifeos_activity_actor", default=None)
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def push_activity_actor(actor_id: str | None) -> Token[str | None]:
    """Bind an actor to activity emitted by the current request context."""
    return _ACTIVITY_ACTOR.set(actor_id)


def reset_activity_actor(token: Token[str | None]) -> None:
    """Restore the previous request-scoped activity actor."""
    _ACTIVITY_ACTOR.reset(token)


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    timestamp: str
    tool: str
    actor_id: str | None = None
    focus_paths: tuple[str, ...] = ()
    instruction_ids: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    proposal_id: str | None = None
    target_paths: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    operation_count: int | None = None


class ActivityStore:
    """Append/read bounded routing metadata without canonical content bodies."""

    def __init__(self, runtime_dir: Path, *, runtime_dir_fd: int | None = None) -> None:
        self.runtime_dir = Path(runtime_dir).resolve(strict=False)
        self.path = self.runtime_dir / "activity" / "mcp.jsonl"
        self._runtime_dir_fd = runtime_dir_fd

    @staticmethod
    def _clean_paths(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(item) for item in values if str(item)))

    def _open_activity_directory(self, *, create: bool) -> int | None:
        if self._runtime_dir_fd is None:
            return None
        if create:
            try:
                os.mkdir("activity", mode=0o700, dir_fd=self._runtime_dir_fd)
            except FileExistsError:
                pass
        try:
            return os.open("activity", _DIRECTORY_FLAGS, dir_fd=self._runtime_dir_fd)
        except FileNotFoundError:
            return None

    @staticmethod
    def _verify_regular_file(fd: int) -> None:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("activity log path is not a regular file")

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
            actor_id=_ACTIVITY_ACTOR.get(),
            focus_paths=self._clean_paths(focus_paths),
            instruction_ids=self._clean_paths(instruction_ids),
            source_paths=self._clean_paths(source_paths),
            proposal_id=proposal_id,
            target_paths=self._clean_paths(target_paths),
            changed_paths=self._clean_paths(changed_paths),
            operation_count=operation_count,
        )
        try:
            if self._runtime_dir_fd is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(asdict(record), sort_keys=True, ensure_ascii=False) + "\n"
                    )
            else:
                activity_fd = self._open_activity_directory(create=True)
                if activity_fd is None:
                    raise OSError("activity directory could not be opened")
                try:
                    flags = (
                        os.O_WRONLY
                        | os.O_APPEND
                        | os.O_CREAT
                        | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_CLOEXEC", 0)
                    )
                    log_fd = os.open(
                        "mcp.jsonl",
                        flags,
                        0o600,
                        dir_fd=activity_fd,
                    )
                    try:
                        self._verify_regular_file(log_fd)
                        with os.fdopen(log_fd, "a", encoding="utf-8", closefd=False) as handle:
                            handle.write(
                                json.dumps(asdict(record), sort_keys=True, ensure_ascii=False)
                                + "\n"
                            )
                    finally:
                        os.close(log_fd)
                finally:
                    os.close(activity_fd)
        except OSError as error:
            logger.warning("Unable to persist LifeOS activity record to %s: %s", self.path, error)
        return record

    def read(self, *, limit: int = 20) -> tuple[ActivityRecord, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        try:
            if self._runtime_dir_fd is None:
                if not self.path.exists():
                    return ()
                lines = self.path.read_text(encoding="utf-8").splitlines()
            else:
                activity_fd = self._open_activity_directory(create=False)
                if activity_fd is None:
                    return ()
                try:
                    flags = (
                        os.O_RDONLY
                        | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_CLOEXEC", 0)
                    )
                    try:
                        log_fd = os.open("mcp.jsonl", flags, dir_fd=activity_fd)
                    except FileNotFoundError:
                        return ()
                    try:
                        self._verify_regular_file(log_fd)
                        with os.fdopen(log_fd, "r", encoding="utf-8", closefd=False) as handle:
                            lines = handle.read().splitlines()
                    finally:
                        os.close(log_fd)
                finally:
                    os.close(activity_fd)
        except OSError as error:
            logger.warning("Unable to read LifeOS activity records from %s: %s", self.path, error)
            return ()

        records: list[ActivityRecord] = []
        for line in lines:
            try:
                raw: Any = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                raw_actor = raw.get("actor_id")
                records.append(
                    ActivityRecord(
                        timestamp=str(raw["timestamp"]),
                        tool=str(raw["tool"]),
                        actor_id=None if raw_actor is None else str(raw_actor),
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
