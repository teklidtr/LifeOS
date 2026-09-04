import assert from "node:assert/strict";
import test from "node:test";

import { PersonalModelWorkspaceController } from "../src/personal-model-workspace.js";
import { PersonalModelDocument } from "../src/personal-model.js";
import {
  BridgeClient,
  HandshakeResult,
  LifeOSSettings,
} from "../src/protocol.js";

const HASH = `sha256:${"a".repeat(64)}`;

function workspace(): PersonalModelDocument {
  return {
    schema_version: 1,
    source_hash: HASH,
    runtime_state: "ready",
    groups: {
      active: [],
      needs_review: [],
      seeds: [{
        pattern_id: "pattern-seed",
        pattern_path: "patterns/seed.md",
        pattern_content_hash: HASH,
        title: "Pattern seed",
        description: "Seed description.",
        statement: "Seed statement.",
        status: "seed",
        confidence: "medium",
        review_reasons: [],
        origin: { kind: "manual" },
        last_reviewed_at: null,
        review_due_at: null,
        review_due: false,
        evidence_fingerprint: HASH,
        evidence: [],
        evidence_health: "none",
        evidence_diagnostics: [],
        freshness_days: null,
        review_recommendation: "none",
        review_trigger_reasons: [],
        evidence_changes: [],
        related_paths: [],
      }],
      archived: [],
    },
    diagnostics: [],
  };
}

class StubBridge implements BridgeClient {
  constructor(
    private readonly handler: (
      method: string,
      params: Record<string, unknown>,
    ) => unknown | Promise<unknown>,
  ) {}

  async start(_settings: LifeOSSettings): Promise<HandshakeResult> {
    throw new Error("unused");
  }

  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    return await this.handler(method, params) as T;
  }

  onNotification(_listener: (method: string, params: Record<string, unknown>) => void): () => void {
    return () => undefined;
  }

  async stop(): Promise<void> {}
}

test("policy-load failure drops cached Personal Model content", async () => {
  let blocked = false;
  const controller = new PersonalModelWorkspaceController(new StubBridge(() => {
    if (blocked) throw { code: "personal_model_blocked", message: "Policy unavailable." };
    return workspace();
  }));

  await controller.load();
  assert.equal(controller.selected?.pattern_id, "pattern-seed");

  blocked = true;
  await controller.load();

  assert.equal(controller.state.stage, "blocked");
  assert.equal(controller.state.document, undefined);
  assert.equal(controller.state.selectedPatternId, undefined);
});

test("authorization denial during an action drops cached model content", async () => {
  const controller = new PersonalModelWorkspaceController(new StubBridge((method) => {
    if (method === "personal-model.workspace.get") return workspace();
    throw { code: "authorization_denied", message: "Scope changed." };
  }));

  await controller.load();
  assert.equal(controller.selected?.pattern_id, "pattern-seed");

  const preview = await controller.preview({
    action: "adopt",
    transitionReason: "Use the inspected evidence.",
  });

  assert.equal(preview, undefined);
  assert.equal(controller.state.stage, "blocked");
  assert.equal(controller.state.document, undefined);
  assert.equal(controller.state.selectedPatternId, undefined);
});
