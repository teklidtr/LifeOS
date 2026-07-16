import { BridgeClient } from "./protocol.js";
import {
  ReviewArtifact,
  ReviewDecisionKind,
  ReviewKind,
  ReviewPhaseId,
  ReviewSnapshot,
} from "./review-artifact.js";

export type ReviewWorkspaceOrigin = "today" | "week" | "active-note" | "history" | "command-palette";
export type ReviewWorkspaceStage = "idle" | "loading" | "ready" | "stale" | "blocked" | "error";

export interface ReviewPrompt { prompt_id: string; label: string; optional: boolean; phase_id?: ReviewPhaseId; }
export interface ReviewDueState { state: string; reason: string; phase_id?: ReviewPhaseId; }
export interface ReviewHistoryEntry { review_id: string; path: string; review_kind: ReviewKind; period_start: string; period_end: string; status: string; updated_at: string; previous_review_id?: string; next_review_id?: string; }
export interface ReviewOpenState {
  artifact: ReviewArtifact;
  snapshot: ReviewSnapshot;
  prompts: ReviewPrompt[];
  required_sections: string[];
  due: ReviewDueState;
  next_section?: string;
  active_phase?: ReviewPhaseId;
}
export interface ReviewProposalInput {
  itemId: string;
  evidenceFingerprint: string;
  targetPath: string;
  expectedTargetHash: string;
  action: "set_note_status" | "set_review_date" | "update_task_status" | "append_review_reference";
  value: string;
  rationale: string;
  taskId?: string;
}
export interface ReviewProposalResult { proposal_id: string; proposal_path: string; target_path: string; base_hash: string; }
export interface ReviewWorkspaceState {
  stage: ReviewWorkspaceStage;
  origin: ReviewWorkspaceOrigin;
  artifact?: ReviewArtifact;
  snapshot?: ReviewSnapshot;
  prompts: ReviewPrompt[];
  requiredSections: string[];
  due?: ReviewDueState;
  nextSection?: string;
  activePhase?: ReviewPhaseId;
  history: ReviewHistoryEntry[];
  focusTarget: string;
  detail?: string;
  recovery?: string;
}

function key(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function errorState(current: ReviewWorkspaceState, error: unknown): ReviewWorkspaceState {
  const value = error as { code?: string; message?: string; data?: Record<string, unknown> };
  const code = value.code ?? "unknown";
  const detail = value.message ?? String(error);
  if (["stale_write", "stale_review_item"].includes(code)) {
    return { ...current, stage: "stale", detail, recovery: "Reload the artifact and preserve newer Markdown edits.", focusTarget: "review-status" };
  }
  if (["unsupported_review_schema", "duplicate_review_identity", "invalid_review_artifact"].includes(code)) {
    return { ...current, stage: "blocked", detail, recovery: "Repair or migrate the review note before continuing.", focusTarget: "review-status" };
  }
  return { ...current, stage: "error", detail, recovery: "Retry, or open the Markdown artifact directly.", focusTarget: "review-status" };
}

export class ReviewWorkspaceController {
  state: ReviewWorkspaceState = {
    stage: "idle",
    origin: "command-palette",
    prompts: [],
    requiredSections: [],
    history: [],
    focusTarget: "review-workspace-title",
  };

  constructor(private readonly client: BridgeClient, private readonly openPath: (path: string) => void = () => undefined) {}

  private loading(origin = this.state.origin): void {
    this.state = { ...this.state, stage: "loading", origin, detail: undefined, recovery: undefined, focusTarget: "review-status" };
  }

  private accept(result: ReviewOpenState, origin = this.state.origin): ReviewOpenState {
    this.state = {
      ...this.state,
      stage: "ready",
      origin,
      artifact: result.artifact,
      snapshot: result.snapshot,
      prompts: result.prompts ?? [],
      requiredSections: result.required_sections ?? [],
      due: result.due,
      nextSection: result.next_section,
      activePhase: result.active_phase ?? result.artifact.metadata.current_phase,
      detail: undefined,
      recovery: undefined,
      focusTarget: result.next_section ? `section-${result.next_section}` : "review-artifact",
    };
    return result;
  }

  private requireArtifact(): ReviewArtifact {
    if (!this.state.artifact) throw new Error("Review artifact is not loaded.");
    return this.state.artifact;
  }

  async open(kind: ReviewKind, day: string, timezone: string, now: string, origin: ReviewWorkspaceOrigin, phase?: ReviewPhaseId): Promise<ReviewOpenState> {
    this.loading(origin);
    try {
      const result = await this.client.call<ReviewOpenState>("review.artifact.open", {
        kind, day, timezone, now, phase, refresh: true, idempotency_key: key(`review-open-${kind}-${day}`),
      });
      return this.accept(result, origin);
    } catch (error) {
      this.state = errorState(this.state, error);
      throw error;
    }
  }

  openDaily(day: string, timezone: string, now: string, phase: ReviewPhaseId = "morning", origin: ReviewWorkspaceOrigin = "today"): Promise<ReviewOpenState> {
    return this.open("daily", day, timezone, now, origin, phase);
  }

  openWeekly(day: string, timezone: string, now: string, origin: ReviewWorkspaceOrigin = "week"): Promise<ReviewOpenState> {
    return this.open("weekly", day, timezone, now, origin);
  }

  async openExisting(input: { reviewId?: string; path?: string }, now: string, origin: ReviewWorkspaceOrigin = "active-note"): Promise<ReviewOpenState> {
    this.loading(origin);
    try {
      const loaded = await this.client.call<{ artifact: ReviewArtifact; snapshot: ReviewSnapshot }>("review.artifact.load", {
        review_id: input.reviewId, path: input.path, now,
      });
      return this.accept({ artifact: loaded.artifact, snapshot: loaded.snapshot, prompts: [], required_sections: [], due: { state: loaded.artifact.metadata.status, reason: "Loaded from canonical Markdown." } }, origin);
    } catch (error) {
      this.state = errorState(this.state, error);
      throw error;
    }
  }

  async refresh(now: string): Promise<void> {
    const artifact = this.requireArtifact();
    this.loading();
    try {
      const result = await this.client.call<{ artifact: ReviewArtifact; snapshot: ReviewSnapshot }>("review.artifact.refresh", {
        review_id: artifact.metadata.review_id, expected_hash: artifact.content_hash, now,
        idempotency_key: key(`review-refresh-${artifact.metadata.review_id}`),
      });
      this.accept({ artifact: result.artifact, snapshot: result.snapshot, prompts: this.state.prompts, required_sections: this.state.requiredSections, due: this.state.due ?? { state: "open", reason: "Refreshed." }, next_section: this.state.nextSection, active_phase: this.state.activePhase });
    } catch (error) {
      this.state = errorState(this.state, error);
      throw error;
    }
  }

  async loadHistory(kind?: ReviewKind, limit = 50): Promise<ReviewHistoryEntry[]> {
    try {
      const history = await this.client.call<ReviewHistoryEntry[]>("review.artifact.history", { kind, limit });
      this.state = { ...this.state, history, focusTarget: "review-history" };
      return history;
    } catch (error) {
      this.state = errorState(this.state, error);
      throw error;
    }
  }

  async markSection(phaseId: ReviewPhaseId, sectionId: string, action: "complete" | "skip" | "reopen", now: string): Promise<ReviewArtifact> {
    return this.mutate("review.artifact.section", { phase_id: phaseId, section_id: sectionId, action, now }, `review-section-${sectionId}`);
  }

  async markPhase(phaseId: ReviewPhaseId, action: "complete" | "skip" | "reopen", now: string): Promise<ReviewArtifact> {
    return this.mutate("review.artifact.phase", { phase_id: phaseId, action, required_sections: this.state.requiredSections, now }, `review-phase-${phaseId}`);
  }

  async answer(promptId: string, value: string, now: string, phaseId?: ReviewPhaseId): Promise<ReviewArtifact> {
    return this.mutate("review.artifact.answer", { prompt_id: promptId, value, phase_id: phaseId, now }, `review-answer-${promptId}`);
  }

  async decide(itemId: string, evidenceFingerprint: string, decision: ReviewDecisionKind, now: string, note?: string, proposalId?: string): Promise<ReviewArtifact> {
    return this.mutate("review.artifact.decide", { item_id: itemId, evidence_fingerprint: evidenceFingerprint, decision, note, proposal_id: proposalId, now }, `review-decision-${itemId}`);
  }

  async createProposal(input: ReviewProposalInput, now: string): Promise<ReviewProposalResult> {
    const artifact = this.requireArtifact();
    return this.client.call<ReviewProposalResult>("review.proposal.create", {
      review_id: artifact.metadata.review_id,
      item_id: input.itemId,
      evidence_fingerprint: input.evidenceFingerprint,
      target_path: input.targetPath,
      expected_target_hash: input.expectedTargetHash,
      action: input.action,
      value: input.value,
      rationale: input.rationale,
      task_id: input.taskId,
      now,
    });
  }

  complete(now: string): Promise<ReviewArtifact> { return this.mutate("review.artifact.complete", { now }, "review-complete"); }
  skip(now: string, note?: string): Promise<ReviewArtifact> { return this.mutate("review.artifact.skip", { now, note }, "review-skip"); }
  reopen(now: string, phaseId?: ReviewPhaseId): Promise<ReviewArtifact> { return this.mutate("review.artifact.reopen", { now, phase_id: phaseId }, "review-reopen"); }

  openArtifact(): void { const artifact = this.requireArtifact(); this.openPath(artifact.path); }
  openSource(path: string): void { this.openPath(path); }
  openHistoryEntry(entry: ReviewHistoryEntry): void { this.openPath(entry.path); }

  keyboardLabels(): Record<string, string> {
    return {
      refresh: "Refresh managed review evidence",
      openArtifact: "Open canonical review Markdown",
      history: "Open review history",
      complete: "Complete review",
      skip: "Intentionally skip review",
      reopen: "Reopen review",
    };
  }

  private async mutate(method: string, fields: Record<string, unknown>, prefix: string): Promise<ReviewArtifact> {
    const artifact = this.requireArtifact();
    try {
      const updated = await this.client.call<ReviewArtifact>(method, {
        review_id: artifact.metadata.review_id,
        expected_hash: artifact.content_hash,
        idempotency_key: key(prefix),
        ...fields,
      });
      this.state = { ...this.state, stage: "ready", artifact: updated, activePhase: updated.metadata.current_phase, focusTarget: "review-status", detail: undefined, recovery: undefined };
      return updated;
    } catch (error) {
      this.state = errorState(this.state, error);
      throw error;
    }
  }
}
