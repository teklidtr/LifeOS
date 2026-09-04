import assert from "node:assert/strict";
import test from "node:test";
import { BridgeClient, HandshakeResult, LifeOSSettings } from "../src/protocol.js";
import { ReviewArtifact, ReviewSnapshot } from "../src/review-artifact.js";
import { ReviewWorkspaceController } from "../src/review-workspace.js";

const fingerprint = `sha256:${"c".repeat(64)}`;
const baseArtifact: ReviewArtifact = {
  path: "reviews/daily/2026-09-04.md",
  content_hash: `sha256:${"a".repeat(64)}`,
  metadata: {
    review_id: "daily-2026-09-04", schema_version: 1, review_kind: "daily",
    period_start: "2026-09-04", period_end: "2026-09-04", timezone: "Europe/Istanbul",
    status: "open", created_at: "2026-09-04T08:00:00+03:00", updated_at: "2026-09-04T08:00:00+03:00",
    phases: [
      { phase_id: "morning", state: "pending", completed_sections: [], skipped_sections: [] },
      { phase_id: "evening", state: "pending", completed_sections: [], skipped_sections: [] },
    ], current_phase: "morning", item_decisions: [], answers: [], proposal_refs: [], migrated_from: [], snapshot_history: [], lifecycle_events: [],
  },
  body: "# Daily review",
};
const snapshot: ReviewSnapshot = {
  snapshot_id: "snapshot:daily:pattern", generated_at: "2026-09-04T08:00:00+03:00",
  content_hash: `sha256:${"b".repeat(64)}`, sections: [], diagnostics: [],
};

class PatternBridge implements BridgeClient {
  calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  artifact = structuredClone(baseArtifact);
  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }
  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push({ method, params });
    if (method === "review.artifact.open") return { artifact: this.artifact, snapshot, prompts: [], required_sections: [], due: { state: "available", reason: "ready" }, active_phase: "morning" } as T;
    if (method === "review.artifact.refresh") return { artifact: this.artifact, snapshot } as T;
    if (method === "review.artifact.decide") {
      this.artifact = structuredClone(this.artifact);
      this.artifact.metadata.item_decisions = [{
        item_id: String(params.item_id), evidence_fingerprint: String(params.evidence_fingerprint),
        decision: "propose_change", decided_at: String(params.now), proposal_id: "proposal-pattern",
      }];
      this.artifact.metadata.proposal_refs = ["proposal-pattern"];
      return this.artifact as T;
    }
    throw new Error(`unexpected method ${method}`);
  }
  onNotification(_listener: (method: string, params: Record<string, unknown>) => void): () => void { return () => undefined; }
  async stop(): Promise<void> {}
}

test("daily workspace transports explicit urgent and pinned pattern ids through refresh", async () => {
  const bridge = new PatternBridge();
  const controller = new ReviewWorkspaceController(bridge);
  await controller.openDaily(
    "2026-09-04", "Europe/Istanbul", "2026-09-04T08:00:00+03:00", "morning", "today",
    { urgentPatternIds: ["urgent", "urgent"], pinnedPatternIds: ["pinned"] },
  );
  const opened = bridge.calls[0]!;
  assert.deepEqual(opened.params.urgent_pattern_ids, ["urgent"]);
  assert.deepEqual(opened.params.pinned_pattern_ids, ["pinned"]);

  controller.setPatternAttention({ urgentPatternIds: ["urgent-2"], pinnedPatternIds: ["pinned-2"] });
  await controller.refresh("2026-09-04T08:05:00+03:00");
  const refreshed = bridge.calls.at(-1)!;
  assert.equal(refreshed.method, "review.artifact.refresh");
  assert.deepEqual(refreshed.params.urgent_pattern_ids, ["urgent-2"]);
  assert.deepEqual(refreshed.params.pinned_pattern_ids, ["pinned-2"]);
});

test("personal-pattern proposal action routes through propose-change decision and attaches draft", async () => {
  const bridge = new PatternBridge();
  const controller = new ReviewWorkspaceController(bridge);
  await controller.openDaily("2026-09-04", "Europe/Istanbul", "2026-09-04T08:00:00+03:00");
  const proposal = await controller.createProposal({
    itemId: "personal-pattern:quiet", evidenceFingerprint: fingerprint,
    targetPath: "patterns/quiet.md", expectedTargetHash: `sha256:${"d".repeat(64)}`,
    action: "set_note_status", value: "paused", rationale: "Review this pattern explicitly.",
  }, "2026-09-04T08:10:00+03:00");

  assert.equal(proposal.proposal_id, "proposal-pattern");
  assert.equal(bridge.calls.at(-1)?.method, "review.artifact.decide");
  assert.equal(bridge.calls.at(-1)?.params.decision, "propose_change");
  assert.equal(bridge.calls.some((call) => call.method === "review.proposal.create"), false);
});
