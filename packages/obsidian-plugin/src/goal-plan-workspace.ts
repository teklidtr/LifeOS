import { BridgeClient } from "./protocol.js";
import { CopilotPlanningSession } from "./goal-plan.js";

export type WorkspaceOrigin = "goal-note" | "quick-capture" | "goal-review" | "command-palette";
export type WorkspaceStage =
  | "idle"
  | "loading"
  | "context-preview"
  | "clarification"
  | "option-review"
  | "draft-edit"
  | "proposal-created"
  | "parked"
  | "abandoned"
  | "error";

export type WorkspaceErrorKind =
  | "missing-bridge"
  | "missing-model"
  | "permission-denied"
  | "protocol-incompatible"
  | "stale-source"
  | "invalid-output"
  | "bridge-restarted"
  | "recovery-required"
  | "unknown";

export interface ContextPreview {
  schema_version: number;
  goal_id: string;
  goal_hash: string;
  items: Array<{
    source_id: string;
    path: string;
    content_hash: string;
    inclusion_reason: string;
    excerpt: string;
    freshness: "current" | "stale";
    explicit: boolean;
    redactions: Array<{ label: string; occurrences: number }>;
  }>;
  omissions: Array<{ path: string; reason: string; detail: string }>;
  total_bytes: number;
  truncated: boolean;
}

export interface SessionSnapshot {
  session: CopilotPlanningSession;
  current_question?: {
    question_id: string;
    category: string;
    prompt: string;
    required: boolean;
    source: string;
    reason: string;
  };
  source_stale: boolean;
  allowed_outcomes: string[];
  recommended_outcomes: string[];
}

export interface PlanOptionSummary {
  option_id: string;
  title: string;
  strategy: string;
  desired_outcome: string;
  milestones: Array<{ milestone_id: string; title: string; outcome: string; wave: string }>;
  risks: string[];
  tradeoffs: string[];
  unresolved_questions: string[];
}

export interface PlanOptionSet {
  outcome: "options" | "no-viable-option" | "experiment-first" | "link-existing-plan";
  options: PlanOptionSummary[];
  diagnostics: string[];
}

export interface Decomposition {
  option_id: string;
  actions: Array<{
    task_id: string;
    title: string;
    duration?: number;
    milestone_id?: string;
    rationale?: string;
    verification: string;
  }>;
  milestones: Array<{ milestone_id: string; title: string; outcome: string; wave: string }>;
  findings: Array<{ code: string; severity: string; item_id: string; message: string }>;
}

export interface CapacityReport {
  fit: "comfortable" | "marginal" | "overload" | "unknown";
  findings: Array<{
    code: string;
    severity: string;
    title: string;
    evidence_refs: string[];
    missingness: string[];
    possible_adjustments: string[];
  }>;
  alternatives: string[];
}

export interface Explanation {
  option_id: string;
  summary: string;
  items: unknown[];
  omissions: unknown[];
  contradictions: unknown[];
}

export interface ProposalResult {
  proposal_id: string;
  proposal_path: string;
  plan_path: string;
}

export interface EditablePlanDraft {
  optionId: string;
  planId: string;
  planPath: string;
  planTitle: string;
  desiredOutcome: string;
  includedMilestoneIds: string[];
  includedActionIds: string[];
  milestoneEdits: Record<string, Record<string, unknown>>;
  actionEdits: Record<string, Record<string, unknown>>;
  goalUpdates: Record<string, unknown>;
  linkGoal: boolean;
  conflictEdits: Array<{ target_path: string; action: "pause" | "supersede" }>;
}

export interface WorkspaceState {
  stage: WorkspaceStage;
  origin?: WorkspaceOrigin;
  goalPath?: string;
  sessionId?: string;
  session?: SessionSnapshot;
  context?: ContextPreview;
  options?: PlanOptionSet;
  selectedOptionId?: string;
  decomposition?: Decomposition;
  capacity?: CapacityReport;
  explanation?: Explanation;
  draft?: EditablePlanDraft;
  proposal?: ProposalResult;
  error?: { kind: WorkspaceErrorKind; title: string; detail: string; retryable: boolean };
  focusTarget: string;
  dirty: boolean;
}

export interface WorkspacePersistence {
  load(sessionId: string): Promise<Partial<WorkspaceState> | undefined>;
  save(sessionId: string, state: Partial<WorkspaceState>): Promise<void>;
  clear(sessionId: string): Promise<void>;
}

export class MemoryWorkspacePersistence implements WorkspacePersistence {
  private values = new Map<string, Partial<WorkspaceState>>();
  async load(sessionId: string): Promise<Partial<WorkspaceState> | undefined> { return this.values.get(sessionId); }
  async save(sessionId: string, state: Partial<WorkspaceState>): Promise<void> { this.values.set(sessionId, structuredClone(state)); }
  async clear(sessionId: string): Promise<void> { this.values.delete(sessionId); }
}

export interface WorkspaceAction {
  id: string;
  label: string;
  shortcut: string;
  ariaLabel: string;
}

export class GoalPlanWorkspaceController {
  state: WorkspaceState = { stage: "idle", focusTarget: "workspace-title", dirty: false };

  constructor(
    private readonly client: BridgeClient,
    private readonly persistence: WorkspacePersistence = new MemoryWorkspacePersistence(),
  ) {}

  async startFromGoal(goalPath: string, sessionId: string, origin: WorkspaceOrigin = "goal-note"): Promise<SessionSnapshot> {
    return this.run(async () => {
      const session = await this.client.call<SessionSnapshot>("copilot.session.start", {
        goal_path: goalPath,
        session_id: sessionId,
      });
      this.state = {
        stage: session.current_question ? "clarification" : "context-preview",
        origin,
        goalPath,
        sessionId,
        session,
        focusTarget: session.current_question ? "clarification-question" : "context-preview",
        dirty: false,
      };
      await this.persist();
      return session;
    });
  }

  async startFromQuickCapture(goalPath: string, capturePath: string, sessionId: string): Promise<SessionSnapshot> {
    return this.run(async () => {
      const session = await this.client.call<SessionSnapshot>("copilot.session.start", {
        goal_path: goalPath,
        session_id: sessionId,
        selected_context_refs: [capturePath],
      });
      this.state = {
        stage: session.current_question ? "clarification" : "context-preview",
        origin: "quick-capture",
        goalPath,
        sessionId,
        session,
        focusTarget: session.current_question ? "clarification-question" : "context-preview",
        dirty: false,
      };
      await this.persist();
      return session;
    });
  }

  async resume(sessionId: string): Promise<SessionSnapshot> {
    return this.run(async () => {
      const session = await this.client.call<SessionSnapshot>("copilot.session.get", { session_id: sessionId });
      const local = await this.persistence.load(sessionId);
      const stage = this.stageForSession(session);
      this.state = {
        ...local,
        stage,
        sessionId,
        goalPath: session.session.goal_ref,
        session,
        focusTarget: stage === "clarification" ? "clarification-question" : "workspace-title",
        dirty: Boolean(local?.dirty),
      } as WorkspaceState;
      if (session.source_stale) this.setError("stale-source", "Goal changed during planning", "Review the current goal before continuing.", false);
      return session;
    });
  }

  async previewContext(options: { includePaths?: string[]; excludePaths?: string[]; redactTerms?: string[]; allowedSensitiveRoots?: string[] } = {}): Promise<ContextPreview> {
    const goalPath = this.requireGoalPath();
    return this.run(async () => {
      const context = await this.client.call<ContextPreview>("copilot.context.preview", {
        goal_path: goalPath,
        include_paths: options.includePaths ?? [],
        exclude_paths: options.excludePaths ?? [],
        redact_terms: options.redactTerms ?? [],
        allowed_sensitive_roots: options.allowedSensitiveRoots ?? [],
      });
      this.state = { ...this.state, stage: "context-preview", context, focusTarget: "context-item-list" };
      await this.persist();
      return context;
    });
  }

  async answerCurrent(responseKind: "answered" | "skipped" | "unknown" | "not-relevant", value?: string): Promise<SessionSnapshot> {
    const session = this.requireSession();
    const question = session.current_question;
    if (!question) throw new Error("No visible clarification question exists.");
    return this.run(async () => {
      const updated = await this.client.call<SessionSnapshot>("copilot.session.answer", {
        session_id: session.session.session_id,
        question_id: question.question_id,
        response_kind: responseKind,
        value,
        expected_revision: session.session.source_revision,
      });
      this.state = {
        ...this.state,
        stage: updated.current_question ? "clarification" : "context-preview",
        session: updated,
        focusTarget: updated.current_question ? "clarification-question" : "context-preview",
        dirty: false,
      };
      await this.persist();
      return updated;
    });
  }

  async closeSession(outcome: "ready-to-plan" | "experiment" | "park" | "continue-reflecting" | "link-existing-plan" | "abandon", label: string, rationale?: string): Promise<SessionSnapshot> {
    const session = this.requireSession();
    return this.run(async () => {
      const updated = await this.client.call<SessionSnapshot>("copilot.session.close", {
        session_id: session.session.session_id,
        outcome,
        label,
        rationale,
        expected_revision: session.session.source_revision,
      });
      const stage: WorkspaceStage = outcome === "park" ? "parked" : outcome === "abandon" ? "abandoned" : "context-preview";
      this.state = { ...this.state, stage, session: updated, focusTarget: "workspace-status", dirty: false };
      await this.persist();
      return updated;
    });
  }

  async generateOptions(asOf: string): Promise<PlanOptionSet> {
    const session = this.requireSession();
    return this.run(async () => {
      const options = await this.client.call<PlanOptionSet>("copilot.options.generate", {
        session_id: session.session.session_id,
        as_of: asOf,
      });
      this.state = { ...this.state, stage: "option-review", options, focusTarget: "option-list", dirty: false };
      await this.persist();
      return options;
    });
  }

  async selectOption(optionId: string, asOf: string): Promise<Decomposition> {
    const session = this.requireSession();
    if (!this.state.options?.options.some((item) => item.option_id === optionId)) throw new Error("Option is not in the visible option set.");
    return this.run(async () => {
      const decomposition = await this.client.call<Decomposition>("copilot.option.decompose", {
        session_id: session.session.session_id,
        option_id: optionId,
        as_of: asOf,
      });
      const option = this.state.options?.options.find((item) => item.option_id === optionId);
      if (!option) throw new Error("Option disappeared from the visible option set.");
      const draft: EditablePlanDraft = {
        optionId,
        planId: `plan-${optionId.replace(/^option-/, "")}`,
        planPath: `plans/${optionId.replace(/^option-/, "")}.md`,
        planTitle: option.title,
        desiredOutcome: option.desired_outcome,
        includedMilestoneIds: decomposition.milestones.map((item) => item.milestone_id),
        includedActionIds: decomposition.actions.map((item) => item.task_id),
        milestoneEdits: {}, actionEdits: {}, goalUpdates: {}, linkGoal: true, conflictEdits: [],
      };
      this.state = { ...this.state, stage: "draft-edit", selectedOptionId: optionId, decomposition, draft, focusTarget: "draft-plan-title", dirty: false };
      await this.persist();
      return decomposition;
    });
  }

  editDraft(patch: Partial<EditablePlanDraft>): void {
    if (!this.state.draft) throw new Error("No editable draft exists.");
    this.state = { ...this.state, draft: { ...this.state.draft, ...patch }, dirty: true, focusTarget: "draft-editor" };
  }

  includeMilestone(milestoneId: string, included: boolean): void {
    const draft = this.requireDraft();
    const values = new Set(draft.includedMilestoneIds);
    included ? values.add(milestoneId) : values.delete(milestoneId);
    const includedActionIds = included ? draft.includedActionIds : draft.includedActionIds.filter((id) => this.state.decomposition?.actions.find((action) => action.task_id === id)?.milestone_id !== milestoneId);
    this.editDraft({ includedMilestoneIds: [...values].sort(), includedActionIds });
  }

  includeAction(actionId: string, included: boolean): void {
    const draft = this.requireDraft();
    const values = new Set(draft.includedActionIds);
    included ? values.add(actionId) : values.delete(actionId);
    this.editDraft({ includedActionIds: [...values].sort() });
  }

  async saveDraft(): Promise<void> {
    await this.persist();
    this.state = { ...this.state, dirty: false, focusTarget: "draft-saved-status" };
  }

  async checkCapacity(asOf: string, availableMinutes: number | null, recurringWorkloads: unknown[] = [], adaptiveDurations?: Record<string, number | null>): Promise<CapacityReport> {
    const session = this.requireSession();
    const optionId = this.requireOptionId();
    return this.run(async () => {
      const capacity = await this.client.call<CapacityReport>("copilot.capacity.check", {
        session_id: session.session.session_id,
        option_id: optionId,
        as_of: asOf,
        available_minutes: availableMinutes,
        recurring_workloads: recurringWorkloads,
        adaptive_durations: adaptiveDurations,
      });
      this.state = { ...this.state, capacity, focusTarget: "capacity-findings" };
      await this.persist();
      return capacity;
    });
  }

  async explain(asOf: string, availableMinutes: number | null): Promise<Explanation> {
    const session = this.requireSession();
    const optionId = this.requireOptionId();
    return this.run(async () => {
      const explanation = await this.client.call<Explanation>("copilot.explain", {
        session_id: session.session.session_id,
        option_id: optionId,
        as_of: asOf,
        available_minutes: availableMinutes,
      });
      this.state = { ...this.state, explanation, focusTarget: "explanation-panel" };
      await this.persist();
      return explanation;
    });
  }

  async compare(optionIds: string[], asOf: string, availableMinutes: number | null): Promise<Record<string, unknown>> {
    const session = this.requireSession();
    return this.run(() => this.client.call<Record<string, unknown>>("copilot.compare", {
      session_id: session.session.session_id,
      option_ids: optionIds,
      as_of: asOf,
      available_minutes: availableMinutes,
    }));
  }

  async createProposal(asOf: string): Promise<ProposalResult> {
    const session = this.requireSession();
    const draft = this.requireDraft();
    return this.run(async () => {
      const proposal = await this.client.call<ProposalResult>("copilot.proposal.create", {
        session_id: session.session.session_id,
        option_id: draft.optionId,
        as_of: asOf,
        expected_revision: session.session.source_revision,
        plan_id: draft.planId,
        plan_path: draft.planPath,
        plan_title: draft.planTitle,
        desired_outcome: draft.desiredOutcome,
        included_milestone_ids: draft.includedMilestoneIds,
        included_action_ids: draft.includedActionIds,
        milestone_edits: draft.milestoneEdits,
        action_edits: draft.actionEdits,
        goal_updates: draft.goalUpdates,
        link_goal: draft.linkGoal,
        conflict_edits: draft.conflictEdits,
      });
      this.state = { ...this.state, stage: "proposal-created", proposal, dirty: false, focusTarget: "proposal-handoff" };
      await this.persistence.clear(session.session.session_id);
      return proposal;
    });
  }

  criticalActions(): WorkspaceAction[] {
    return [
      { id: "continue", label: "Continue planning", shortcut: "Enter", ariaLabel: "Continue to the next goal planning step" },
      { id: "preview", label: "Preview planning context", shortcut: "P", ariaLabel: "Preview every note sent to the planning model" },
      { id: "compare", label: "Compare plan options", shortcut: "C", ariaLabel: "Compare visible plan options by explicit criteria" },
      { id: "save", label: "Save local draft", shortcut: "S", ariaLabel: "Save the disposable draft for this planning session" },
      { id: "park", label: "Park this goal", shortcut: "K", ariaLabel: "Park the planning session without changing the goal" },
      { id: "abandon", label: "Abandon planning draft", shortcut: "A", ariaLabel: "Abandon this draft without changing canonical Markdown" },
      { id: "proposal", label: "Create reviewable proposal", shortcut: "G", ariaLabel: "Create a proposal that still requires review approval and application" },
    ];
  }

  markBridgeRestarted(): void {
    this.setError("bridge-restarted", "LifeOS engine restarted", "Resume the durable planning session to continue.", true);
  }

  private async persist(): Promise<void> {
    if (!this.state.sessionId) return;
    await this.persistence.save(this.state.sessionId, {
      origin: this.state.origin,
      goalPath: this.state.goalPath,
      selectedOptionId: this.state.selectedOptionId,
      context: this.state.context,
      options: this.state.options,
      decomposition: this.state.decomposition,
      capacity: this.state.capacity,
      explanation: this.state.explanation,
      draft: this.state.draft,
      dirty: this.state.dirty,
    });
  }

  private async run<T>(operation: () => Promise<T>): Promise<T> {
    const previous = this.state;
    this.state = { ...this.state, stage: "loading", focusTarget: "workspace-progress" };
    try { return await operation(); }
    catch (error) {
      this.state = previous;
      const mapped = this.mapError(error);
      this.setError(mapped.kind, mapped.title, mapped.detail, mapped.retryable);
      throw error;
    }
  }

  private mapError(error: unknown): { kind: WorkspaceErrorKind; title: string; detail: string; retryable: boolean } {
    const record = typeof error === "object" && error !== null ? error as Record<string, unknown> : {};
    const code = typeof record.code === "string" ? record.code : "";
    const message = error instanceof Error ? error.message : typeof record.message === "string" ? record.message : "Unexpected goal planning error.";
    if (code.includes("stale")) return { kind: "stale-source", title: "Planning source changed", detail: message, retryable: false };
    if (code.includes("permission") || code.includes("denied")) return { kind: "permission-denied", title: "Context permission denied", detail: message, retryable: false };
    if (code.includes("protocol") || code.includes("incompatible")) return { kind: "protocol-incompatible", title: "LifeOS versions are incompatible", detail: message, retryable: false };
    if (code.includes("model") || message.toLowerCase().includes("model")) return { kind: "missing-model", title: "Planning model is unavailable", detail: message, retryable: true };
    if (code.includes("recovery")) return { kind: "recovery-required", title: "Proposal recovery is required", detail: message, retryable: false };
    if (code.includes("copilot") || code.includes("invalid")) return { kind: "invalid-output", title: "Planning output was rejected", detail: message, retryable: true };
    if (message.toLowerCase().includes("bridge") || message.toLowerCase().includes("python")) return { kind: "missing-bridge", title: "LifeOS engine is unavailable", detail: message, retryable: true };
    return { kind: "unknown", title: "Goal planning could not continue", detail: message, retryable: true };
  }

  private setError(kind: WorkspaceErrorKind, title: string, detail: string, retryable: boolean): void {
    this.state = { ...this.state, stage: "error", error: { kind, title, detail, retryable }, focusTarget: "workspace-error" };
  }

  private stageForSession(snapshot: SessionSnapshot): WorkspaceStage {
    if (snapshot.session.status === "parked") return "parked";
    if (snapshot.session.status === "abandoned") return "abandoned";
    if (snapshot.session.status === "proposal-created") return "proposal-created";
    return snapshot.current_question ? "clarification" : "context-preview";
  }

  private requireGoalPath(): string {
    if (!this.state.goalPath) throw new Error("No goal path is selected.");
    return this.state.goalPath;
  }
  private requireSession(): SessionSnapshot {
    if (!this.state.session) throw new Error("No planning session is active.");
    return this.state.session;
  }
  private requireOptionId(): string {
    if (!this.state.selectedOptionId) throw new Error("No plan option is selected.");
    return this.state.selectedOptionId;
  }
  private requireDraft(): EditablePlanDraft {
    if (!this.state.draft) throw new Error("No editable draft exists.");
    return this.state.draft;
  }
}
