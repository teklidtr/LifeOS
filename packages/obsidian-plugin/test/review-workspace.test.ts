import assert from "node:assert/strict";
import test from "node:test";
import { BridgeClient, HandshakeResult, LifeOSSettings } from "../src/protocol.js";
import { ReviewArtifact, ReviewSnapshot } from "../src/review-artifact.js";
import { ReviewWorkspaceController } from "../src/review-workspace.js";

const artifact: ReviewArtifact = {
  path: "reviews/daily/2026-07-16.md",
  content_hash: "a".repeat(64),
  metadata: {
    review_id: "daily-2026-07-16", schema_version: 1, review_kind: "daily",
    period_start: "2026-07-16", period_end: "2026-07-16", timezone: "Europe/Istanbul",
    status: "open", created_at: "2026-07-16T08:00:00+03:00", updated_at: "2026-07-16T08:00:00+03:00",
    phases: [
      { phase_id: "morning", state: "pending", completed_sections: [], skipped_sections: [] },
      { phase_id: "evening", state: "pending", completed_sections: [], skipped_sections: [] },
    ], current_phase: "morning", item_decisions: [], answers: [], proposal_refs: [], migrated_from: [], snapshot_history: [], lifecycle_events: [],
  },
  body: "# Daily review",
};
const snapshot: ReviewSnapshot = { snapshot_id: "snapshot:daily:test", generated_at: "2026-07-16T08:00:00+03:00", content_hash: `sha256:${"b".repeat(64)}`, sections: [], diagnostics: [] };

class FakeBridge implements BridgeClient {
  calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  fail?: { code: string; message: string };
  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }
  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push({ method, params });
    if (this.fail) throw this.fail;
    if (method === "review.artifact.history") return [{ review_id: artifact.metadata.review_id, path: artifact.path, review_kind: "daily", period_start: "2026-07-16", period_end: "2026-07-16", status: "open", updated_at: artifact.metadata.updated_at }] as T;
    if (method === "review.artifact.migration.preview") return { candidates: [] } as T;
    if (method === "review.artifact.migration.apply") return { migrated: [], already_migrated: [], conflicts: [], preserved_sources: [] } as T;
    if (method === "review.artifact.rebuild") return { artifacts: 0, progress_entries: 0, history_entries: 0, invalid_paths: [], progress_index: "", history_index: "" } as T;
    if (method === "review.artifact.open") return { artifact, snapshot, prompts: [], required_sections: ["attention"], due: { state: "available", reason: "ready" }, next_section: "attention", active_phase: "morning" } as T;
    if (method === "review.artifact.load" || method === "review.artifact.refresh") return { artifact, snapshot } as T;
    if (method === "review.proposal.create") return { proposal_id: "proposal-1", proposal_path: "proposals/proposal-1", target_path: "plans/a.md", base_hash: "hash" } as T;
    return artifact as T;
  }
  onNotification(_listener: (method: string, params: Record<string, unknown>) => void): () => void { return () => undefined; }
  async stop(): Promise<void> {}
}

test("workspace opens, resumes, mutates, and navigates canonical review notes", async () => {
  const bridge = new FakeBridge(); const opened: string[] = [];
  const controller = new ReviewWorkspaceController(bridge, (path) => opened.push(path));
  await controller.openDaily("2026-07-16", "Europe/Istanbul", "2026-07-16T08:00:00+03:00");
  assert.equal(controller.state.stage, "ready");
  assert.equal(controller.state.nextSection, "attention");
  await controller.markSection("morning", "attention", "complete", "2026-07-16T08:05:00+03:00");
  await controller.answer("morning-intent", "Protect reading time", "2026-07-16T08:06:00+03:00", "morning");
  await controller.loadHistory("daily");
  controller.openArtifact(); controller.openHistoryEntry(controller.state.history[0]!);
  assert.deepEqual(opened, [artifact.path, artifact.path]);
  assert.deepEqual(bridge.calls.map((item) => item.method), ["review.artifact.open", "review.artifact.section", "review.artifact.answer", "review.artifact.history"]);
  assert.equal(controller.keyboardLabels().openArtifact, "Open canonical review Markdown");
});

test("workspace exposes stale and unsupported recovery states", async () => {
  const bridge = new FakeBridge(); const controller = new ReviewWorkspaceController(bridge);
  await controller.openExisting({ path: artifact.path }, "2026-07-16T08:00:00+03:00");
  bridge.fail = { code: "stale_write", message: "changed" };
  await assert.rejects(() => controller.refresh("2026-07-16T08:10:00+03:00"));
  assert.equal(controller.state.stage, "stale");
  bridge.fail = { code: "unsupported_review_schema", message: "newer schema" };
  await assert.rejects(() => controller.openExisting({ path: artifact.path }, "2026-07-16T08:11:00+03:00"));
  assert.equal(controller.state.stage, "blocked");
});

test("proposal handoff remains a separate draft action", async () => {
  const bridge = new FakeBridge(); const controller = new ReviewWorkspaceController(bridge);
  await controller.openDaily("2026-07-16", "Europe/Istanbul", "2026-07-16T08:00:00+03:00");
  const proposal = await controller.createProposal({
    itemId: "plan-a", evidenceFingerprint: `sha256:${"c".repeat(64)}`, targetPath: "plans/a.md",
    expectedTargetHash: `sha256:${"d".repeat(64)}`, action: "set_note_status", value: "paused", rationale: "Capacity changed.",
  }, "2026-07-16T08:10:00+03:00");
  assert.equal(proposal.proposal_id, "proposal-1");
  assert.equal(bridge.calls.at(-1)?.method, "review.proposal.create");
});

test("migration remains previewed and rebuild is explicit", async () => {
  const bridge = new FakeBridge();
  const controller = new ReviewWorkspaceController(bridge);
  const preview = await controller.previewMigration();
  await controller.applyMigration("2026-07-16T12:00:00+03:00", preview);
  await controller.rebuildIndexes();
  assert.deepEqual(bridge.calls.slice(-3).map((item) => item.method), [
    "review.artifact.migration.preview", "review.artifact.migration.apply", "review.artifact.rebuild",
  ]);
});
