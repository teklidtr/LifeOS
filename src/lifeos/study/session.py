"""Runtime study-session lifecycle with canonical session outcomes."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from lifeos.daily.errors import DailyInteractionError
from lifeos.daily.service import _atomic_write, _frontmatter_document, _read_existing, content_hash
from lifeos.study.review import ReviewPlan, build_review_plan, load_flashcards
from lifeos.vault import VaultAccessError, read_vault_markdown

SessionState = Literal["active", "paused", "finished", "abandoned"]


@dataclass(frozen=True, slots=True)
class StudySession:
    session_id: str
    state: SessionState
    day: date
    started_at: str
    updated_at: str
    topic: str | None
    budget_minutes: int
    card_ids: tuple[str, ...]
    card_paths: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    paused_seconds: int = 0
    actual_minutes: int | None = None
    source_changes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StudySessionService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path, actor_id: str = "local-user") -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.actor_id = actor_id
        self.sessions_dir = runtime_dir / "study-sessions"

    def plan(self, *, day: date, minutes: int, topic: str | None = None) -> ReviewPlan:
        return build_review_plan(
            cards=load_flashcards(self.vault_root),
            as_of=day,
            available_minutes=minutes,
            topic=topic,
        )

    def start(
        self,
        *,
        day: date,
        minutes: int,
        topic: str | None = None,
        session_id: str | None = None,
        now: datetime | None = None,
    ) -> StudySession:
        plan = self.plan(day=day, minutes=minutes, topic=topic)
        card_ids = tuple(card_id for session in plan.sessions for card_id in session.card_ids)
        card_paths = tuple(path for session in plan.sessions for path in session.card_paths)
        if not card_ids:
            raise DailyInteractionError(
                "empty_study_session",
                "No due cards fit this study session.",
                "Increase the time budget, change topic, or study a source note directly.",
            )
        stable_id = session_id or f"study-{day.isoformat()}-{uuid.uuid4().hex[:12]}"
        path = self._path(stable_id)
        if path.exists():
            return self.load(stable_id)
        moment = (now or datetime.now().astimezone()).isoformat()
        hashes: list[tuple[str, str]] = []
        for card_path in card_paths:
            try:
                source = read_vault_markdown(self.vault_root, card_path)
                hashes.append((card_path, content_hash(source.content_bytes)))
            except VaultAccessError:
                hashes.append((card_path, "missing"))
        result = StudySession(
            stable_id,
            "active",
            day,
            moment,
            moment,
            topic,
            minutes,
            card_ids,
            card_paths,
            tuple(hashes),
        )
        self._save(result)
        return result

    def load(self, session_id: str) -> StudySession:
        path = self._path(session_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["day"] = date.fromisoformat(raw["day"])
            for key in ("card_ids", "card_paths", "source_hashes", "source_changes"):
                raw[key] = tuple(tuple(item) if key == "source_hashes" else item for item in raw.get(key, []))
            return StudySession(**raw)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DailyInteractionError(
                "study_session_unavailable",
                f"Study session could not be loaded: {session_id}",
                "Restart the session or repair disposable runtime state.",
            ) from exc

    def list_open(self) -> tuple[StudySession, ...]:
        if not self.sessions_dir.exists():
            return ()
        sessions = []
        for path in sorted(self.sessions_dir.glob("*.json")):
            session = self.load(path.stem)
            if session.state in {"active", "paused"}:
                sessions.append(session)
        return tuple(sessions)

    def transition(
        self,
        *,
        session_id: str,
        action: Literal["pause", "resume", "finish", "abandon"],
        now: datetime | None = None,
        actual_minutes: int | None = None,
        expected_journal_hash: str | None = None,
    ) -> StudySession:
        current = self.load(session_id)
        allowed = {
            "active": {"pause", "finish", "abandon"},
            "paused": {"resume", "finish", "abandon"},
            "finished": set(),
            "abandoned": set(),
        }
        if action not in allowed[current.state]:
            raise DailyInteractionError(
                "invalid_study_transition",
                f"Cannot {action} a {current.state} session.",
                "Reload the study session.",
            )
        moment = now or datetime.now().astimezone()
        state: SessionState = {
            "pause": "paused",
            "resume": "active",
            "finish": "finished",
            "abandon": "abandoned",
        }[action]  # type: ignore[assignment]
        changes = self._source_changes(current)
        minutes = actual_minutes
        if action in {"finish", "abandon"}:
            if minutes is None:
                started = datetime.fromisoformat(current.started_at)
                minutes = max(0, int((moment - started).total_seconds() // 60))
            if type(minutes) is not int or minutes < 0 or minutes > 1440:
                raise DailyInteractionError(
                    "invalid_duration",
                    "Study session duration must be from 0 to 1440 minutes.",
                    "Correct the duration.",
                )
        updated = StudySession(
            current.session_id,
            state,
            current.day,
            current.started_at,
            moment.isoformat(),
            current.topic,
            current.budget_minutes,
            current.card_ids,
            current.card_paths,
            current.source_hashes,
            current.paused_seconds,
            minutes,
            changes,
        )
        if action in {"finish", "abandon"}:
            self._append_journal(updated, expected_journal_hash=expected_journal_hash)
        self._save(updated)
        return updated

    def _source_changes(self, session: StudySession) -> tuple[str, ...]:
        changed: list[str] = []
        for path, expected in session.source_hashes:
            try:
                source = read_vault_markdown(self.vault_root, path)
                actual = content_hash(source.content_bytes)
            except VaultAccessError:
                actual = "missing"
            if actual != expected:
                changed.append(path)
        return tuple(changed)

    def _append_journal(self, session: StudySession, *, expected_journal_hash: str | None) -> None:
        relative = f"journal/{session.day.isoformat()}.md"
        target = self.vault_root / relative
        created = not target.exists()
        if created:
            frontmatter: dict[str, Any] = {
                "type": "journal",
                "title": session.day.isoformat(),
                "date": session.day,
                "status": "active",
                "study_sessions": [],
            }
            body = ""
            old_hash = None
        else:
            old, frontmatter, body = _read_existing(self.vault_root, relative)
            old_hash = content_hash(old)
            if expected_journal_hash is not None and old_hash != expected_journal_hash:
                raise DailyInteractionError(
                    "stale_write",
                    "The journal changed before the study result was recorded.",
                    "Reload the journal and finish again.",
                )
        events = frontmatter.setdefault("study_sessions", [])
        if not isinstance(events, list):
            raise DailyInteractionError(
                "invalid_note",
                "Journal study_sessions must be a list.",
                "Repair the journal note.",
            )
        if not any(isinstance(item, dict) and item.get("session_id") == session.session_id for item in events):
            events.append(
                {
                    "session_id": session.session_id,
                    "state": session.state,
                    "started_at": session.started_at,
                    "ended_at": session.updated_at,
                    "actual_minutes": session.actual_minutes,
                    "budget_minutes": session.budget_minutes,
                    "topic": session.topic,
                    "card_ids": list(session.card_ids),
                    "source_refs": list(session.card_paths),
                    "source_changes": list(session.source_changes),
                    "actor": self.actor_id,
                }
            )
        document = _frontmatter_document(frontmatter, body, preserve_body=not created)
        _atomic_write(
            self.vault_root,
            relative,
            document,
            expected_hash=old_hash,
            create=created,
        )

    def _path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or ".." in session_id:
            raise DailyInteractionError(
                "invalid_session_id",
                "Study session ID is invalid.",
                "Reload the study view.",
            )
        return self.sessions_dir / f"{session_id}.json"

    def _save(self, session: StudySession) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(session.session_id)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(session.to_dict(), sort_keys=True, default=str) + "\n")
        os.replace(temp, path)
