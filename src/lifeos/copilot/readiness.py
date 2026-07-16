"""Deterministic goal readiness diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .contracts import CopilotIndex, GoalRecord, PlanRecord

ReadinessCategory = Literal["hard-blocker", "clarification", "optional", "information"]
ReadinessPath = Literal["decline", "clarify", "link-existing-plan", "plan", "park"]


@dataclass(frozen=True, slots=True)
class ReadinessFinding:
    code: str
    category: ReadinessCategory
    field: str
    message: str
    required: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GoalReadinessReport:
    goal_id: str
    source_path: str
    source_hash: str
    ready: bool
    path: ReadinessPath
    findings: tuple[ReadinessFinding, ...]
    active_plan_ids: tuple[str, ...]
    missing_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "findings": [item.to_dict() for item in self.findings],
        }


def evaluate_goal_readiness(goal: GoalRecord, *, index: CopilotIndex) -> GoalReadinessReport:
    findings: list[ReadinessFinding] = []
    plans_by_id = {plan.plan_id: plan for plan in index.plans}
    active_plans: list[PlanRecord] = []

    if goal.status == "archived":
        findings.append(
            ReadinessFinding(
                "goal-archived",
                "hard-blocker",
                "status",
                "Archived goals must be explicitly reopened before planning.",
                True,
            )
        )

    duplicate = any(
        diagnostic.code == "copilot-id-duplicate" and diagnostic.path == goal.path
        for diagnostic in index.diagnostics
    )
    if duplicate:
        findings.append(
            ReadinessFinding(
                "goal-id-conflict",
                "hard-blocker",
                "id",
                "The goal ID is not unique in the vault.",
                True,
            )
        )

    for ref in sorted(goal.active_plan_refs):
        plan_id = ref.strip("[]").split("/")[-1].removesuffix(".md")
        plan = plans_by_id.get(plan_id)
        if plan is None:
            findings.append(
                ReadinessFinding(
                    "active-plan-missing",
                    "clarification",
                    "active_plans",
                    f"The linked active plan could not be found: {ref}",
                    True,
                )
            )
        elif plan.status in {"active", "seed", "needs-review"}:
            active_plans.append(plan)

    required_fields = (
        ("why", goal.why, "What makes this direction matter now?"),
        (
            "desired_change",
            goal.desired_change,
            "What observable change would make the next planning period worthwhile?",
        ),
        ("horizon", goal.horizon, "What broad horizon should the copilot plan within?"),
    )
    missing: list[str] = []
    for field, value, question in required_fields:
        if value is None:
            missing.append(field)
            findings.append(
                ReadinessFinding(
                    f"missing-{field.replace('_', '-')}",
                    "clarification",
                    field,
                    question,
                    True,
                )
            )

    if not goal.constraints:
        findings.append(
            ReadinessFinding(
                "constraints-unknown",
                "optional",
                "constraints",
                "Constraints are unknown; they may be clarified or left explicitly unknown.",
                False,
            )
        )
    if not goal.non_goals:
        findings.append(
            ReadinessFinding(
                "non-goals-unknown",
                "optional",
                "non_goals",
                "A boundary may help prevent the plan from becoming an obligation warehouse.",
                False,
            )
        )
    if goal.readiness == "ready" and missing:
        findings.append(
            ReadinessFinding(
                "readiness-contradiction",
                "hard-blocker",
                "readiness",
                "The goal is marked ready while required planning facts remain unknown.",
                True,
            )
        )
    if len(active_plans) > 1:
        findings.append(
            ReadinessFinding(
                "several-active-plans",
                "clarification",
                "active_plans",
                "Several active plans are linked; clarify whether they overlap or remain distinct.",
                True,
            )
        )
    elif len(active_plans) == 1:
        findings.append(
            ReadinessFinding(
                "existing-active-plan",
                "information",
                "active_plans",
                "An existing active plan may already cover this direction.",
                False,
            )
        )

    hard_blocked = any(item.category == "hard-blocker" for item in findings)
    clarification_needed = any(
        item.category == "clarification" and item.required for item in findings
    )
    if hard_blocked:
        path: ReadinessPath = "decline"
    elif clarification_needed:
        path = "clarify"
    elif active_plans:
        path = "link-existing-plan"
    elif goal.readiness == "parked":
        path = "park"
    else:
        path = "plan"
    return GoalReadinessReport(
        goal_id=goal.goal_id,
        source_path=goal.path,
        source_hash=goal.content_hash,
        ready=path in {"plan", "link-existing-plan"},
        path=path,
        findings=tuple(
            sorted(findings, key=lambda item: (not item.required, item.category, item.code))
        ),
        active_plan_ids=tuple(sorted(plan.plan_id for plan in active_plans)),
        missing_fields=tuple(missing),
    )
