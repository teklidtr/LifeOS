import { BridgeClient } from "./protocol.js";
import {
  AnalysisRecord,
  ExperimentArtifact,
  ExperimentComparison,
  ExperimentDesignWarning,
  ExperimentDueWindow,
  ExperimentIndexEntry,
  ExperimentIndexReport,
  ExperimentObservation,
  ExperimentProtocol,
  ExperimentProposalPreview,
  ExperimentProposalResult,
  ExperimentState,
  ObservationState,
  SafetyClassification,
  SourceReference,
} from "./experiment.js";

export type ExperimentWorkspaceOrigin =
  | "ribbon" | "command-palette" | "goal" | "plan" | "task" | "capture"
  | "daily-review" | "weekly-review" | "active-note" | "history" | "knowledge-conversation";

export type ExperimentWorkspaceStage =
  | "idle" | "loading" | "design" | "ready" | "empty" | "no-active"
  | "malformed-artifact" | "stale-artifact" | "unsupported-schema" | "missing-index"
  | "rebuild-in-progress" | "provider-unavailable" | "provider-timeout" | "unsafe-blocked"
  | "insufficient-evidence" | "conflicting-edits" | "proposal-created" | "proposal-stale"
  | "migration-required" | "error";

export interface ExperimentWorkspaceState {
  stage: ExperimentWorkspaceStage;
  origin: ExperimentWorkspaceOrigin;
  artifact?: ExperimentArtifact;
  experiments: ExperimentArtifact[];
  history: ExperimentIndexEntry[];
  warnings: ExperimentDesignWarning[];
  acknowledgedWarnings: string[];
  safety?: SafetyClassification;
  due: ExperimentDueWindow[];
  analysis?: AnalysisRecord;
  comparison?: ExperimentComparison;
  proposalPreview?: ExperimentProposalPreview;
  focusTarget: string;
  statusAnnouncement: string;
  detail?: string;
  recovery?: string;
}

export interface ExperimentCreateInput {
  title: string;
  description?: string;
  category?: string;
  protocol: ExperimentProtocol;
  origins?: SourceReference[];
  now?: string;
}

export interface ObservationInput {
  measureId: string;
  phaseId: string;
  observedAt: string;
  state: ObservationState;
  value?: number | boolean | string;
  note?: string;
  context?: string[];
  sourceRefs?: SourceReference[];
  observationId?: string;
  now?: string;
}

export interface ExperimentProposalInput {
  action: string;
  targetPath: string;
  content: string;
  createTarget: boolean;
  includedActions?: string[];
  excludedActions?: string[];
  now?: string;
}

export interface ExperimentWorkspaceAction {
  id: string;
  label: string;
  shortcut: string;
  ariaLabel: string;
}

function errorState(current: ExperimentWorkspaceState, error: unknown): ExperimentWorkspaceState {
  const value = error as { code?: string; message?: string };
  const code = value.code ?? "unknown";
  const detail = value.message ?? String(error);
  const common = { ...current, detail, focusTarget: "experiment-status", statusAnnouncement: detail };
  if (["stale_artifact", "stale_write"].includes(code)) return {
    ...common, stage: "stale-artifact", recovery: "Reload the canonical experiment and preserve newer Markdown edits.",
  };
  if (["proposal_stale", "stale_target"].includes(code)) return {
    ...common, stage: "proposal-stale", recovery: "Refresh the target and create a new proposal preview.",
  };
  if (["conflicting_edits", "protocol_amendment_required"].includes(code)) return {
    ...common, stage: "conflicting-edits", recovery: "Reload, then record a dated protocol amendment instead of rewriting history.",
  };
  if (["unsupported_schema", "unsupported_experiment_schema"].includes(code)) return {
    ...common, stage: "unsupported-schema", recovery: "Preview migration or open the Markdown artifact without managed editing.",
  };
  if (["malformed_artifact", "invalid_experiment_artifact", "duplicate_identity"].includes(code)) return {
    ...common, stage: "malformed-artifact", recovery: "Repair the canonical Markdown or rebuild to inspect diagnostics.",
  };
  if (["missing_index", "rebuild_required", "corrupt_index"].includes(code)) return {
    ...common, stage: "missing-index", recovery: "Rebuild disposable experiment history from canonical Markdown.",
  };
  if (["unsafe_experiment", "experiment_blocked", "emergency"].includes(code)) return {
    ...common, stage: "unsafe-blocked", recovery: "Do not schedule this intervention. Review the safety explanation and seek appropriate professional help.",
  };
  if (["insufficient_evidence", "analysis_required"].includes(code)) return {
    ...common, stage: "insufficient-evidence", recovery: "Inspect raw observations, collect more data, or record an inconclusive result.",
  };
  if (["provider_unavailable", "unavailable_provider", "missing_model"].includes(code)) return {
    ...common, stage: "provider-unavailable", recovery: "Continue with deterministic design, tracking, and analysis.",
  };
  if (code === "timeout") return {
    ...common, stage: "provider-timeout", recovery: "Retry optional assistance or continue without a model.",
  };
  if (["migration_required", "legacy_experiment"].includes(code)) return {
    ...common, stage: "migration-required", recovery: "Preview the conservative migration before applying it.",
  };
  return { ...common, stage: "error", recovery: "Retry, rebuild derived state, or open the canonical Markdown directly." };
}

export class ExperimentWorkspaceController {
  state: ExperimentWorkspaceState = {
    stage: "idle",
    origin: "command-palette",
    experiments: [],
    history: [],
    warnings: [],
    acknowledgedWarnings: [],
    due: [],
    focusTarget: "experiment-workspace-title",
    statusAnnouncement: "Experiment workspace is ready.",
  };

  constructor(private readonly client: BridgeClient, private readonly openPath: (path: string) => void = () => undefined) {}

  prepare(origin: ExperimentWorkspaceOrigin, sourcePath?: string): void {
    this.state = {
      ...this.state,
      stage: "design",
      origin,
      detail: sourcePath ? `Designing from ${sourcePath}. Review exactly what will be linked.` : "Design a small, observable experiment.",
      recovery: undefined,
      focusTarget: "experiment-question",
      statusAnnouncement: "Experiment design workspace opened.",
    };
  }

  acknowledgeWarning(code: string): void {
    if (!this.state.warnings.some((warning) => warning.code === code && warning.acknowledgeable)) return;
    this.state = {
      ...this.state,
      acknowledgedWarnings: [...new Set([...this.state.acknowledgedWarnings, code])],
      focusTarget: `warning-${code}`,
      statusAnnouncement: `Warning ${code} acknowledged.`,
    };
  }

  async create(input: ExperimentCreateInput): Promise<ExperimentArtifact> {
    this.loading("Creating canonical experiment Markdown.");
    try {
      const artifact = await this.client.call<ExperimentArtifact>("experiment.create", {
        title: input.title,
        description: input.description ?? "",
        category: input.category ?? "other",
        protocol: input.protocol,
        origins: input.origins ?? [],
        now: input.now,
      });
      return this.accept(artifact, "Experiment created. Protocol remains editable until activation.");
    } catch (error) { return this.fail(error); }
  }

  async list(states?: ExperimentState[]): Promise<ExperimentArtifact[]> {
    this.loading("Loading experiments.");
    try {
      const experiments = await this.client.call<ExperimentArtifact[]>("experiment.list", { states });
      this.state = {
        ...this.state,
        stage: experiments.length ? "ready" : "empty",
        experiments,
        detail: experiments.length ? undefined : "No experiments match this view.",
        recovery: experiments.length ? undefined : "Create an experiment or change the filters.",
        focusTarget: experiments.length ? "experiment-list" : "experiment-empty-state",
        statusAnnouncement: experiments.length ? `${experiments.length} experiments loaded.` : "No experiments found.",
      };
      return experiments;
    } catch (error) { return this.fail(error); }
  }

  async load(path: string, origin = this.state.origin): Promise<ExperimentArtifact> {
    this.loading("Loading canonical experiment Markdown.", origin);
    try {
      const artifact = await this.client.call<ExperimentArtifact>("experiment.load", { path });
      return this.accept(artifact, "Experiment loaded from canonical Markdown.");
    } catch (error) { return this.fail(error); }
  }

  async evaluateDesign(protocol: ExperimentProtocol): Promise<ExperimentDesignWarning[]> {
    try {
      const warnings = await this.client.call<ExperimentDesignWarning[]>("experiment.design.evaluate", {
        protocol,
        current_experiment_id: this.state.artifact?.metadata.experiment_id,
      });
      this.state = {
        ...this.state,
        warnings,
        safety: this.state.safety,
        stage: warnings.some((warning) => warning.severity === "blocking") ? "unsafe-blocked" : "design",
        focusTarget: warnings.length ? "experiment-warnings" : "experiment-question",
        statusAnnouncement: warnings.length ? `${warnings.length} design recommendations available.` : "No design warnings found.",
      };
      return warnings;
    } catch (error) { return this.fail(error); }
  }

  async classifySafety(protocol: ExperimentProtocol): Promise<SafetyClassification> {
    try {
      const safety = await this.client.call<SafetyClassification>("experiment.safety.classify", { protocol });
      this.state = {
        ...this.state,
        safety,
        stage: safety.allows_activation ? this.state.stage : "unsafe-blocked",
        detail: safety.explanation,
        recovery: safety.allows_activation ? undefined : "Do not activate this protocol. Follow the visible safety guidance.",
        focusTarget: "experiment-safety",
        statusAnnouncement: safety.explanation,
      };
      return safety;
    } catch (error) { return this.fail(error); }
  }

  transition(target: ExperimentState, now?: string, reason = ""): Promise<ExperimentArtifact> {
    const artifact = this.requireArtifact();
    return this.mutate("experiment.transition", { target, reason, now }, `Experiment moved to ${target}.`, artifact);
  }

  updateDraftProtocol(protocol: ExperimentProtocol, now?: string): Promise<ExperimentArtifact> {
    const artifact = this.requireArtifact();
    return this.mutate("experiment.protocol.update", { protocol, now }, "Draft protocol updated.", artifact);
  }

  addAmendment(protocol: ExperimentProtocol, reason: string, changes: string[], now?: string): Promise<ExperimentArtifact> {
    const artifact = this.requireArtifact();
    return this.mutate("experiment.amendment.add", { protocol, reason, changes, now }, "Protocol amendment recorded without rewriting prior history.", artifact);
  }

  recordObservation(input: ObservationInput): Promise<ExperimentArtifact> {
    const artifact = this.requireArtifact();
    return this.mutate("experiment.observation.record", {
      measure_id: input.measureId,
      phase_id: input.phaseId,
      observed_at: input.observedAt,
      state: input.state,
      value: input.value,
      note: input.note ?? "",
      context: input.context ?? [],
      source_refs: input.sourceRefs ?? [],
      observation_id: input.observationId,
      now: input.now,
    }, input.state === "measured" ? "Observation recorded." : `Observation recorded as ${input.state}; no zero was invented.`, artifact);
  }

  async loadDue(now: string): Promise<ExperimentDueWindow[]> {
    const artifact = this.requireArtifact();
    try {
      const due = await this.client.call<ExperimentDueWindow[]>("experiment.schedule.due", { path: artifact.path, now });
      this.state = {
        ...this.state,
        due,
        focusTarget: due.length ? "experiment-due-observations" : "experiment-status",
        statusAnnouncement: due.length ? `${due.length} observation windows loaded.` : "No observation is due.",
      };
      return due;
    } catch (error) { return this.fail(error); }
  }

  async analyze(now?: string, save = true): Promise<AnalysisRecord | ExperimentArtifact> {
    const artifact = this.requireArtifact();
    this.loading("Running local deterministic analysis.");
    try {
      const result = await this.client.call<AnalysisRecord | ExperimentArtifact>("experiment.analysis.run", {
        path: artifact.path, expected_hash: artifact.content_hash, now, save,
      });
      if ("metadata" in result) {
        const updated = this.accept(result, "Analysis saved to the experiment artifact.");
        const analysis = updated.metadata.analyses.at(-1);
        this.state = {
          ...this.state,
          analysis,
          stage: analysis?.status === "insufficient-evidence" ? "insufficient-evidence" : "ready",
          focusTarget: "experiment-analysis",
          statusAnnouncement: analysis?.status === "insufficient-evidence" ? "Analysis found insufficient evidence." : "Analysis ready.",
        };
        return updated;
      }
      this.state = {
        ...this.state,
        analysis: result,
        stage: result.status === "insufficient-evidence" ? "insufficient-evidence" : "ready",
        focusTarget: "experiment-analysis",
        statusAnnouncement: result.status === "insufficient-evidence" ? "Analysis found insufficient evidence." : "Analysis preview ready.",
      };
      return result;
    } catch (error) { return this.fail(error); }
  }

  recordConclusion(conclusion: string, notes: string, followUpDecisions: string[], now?: string): Promise<ExperimentArtifact> {
    const artifact = this.requireArtifact();
    return this.mutate("experiment.conclusion.record", {
      conclusion, notes, follow_up_decisions: followUpDecisions, now,
    }, "Conclusion recorded with limitations and follow-up decisions.", artifact);
  }

  async clone(title?: string, now?: string): Promise<ExperimentArtifact> {
    const artifact = this.requireArtifact();
    this.loading("Cloning the protocol as a new experiment.");
    try {
      const clone = await this.client.call<ExperimentArtifact>("experiment.clone", { path: artifact.path, title, now });
      return this.accept(clone, "New experiment created with preserved lineage.");
    } catch (error) { return this.fail(error); }
  }

  async loadHistory(): Promise<ExperimentIndexReport> {
    try {
      const report = await this.client.call<ExperimentIndexReport>("experiment.history.load", {});
      const stage = report.state === "missing-index" || report.state === "corrupt-index" ? "missing-index" : report.entries.length ? "ready" : "empty";
      this.state = {
        ...this.state,
        stage,
        history: report.entries,
        detail: stage === "missing-index" ? "Experiment history index is unavailable." : undefined,
        recovery: stage === "missing-index" ? "Rebuild disposable history from canonical Markdown." : undefined,
        focusTarget: stage === "missing-index" ? "experiment-history-recovery" : "experiment-history",
        statusAnnouncement: stage === "missing-index" ? "Experiment history needs rebuilding." : `${report.entries.length} history entries loaded.`,
      };
      return report;
    } catch (error) { return this.fail(error); }
  }

  async rebuildHistory(interruptAfter?: number): Promise<ExperimentIndexReport> {
    this.state = { ...this.state, stage: "rebuild-in-progress", focusTarget: "experiment-history-status", statusAnnouncement: "Experiment history rebuild started." };
    try {
      const report = await this.client.call<ExperimentIndexReport>("experiment.history.rebuild", { interrupt_after: interruptAfter });
      this.state = {
        ...this.state,
        stage: report.state === "interrupted" ? "rebuild-in-progress" : report.entries.length ? "ready" : "empty",
        history: report.entries,
        detail: report.state === "interrupted" ? "Rebuild was interrupted and can be resumed safely." : undefined,
        recovery: report.state === "interrupted" ? "Run rebuild again; canonical Markdown was not changed." : undefined,
        focusTarget: "experiment-history",
        statusAnnouncement: report.state === "interrupted" ? "Experiment history rebuild interrupted." : "Experiment history rebuilt.",
      };
      return report;
    } catch (error) { return this.fail(error); }
  }

  async compare(leftId: string, rightId: string): Promise<ExperimentComparison> {
    try {
      const comparison = await this.client.call<ExperimentComparison>("experiment.compare", { left_id: leftId, right_id: rightId });
      this.state = {
        ...this.state,
        comparison,
        detail: comparison.warning,
        focusTarget: "experiment-comparison",
        statusAnnouncement: comparison.compatible ? "Experiment comparison ready." : "Experiments are not directly compatible.",
      };
      return comparison;
    } catch (error) { return this.fail(error); }
  }

  async previewProposal(input: ExperimentProposalInput): Promise<ExperimentProposalPreview> {
    const artifact = this.requireArtifact();
    try {
      const preview = await this.client.call<ExperimentProposalPreview>("experiment.proposal.preview", this.proposalParams(artifact, input));
      this.state = { ...this.state, proposalPreview: preview, focusTarget: "experiment-proposal-preview", statusAnnouncement: "Proposal preview ready for review." };
      return preview;
    } catch (error) { return this.fail(error); }
  }

  async createProposal(input: ExperimentProposalInput): Promise<ExperimentProposalResult> {
    const artifact = this.requireArtifact();
    try {
      const result = await this.client.call<ExperimentProposalResult>("experiment.proposal.create", this.proposalParams(artifact, input));
      this.state = {
        ...this.state,
        stage: "proposal-created",
        proposalPreview: result.preview,
        detail: `Proposal ${result.proposal_id} created. Nothing has been applied.`,
        focusTarget: "experiment-proposal-created",
        statusAnnouncement: "Proposal created. External canonical data remains unchanged.",
      };
      return result;
    } catch (error) { return this.fail(error); }
  }

  openArtifact(): void { this.openPath(this.requireArtifact().path); }
  openHistoryEntry(entry: ExperimentIndexEntry): void { this.openPath(entry.path); }
  openObservationSource(observation: ExperimentObservation, index = 0): void {
    const source = observation.source_refs[index];
    if (source) this.openPath(source.path);
  }

  keyboardActions(): ExperimentWorkspaceAction[] {
    return [
      { id: "create", label: "Create", shortcut: "C", ariaLabel: "Create a new personal experiment draft" },
      { id: "observe", label: "Observe", shortcut: "O", ariaLabel: "Record a measured, missing, skipped, or unavailable observation" },
      { id: "pause", label: "Pause", shortcut: "P", ariaLabel: "Pause the active experiment without losing its schedule" },
      { id: "amend", label: "Amend", shortcut: "A", ariaLabel: "Record a dated protocol amendment with a reason" },
      { id: "analyze", label: "Analyze", shortcut: "N", ariaLabel: "Run deterministic descriptive analysis and inspect raw observations" },
      { id: "history", label: "History", shortcut: "H", ariaLabel: "Browse current and historical personal experiments" },
      { id: "proposal", label: "Proposal", shortcut: "R", ariaLabel: "Review a proposal for follow-up actions without applying it" },
      { id: "open", label: "Markdown", shortcut: "M", ariaLabel: "Open the canonical experiment Markdown artifact" },
    ];
  }

  private loading(announcement: string, origin = this.state.origin): void {
    this.state = { ...this.state, stage: "loading", origin, detail: undefined, recovery: undefined, focusTarget: "experiment-status", statusAnnouncement: announcement };
  }

  private accept(artifact: ExperimentArtifact, announcement: string): ExperimentArtifact {
    this.state = {
      ...this.state,
      stage: artifact.metadata.safety.allows_activation ? "ready" : "unsafe-blocked",
      artifact,
      safety: artifact.metadata.safety,
      analysis: artifact.metadata.analyses.at(-1),
      detail: artifact.metadata.safety.allows_activation ? undefined : artifact.metadata.safety.explanation,
      recovery: artifact.metadata.safety.allows_activation ? undefined : "Keep this experiment informational-only; do not activate the intervention.",
      focusTarget: artifact.metadata.safety.allows_activation ? "experiment-artifact" : "experiment-safety",
      statusAnnouncement: announcement,
    };
    return artifact;
  }

  private requireArtifact(): ExperimentArtifact {
    if (!this.state.artifact) throw new Error("Experiment artifact is not loaded.");
    return this.state.artifact;
  }

  private async mutate(method: string, fields: Record<string, unknown>, announcement: string, artifact: ExperimentArtifact): Promise<ExperimentArtifact> {
    this.loading(announcement);
    try {
      const updated = await this.client.call<ExperimentArtifact>(method, {
        path: artifact.path,
        expected_hash: artifact.content_hash,
        ...fields,
      });
      return this.accept(updated, announcement);
    } catch (error) { return this.fail(error); }
  }

  private proposalParams(artifact: ExperimentArtifact, input: ExperimentProposalInput): Record<string, unknown> {
    return {
      experiment_path: artifact.path,
      action: input.action,
      target_path: input.targetPath,
      content: input.content,
      create_target: input.createTarget,
      included_actions: input.includedActions ?? [],
      excluded_actions: input.excludedActions ?? [],
      now: input.now,
    };
  }

  private fail(error: unknown): never {
    this.state = errorState(this.state, error);
    throw error;
  }
}
