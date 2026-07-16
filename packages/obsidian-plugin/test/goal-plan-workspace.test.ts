import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeClient,
  GoalPlanWorkspaceController,
  HandshakeResult,
  LifeOSSettings,
  MemoryWorkspacePersistence,
} from "../src/index.js";

class Client implements BridgeClient {
  calls: Array<[string, Record<string, unknown>]> = [];
  fail?: { code: string; message: string };
  revision = 1;
  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }
  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push([method, params]);
    if (this.fail) throw this.fail;
    if (method === "copilot.session.start" || method === "copilot.session.get" || method === "copilot.session.answer" || method === "copilot.session.close") {
      const status = params.outcome === "park" ? "parked" : params.outcome === "abandon" ? "abandoned" : "ready";
      return {
        session: {
          schema_version: 1, session_id: params.session_id ?? "session-cell", goal_ref: params.goal_path ?? "goals/cell.md",
          goal_hash: "sha256:a", status, answers: [], selected_context_refs: params.selected_context_refs ?? [],
          excluded_context_refs: [], decisions: [], proposal_ids: [], source_revision: this.revision++,
        },
        current_question: method === "copilot.session.start" ? {
          question_id: "purpose", category: "purpose", prompt: "Why now?", required: true,
          source: "deterministic", reason: "Needed",
        } : undefined,
        source_stale: false, allowed_outcomes: ["ready-to-plan", "park", "abandon"], recommended_outcomes: [],
      } as T;
    }
    if (method === "copilot.context.preview") return { schema_version: 1, goal_id: "goal-cell", goal_hash: "sha256:a", items: [], omissions: [], total_bytes: 0, truncated: false } as T;
    if (method === "copilot.options.generate") return { outcome: "options", diagnostics: [], options: [{ option_id: "option-cell", title: "Cell plan", strategy: "Bounded", desired_outcome: "Explain cells", milestones: [{ milestone_id: "milestone-cell", title: "Foundation", outcome: "Explain two chapters", wave: "current" }], risks: [], tradeoffs: [], unresolved_questions: [] }] } as T;
    if (method === "copilot.option.decompose") return { option_id: "option-cell", milestones: [{ milestone_id: "milestone-cell", title: "Foundation", outcome: "Explain two chapters", wave: "current" }], actions: [{ task_id: "task-cell", title: "Read chapter", milestone_id: "milestone-cell", verification: "One note" }], findings: [] } as T;
    if (method === "copilot.capacity.check") return { fit: "comfortable", findings: [], alternatives: [] } as T;
    if (method === "copilot.explain") return { option_id: "option-cell", summary: "Visible evidence", items: [], omissions: [], contradictions: [] } as T;
    if (method === "copilot.compare") return { dimensions: [] } as T;
    if (method === "copilot.proposal.create") return { proposal_id: "prop-x", proposal_path: "proposals/prop-x", plan_path: "plans/cell.md" } as T;
    if (method === "copilot.replanning.scan") return [{
      trigger_id: "replan:cell", code: "plan-no-feasible-next-action", severity: "attention",
      target_kind: "plan", target_id: "plan-cell", target_path: "plans/cell.md",
      title: "Plan needs a next wave", detail: "No feasible next action", evidence_refs: ["sha256:a"],
      evidence_fingerprint: "sha256:feed", possible_outcomes: ["continue-unchanged", "adjust-next-wave"],
    }] as T;
    if (method === "copilot.replanning.review") return {
      schema_version: 1, review_id: "replan-review", target_kind: "plan", target_id: "plan-cell",
      target_path: "plans/cell.md", target_hash: "sha256:a", triggers: [{
        trigger_id: "replan:cell", code: "plan-no-feasible-next-action", severity: "attention",
        target_kind: "plan", target_id: "plan-cell", target_path: "plans/cell.md",
        title: "Plan needs a next wave", detail: "No feasible next action", evidence_refs: ["sha256:a"],
        evidence_fingerprint: "sha256:feed", possible_outcomes: ["continue-unchanged", "adjust-next-wave"],
      }], comparisons: [], evidence: [], outcomes: ["continue-unchanged", "pause"],
      recommended_outcomes: ["continue-unchanged"], questions: [], lineage: [], generated_as_of: "2026-07-16",
    } as T;
    if (method === "copilot.replanning.suppress") return { suppressed: true } as T;
    if (method === "copilot.replanning.proposal.create") return params.outcome === "continue-unchanged"
      ? { proposal_created: false, outcome: "continue-unchanged" } as T
      : { proposal_id: "prop-replan", proposal_path: "proposals/prop-replan", target_path: "plans/cell.md", base_hash: "sha256:a", outcome: params.outcome } as T;
    throw new Error(`unsupported ${method}`);
  }
  onNotification(): () => void { return () => {}; }
  async stop(): Promise<void> {}
}

test("goal-note critical path stays on typed Python bridge operations", async () => {
  const client = new Client();
  const controller = new GoalPlanWorkspaceController(client);
  await controller.startFromGoal("goals/cell.md", "session-cell");
  assert.equal(controller.state.stage, "clarification");
  await controller.answerCurrent("answered", "Understand living systems");
  await controller.previewContext({ includePaths: ["wiki/cells.md"], excludePaths: ["journal/private.md"], redactTerms: ["secret"] });
  await controller.generateOptions("2026-07-16");
  await controller.selectOption("option-cell", "2026-07-16");
  controller.editDraft({ planTitle: "Edited cell plan" });
  controller.includeAction("task-cell", false);
  await controller.saveDraft();
  await controller.checkCapacity("2026-07-16", 240, [{ workload_id: "run", title: "Running", minutes: 60, kind: "exercise" }]);
  await controller.explain("2026-07-16", 240);
  await controller.compare(["option-cell"], "2026-07-16", 240);
  const proposal = await controller.createProposal("2026-07-16");
  assert.equal(proposal.proposal_id, "prop-x");
  assert.equal(controller.state.stage, "proposal-created");
  assert.deepEqual(client.calls.map((item) => item[0]), [
    "copilot.session.start", "copilot.session.answer", "copilot.context.preview",
    "copilot.options.generate", "copilot.option.decompose", "copilot.capacity.check",
    "copilot.explain", "copilot.compare", "copilot.proposal.create",
  ]);
  assert.equal(client.calls.at(-1)?.[1].plan_title, "Edited cell plan");
  assert.deepEqual(client.calls.at(-1)?.[1].included_action_ids, []);
});

test("quick capture adds explicit context and durable session can resume after restart", async () => {
  const client = new Client(); const persistence = new MemoryWorkspacePersistence();
  const first = new GoalPlanWorkspaceController(client, persistence);
  await first.startFromQuickCapture("goals/cell.md", "raw/capture.md", "session-cell");
  assert.deepEqual(client.calls[0]?.[1].selected_context_refs, ["raw/capture.md"]);
  first.editDraft = first.editDraft.bind(first);
  const restarted = new GoalPlanWorkspaceController(client, persistence);
  await restarted.resume("session-cell");
  assert.equal(restarted.state.goalPath, "goals/cell.md");
  restarted.markBridgeRestarted();
  assert.equal(restarted.state.error?.kind, "bridge-restarted");
  await restarted.resume("session-cell");
  assert.equal(restarted.state.stage, "context-preview");
});

test("park and abandon remain non-canonical session outcomes", async () => {
  const client = new Client(); const controller = new GoalPlanWorkspaceController(client);
  await controller.startFromGoal("goals/cell.md", "session-cell");
  await controller.closeSession("park", "Not now");
  assert.equal(controller.state.stage, "parked");
  await controller.resume("session-cell");
  await controller.closeSession("abandon", "Direction no longer matters");
  assert.equal(controller.state.stage, "abandoned");
});

test("errors expose stale, model, permission, protocol, recovery, and bridge states", async () => {
  const cases = [
    ["copilot_session_stale", "stale-source"],
    ["model_unavailable", "missing-model"],
    ["permission_denied", "permission-denied"],
    ["protocol_incompatible", "protocol-incompatible"],
    ["recovery_required", "recovery-required"],
    ["bridge_unavailable", "missing-bridge"],
  ] as const;
  for (const [code, expected] of cases) {
    const client = new Client(); client.fail = { code, message: code };
    const controller = new GoalPlanWorkspaceController(client);
    await assert.rejects(() => controller.startFromGoal("goals/cell.md", "session-cell"));
    assert.equal(controller.state.error?.kind, expected);
  }
});

test("keyboard-only actions have explicit accessible labels and never apply a proposal", () => {
  const controller = new GoalPlanWorkspaceController(new Client());
  const actions = controller.criticalActions();
  assert.deepEqual(actions.map((item) => item.shortcut), ["Enter", "P", "C", "S", "K", "A", "G"]);
  assert.equal(actions.every((item) => item.ariaLabel.length > item.label.length), true);
  assert.equal(actions.some((item) => item.id === "apply"), false);
});

test("living review scans, suppresses exact evidence, and creates proposals without applying", async () => {
  const client = new Client();
  const controller = new GoalPlanWorkspaceController(client);
  const triggers = await controller.scanReplanning("2026-07-16");
  assert.equal(triggers.length, 1);
  const review = await controller.openReplanningReview("plans/cell.md", "2026-07-16", {
    corrections: [{ evidence_id: "correction-1", kind: "correction", statement: "Capacity changed" }],
  });
  assert.equal(controller.state.stage, "replanning-review");
  const unchanged = await controller.createReplanningProposal("continue-unchanged", "The plan still fits.");
  assert.equal(unchanged.proposal_created, false);
  const proposal = await controller.createReplanningProposal("pause", "Protect capacity while prerequisites change.");
  assert.equal(proposal.proposal_id, "prop-replan");
  assert.equal(controller.state.stage, "proposal-created");
  await controller.suppressReplanning(review.triggers[0]!);
  assert.equal(controller.state.replanningTriggers?.length, 0);
  assert.deepEqual(client.calls.slice(-4).map((item) => item[0]), [
    "copilot.replanning.review",
    "copilot.replanning.proposal.create",
    "copilot.replanning.proposal.create",
    "copilot.replanning.suppress",
  ]);
  assert.equal(client.calls.some((item) => item[0].includes("apply")), false);
});
