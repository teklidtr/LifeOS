import assert from "node:assert/strict";
import test from "node:test";

import { PersonalModelWorkspaceController } from "../src/personal-model-workspace.js";
import {
  actionsForPersonalModelItem,
  nextPersonalModelView,
  PersonalModelDocument,
  PersonalModelItem,
} from "../src/personal-model.js";
import { BridgeClient, HandshakeResult, LifeOSSettings } from "../src/protocol.js";

const hash = (char: string) => `sha256:${char.repeat(64)}`;

function item(
  id: string,
  status: PersonalModelItem["status"],
  overrides: Partial<PersonalModelItem> = {},
): PersonalModelItem {
  return {
    pattern_id: id,
    pattern_path: `patterns/${id}.md`,
    pattern_content_hash: hash("a"),
    title: id,
    description: `Description for ${id}.`,
    statement: `Statement for ${id}.`,
    status,
    confidence: "medium",
    review_reasons: status === "needs-review" ? ["Evidence changed."] : [],
    origin: { kind: "manual" },
    last_reviewed_at: null,
    review_due_at: null,
    review_due: false,
    evidence_fingerprint: hash("b"),
    evidence: [],
    evidence_health: "none",
    evidence_diagnostics: [],
    freshness_days: null,
    review_recommendation: "none",
    review_trigger_reasons: [],
    evidence_changes: [],
    related_paths: [],
    ...overrides,
  };
}

function document(overrides: Partial<PersonalModelDocument["groups"]> = {}): PersonalModelDocument {
  return {
    schema_version: 1,
    source_hash: hash("c"),
    runtime_state: "ready",
    groups: {
      active: [],
      needs_review: [],
      seeds: [],
      archived: [],
      ...overrides,
    },
    diagnostics: [],
  };
}

class PersonalModelBridge implements BridgeClient {
  calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  workspace = document();
  failure?: { code: string; message: string };

  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }

  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push({ method, params });
    if (this.failure) {
      const failure = this.failure;
      this.failure = undefined;
      throw failure;
    }
    if (method === "personal-model.workspace.get" || method === "personal-model.rebuild") {
      return this.workspace as T;
    }
    if (method === "personal-model.proposal.preview") {
      return {
        preview: {
          proposal_id: "proposal-pattern",
          action: params.action === "adopt" ? "promote-active" : String(params.action),
          pattern_id: "pattern-seed",
          target_path: String(params.target_path),
          operation: "patch_human_file",
          from_status: "seed",
          to_status: "active",
          base_hash: String(params.expected_target_hash),
          evidence_fingerprint: hash("b"),
          transition_reason: String(params.transition_reason),
          candidate_content: "---\nstatus: active\n---\n",
        },
      } as T;
    }
    if (method === "personal-model.proposal.create") {
      return {
        proposal_id: "proposal-pattern",
        proposal_path: "proposals/proposal-pattern",
        preview: {
          proposal_id: "proposal-pattern",
          action: "promote-active",
          pattern_id: "pattern-seed",
          target_path: String(params.target_path),
          operation: "patch_human_file",
          from_status: "seed",
          to_status: "active",
          base_hash: String(params.expected_target_hash),
          evidence_fingerprint: hash("b"),
          transition_reason: String(params.transition_reason),
          candidate_content: "---\nstatus: active\n---\n",
        },
      } as T;
    }
    throw new Error(`unexpected method ${method}`);
  }

  onNotification(_listener: (method: string, params: Record<string, unknown>) => void): () => void {
    return () => undefined;
  }

  async stop(): Promise<void> {}
}

test("mixed workspace prioritizes needs-review while preserving all four views", async () => {
  const bridge = new PersonalModelBridge();
  bridge.workspace = document({
    active: [item("active", "active")],
    needs_review: [item("review", "needs-review")],
    seeds: [item("seed", "seed")],
    archived: [item("archive", "archived")],
  });
  const controller = new PersonalModelWorkspaceController(bridge);

  await controller.load("2026-09-04T12:00:00Z");

  assert.equal(controller.state.stage, "ready");
  assert.equal(controller.state.view, "needs_review");
  assert.equal(controller.selected?.pattern_id, "review");
  controller.setView("seeds");
  assert.equal(controller.selected?.pattern_id, "seed");
  assert.deepEqual(actionsForPersonalModelItem(controller.selected!), ["adopt", "revise", "contest", "archive"]);
});

test("empty workspace is explicit and rebuildable rather than an error", async () => {
  const bridge = new PersonalModelBridge();
  const controller = new PersonalModelWorkspaceController(bridge);

  await controller.load();
  assert.equal(controller.state.stage, "empty");
  assert.match(controller.state.recovery ?? "", /Track a seed/i);

  await controller.rebuild("2026-09-04T12:00:00Z");
  assert.equal(bridge.calls.at(-1)?.method, "personal-model.rebuild");
  assert.equal(controller.state.stage, "empty");
});

test("missing derived runtime offers explicit rebuild recovery", async () => {
  const bridge = new PersonalModelBridge();
  bridge.failure = {
    code: "personal_model_rebuild_required",
    message: "Derived Personal Model is missing.",
  };
  bridge.workspace = document({ active: [item("active", "active")] });
  const controller = new PersonalModelWorkspaceController(bridge);

  await controller.load();
  assert.equal(controller.state.stage, "missing-runtime");
  assert.match(controller.state.recovery ?? "", /Rebuild disposable/i);

  await controller.rebuild();
  assert.equal(controller.state.stage, "ready");
  assert.equal(controller.selected?.pattern_id, "active");
});

test("evidence navigation opens the resolved current source and related review or experiment", async () => {
  const opened: string[] = [];
  const evidenceItem = item("evidence", "active", {
    evidence: [{ path: "journal/old.md", content_hash: hash("d"), role: "supporting" }],
    evidence_health: "attention",
    evidence_diagnostics: [{
      reference: { path: "journal/old.md", content_hash: hash("d"), role: "supporting" },
      state: "moved",
      current_path: "journal/moved.md",
      current_content_hash: hash("d"),
      candidate_paths: [],
    }],
    evidence_changes: [{
      role: "supporting",
      reviewed_path: "journal/old.md",
      reviewed_content_hash: hash("d"),
      state: "moved",
      current_path: "journal/moved.md",
      current_content_hash: hash("d"),
    }],
    related_paths: [{ path: "experiments/2026/walk.md", kind: "experiment" }],
  });
  const bridge = new PersonalModelBridge();
  bridge.workspace = document({ active: [evidenceItem] });
  const controller = new PersonalModelWorkspaceController(bridge, (path) => opened.push(path));

  await controller.load();
  controller.openEvidence(0);
  controller.openRelated("experiments/2026/walk.md");

  assert.deepEqual(opened, ["journal/moved.md", "experiments/2026/walk.md"]);
  assert.equal(controller.selected?.evidence_changes[0]?.state, "moved");
});

test("proposal preview carries the inspected hash and creation reuses the reviewed request", async () => {
  const bridge = new PersonalModelBridge();
  bridge.workspace = document({ seeds: [item("pattern-seed", "seed")] });
  const controller = new PersonalModelWorkspaceController(bridge);
  await controller.load();

  const preview = await controller.preview({
    action: "adopt",
    transitionReason: "I reviewed the visible evidence.",
  }, "2026-09-04T12:00:00Z");

  assert.equal(preview?.action, "promote-active");
  const previewCall = bridge.calls.at(-1)!;
  assert.equal(previewCall.method, "personal-model.proposal.preview");
  assert.equal(previewCall.params.expected_target_hash, hash("a"));
  assert.equal(controller.state.stage, "proposal-preview");

  const created = await controller.createPreviewed();
  assert.equal(created?.proposal_id, "proposal-pattern");
  assert.equal(bridge.calls.at(-1)?.method, "personal-model.proposal.create");
  assert.equal(controller.state.stage, "proposal-created");
  assert.match(controller.state.detail ?? "", /unchanged until proposal acceptance/i);
});

test("stale proposal target blocks preview and points back to refresh", async () => {
  const bridge = new PersonalModelBridge();
  bridge.workspace = document({ seeds: [item("pattern-seed", "seed")] });
  const controller = new PersonalModelWorkspaceController(bridge);
  await controller.load();
  bridge.failure = { code: "stale_target", message: "Pattern changed after inspection." };

  const preview = await controller.preview({ action: "adopt", transitionReason: "Adopt." });

  assert.equal(preview, undefined);
  assert.equal(controller.state.stage, "stale");
  assert.match(controller.state.recovery ?? "", /Refresh the workspace/i);
});

test("keyboard view navigation wraps predictably and uses native-button activation semantics", () => {
  assert.equal(nextPersonalModelView("active", "ArrowLeft"), "archived");
  assert.equal(nextPersonalModelView("active", "ArrowRight"), "needs_review");
  assert.equal(nextPersonalModelView("seeds", "Home"), "active");
  assert.equal(nextPersonalModelView("active", "End"), "archived");
});
