"""Python-owned semantic capability metadata for user-facing discovery surfaces."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
import re
from typing import Literal

CapabilityVisibility = Literal["explore", "internal"]
CapabilityMaturity = Literal["stable", "beta", "experimental"]
CapabilityBackingKind = Literal["bridge_method", "workflow", "data_source"]
CapabilityEntryPointKind = Literal[
    "obsidian_command",
    "obsidian_view",
    "cli",
    "mcp_tool",
    "workflow",
]

SEMANTIC_CAPABILITY_SCHEMA_VERSION = 1

_ALLOWED_VISIBILITY = frozenset({"explore", "internal"})
_ALLOWED_MATURITY = frozenset({"stable", "beta", "experimental"})
_ALLOWED_BACKING_KINDS = frozenset({"bridge_method", "workflow", "data_source"})
_ALLOWED_ENTRY_POINT_KINDS = frozenset(
    {"obsidian_command", "obsidian_view", "cli", "mcp_tool", "workflow"}
)
_CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)*$")
_BRIDGE_METHOD = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$")


class CapabilityDefinitionError(ValueError):
    """Raised when semantic capability metadata violates the registry contract."""


@dataclass(frozen=True, slots=True)
class CapabilityBackingReference:
    """Concrete LifeOS machinery that materially implements a semantic capability."""

    kind: CapabilityBackingKind
    ref: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "ref": self.ref}


@dataclass(frozen=True, slots=True)
class CapabilityEntryPoint:
    """Direct user entry point for a capability when one exists."""

    kind: CapabilityEntryPointKind
    target: str
    label: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"kind": self.kind, "target": self.target, "label": self.label}


@dataclass(frozen=True, slots=True)
class SemanticCapability:
    """Stable metadata describing one composed LifeOS capability."""

    capability_id: str
    name: str
    description: str
    category: str
    visibility: CapabilityVisibility
    maturity: CapabilityMaturity
    requirements: tuple[str, ...] = ()
    backing: tuple[CapabilityBackingReference, ...] = ()
    entry_points: tuple[CapabilityEntryPoint, ...] = ()
    example_prompts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "visibility": self.visibility,
            "maturity": self.maturity,
            "requirements": list(self.requirements),
            "backing": [item.to_dict() for item in self.backing],
            "entry_points": [item.to_dict() for item in self.entry_points],
            "example_prompts": list(self.example_prompts),
        }


class CapabilityRegistry:
    """Validated, deterministic in-process registry of semantic capabilities."""

    __slots__ = ("_by_id", "_capabilities")

    def __init__(self, definitions: Iterable[SemanticCapability]) -> None:
        capabilities = tuple(definitions)
        seen: set[str] = set()
        for capability in capabilities:
            self._validate_capability(capability)
            if capability.capability_id in seen:
                raise CapabilityDefinitionError(
                    f"Duplicate capability ID: {capability.capability_id}"
                )
            seen.add(capability.capability_id)
        self._capabilities = tuple(sorted(capabilities, key=lambda item: item.capability_id))
        self._by_id = {item.capability_id: item for item in self._capabilities}

    def list_capabilities(self) -> tuple[SemanticCapability, ...]:
        return self._capabilities

    def get(self, capability_id: str) -> SemanticCapability | None:
        return self._by_id.get(capability_id)

    def validate_bridge_methods(self, known_methods: Collection[str]) -> None:
        """Fail if any declared bridge-method backing reference is not implemented."""

        available = frozenset(known_methods)
        for capability in self._capabilities:
            for reference in capability.backing:
                if reference.kind == "bridge_method" and reference.ref not in available:
                    raise CapabilityDefinitionError(
                        f"Capability {capability.capability_id} references unknown bridge method "
                        f"{reference.ref}"
                    )

    @classmethod
    def _validate_capability(cls, capability: object) -> None:
        if not isinstance(capability, SemanticCapability):
            raise CapabilityDefinitionError(
                "Capability registry entries must be SemanticCapability instances"
            )
        if not isinstance(capability.capability_id, str) or not _CAPABILITY_ID.fullmatch(
            capability.capability_id
        ):
            raise CapabilityDefinitionError(f"Invalid capability ID: {capability.capability_id!r}")
        cls._require_text(capability.name, "name", capability.capability_id)
        cls._require_text(capability.description, "description", capability.capability_id)
        cls._require_text(capability.category, "category", capability.capability_id)
        if (
            not isinstance(capability.visibility, str)
            or capability.visibility not in _ALLOWED_VISIBILITY
        ):
            raise CapabilityDefinitionError(
                f"Invalid visibility for {capability.capability_id}: {capability.visibility!r}"
            )
        if not isinstance(capability.maturity, str) or capability.maturity not in _ALLOWED_MATURITY:
            raise CapabilityDefinitionError(
                f"Invalid maturity for {capability.capability_id}: {capability.maturity!r}"
            )
        if not isinstance(capability.requirements, tuple):
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} requirements must be a tuple"
            )
        if not isinstance(capability.backing, tuple) or not all(
            isinstance(item, CapabilityBackingReference) for item in capability.backing
        ):
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} backing must contain backing references"
            )
        if not isinstance(capability.entry_points, tuple) or not all(
            isinstance(item, CapabilityEntryPoint) for item in capability.entry_points
        ):
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} entry_points must contain entry points"
            )
        if not isinstance(capability.example_prompts, tuple):
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} example_prompts must be a tuple"
            )
        if not capability.backing:
            raise CapabilityDefinitionError(
                f"Capability {capability.capability_id} must declare implementation backing"
            )

        cls._validate_string_items(capability.requirements, "requirement", capability.capability_id)
        cls._validate_string_items(
            capability.example_prompts, "example prompt", capability.capability_id
        )

        backing_seen: set[tuple[str, str]] = set()
        for reference in capability.backing:
            if not isinstance(reference.kind, str) or reference.kind not in _ALLOWED_BACKING_KINDS:
                raise CapabilityDefinitionError(
                    f"Invalid backing kind for {capability.capability_id}: {reference.kind!r}"
                )
            cls._require_identifier(reference.ref, "backing reference", capability.capability_id)
            if reference.kind == "bridge_method" and not _BRIDGE_METHOD.fullmatch(reference.ref):
                raise CapabilityDefinitionError(
                    f"Malformed bridge method for {capability.capability_id}: {reference.ref!r}"
                )
            backing_key = (reference.kind, reference.ref)
            if backing_key in backing_seen:
                raise CapabilityDefinitionError(
                    f"Duplicate backing reference for {capability.capability_id}: {reference.ref}"
                )
            backing_seen.add(backing_key)

        entry_seen: set[tuple[str, str]] = set()
        for entry_point in capability.entry_points:
            if (
                not isinstance(entry_point.kind, str)
                or entry_point.kind not in _ALLOWED_ENTRY_POINT_KINDS
            ):
                raise CapabilityDefinitionError(
                    f"Invalid entry-point kind for {capability.capability_id}: {entry_point.kind!r}"
                )
            cls._require_identifier(
                entry_point.target, "entry-point target", capability.capability_id
            )
            if entry_point.label is not None:
                cls._require_text(entry_point.label, "entry-point label", capability.capability_id)
            entry_key = (entry_point.kind, entry_point.target)
            if entry_key in entry_seen:
                raise CapabilityDefinitionError(
                    f"Duplicate entry point for {capability.capability_id}: {entry_point.target}"
                )
            entry_seen.add(entry_key)

    @staticmethod
    def _require_text(value: object, field: str, capability_id: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise CapabilityDefinitionError(f"Capability {capability_id} has an empty {field}")

    @staticmethod
    def _require_identifier(value: object, field: str, capability_id: str) -> None:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(character.isspace() or ord(character) < 32 for character in value)
        ):
            raise CapabilityDefinitionError(
                f"Capability {capability_id} has a malformed {field}: {value!r}"
            )

    @classmethod
    def _validate_string_items(
        cls, values: tuple[str, ...], field: str, capability_id: str
    ) -> None:
        seen: set[str] = set()
        for value in values:
            cls._require_text(value, field, capability_id)
            if value in seen:
                raise CapabilityDefinitionError(
                    f"Capability {capability_id} has a duplicate {field}: {value!r}"
                )
            seen.add(value)


def _capability(
    capability_id: str,
    name: str,
    description: str,
    category: str,
    *,
    visibility: CapabilityVisibility = "explore",
    maturity: CapabilityMaturity = "stable",
    requirements: tuple[str, ...] = (),
    bridge_methods: tuple[str, ...] = (),
    workflows: tuple[str, ...] = (),
    data_sources: tuple[str, ...] = (),
    entry_points: tuple[CapabilityEntryPoint, ...] = (),
    example_prompts: tuple[str, ...] = (),
) -> SemanticCapability:
    """Build one static inventory entry without hiding its concrete backing kinds."""

    backing = tuple(
        CapabilityBackingReference("bridge_method", reference) for reference in bridge_methods
    )
    backing += tuple(CapabilityBackingReference("workflow", reference) for reference in workflows)
    backing += tuple(
        CapabilityBackingReference("data_source", reference) for reference in data_sources
    )
    return SemanticCapability(
        capability_id=capability_id,
        name=name,
        description=description,
        category=category,
        visibility=visibility,
        maturity=maturity,
        requirements=requirements,
        backing=backing,
        entry_points=entry_points,
        example_prompts=example_prompts,
    )


_CONFIGURED_VAULT = ("A configured LifeOS vault",)
_CONFIGURED_MCP = ("A configured LifeOS vault and LifeOS MCP connection",)


CAPABILITY_REGISTRY = CapabilityRegistry(
    (
        _capability(
            "system.vault-setup",
            "Set up a LifeOS vault",
            "Create the supported first-party LifeOS vault scaffold without overwriting existing content.",
            "Setup & Operations",
            workflows=("cli.vault-init",),
            entry_points=(CapabilityEntryPoint("cli", "lifeos.init", "lifeos init"),),
        ),
        _capability(
            "system.health-diagnostics",
            "Check LifeOS health",
            "Inspect vault status and installation readiness without turning disposable state into authority.",
            "Setup & Operations",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=("system.status",),
            workflows=("cli.doctor", "cli.status"),
            entry_points=(
                CapabilityEntryPoint("cli", "lifeos.doctor", "lifeos doctor"),
                CapabilityEntryPoint("cli", "lifeos.status", "lifeos status"),
            ),
        ),
        _capability(
            "system.home-node-service",
            "Run an always-on home node",
            "Serve the authenticated LifeOS MCP runtime with node-local disposable state and bounded remote access.",
            "Setup & Operations",
            requirements=(
                "A valid LifeOS configuration with vault and runtime directories",
                "Linux and the optional LifeOS MCP dependency group",
                "An explicit stable --actor-id",
                "Exactly one service token source via LIFEOS_SERVICE_TOKEN or LIFEOS_SERVICE_TOKEN_FILE with a token of at least 32 characters",
            ),
            workflows=("cli.home-node-service",),
            entry_points=(CapabilityEntryPoint("cli", "lifeos.serve", "lifeos serve"),),
        ),
        _capability(
            "planning.today",
            "Plan today",
            "Build a bounded daily menu from current plans, time, energy, motivation, and work-mode constraints.",
            "Planning",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=("today.get",),
            workflows=("cli.plan-today",),
            entry_points=(
                CapabilityEntryPoint("obsidian_view", "lifeos-today", "Open LifeOS Today"),
                CapabilityEntryPoint("obsidian_command", "lifeos-open-today", "Open LifeOS Today"),
                CapabilityEntryPoint("cli", "lifeos.plan.today", "lifeos plan today"),
            ),
            example_prompts=(
                "Use my LifeOS plans and current constraints to show what I could focus on today.",
            ),
        ),
        _capability(
            "planning.goal-to-plan",
            "Turn a goal into a plan",
            "Inspect a LifeOS goal, clarify missing context, compare options, and draft reviewable planning changes.",
            "Planning",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "copilot.note.inspect",
                "copilot.goal.readiness",
                "copilot.context.preview",
                "copilot.session.start",
                "copilot.session.get",
                "copilot.session.answer",
                "copilot.session.close",
                "copilot.options.generate",
                "copilot.option.decompose",
                "copilot.capacity.check",
                "copilot.explain",
                "copilot.compare",
                "copilot.counterfactual",
                "copilot.proposal.create",
                "copilot.replanning.scan",
                "copilot.replanning.review",
                "copilot.replanning.suppress",
                "copilot.replanning.proposal.create",
            ),
            entry_points=(
                CapabilityEntryPoint(
                    "obsidian_view", "lifeos-goal-plan", "Open Goal-to-Plan Copilot"
                ),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-open-goal-plan", "Open Goal-to-Plan Copilot"
                ),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-plan-active-goal", "Plan from Active Goal Note"
                ),
            ),
            example_prompts=(
                "Use my active LifeOS goal and nearby context to help me build a realistic plan.",
            ),
        ),
        _capability(
            "planning.adaptive-feedback",
            "Adapt planning from feedback",
            "Record check-ins and outcomes, explain planning signals, and propose bounded preference changes from observed feedback.",
            "Planning",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "attention.evaluate",
                "attention.preference",
                "daily.capture",
                "daily.checkin",
                "daily.task_outcome",
                "daily.review",
                "feedback.dataset.status",
                "feedback.duration",
                "feedback.capacity",
                "feedback.avoidance",
                "feedback.plan",
                "feedback.explain",
                "feedback.preferences.get",
                "feedback.preferences.update",
                "feedback.outcome.correct",
                "feedback.proposal.create",
            ),
            data_sources=("journal.feedback-observations",),
        ),
        _capability(
            "study.review-sessions",
            "Build study review sessions",
            "Turn due flashcards into time-bounded review workloads and track the resulting study session.",
            "Study",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "study.plan",
                "study.session.start",
                "study.session.transition",
                "study.session.open",
            ),
            workflows=("cli.study-review",),
            data_sources=("flashcards.canonical",),
            entry_points=(
                CapabilityEntryPoint("cli", "lifeos.study.review", "lifeos study review"),
            ),
        ),
        _capability(
            "reflection.reviews",
            "Run daily and weekly reviews",
            "Build, answer, save, revisit, and propose changes from durable LifeOS review artifacts.",
            "Reflection",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "review.build",
                "review.progress",
                "review.save",
                "review.artifact.open",
                "review.artifact.load",
                "review.artifact.refresh",
                "review.artifact.history",
                "review.artifact.section",
                "review.artifact.phase",
                "review.artifact.answer",
                "review.artifact.decide",
                "review.artifact.complete",
                "review.artifact.skip",
                "review.artifact.reopen",
                "review.proposal.create",
            ),
            entry_points=(
                CapabilityEntryPoint("obsidian_view", "lifeos-reviews", "Open LifeOS Reviews"),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-open-daily-review", "Open Today's Review"
                ),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-open-weekly-review", "Open This Week's Review"
                ),
            ),
        ),
        _capability(
            "knowledge.semantic-retrieval",
            "Build bounded context",
            "Select inspectable LifeOS evidence with hybrid retrieval when available and deterministic lexical fallback otherwise.",
            "Knowledge",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=("retrieval.search",),
            workflows=("context.bounded-pack",),
            data_sources=("vault.canonical-markdown", "retrieval.disposable-index"),
            entry_points=(
                CapabilityEntryPoint("cli", "lifeos.context.build", "lifeos context build"),
                CapabilityEntryPoint("mcp_tool", "vault_context", "Build a LifeOS context pack"),
            ),
            example_prompts=(
                "Build a LifeOS context pack for this question and keep the evidence bounded.",
            ),
        ),
        _capability(
            "knowledge.conversations",
            "Have knowledge conversations",
            "Ask scoped questions over LifeOS sources, pin or exclude evidence, branch conversations, and draft grounded follow-up changes.",
            "Knowledge",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "conversation.create",
                "conversation.list",
                "conversation.load",
                "conversation.ask",
                "conversation.scope.update",
                "conversation.source.pin",
                "conversation.source.exclude",
                "conversation.branch",
                "conversation.rename",
                "conversation.archive",
                "conversation.stale.check",
                "conversation.proposal.preview",
                "conversation.proposal.create",
            ),
            entry_points=(
                CapabilityEntryPoint(
                    "obsidian_view", "lifeos-knowledge-conversation", "Open Knowledge Conversation"
                ),
                CapabilityEntryPoint(
                    "obsidian_command",
                    "lifeos-open-knowledge-conversation",
                    "Open Knowledge Conversation",
                ),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-ask-active-note", "Ask About Active Note"
                ),
            ),
            example_prompts=(
                "Use my LifeOS notes to answer this question and keep the supporting sources visible.",
            ),
        ),
        _capability(
            "experiments.personal-experiments",
            "Run personal experiments",
            "Design, track, analyze, compare, and conclude reviewable personal experiments without treating observations as automatic causation.",
            "Experiments",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "experiment.create",
                "experiment.list",
                "experiment.load",
                "experiment.design.evaluate",
                "experiment.safety.classify",
                "experiment.transition",
                "experiment.protocol.update",
                "experiment.amendment.add",
                "experiment.observation.record",
                "experiment.schedule.due",
                "experiment.analysis.run",
                "experiment.conclusion.record",
                "experiment.clone",
                "experiment.history.load",
                "experiment.privacy.preview",
                "experiment.compare",
                "experiment.proposal.preview",
                "experiment.proposal.create",
            ),
            entry_points=(
                CapabilityEntryPoint(
                    "obsidian_view", "lifeos-experiments", "Open Personal Experiments"
                ),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-create-experiment", "Create Personal Experiment"
                ),
            ),
        ),
        _capability(
            "capture.rich-capture",
            "Capture real-world evidence",
            "Save meals, exercise, text, and attachments as canonical captures with local extraction, integrity checks, links, and reviewable follow-up changes.",
            "Capture",
            maturity="beta",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "capture.create",
                "capture.read",
                "capture.update",
                "capture.transition",
                "capture.list",
                "capture.filter",
                "capture.visualization.build",
                "capture.attachment.add",
                "capture.attachment.remove",
                "capture.attachment.audit",
                "capture.enrichment.start",
                "capture.enrichment.run",
                "capture.enrichment.cancel",
                "capture.enrichment.retry",
                "capture.inference.decide",
                "capture.link",
                "capture.unlink",
                "capture.split",
                "capture.merge.preview",
                "capture.merge.apply",
                "capture.privacy.preview",
                "capture.proposal.preview",
                "capture.proposal.create",
            ),
            entry_points=(
                CapabilityEntryPoint("obsidian_view", "lifeos-rich-capture", "Open Rich Capture"),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-open-rich-capture", "Open Rich Capture"
                ),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-quick-capture-meal", "Quick Capture Meal"
                ),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-quick-capture-exercise", "Quick Capture Exercise"
                ),
            ),
        ),
        _capability(
            "personal-model.evidence-backed-reflection",
            "Build an evidence-backed Personal Model",
            "Review working hypotheses about recurring patterns with bounded evidence, explicit uncertainty, and proposal-gated semantic changes.",
            "Reflection",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "personal-model.workspace.get",
                "personal-model.proposal.preview",
                "personal-model.proposal.create",
            ),
            workflows=("mcp.personal-pattern-proposal",),
            data_sources=("patterns.canonical-hypotheses",),
            entry_points=(
                CapabilityEntryPoint(
                    "obsidian_view", "lifeos-personal-model", "Open Personal Model"
                ),
                CapabilityEntryPoint(
                    "obsidian_command", "lifeos-open-personal-model", "Open Personal Model"
                ),
                CapabilityEntryPoint(
                    "mcp_tool", "personal_pattern_propose", "Propose a personal-pattern seed"
                ),
                CapabilityEntryPoint(
                    "mcp_tool",
                    "personal_pattern_review_proposal",
                    "Propose a reviewed pattern revision",
                ),
            ),
            example_prompts=(
                "Use only the LifeOS evidence I selected to draft a reviewable pattern hypothesis.",
            ),
        ),
        _capability(
            "change.proposal-review",
            "Review and apply proposed changes",
            "Inspect LifeOS proposals, verify immutable review context, and move approved changes through the explicit proposal lifecycle.",
            "Change Review",
            requirements=_CONFIGURED_VAULT,
            bridge_methods=(
                "proposal.list",
                "proposal.inspect",
                "proposal.prepare",
                "proposal.execute",
                "ownership.orphans.list",
                "ownership.release.proposal.create",
            ),
            workflows=("mcp.proposal-lifecycle",),
            entry_points=(
                CapabilityEntryPoint("obsidian_view", "lifeos-proposals", "Open Proposals"),
                CapabilityEntryPoint("obsidian_command", "lifeos-open-proposals", "Open Proposals"),
                CapabilityEntryPoint("mcp_tool", "proposal_submit", "Submit a proposal"),
                CapabilityEntryPoint("mcp_tool", "proposal_approve", "Approve a proposal"),
                CapabilityEntryPoint("mcp_tool", "proposal_apply", "Apply an approved proposal"),
            ),
        ),
        _capability(
            "knowledge.vault-exploration",
            "Explore the vault with an agent",
            "Give an MCP-connected agent bounded read-only tools for listing, searching, reading, linking, and identifying canonical LifeOS notes.",
            "Knowledge",
            requirements=_CONFIGURED_MCP,
            workflows=("mcp.vault-exploration",),
            data_sources=("vault.canonical-markdown",),
            entry_points=(
                CapabilityEntryPoint("mcp_tool", "vault_list", "List vault notes"),
                CapabilityEntryPoint("mcp_tool", "vault_search", "Search vault notes"),
                CapabilityEntryPoint("mcp_tool", "vault_read_markdown", "Read a Markdown note"),
                CapabilityEntryPoint("mcp_tool", "vault_read_many", "Read several notes"),
                CapabilityEntryPoint("mcp_tool", "vault_links", "Inspect note links"),
                CapabilityEntryPoint("mcp_tool", "vault_note_identity", "Resolve note identity"),
                CapabilityEntryPoint("mcp_tool", "wiki_search", "Search durable wiki notes"),
            ),
            example_prompts=(
                "Search my LifeOS vault for the evidence relevant to this question before answering.",
            ),
        ),
        _capability(
            "knowledge.wiki-evolution",
            "Evolve durable wiki knowledge",
            "Turn selected canonical evidence into coordinated reviewable wiki creates or exact-section updates while preserving source history.",
            "Knowledge",
            requirements=_CONFIGURED_MCP,
            workflows=("mcp.wiki-evolution",),
            data_sources=("wiki.generated-provenance",),
            entry_points=(
                CapabilityEntryPoint(
                    "mcp_tool", "ingestion_evolve_wiki_proposal", "Draft a wiki evolution"
                ),
                CapabilityEntryPoint(
                    "mcp_tool",
                    "ingestion_evolve_wiki_batch_proposal",
                    "Draft coordinated wiki evolutions",
                ),
            ),
            example_prompts=(
                "Use this LifeOS source to evolve durable wiki knowledge only where it adds a reusable delta.",
            ),
        ),
        _capability(
            "study.learning-evolution",
            "Evolve study material",
            "Turn a selected study source into reviewable wiki changes plus selective flashcards when retrieval practice serves the learning goal.",
            "Study",
            requirements=_CONFIGURED_MCP,
            workflows=("mcp.study-learning-evolution",),
            data_sources=("study.canonical-sources",),
            entry_points=(
                CapabilityEntryPoint(
                    "mcp_tool",
                    "study_evolve_learning_proposal",
                    "Draft a study-learning evolution",
                ),
            ),
            example_prompts=(
                "Use this LifeOS study source to improve durable notes and add only flashcards worth retrieving later.",
            ),
        ),
        _capability(
            "knowledge.evidence-grounded-research",
            "Capture external research evidence",
            "Check existing LifeOS context first, then capture selected external evidence as hash-bound raw research only when a material gap remains.",
            "Knowledge",
            requirements=_CONFIGURED_MCP,
            workflows=("mcp.evidence-grounded-research",),
            data_sources=("raw.research-evidence",),
            entry_points=(
                CapabilityEntryPoint(
                    "mcp_tool", "research_query_context", "Check existing LifeOS research context"
                ),
                CapabilityEntryPoint(
                    "mcp_tool", "research_capture_evidence", "Capture selected research evidence"
                ),
            ),
            example_prompts=(
                "Check my LifeOS knowledge first, then preserve only the external evidence needed to fill a real gap.",
            ),
        ),
        _capability(
            "observation.pattern-analysis",
            "Analyze tentative personal patterns",
            "Compare journal metrics or activities with explicit sample counts, uncertainty, and noncausal caveats.",
            "Observation",
            requirements=_CONFIGURED_VAULT,
            workflows=("cli.observe-patterns",),
            data_sources=("journal.metrics-and-activities",),
            entry_points=(
                CapabilityEntryPoint("cli", "lifeos.observe.patterns", "lifeos observe patterns"),
            ),
        ),
        _capability(
            "knowledge.graph-views",
            "Build derived graph views",
            "Build and inspect disposable knowledge, provenance, personal-pattern, and system graph projections from canonical state.",
            "Knowledge",
            requirements=_CONFIGURED_VAULT + ("features.graphify enabled in lifeos.yml",),
            workflows=("cli.graph-views",),
            data_sources=("graph.derived-views",),
            entry_points=(
                CapabilityEntryPoint("cli", "lifeos.graph.build", "lifeos graph build"),
                CapabilityEntryPoint("cli", "lifeos.graph.status", "lifeos graph status"),
            ),
        ),
        _capability(
            "sharing.purpose-specific-exports",
            "Build purpose-specific exports",
            "Create inspectable public-wiki, study, trusted-agent, or personal-review bundles without replacing canonical Markdown.",
            "Sharing",
            requirements=_CONFIGURED_VAULT + ("features.exports enabled in lifeos.yml",),
            workflows=("cli.purpose-specific-exports",),
            data_sources=("exports.derived-bundles",),
            entry_points=(
                CapabilityEntryPoint("cli", "lifeos.export.build", "lifeos export build"),
                CapabilityEntryPoint("cli", "lifeos.export.status", "lifeos export status"),
            ),
        ),
        _capability(
            "system.capability-discovery",
            "Capability discovery",
            "Provides machine-readable semantic capability metadata to first-party LifeOS discovery surfaces.",
            "System",
            visibility="internal",
            bridge_methods=("capability.list", "capability.get"),
        ),
        _capability(
            "system.desktop-runtime",
            "Desktop runtime plumbing",
            "Low-level desktop process health and cancellation primitives used by first-party workspaces rather than exposed as Explore abilities.",
            "System",
            visibility="internal",
            bridge_methods=("system.health", "request.cancel"),
        ),
        _capability(
            "system.scheduler-runtime",
            "Scheduler runtime plumbing",
            "Background scheduler configuration and service installation primitives that support higher-level planning and review workflows.",
            "System",
            visibility="internal",
            bridge_methods=(
                "scheduler.config.get",
                "scheduler.config.set",
                "scheduler.service.status",
                "scheduler.service.install",
                "scheduler.service.uninstall",
            ),
        ),
        _capability(
            "system.registry-maintenance",
            "Derived-state maintenance",
            "Explicit registry refresh and MCP activity inspection used to maintain or diagnose disposable runtime state.",
            "System",
            visibility="internal",
            workflows=("cli.registry-refresh", "mcp.runtime-maintenance"),
            entry_points=(
                CapabilityEntryPoint("cli", "lifeos.scan", "lifeos scan"),
                CapabilityEntryPoint("mcp_tool", "registry_refresh", "Refresh registry state"),
                CapabilityEntryPoint("mcp_tool", "runtime_activity", "Inspect MCP activity"),
            ),
        ),
        _capability(
            "reflection.review-maintenance",
            "Review artifact maintenance",
            "Migration and rebuild primitives for durable review artifacts; they support recovery and compatibility rather than a separate Explore feature.",
            "Reflection",
            visibility="internal",
            bridge_methods=(
                "review.artifact.migration.preview",
                "review.artifact.migration.apply",
                "review.artifact.rebuild",
            ),
        ),
        _capability(
            "planning.feedback-maintenance",
            "Feedback maintenance",
            "Dataset rebuild, preference migration, reset, and replay operations that maintain the adaptive-feedback subsystem.",
            "Planning",
            visibility="internal",
            bridge_methods=(
                "feedback.dataset.rebuild",
                "feedback.preferences.migrate",
                "feedback.reset",
                "feedback.replay",
            ),
        ),
        _capability(
            "knowledge.retrieval-maintenance",
            "Retrieval index maintenance",
            "Health, rebuild, recovery, and synchronization operations for disposable retrieval indexes.",
            "Knowledge",
            visibility="internal",
            bridge_methods=(
                "retrieval.index.health",
                "retrieval.index.rebuild",
                "retrieval.index.recovery.plan",
                "retrieval.index.recover",
                "retrieval.index.sync",
            ),
        ),
        _capability(
            "experiments.maintenance",
            "Experiment maintenance",
            "History rebuild, migration, and recovery-audit operations supporting personal experiments.",
            "Experiments",
            visibility="internal",
            bridge_methods=(
                "experiment.history.rebuild",
                "experiment.migration.preview",
                "experiment.migration.apply",
                "experiment.recovery.audit",
            ),
        ),
        _capability(
            "capture.maintenance",
            "Capture maintenance",
            "Rebuild and migration operations for capture-derived state and schema compatibility.",
            "Capture",
            visibility="internal",
            bridge_methods=(
                "capture.rebuild",
                "capture.migration.preview",
                "capture.migration.apply",
            ),
        ),
        _capability(
            "personal-model.maintenance",
            "Personal Model maintenance",
            "Explicit rebuild of disposable Personal Model projections from canonical pattern hypotheses.",
            "Reflection",
            visibility="internal",
            bridge_methods=("personal-model.rebuild",),
        ),
        _capability(
            "knowledge.ingestion-compatibility",
            "Legacy ingestion compatibility",
            "Older narrow ingestion proposal tools retained for compatibility while wiki and study evolution use the preferred composed workflows.",
            "Knowledge",
            visibility="internal",
            workflows=("mcp.ingestion-compatibility",),
            entry_points=(
                CapabilityEntryPoint(
                    "mcp_tool", "research_create_wiki_proposal", "Legacy research wiki proposal"
                ),
                CapabilityEntryPoint(
                    "mcp_tool", "ingestion_create_wiki_proposal", "Legacy wiki create proposal"
                ),
                CapabilityEntryPoint(
                    "mcp_tool",
                    "ingestion_create_wiki_and_update_section_proposal",
                    "Legacy combined wiki proposal",
                ),
                CapabilityEntryPoint(
                    "mcp_tool",
                    "ingestion_update_wiki_section_proposal",
                    "Legacy wiki section proposal",
                ),
            ),
        ),
    )
)
