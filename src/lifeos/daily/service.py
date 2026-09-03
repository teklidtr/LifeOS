"""Safe canonical mutations initiated explicitly by the local user."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import yaml

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos.daily.contracts import (
    CanonicalReference,
    CheckInRequest,
    MutationResult,
    QuickCaptureRequest,
    ReviewNoteRequest,
    TaskOutcomeRequest,
)
from lifeos.daily.errors import DailyInteractionError
from lifeos.markdown.parser import ManagedBlock, parse_markdown_note, replace_managed_block
from lifeos.vault import VaultAccessError, read_vault_markdown

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_LEVELS = {"low", "medium", "high"}


def content_hash(content: str | bytes) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def _safe_path(path: str, *, suffix: str = ".md") -> str:
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise DailyInteractionError(
            "invalid_path", "Path is invalid.", "Choose a vault-relative path."
        )
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise DailyInteractionError(
            "invalid_path", "Path must stay inside the vault.", "Choose a vault-relative path."
        )
    if not path.endswith(suffix):
        raise DailyInteractionError(
            "invalid_path", f"Path must end with {suffix}.", "Choose a Markdown file."
        )
    return pure.as_posix()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
    return slug[:80] or "capture"


def _frontmatter_document(
    frontmatter: dict[str, Any], body: str, *, preserve_body: bool = False
) -> str:
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    if preserve_body:
        return f"---\n{dumped}\n---\n{body}"
    normalized_body = body.lstrip("\n")
    return f"---\n{dumped}\n---\n\n{normalized_body}".rstrip() + "\n"


def _read_existing(vault_root: Path, relative_path: str) -> tuple[str, dict[str, Any], str]:
    try:
        source = read_vault_markdown(vault_root, relative_path)
    except VaultAccessError as exc:
        if exc.code == "not-found":
            raise DailyInteractionError(
                "not_found", f"Note not found: {relative_path}", "Reload the dashboard."
            ) from exc
        raise DailyInteractionError(
            "storage_unavailable", str(exc), "Check vault access and retry."
        ) from exc
    parsed = parse_markdown_note(source.path, content=source.content)
    error = next((finding for finding in parsed.findings if finding.severity == "error"), None)
    if error is not None:
        raise DailyInteractionError(
            "invalid_note", error.message, "Repair the note before changing it."
        )
    return source.content, dict(parsed.frontmatter), parsed.body


def _review_managed_block(body: str, name: str, path: str) -> ManagedBlock:
    parsed = parse_markdown_note(Path(path), content=f"---\n---\n{body}")
    error = next((finding for finding in parsed.findings if finding.severity == "error"), None)
    if error is not None:
        raise DailyInteractionError(
            "invalid_note", error.message, "Restore the managed block before updating."
        )
    matches = [block for block in parsed.managed_blocks if block.name == name]
    if len(matches) != 1 or len(parsed.managed_blocks) != 1:
        raise DailyInteractionError(
            "invalid_note",
            f"Review {name} managed block must be the only managed block; found {len(matches)} matching and {len(parsed.managed_blocks)} total.",
            "Restore the managed block before updating.",
        )
    return matches[0]


def _replace_review_managed_block(body: str, name: str, replacement: str, path: str) -> str:
    block = _review_managed_block(body, name, path)
    try:
        result = replace_managed_block(body, block, replacement)
    except ValueError as error:
        raise DailyInteractionError(
            "invalid_note", str(error), "Restore the managed block before updating."
        ) from error
    _review_managed_block(result, name, path)
    return result


def _ensure_expected(actual: str, expected: str | None, path: str) -> None:
    if expected is None or actual != expected:
        raise DailyInteractionError(
            "stale_write",
            f"The note changed after it was opened: {path}",
            "Reload the note, review the new content, and retry.",
            {"path": path, "actual_hash": actual},
        )


def _atomic_write(
    vault_root: Path, relative_path: str, content: str, *, expected_hash: str | None, create: bool
) -> None:
    parts = PurePosixPath(relative_path).parts
    current = vault_root
    for part in parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise DailyInteractionError(
                "unsafe_path",
                "A symlinked directory was rejected.",
                "Use a regular vault directory.",
            )
        current.mkdir(mode=0o755, exist_ok=True)
    parent = vault_root.joinpath(*parts[:-1])
    if parent.is_symlink():
        raise DailyInteractionError(
            "unsafe_path", "A symlinked directory was rejected.", "Use a regular vault directory."
        )
    dir_fd = os.open(
        parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    try:

        def check() -> None:
            target = parent / parts[-1]
            if create:
                if target.exists():
                    raise DailyInteractionError(
                        "conflict",
                        f"Target already exists: {relative_path}",
                        "Choose another title or reload.",
                    )
            else:
                try:
                    current_bytes = target.read_bytes()
                except OSError as exc:
                    raise DailyInteractionError(
                        "storage_unavailable",
                        "Target could not be re-read.",
                        "Retry after checking storage.",
                    ) from exc
                _ensure_expected(content_hash(current_bytes), expected_hash, relative_path)

        atomic_write_file_secure(
            dir_fd, parts[-1], content.encode("utf-8"), pre_replace_check=check
        )
    except AtomicWriteError as exc:
        raise DailyInteractionError(
            "storage_unavailable", str(exc), "Check storage and retry."
        ) from exc
    finally:
        os.close(dir_fd)


class DailyInteractionService:
    """One typed boundary for direct, local, user-authorized mutations."""

    def __init__(
        self, *, vault_root: Path, runtime_dir: Path, actor_id: str = "local-user"
    ) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.actor_id = actor_id.strip()
        if not self.actor_id:
            raise DailyInteractionError(
                "invalid_actor", "Actor ID must not be blank.", "Configure a local actor ID."
            )
        self._cache_path = runtime_dir / "daily" / "idempotency.json"

    def _cached(
        self, key: str, operation: str, fingerprint: str, build: Callable[[], MutationResult]
    ) -> MutationResult:
        if not isinstance(key, str) or not _SAFE_ID.fullmatch(key):
            raise DailyInteractionError(
                "invalid_idempotency_key",
                "Idempotency key is invalid.",
                "Use 1-128 lowercase letters, digits, dot, underscore, or hyphen.",
            )
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache = json.loads(self._cache_path.read_text()) if self._cache_path.exists() else {}
        except (OSError, json.JSONDecodeError) as exc:
            raise DailyInteractionError(
                "runtime_corrupt",
                "Idempotency state is unavailable.",
                "Repair or remove the disposable daily runtime state.",
            ) from exc
        existing = cache.get(key)
        if existing is not None:
            if existing.get("operation") != operation or existing.get("fingerprint") != fingerprint:
                raise DailyInteractionError(
                    "idempotency_conflict",
                    "Idempotency key was reused for a different action.",
                    "Generate a new idempotency key.",
                )
            result = existing["result"]
            ref = CanonicalReference(**result["reference"])
            return MutationResult(
                result["operation"],
                ref,
                result["idempotency_key"],
                result["created"],
                result["data"],
            )
        result = build()
        cache[key] = {
            "operation": operation,
            "fingerprint": fingerprint,
            "result": result.to_dict(),
        }
        temp = self._cache_path.with_suffix(".tmp")
        temp.write_text(json.dumps(cache, sort_keys=True, separators=(",", ":")) + "\n")
        os.replace(temp, self._cache_path)
        return result

    def quick_capture(self, request: QuickCaptureRequest) -> MutationResult:
        payload = json.dumps(asdict(request), sort_keys=True, default=str)
        fingerprint = content_hash(payload)

        def build() -> MutationResult:
            title = request.title.strip()
            if not title:
                raise DailyInteractionError(
                    "invalid_title", "Title must not be blank.", "Enter a short title."
                )
            metadata = dict(request.metadata or {})
            if request.kind == "task":
                if not request.plan_path or not request.task:
                    raise DailyInteractionError(
                        "invalid_task",
                        "Task capture requires a plan and task fields.",
                        "Choose a plan and enter task details.",
                    )
                path = _safe_path(request.plan_path)
                old_content, frontmatter, body = _read_existing(self.vault_root, path)
                actual_hash = content_hash(old_content)
                _ensure_expected(actual_hash, request.expected_hash, path)
                tasks = frontmatter.get("tasks")
                if tasks is None:
                    tasks = []
                    frontmatter["tasks"] = tasks
                if not isinstance(tasks, list):
                    raise DailyInteractionError(
                        "invalid_note", "Plan tasks must be a list.", "Repair the plan note."
                    )
                task = dict(request.task)
                task_id = task.get("task_id")
                duration = task.get("duration")
                if not isinstance(task_id, str) or not _SAFE_ID.fullmatch(task_id):
                    raise DailyInteractionError(
                        "invalid_task", "task_id is invalid.", "Use a stable lowercase task ID."
                    )
                if any(isinstance(item, dict) and item.get("task_id") == task_id for item in tasks):
                    raise DailyInteractionError(
                        "conflict", "The task ID already exists.", "Choose a different task ID."
                    )
                if type(duration) is not int or duration < 1 or duration > 1440:
                    raise DailyInteractionError(
                        "invalid_duration",
                        "Task duration must be from 1 to 1440 minutes.",
                        "Correct the estimate.",
                    )
                required = {
                    "title": title,
                    "status": "todo",
                    "energy": "medium",
                    "motivation": "medium",
                    "mode": "general",
                    "blocked_by": [],
                }
                for key, required_value in required.items():
                    task.setdefault(key, required_value)
                if task.get("energy") not in _LEVELS or task.get("motivation") not in _LEVELS:
                    raise DailyInteractionError(
                        "invalid_level",
                        "Task energy and motivation must be low, medium, or high.",
                        "Correct the task capacity fields.",
                    )
                tasks.append(task)
                document = _frontmatter_document(frontmatter, body, preserve_body=True)
                _atomic_write(
                    self.vault_root, path, document, expected_hash=actual_hash, create=False
                )
                ref = CanonicalReference(
                    path, content_hash(document), str(frontmatter.get("id") or ""), task_id
                )
                return MutationResult(
                    "quick_capture",
                    ref,
                    request.idempotency_key,
                    False,
                    {"kind": request.kind, "task_id": task_id},
                )

            if request.kind == "metric":
                day_value = metadata.get("day", date.today().isoformat())
                metric = metadata.get("metric")
                metric_value = metadata.get("value")
                if not isinstance(day_value, str) or not isinstance(metric, str):
                    raise DailyInteractionError(
                        "invalid_metric",
                        "Metric capture requires day and metric.",
                        "Choose a date and metric.",
                    )
                try:
                    day = date.fromisoformat(day_value)
                except ValueError as exc:
                    raise DailyInteractionError(
                        "invalid_date", "Metric day must be an ISO date.", "Correct the date."
                    ) from exc
                if isinstance(metric_value, bool) or not isinstance(
                    metric_value, (int, float, str)
                ):
                    raise DailyInteractionError(
                        "invalid_metric", "Metric value must be a scalar.", "Correct the value."
                    )
                result = self.update_checkin(
                    CheckInRequest(
                        request.idempotency_key + "-metric",
                        day,
                        "morning",
                        {metric: metric_value},
                        note=request.content,
                        expected_hash=request.expected_hash,
                    )
                )
                return MutationResult(
                    "quick_capture",
                    result.reference,
                    request.idempotency_key,
                    result.created,
                    {"kind": request.kind, "metric": metric},
                )

            if request.kind == "journal":
                day_value = metadata.get("day", date.today().isoformat())
                try:
                    day = (
                        date.fromisoformat(day_value)
                        if isinstance(day_value, str)
                        else date.today()
                    )
                except ValueError as exc:
                    raise DailyInteractionError(
                        "invalid_date", "Journal day must be an ISO date.", "Correct the date."
                    ) from exc
                result = self.update_checkin(
                    CheckInRequest(
                        request.idempotency_key + "-journal",
                        day,
                        "evening",
                        {},
                        note=f"### {title}\n\n{request.content}",
                        expected_hash=request.expected_hash,
                    )
                )
                return MutationResult(
                    "quick_capture",
                    result.reference,
                    request.idempotency_key,
                    result.created,
                    {"kind": request.kind},
                )

            type_by_kind = {"thought": "raw", "project": "plan", "flashcard": "flashcard"}
            root_by_kind = {"thought": "raw", "project": "plans", "flashcard": "flashcards"}
            note_type = type_by_kind[request.kind]
            root = root_by_kind[request.kind]
            path = _safe_path(
                request.target_path or f"{root}/{date.today().isoformat()}-{_slug(title)}.md"
            )
            note_id = f"{note_type}-{_slug(title)}-{request.idempotency_key[:12]}"
            new_frontmatter: dict[str, Any] = {
                "id": note_id,
                "type": note_type,
                "title": title,
                "description": title,
                "status": "inbox" if request.kind == "thought" else "active",
                "captured_by": self.actor_id,
            }
            if request.kind == "project":
                new_frontmatter.update(
                    {
                        "desired_outcome": metadata.pop(
                            "desired_outcome", request.content.strip() or title
                        ),
                        "tasks": [],
                    }
                )
            elif request.kind == "flashcard":
                question = metadata.pop("question", title)
                answer = metadata.pop("answer", request.content)
                due = metadata.pop("due", date.today().isoformat())
                estimated = metadata.pop("estimated_seconds", 45)
                if (
                    not isinstance(question, str)
                    or not question.strip()
                    or not isinstance(answer, str)
                    or not answer.strip()
                ):
                    raise DailyInteractionError(
                        "invalid_flashcard",
                        "Flashcard question and answer are required.",
                        "Complete both fields.",
                    )
                if type(estimated) is not int or estimated < 5 or estimated > 3600:
                    raise DailyInteractionError(
                        "invalid_duration",
                        "Flashcard estimate must be from 5 to 3600 seconds.",
                        "Correct the estimate.",
                    )
                new_frontmatter.update(
                    {
                        "card_id": note_id,
                        "topic": metadata.pop("topic", "Inbox"),
                        "question": question,
                        "answer": answer,
                        "due": due,
                        "estimated_seconds": estimated,
                        "source_refs": metadata.pop("source_refs", []),
                    }
                )
            for key, value in metadata.items():
                if key not in frontmatter:
                    frontmatter[key] = value
            body_content = "" if request.kind in {"project", "flashcard"} else request.content
            document = _frontmatter_document(new_frontmatter, body_content)
            _atomic_write(self.vault_root, path, document, expected_hash=None, create=True)
            ref = CanonicalReference(path, content_hash(document), note_id)
            return MutationResult(
                "quick_capture", ref, request.idempotency_key, True, {"kind": request.kind}
            )

        return self._cached(request.idempotency_key, "quick_capture", fingerprint, build)

    def update_checkin(self, request: CheckInRequest) -> MutationResult:
        payload = json.dumps(asdict(request), sort_keys=True, default=str)
        fingerprint = content_hash(payload)

        def build() -> MutationResult:
            if not request.metrics and not request.activities and not request.note.strip():
                raise DailyInteractionError(
                    "empty_checkin",
                    "Check-in contains no data.",
                    "Add a metric, activity, or note.",
                )
            for key, value in request.metrics.items():
                if (
                    not isinstance(key, str)
                    or not _SAFE_ID.fullmatch(key)
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float, str))
                ):
                    raise DailyInteractionError(
                        "invalid_metric",
                        f"Metric is invalid: {key}",
                        "Use a stable metric name and scalar value.",
                    )
            path = f"journal/{request.day.isoformat()}.md"
            target = self.vault_root / path
            created = not target.exists()
            if created:
                frontmatter: dict[str, Any] = {
                    "type": "journal",
                    "title": request.day.isoformat(),
                    "date": request.day,
                    "status": "active",
                    "metrics": {},
                    "activities": [],
                }
                body = ""
                actual_hash = None
            else:
                old, frontmatter, body = _read_existing(self.vault_root, path)
                actual_hash = content_hash(old)
                _ensure_expected(actual_hash, request.expected_hash, path)
            metrics = frontmatter.setdefault("metrics", {})
            if not isinstance(metrics, dict):
                raise DailyInteractionError(
                    "invalid_note", "Journal metrics must be a mapping.", "Repair the journal note."
                )
            metrics.update(request.metrics)
            activities = frontmatter.setdefault("activities", [])
            if not isinstance(activities, list):
                raise DailyInteractionError(
                    "invalid_note", "Journal activities must be a list.", "Repair the journal note."
                )
            activities.extend(item for item in request.activities if item not in activities)
            section = (
                f"## {request.period.title()} check-in\n\n{request.note.strip()}\n"
                if request.note.strip()
                else ""
            )
            if section:
                if created:
                    body = body.rstrip()
                body += "\n\n" + section
            document = _frontmatter_document(frontmatter, body, preserve_body=not created)
            _atomic_write(
                self.vault_root, path, document, expected_hash=actual_hash, create=created
            )
            ref = CanonicalReference(
                path, content_hash(document), None, f"{request.period}-check-in"
            )
            return MutationResult(
                "checkin",
                ref,
                request.idempotency_key,
                created,
                {"period": request.period, "day": request.day.isoformat()},
            )

        return self._cached(request.idempotency_key, "checkin", fingerprint, build)

    def record_task_outcome(self, request: TaskOutcomeRequest) -> MutationResult:
        payload = json.dumps(asdict(request), sort_keys=True, default=str)
        fingerprint = content_hash(payload)

        def build() -> MutationResult:
            path = _safe_path(request.plan_path)
            old, frontmatter, body = _read_existing(self.vault_root, path)
            actual_hash = content_hash(old)
            _ensure_expected(actual_hash, request.expected_hash, path)
            tasks = frontmatter.get("tasks")
            if not isinstance(tasks, list):
                raise DailyInteractionError(
                    "invalid_note", "Plan tasks must be a list.", "Repair the plan note."
                )
            matched: dict[str, Any] | None = None
            for task in tasks:
                if isinstance(task, dict) and task.get("task_id") == request.task_id:
                    matched = task
                    break
            if matched is None:
                raise DailyInteractionError(
                    "task_not_found",
                    f"Task not found: {request.task_id}",
                    "Reload the plan and choose an existing task.",
                )
            current_status = str(matched.get("status", "todo")).casefold()
            if current_status in {"done", "completed", "cancelled", "archived"}:
                raise DailyInteractionError(
                    "invalid_transition",
                    f"Task in terminal state {current_status} cannot receive {request.outcome}.",
                    "Reload the plan or create a new task.",
                )
            status_map = {
                "started": "active",
                "done": "done",
                "partial": "active",
                "skipped": "todo",
                "deferred": "todo",
                "cancelled": "cancelled",
            }
            matched["status"] = status_map[request.outcome]
            if request.outcome == "deferred" and request.deferred_until is not None:
                matched["due"] = request.deferred_until
            event: dict[str, Any] = {
                "event_id": request.idempotency_key,
                "task_id": request.task_id,
                "outcome": request.outcome,
                "date": request.day,
                "actor": self.actor_id,
            }
            for key in ("planned_minutes", "actual_minutes"):
                value = getattr(request, key)
                if value is not None:
                    if type(value) is not int or value < 0 or value > 1440:
                        raise DailyInteractionError(
                            "invalid_duration",
                            f"{key} must be from 0 to 1440.",
                            "Correct the duration.",
                        )
                    event[key] = value
            for key in ("energy_before", "energy_after", "motivation_before"):
                value = getattr(request, key)
                if value is not None:
                    if value not in _LEVELS:
                        raise DailyInteractionError(
                            "invalid_level",
                            f"{key} must be low, medium, or high.",
                            "Correct the capacity value.",
                        )
                    event[key] = value
            for key in ("difficulty", "satisfaction"):
                value = getattr(request, key)
                if value is not None:
                    if type(value) is not int or value < 1 or value > 10:
                        raise DailyInteractionError(
                            "invalid_score", f"{key} must be from 1 to 10.", "Correct the score."
                        )
                    event[key] = value
            for key in ("reason", "note", "started_at", "ended_at", "source_ref"):
                value = getattr(request, key)
                if value:
                    event[key] = value.strip()
            history = frontmatter.setdefault("execution_history", [])
            if not isinstance(history, list):
                raise DailyInteractionError(
                    "invalid_note", "Execution history must be a list.", "Repair the plan note."
                )
            history.append(event)
            document = _frontmatter_document(frontmatter, body, preserve_body=True)
            _atomic_write(self.vault_root, path, document, expected_hash=actual_hash, create=False)
            ref = CanonicalReference(
                path, content_hash(document), str(frontmatter.get("id") or ""), request.task_id
            )
            return MutationResult(
                "task_outcome",
                ref,
                request.idempotency_key,
                False,
                {"task_id": request.task_id, "outcome": request.outcome},
            )

        return self._cached(request.idempotency_key, "task_outcome", fingerprint, build)

    def create_review_note(self, request: ReviewNoteRequest) -> MutationResult:
        payload = json.dumps(asdict(request), sort_keys=True, default=str)
        fingerprint = content_hash(payload)

        def build() -> MutationResult:
            suffix = (
                request.day.isoformat()
                if request.kind != "weekly"
                else f"{request.day.isocalendar().year}-W{request.day.isocalendar().week:02d}"
            )
            path = f"reviews/{request.kind}-{suffix}.md"
            target = self.vault_root / path
            created = not target.exists()
            managed = f"<!-- lifeos:managed:start facts -->\n{request.facts_markdown.rstrip()}\n<!-- lifeos:managed:end facts -->"
            if created:
                fm = {
                    "type": "review",
                    "review_kind": request.kind,
                    "date": request.day,
                    "status": "active",
                }
                body = f"# {request.kind.title()} review\n\n{managed}\n\n## Reflection\n\n"
                _review_managed_block(body, "facts", path)
                old_hash = None
            else:
                old, fm, body = _read_existing(self.vault_root, path)
                old_hash = content_hash(old)
                _ensure_expected(old_hash, request.expected_hash, path)
                body = _replace_review_managed_block(body, "facts", managed, path)
            document = _frontmatter_document(fm, body, preserve_body=not created)
            _atomic_write(self.vault_root, path, document, expected_hash=old_hash, create=created)
            ref = CanonicalReference(path, content_hash(document), None, "facts")
            return MutationResult(
                "review_note", ref, request.idempotency_key, created, {"kind": request.kind}
            )

        return self._cached(request.idempotency_key, "review_note", fingerprint, build)
