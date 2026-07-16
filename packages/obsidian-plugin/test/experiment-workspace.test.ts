import assert from "node:assert/strict";
import test from "node:test";
import {
  BridgeClient,
  ExperimentArtifact,
  ExperimentProtocol,
  ExperimentWorkspaceController,
  HandshakeResult,
  LifeOSSettings,
} from "../src/index.js";

const protocol: ExperimentProtocol = {
  question: "Does a morning walk relate to focus?",
  hypothesis: "Focus ratings will be higher after a morning walk.",
  rationale: "A small observable comparison.",
  intervention: "Walk for 20 minutes after breakfast",
  constants: ["same study block"],
  comparison: "Two-day no-walk baseline",
  baseline_requirements: "Two baseline observations",
  outcome_measures: [{
    measure_id: "focus", display_name: "Focus rating", kind: "rating", role: "primary",
    cadence: "daily", source: "manual", direction: "increase", missing_behavior: "report", aggregation: "mean",
  }, {
    measure_id: "walked", display_name: "Walk completed", kind: "completion", role: "adherence",
    cadence: "daily", source: "manual", direction: "increase", missing_behavior: "report", aggregation: "rate",
  }],
  phases: [
    { phase_id: "base", name: "Baseline", kind: "baseline", start_date: "2026-07-16", end_date: "2026-07-17", intervention: "" },
    { phase_id: "walk", name: "Morning walk", kind: "intervention", start_date: "2026-07-18", end_date: "2026-07-21", intervention: "Morning walk" },
  ],
  adherence_expectation: "Record whether the walk happened.",
  confounders: ["sleep"], risks: [], stop_rules: ["Stop for pain"],
  success_criteria: ["Intervention average is higher"], failure_criteria: ["No improvement"],
  inconclusive_criteria: ["Fewer than four measured focus ratings"],
  schedule: { timezone: "Europe/Istanbul", time: "12:00", window_minutes: 60, grace_minutes: 60 },
};

function artifact(state: ExperimentArtifact["metadata"]["state"] = "drafting"): ExperimentArtifact {
  return {
    path: "experiments/2026/morning-walk-exp-123.md", content_hash: "sha256:abc", human_body: "My notes\n",
    metadata: {
      type: "personal-experiment", experiment_schema: 1, experiment_id: "exp-123", title: "Morning walk",
      description: "", state, category: "focus", created_at: "2026-07-16T09:00:00+00:00", updated_at: "2026-07-16T09:00:00+00:00",
      protocol, safety: { level: "ordinary", codes: [], explanation: "No blocking issue.", professional_guidance_recommended: false, allows_activation: true },
      origins: [], linked_habits: [], linked_metrics: [], linked_tasks: [], linked_diary: [], linked_checkins: [], linked_reviews: [], source_refs: [], observations: [], amendments: [], lifecycle: [], analyses: [], conclusion_notes: "", follow_up_decisions: [],
    },
  };
}

class Client implements BridgeClient {
  calls: Array<[string, Record<string, unknown>]> = [];
  failure?: { code: string; message: string };
  current = artifact();
  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }
  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push([method, params]);
    if (this.failure) throw this.failure;
    if (method === "experiment.create" || method === "experiment.load") return this.current as T;
    if (method === "experiment.list") return [this.current] as T;
    if (method === "experiment.design.evaluate") return [{
      code: "short-duration", severity: "recommendation", title: "Duration is short", explanation: "Few observations.",
      recommendation: "Extend or precommit to inconclusive.", evidence: ["6"], acknowledgeable: true,
    }] as T;
    if (method === "experiment.safety.classify") return this.current.metadata.safety as T;
    if (["experiment.transition", "experiment.protocol.update", "experiment.amendment.add", "experiment.observation.record", "experiment.conclusion.record"].includes(method)) {
      this.current = { ...this.current, content_hash: `sha256:${this.calls.length}` };
      return this.current as T;
    }
    if (method === "experiment.schedule.due") return [{ measure_id: "focus", phase_id: "walk", due_at: "2026-07-18T12:00:00+03:00", opens_at: "2026-07-18T11:00:00+03:00", closes_at: "2026-07-18T13:00:00+03:00", status: "open" }] as T;
    if (method === "experiment.analysis.run") return { analysis_id: "ana-1", created_at: "2026-07-21T12:00:00Z", status: "insufficient-evidence", summaries: [], observation_ids: [], assumptions: [], missing_data_treatment: "Explicit missing states excluded.", limitations: ["No causation."], evidence_kind: "descriptive" } as T;
    if (method === "experiment.clone") return { ...this.current, path: "experiments/2026/repeat.md", metadata: { ...this.current.metadata, experiment_id: "exp-456", repeated_from_experiment_id: "exp-123" } } as T;
    if (method === "experiment.history.load") return { state: "missing-index", entries: [], diagnostics: [{ code: "rebuild_required" }] } as T;
    if (method === "experiment.history.rebuild") return { state: "ready", entries: [{ experiment_id: "exp-123", path: this.current.path, content_hash: this.current.content_hash, title: "Morning walk", state: "drafting", category: "focus", updated_at: "2026-07-16", measure_ids: ["focus"] }], diagnostics: [] } as T;
    if (method === "experiment.compare") return { left: {}, right: {}, compatible: false, warning: "Measures do not match." } as T;
    if (method === "experiment.proposal.preview") return { proposal_id: "prop-1", action: "create-tasks", target_path: "tasks/ready/x.md", operation: "create_file", source_experiment_id: "exp-123", source_experiment_hash: "sha256:abc", analysis_limitations: ["No causation."], included_actions: ["create task"], excluded_actions: ["change habit"] } as T;
    if (method === "experiment.proposal.create") return { proposal_id: "prop-1", proposal_path: "proposals/prop-1", preview: {} } as T;
    throw new Error(`unhandled ${method}`);
  }
  onNotification(_listener: (method: string, params: Record<string, unknown>) => void): () => void { return () => undefined; }
  async stop(): Promise<void> {}
}

test("workspace creates, designs, tracks explicit missingness, and opens canonical Markdown", async () => {
  const client = new Client(); const opened: string[] = [];
  const controller = new ExperimentWorkspaceController(client, (path) => opened.push(path));
  controller.prepare("goal", "goals/focus.md");
  assert.equal(controller.state.stage, "design");
  await controller.evaluateDesign(protocol);
  controller.acknowledgeWarning("short-duration");
  assert.deepEqual(controller.state.acknowledgedWarnings, ["short-duration"]);
  await controller.create({ title: "Morning walk", category: "focus", protocol, origins: [{ path: "goals/focus.md", relation: "origin" }] });
  await controller.recordObservation({ measureId: "focus", phaseId: "base", observedAt: "2026-07-16T12:00:00+03:00", state: "skipped", note: "Travel" });
  const observationCall = client.calls.find(([method]) => method === "experiment.observation.record")!;
  assert.equal(observationCall[1].state, "skipped");
  assert.equal(observationCall[1].value, undefined);
  controller.openArtifact();
  assert.deepEqual(opened, ["experiments/2026/morning-walk-exp-123.md"]);
});

test("workspace exposes lifecycle, analysis, history recovery, comparisons, and proposal review without apply", async () => {
  const client = new Client(); const controller = new ExperimentWorkspaceController(client);
  await controller.load("experiments/2026/morning-walk-exp-123.md");
  await controller.transition("baseline", "2026-07-16T12:00:00Z");
  await controller.addAmendment(protocol, "Extend collection", ["End date moved"], "2026-07-17T12:00:00Z");
  await controller.loadDue("2026-07-18T12:00:00+03:00");
  assert.equal(controller.state.due[0]?.status, "open");
  await controller.analyze(undefined, false);
  assert.equal(controller.state.stage, "insufficient-evidence");
  await controller.loadHistory();
  assert.equal(controller.state.stage, "missing-index");
  await controller.rebuildHistory();
  assert.equal(controller.state.history.length, 1);
  await controller.compare("exp-123", "exp-456");
  assert.equal(controller.state.comparison?.compatible, false);
  await controller.previewProposal({ action: "create-tasks", targetPath: "tasks/ready/x.md", content: "# Task", createTarget: true });
  await controller.createProposal({ action: "create-tasks", targetPath: "tasks/ready/x.md", content: "# Task", createTarget: true });
  assert.equal(controller.state.stage, "proposal-created");
  assert.equal(client.calls.some(([method]) => method.includes("apply")), false);
});

test("unsafe, stale, provider, malformed, and migration errors remain explicit and recoverable", async () => {
  const client = new Client(); const controller = new ExperimentWorkspaceController(client);
  for (const [code, expected] of [
    ["unsafe_experiment", "unsafe-blocked"], ["stale_artifact", "stale-artifact"],
    ["timeout", "provider-timeout"], ["malformed_artifact", "malformed-artifact"],
    ["migration_required", "migration-required"], ["unsupported_schema", "unsupported-schema"],
  ] as const) {
    client.failure = { code, message: code };
    await assert.rejects(() => controller.load("experiments/x.md"));
    assert.equal(controller.state.stage, expected);
  }
});

test("keyboard actions are accessible and never expose direct external mutation", () => {
  const actions = new ExperimentWorkspaceController(new Client()).keyboardActions();
  assert.deepEqual(actions.map((item) => item.shortcut), ["C", "O", "P", "A", "N", "H", "R", "M"]);
  assert.equal(actions.some((item) => item.id === "apply"), false);
  assert.equal(actions.every((item) => item.ariaLabel.length > item.label.length), true);
});
