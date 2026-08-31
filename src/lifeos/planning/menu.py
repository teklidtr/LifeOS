"""Adaptive, deterministic daily-menu planning."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

from lifeos.diagnostics import (
    DiagnosticError,
    diagnostic_error_message,
    diagnostics_from_findings,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown

Level = Literal["low", "medium", "high"]
_LEVELS: dict[str, int] = {"low": 1, "medium": 2, "high": 3}
_ACTIVE_STATUSES = frozenset({"todo", "active", "pending"})
_DONE_STATUSES = frozenset({"done", "completed", "archived"})
_MAX_EXACT_CANDIDATES = 20
_MAX_AVAILABLE_MINUTES = 1440
_FIT_SCALE = 1000


class PlanningError(DiagnosticError):
    """Raised when plan actions or capacity inputs are invalid."""


@dataclass(frozen=True, slots=True)
class PlanningAction:
    task_id: str
    title: str
    status: str
    duration: int
    energy: Level
    motivation: Level
    mode: str
    goal: str
    plan: str
    due: date | None
    blocked_by: tuple[str, ...]
    source_path: str


@dataclass(frozen=True, slots=True)
class MenuItem:
    task_id: str
    title: str
    duration: int
    mode: str
    goal: str
    plan: str
    reason: str


@dataclass(frozen=True, slots=True)
class DeferredAction:
    task_id: str
    title: str
    reason: str


@dataclass(frozen=True, slots=True)
class MenuOptimizationDiagnostics:
    solver: str
    objective_order: tuple[str, ...]
    selected_score: tuple[int, ...]
    unused_minutes: int
    binding_constraints: tuple[str, ...]
    rejected_eligible: tuple[DeferredAction, ...]


@dataclass(frozen=True, slots=True)
class DailyMenu:
    as_of: date
    available_minutes: int
    energy: Level
    motivation: Level
    selected_minutes: int
    items: tuple[MenuItem, ...]
    deferred: tuple[DeferredAction, ...]
    diagnostics: MenuOptimizationDiagnostics


def _required_str(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanningError(f"{path}: action {key} must be a non-empty string")
    return value.strip()


def _level(data: dict[str, Any], key: str, path: Path) -> Level:
    value = data.get(key, "medium")
    if not isinstance(value, str) or value not in _LEVELS:
        raise PlanningError(f"{path}: action {key} must be low, medium, or high")
    return cast(Level, value)


def _due(value: object, path: Path) -> date | None:
    if value is None or value == "":
        return None
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise PlanningError(f"{path}: action due must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PlanningError(f"{path}: action due must be an ISO date") from exc


def load_plan_actions(vault_root: Path) -> tuple[PlanningAction, ...]:
    actions: list[PlanningAction] = []
    try:
        sources = iter_vault_markdown(vault_root, roots=("plans",))
    except VaultAccessError as exc:
        raise PlanningError(str(exc)) from exc
    for source in sources:
        path = source.path
        parsed = parse_markdown_note(path, content=source.content)
        diagnostics = diagnostics_from_findings(parsed.findings, vault_root=vault_root)
        if diagnostics:
            raise PlanningError(diagnostic_error_message(diagnostics[0]), diagnostic=diagnostics[0])
        if parsed.frontmatter.get("type") != "plan":
            continue
        raw_actions = parsed.frontmatter.get("tasks", [])
        if raw_actions is None:
            continue
        if not isinstance(raw_actions, list):
            raise PlanningError(f"{path}: tasks must be a list")

        default_plan = parsed.durable_fields.id or path.stem
        default_goal = parsed.frontmatter.get("goal", "")
        if not isinstance(default_goal, str):
            raise PlanningError(f"{path}: goal must be a string")

        for raw in raw_actions:
            if not isinstance(raw, dict):
                raise PlanningError(f"{path}: every task must be a mapping")
            duration = raw.get("duration")
            if type(duration) is not int or duration <= 0 or duration > 1440:
                raise PlanningError(f"{path}: action duration must be from 1 to 1440 minutes")
            blocked = raw.get("blocked_by", [])
            if not isinstance(blocked, list) or not all(
                isinstance(item, str) and item.strip() for item in blocked
            ):
                raise PlanningError(
                    f"{path}: action blocked_by must be a list of non-empty strings"
                )
            raw_goal = raw.get("goal", default_goal)
            if not isinstance(raw_goal, str):
                raise PlanningError(f"{path}: action goal must be a string")
            raw_plan = raw.get("plan", default_plan)
            if not isinstance(raw_plan, str) or not raw_plan.strip():
                raise PlanningError(f"{path}: action plan must be a non-empty string")
            status = _required_str(raw, "status", path).casefold()
            actions.append(
                PlanningAction(
                    task_id=_required_str(raw, "task_id", path),
                    title=_required_str(raw, "title", path),
                    status=status,
                    duration=duration,
                    energy=_level(raw, "energy", path),
                    motivation=_level(raw, "motivation", path),
                    mode=_required_str(raw, "mode", path),
                    goal=raw_goal.strip(),
                    plan=raw_plan.strip(),
                    due=_due(raw.get("due"), path),
                    blocked_by=tuple(item.strip() for item in blocked),
                    source_path=path.relative_to(vault_root).as_posix(),
                )
            )

    ids = [action.task_id for action in actions]
    if len(ids) != len(set(ids)):
        raise PlanningError("task_id values must be unique across plan notes")
    return tuple(actions)


def _validate_level(value: str, name: str) -> Level:
    if not isinstance(value, str):
        raise PlanningError(f"{name} must be low, medium, or high")
    normalized = value.strip().casefold()
    if normalized not in _LEVELS:
        raise PlanningError(f"{name} must be low, medium, or high")
    return cast(Level, normalized)


def _due_urgency(action: PlanningAction, *, as_of: date) -> int:
    if action.due is None:
        return 0
    days = (action.due - as_of).days
    if days < 0:
        return 100 + min(abs(days), 365)
    if days == 0:
        return 90
    if days <= 3:
        return 70 - days
    if days <= 7:
        return 40 - days
    return 0


def _mean_fit(levels: tuple[Level, ...], *, target: Level) -> int:
    """Return size-neutral mean fit on a stable integer scale."""
    if not levels:
        return 0
    total = sum(3 - abs(_LEVELS[level] - _LEVELS[target]) for level in levels)
    return total * _FIT_SCALE // len(levels)


def _selection_objective(
    selected: tuple[PlanningAction, ...],
    *,
    as_of: date,
    energy: Level,
    motivation: Level,
) -> tuple[int, ...]:
    """Score menus without treating available capacity as a utilization target."""
    urgencies = tuple(_due_urgency(action, as_of=as_of) for action in selected)
    selected_minutes = sum(action.duration for action in selected)
    return (
        max(urgencies, default=0),
        sum(urgencies),
        _mean_fit(tuple(action.energy for action in selected), target=energy),
        _mean_fit(tuple(action.motivation for action in selected), target=motivation),
        -selected_minutes,
        -len(selected),
        len({action.plan.casefold() for action in selected}),
    )


def _selection_ids(selected: tuple[PlanningAction, ...]) -> tuple[str, ...]:
    return tuple(sorted(action.task_id for action in selected))


def _better_menu_selection(
    candidate: tuple[PlanningAction, ...],
    incumbent: tuple[PlanningAction, ...],
    *,
    as_of: date,
    energy: Level,
    motivation: Level,
) -> bool:
    candidate_score = _selection_objective(
        candidate, as_of=as_of, energy=energy, motivation=motivation
    )
    incumbent_score = _selection_objective(
        incumbent, as_of=as_of, energy=energy, motivation=motivation
    )
    if candidate_score != incumbent_score:
        return candidate_score > incumbent_score
    return _selection_ids(candidate) < _selection_ids(incumbent)


def _selection_state_key(
    selected: tuple[PlanningAction, ...],
    *,
    as_of: date,
    energy: Level,
    motivation: Level,
) -> tuple[int, frozenset[str], tuple[int, ...]]:
    """Retain every aggregate that can affect a future objective comparison."""
    return (
        sum(action.duration for action in selected),
        frozenset(action.plan.casefold() for action in selected),
        _selection_objective(
            selected,
            as_of=as_of,
            energy=energy,
            motivation=motivation,
        ),
    )


def _exact_menu_selection(
    candidates: tuple[PlanningAction, ...],
    *,
    as_of: date,
    available_minutes: int,
    energy: Level,
    motivation: Level,
) -> tuple[PlanningAction, ...]:
    empty_key = _selection_state_key(
        (),
        as_of=as_of,
        energy=energy,
        motivation=motivation,
    )
    states: dict[
        tuple[int, frozenset[str], tuple[int, ...]],
        tuple[PlanningAction, ...],
    ] = {empty_key: ()}
    for action in candidates:
        next_states = dict(states)
        for (used, _plans, _objective), selected in states.items():
            if used + action.duration > available_minutes:
                continue
            candidate = (*selected, action)
            key = _selection_state_key(
                candidate,
                as_of=as_of,
                energy=energy,
                motivation=motivation,
            )
            incumbent = next_states.get(key)
            if incumbent is None or _selection_ids(candidate) < _selection_ids(incumbent):
                next_states[key] = candidate
        states = next_states
    best: tuple[PlanningAction, ...] = ()
    for selected in states.values():
        if _better_menu_selection(
            selected, best, as_of=as_of, energy=energy, motivation=motivation
        ):
            best = selected
    return tuple(
        sorted(
            best,
            key=lambda action: (
                -_due_urgency(action, as_of=as_of),
                action.due or date.max,
                action.task_id,
            ),
        )
    )


def _fallback_menu_selection(
    candidates: tuple[PlanningAction, ...],
    *,
    as_of: date,
    available_minutes: int,
    energy: Level,
    motivation: Level,
) -> tuple[PlanningAction, ...]:
    ranked = sorted(
        candidates,
        key=lambda action: (
            -_due_urgency(action, as_of=as_of),
            -(3 - abs(_LEVELS[action.energy] - _LEVELS[energy])),
            -(3 - abs(_LEVELS[action.motivation] - _LEVELS[motivation])),
            action.duration,
            action.task_id,
        ),
    )
    selected: tuple[PlanningAction, ...] = ()
    used = 0
    for action in ranked:
        if used + action.duration > available_minutes:
            continue
        candidate = (*selected, action)
        if _better_menu_selection(
            candidate,
            selected,
            as_of=as_of,
            energy=energy,
            motivation=motivation,
        ):
            selected = candidate
            used += action.duration
    return selected


def build_daily_menu(
    *,
    actions: tuple[PlanningAction, ...],
    as_of: date,
    available_minutes: int,
    energy: str,
    motivation: str,
    mode: str | None = None,
) -> DailyMenu:
    if (
        type(available_minutes) is not int
        or available_minutes < 0
        or available_minutes > _MAX_AVAILABLE_MINUTES
    ):
        raise PlanningError(
            f"available_minutes must be an integer from 0 to {_MAX_AVAILABLE_MINUTES}"
        )
    energy_level = _validate_level(energy, "energy")
    motivation_level = _validate_level(motivation, "motivation")
    if mode is not None and (not isinstance(mode, str) or not mode.strip()):
        raise PlanningError("mode must be a non-empty string when provided")
    normalized_mode = mode.strip().casefold() if mode is not None else None
    completed = {action.task_id for action in actions if action.status in _DONE_STATUSES}

    eligible: list[PlanningAction] = []
    deferred: list[DeferredAction] = []
    for action in sorted(actions, key=lambda item: item.task_id):
        if action.status in _DONE_STATUSES:
            continue
        if action.status not in _ACTIVE_STATUSES:
            deferred.append(
                DeferredAction(action.task_id, action.title, f"status is {action.status}")
            )
            continue
        unmet = tuple(blocker for blocker in action.blocked_by if blocker not in completed)
        if unmet:
            deferred.append(
                DeferredAction(action.task_id, action.title, f"blocked by {', '.join(unmet)}")
            )
            continue
        if _LEVELS[action.energy] > _LEVELS[energy_level]:
            deferred.append(
                DeferredAction(action.task_id, action.title, "requires more energy than available")
            )
            continue
        if normalized_mode is not None and action.mode.casefold() != normalized_mode:
            deferred.append(DeferredAction(action.task_id, action.title, "mode does not match"))
            continue
        eligible.append(action)

    candidates = tuple(eligible)
    if len(candidates) <= _MAX_EXACT_CANDIDATES:
        solver = "exact-dynamic-programming"
        selected_actions = _exact_menu_selection(
            candidates,
            as_of=as_of,
            available_minutes=available_minutes,
            energy=energy_level,
            motivation=motivation_level,
        )
    else:
        solver = "deterministic-bounded-fallback"
        selected_actions = _fallback_menu_selection(
            candidates,
            as_of=as_of,
            available_minutes=available_minutes,
            energy=energy_level,
            motivation=motivation_level,
        )

    selected_ids = {action.task_id for action in selected_actions}
    selected: list[MenuItem] = []
    remaining = available_minutes
    for action in selected_actions:
        due_reason = ""
        if action.due is not None:
            if action.due < as_of:
                due_reason = "overdue; "
            elif action.due == as_of:
                due_reason = "due today; "
        reason = (
            f"{due_reason}selected for {energy_level} energy and {motivation_level} motivation "
            "by ordered urgency, size-neutral energy fit, size-neutral motivation fit, "
            f"and bounded plan-variety preferences within the {available_minutes}-minute "
            "capacity ceiling"
        )
        selected.append(
            MenuItem(
                task_id=action.task_id,
                title=action.title,
                duration=action.duration,
                mode=action.mode,
                goal=action.goal,
                plan=action.plan,
                reason=reason,
            )
        )
        remaining -= action.duration

    rejected_eligible = tuple(
        DeferredAction(
            action.task_id,
            action.title,
            (
                "exceeds the total time budget"
                if action.duration > available_minutes
                else "not selected by the bounded optimizer's ordered objectives"
            ),
        )
        for action in candidates
        if action.task_id not in selected_ids
    )
    deferred.extend(rejected_eligible)
    deferred.sort(key=lambda item: item.task_id)
    constraints: list[str] = []
    if any(
        action.task_id not in selected_ids and action.duration > remaining for action in candidates
    ):
        constraints.append("time budget")
    if solver == "deterministic-bounded-fallback":
        constraints.append(f"exact solver candidate limit ({_MAX_EXACT_CANDIDATES})")
    diagnostics = MenuOptimizationDiagnostics(
        solver=solver,
        objective_order=(
            "maximum due urgency",
            "total due urgency",
            "mean energy fit",
            "mean motivation fit",
            "lower selected minutes",
            "fewer items",
            "bounded plan variety",
            "stable task ids",
        ),
        selected_score=_selection_objective(
            selected_actions,
            as_of=as_of,
            energy=energy_level,
            motivation=motivation_level,
        ),
        unused_minutes=remaining,
        binding_constraints=tuple(constraints),
        rejected_eligible=rejected_eligible,
    )
    return DailyMenu(
        as_of=as_of,
        available_minutes=available_minutes,
        energy=energy_level,
        motivation=motivation_level,
        selected_minutes=available_minutes - remaining,
        items=tuple(selected),
        deferred=tuple(deferred),
        diagnostics=diagnostics,
    )


def serialize_daily_menu(menu: DailyMenu) -> str:
    return json.dumps(asdict(menu), sort_keys=True, default=str, indent=2)


def format_daily_menu(menu: DailyMenu) -> str:
    lines = [
        f"Proposed menu for {menu.as_of.isoformat()}",
        f"Capacity ceiling: {menu.available_minutes} min, {menu.energy} energy, "
        f"{menu.motivation} motivation",
        f"Selected: {menu.selected_minutes} min",
        f"Optimizer: {menu.diagnostics.solver}; remaining: {menu.diagnostics.unused_minutes} min",
        "",
    ]
    if not menu.items:
        lines.append("No eligible action fits this capacity.")
    for item in menu.items:
        lines.append(f"- {item.title} ({item.duration} min, {item.mode})")
        lines.append(f"  {item.reason}")
    if menu.deferred:
        lines.append("")
        lines.append("Deferred")
        lines.extend(f"- {item.title}: {item.reason}" for item in menu.deferred)
    return "\n".join(lines)