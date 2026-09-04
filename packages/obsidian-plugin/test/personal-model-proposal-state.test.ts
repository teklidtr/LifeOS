import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
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

class ProposalBridge implements BridgeClient {
  calls: string[] = [];

  async start(_settings: LifeOSSettings): Promise<HandshakeResult> {
    throw new Error("unused");
  }

  async call<T>(method: string, _params: Record<string, unknown>): Promise<T> {
    this.calls.push(method);
    if (method === "personal-model.workspace.get") return workspace() as T;
    if (method === "personal-model.proposal.preview") {
      return {
        preview: {
          proposal_id: "proposal-pattern",
          action: "promote-active",
          pattern_id: "pattern-seed",
          target_path: "patterns/seed.md",
          operation: "patch_human_file",
          from_status: "seed",
          to_status: "active",
          base_hash: HASH,
          evidence_fingerprint: HASH,
          transition_reason: "Adopt after review.",
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
          target_path: "patterns/seed.md",
          operation: "patch_human_file",
          from_status: "seed",
          to_status: "active",
          base_hash: HASH,
          evidence_fingerprint: HASH,
          transition_reason: "Adopt after review.",
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

test("unchanged revise is rejected before calling the Python bridge", async () => {
  const bridge = new ProposalBridge();
  const controller = new PersonalModelWorkspaceController(bridge);
  await controller.load();
  const callsBeforeRevision = bridge.calls.length;

  const preview = await controller.preview({
    action: "revise",
    transitionReason: "Review without changing semantics.",
    statement: "Seed statement.",
    confidence: "medium",
  });

  assert.equal(preview, undefined);
  assert.equal(bridge.calls.length, callsBeforeRevision);
  assert.match(controller.state.detail ?? "", /Change the statement, confidence, or evidence/i);
});

test("created draft confirmation closes without claiming the draft was cancelled", async () => {
  const bridge = new ProposalBridge();
  const controller = new PersonalModelWorkspaceController(bridge);
  await controller.load();
  await controller.preview({ action: "adopt", transitionReason: "Adopt after review." });
  await controller.createPreviewed();

  assert.equal(controller.state.stage, "proposal-created");
  assert.equal(controller.state.proposalResult?.proposal_id, "proposal-pattern");

  controller.clearCreatedProposal();

  assert.equal(controller.state.stage, "ready");
  assert.equal(controller.state.proposalPreview, undefined);
  assert.equal(controller.state.proposalResult, undefined);
  assert.match(controller.state.statusAnnouncement, /draft remains available in Proposals/i);
});

test("created proposal renderer replaces preview actions with a close confirmation action", async () => {
  const source = await readFile(
    new URL("../../src/personal-model-obsidian-view.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /if \(!state\.proposalResult\) \{[\s\S]*Create draft proposal[\s\S]*Cancel preview[\s\S]*return;/);
  assert.match(source, /Close confirmation/);
  assert.match(source, /clearCreatedProposal\(\)/);
});
