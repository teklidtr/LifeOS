import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeClient,
  ConfirmationChallenge,
  HandshakeResult,
  LifeOSSettings,
  ProposalController,
  ProposalInspection,
  OrphanedGeneratedOwnership,
  ProposalWorkspaceController,
  formatProposalTimestamp,
  groupProposalsByStatus,
  parseProposalDiff,
  proposalActionsForStatus,
} from "../src/index.js";

class Client implements BridgeClient {
  calls: string[] = [];
  digest = "d";

  async start(_settings: LifeOSSettings): Promise<HandshakeResult> {
    throw new Error("not used in this test");
  }

  async call<T>(method: string, _params: Record<string, unknown>): Promise<T> {
    this.calls.push(method);
    if (method === "proposal.inspect") {
      return {
        proposal_id: "p",
        status: "pending",
        title: "P",
        created_at: "2026-08-22T12:00:00Z",
        description: "D",
        body: "B",
        review_digest: this.digest,
        operations: [],
        related_sources: [],
        findings: [],
      } as T;
    }
    if (method === "proposal.prepare") {
      return {
        token: "t",
        proposal_id: "p",
        action: "approve",
        review_digest: "d",
        expires_at: "x",
      } as T;
    }
    return {} as T;
  }

  onNotification(): () => void {
    return () => {};
  }

  async stop(): Promise<void> {}
}

function inspection(
  id: string,
  status: string,
  title = id,
  createdAt = "2026-08-22T12:00:00Z",
): ProposalInspection {
  return {
    proposal_id: id,
    status,
    title,
    created_at: createdAt,
    description: `Description for ${id}`,
    body: `Body for ${id}`,
    review_digest: "d",
    operations: [{
      operation_id: "op-create-example",
      operation_type: "create_file",
      target_path: "wiki/example.md",
      unified_diff: "--- /dev/null\n+++ b/wiki/example.md\n@@ -0,0 +1 @@\n+Example",
      preview_source: "snapshot",
    }],
    related_sources: ["study/example.md"],
    findings: [],
  };
}

class WorkspaceClient implements BridgeClient {
  calls: string[] = [];
  status = "draft";
  failAcceptance = false;
  releaseCreated = false;
  orphanedOwnership: OrphanedGeneratedOwnership[] = [];

  async start(_settings: LifeOSSettings): Promise<HandshakeResult> {
    throw new Error("not used in this test");
  }

  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push(method);
    if (method === "proposal.list") {
      return (this.releaseCreated
        ? [inspection("release", "draft"), inspection("p", this.status)]
        : [inspection("p", this.status)]) as T;
    }
    if (method === "proposal.inspect") {
      const id = String(params.proposal_id);
      return inspection(id, id === "release" ? "draft" : this.status) as T;
    }
    if (method === "ownership.orphans.list") return this.orphanedOwnership as T;
    if (method === "ownership.release.proposal.create") {
      this.releaseCreated = true;
      return {
        proposal_id: "release",
        target_path: params.target_path,
        proposal_path: "proposals/release",
      } as T;
    }
    if (method === "proposal.prepare") {
      return {
        token: "t",
        proposal_id: "p",
        action: params.action,
        review_digest: "d",
        expires_at: "x",
      } as T;
    }
    if (method === "proposal.execute") {
      if (params.action === "accept" && this.failAcceptance) {
        this.status = "approved";
        throw new Error("Target changed before application.");
      }
      this.status = params.action === "accept" ? "applied" : "pending";
      return { proposal_id: "p", status: this.status } as T;
    }
    throw new Error(`Unexpected method ${method}`);
  }

  onNotification(): () => void {
    return () => {};
  }

  async stop(): Promise<void> {}
}

test("proposal UI binds confirmation to inspected digest", async () => {
  const client = new Client();
  const controller = new ProposalController(
    client,
    async (_challenge: ConfirmationChallenge) => true,
  );

  await controller.execute("p", "approve");

  assert.deepEqual(client.calls, [
    "proposal.inspect",
    "proposal.prepare",
    "proposal.inspect",
    "proposal.execute",
  ]);
});

test("changed proposal invalidates confirmation", async () => {
  const client = new Client();
  const original = client.call.bind(client);
  client.call = async <T>(
    method: string,
    params: Record<string, unknown>,
  ): Promise<T> => {
    const result = await original<T>(method, params);
    if (method === "proposal.prepare") {
      client.digest = "changed";
    }
    return result;
  };
  const controller = new ProposalController(client, async () => true);

  await assert.rejects(() => controller.execute("p", "approve"));
});

test("proposal helpers group lifecycle states and expose only valid actions", () => {
  const groups = groupProposalsByStatus([
    inspection("approved", "approved"),
    inspection("draft-old", "draft", "A", "2026-08-22T10:00:00Z"),
    inspection("draft-new", "draft", "Z", "2026-08-22T11:00:00Z"),
    inspection("custom", "custom"),
  ]);

  assert.deepEqual(groups.map((group) => [
    group.status,
    group.proposals.map((proposal) => proposal.proposal_id),
  ]), [
    ["draft", ["draft-new", "draft-old"]],
    ["approved", ["approved"]],
    ["custom", ["custom"]],
  ]);
  assert.deepEqual(proposalActionsForStatus("draft"), ["accept"]);
  assert.deepEqual(proposalActionsForStatus("pending"), ["accept", "reject"]);
  assert.deepEqual(proposalActionsForStatus("approved"), ["accept", "reject"]);
  assert.deepEqual(proposalActionsForStatus("applied"), []);
});

test("proposal timestamps format locally and preserve malformed values", () => {
  assert.equal(
    formatProposalTimestamp("2026-08-22T12:23:09Z", "tr-TR", "Europe/Istanbul"),
    "22 Ağu 2026 15:23",
  );
  assert.equal(formatProposalTimestamp("not-a-date", "tr-TR"), "not-a-date");
});

test("proposal diff parser tracks GitHub-style line kinds and line numbers", () => {
  const lines = parseProposalDiff([
    "--- a/wiki/example.md",
    "+++ b/wiki/example.md",
    "@@ -10,3 +10,3 @@",
    " context",
    "-old value",
    "+new value",
    " tail",
  ].join("\n"));

  assert.deepEqual(lines.map((line) => [
    line.kind,
    line.oldLine,
    line.newLine,
    line.text,
  ]), [
    ["header", null, null, "--- a/wiki/example.md"],
    ["header", null, null, "+++ b/wiki/example.md"],
    ["hunk", null, null, "@@ -10,3 +10,3 @@"],
    ["context", 10, 10, " context"],
    ["removed", 11, null, "-old value"],
    ["added", null, 11, "+new value"],
    ["context", 12, 12, " tail"],
  ]);
});

test("proposal workspace accepts through one confirmation and refreshes", async () => {
  const client = new WorkspaceClient();
  const workspace = new ProposalWorkspaceController(client, async () => true);
  const announcements: string[] = [];
  const unsubscribe = workspace.subscribe(() => {
    if (workspace.state.announcement) announcements.push(workspace.state.announcement);
  });

  await workspace.load();
  assert.equal(workspace.state.kind, "ready");
  assert.equal(workspace.state.selected?.status, "draft");

  await workspace.execute("accept");

  assert.equal(workspace.state.kind, "ready");
  assert.equal(workspace.state.selected?.status, "applied");
  assert.deepEqual(client.calls, [
    "proposal.list",
    "ownership.orphans.list",
    "proposal.inspect",
    "proposal.prepare",
    "proposal.inspect",
    "proposal.execute",
    "proposal.list",
    "ownership.orphans.list",
  ]);
  assert.equal(announcements.at(-1), "Proposal p accept completed.");
  unsubscribe();
});

test("cancelled workspace confirmation makes no change and does not execute", async () => {
  const client = new WorkspaceClient();
  const workspace = new ProposalWorkspaceController(client, async () => false);
  await workspace.load();

  await workspace.execute("accept");

  assert.equal(workspace.state.kind, "ready");
  assert.equal(workspace.state.announcement, "Confirmation cancelled. No changes were made.");
  assert.equal(client.calls.includes("proposal.execute"), false);
});

test("failed acceptance refreshes the last durable lifecycle state", async () => {
  const client = new WorkspaceClient();
  client.failAcceptance = true;
  const workspace = new ProposalWorkspaceController(client, async () => true);
  await workspace.load();

  await workspace.execute("accept");

  assert.equal(workspace.state.kind, "error");
  assert.equal(workspace.state.selected?.status, "approved");
  assert.match(workspace.state.detail, /Target changed before application/);
  assert.deepEqual(client.calls.slice(-3), [
    "proposal.execute",
    "proposal.list",
    "ownership.orphans.list",
  ]);
});

test("ownership recovery shows restore guidance and creates a reviewed release draft", async () => {
  const client = new WorkspaceClient();
  client.orphanedOwnership = [{
    target_path: "wiki/missing.md",
    content_hash: "a".repeat(64),
    generator_id: "lifeos.test",
    generator_version: "1",
    created_at: "2026-08-22T10:00:00Z",
    updated_at: "2026-08-22T11:00:00Z",
    diagnostic_code: "owned_target_missing",
    diagnostic: "Generated ownership remains canonical, but its target is absent.",
    restore_instructions: "Restore reviewed bytes with the recorded SHA-256.",
  }];
  const workspace = new ProposalWorkspaceController(client, async () => true);

  await workspace.load();
  workspace.showRestoreInstructions("wiki/missing.md");
  assert.equal(workspace.state.restoreTargetPath, "wiki/missing.md");
  assert.match(workspace.state.announcement ?? "", /No changes were made/);
  assert.equal(client.calls.includes("ownership.release.proposal.create"), false);

  await workspace.createOwnershipReleaseProposal("wiki/missing.md");

  assert.equal(workspace.state.selected?.proposal_id, "release");
  assert.match(workspace.state.announcement ?? "", /Review its manifest diff/);
  assert.deepEqual(client.calls.slice(-3), [
    "ownership.release.proposal.create",
    "proposal.list",
    "ownership.orphans.list",
  ]);
});
