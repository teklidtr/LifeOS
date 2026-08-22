import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeClient,
  ConfirmationChallenge,
  HandshakeResult,
  LifeOSSettings,
  ProposalController,
  ProposalInspection,
  ProposalWorkspaceController,
  formatProposalTimestamp,
  groupProposalsByStatus,
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
    operations: [{ operation: "create_file", target_path: "wiki/example.md" }],
    related_sources: ["study/example.md"],
    findings: [],
  };
}

class WorkspaceClient implements BridgeClient {
  calls: string[] = [];
  status = "draft";

  async start(_settings: LifeOSSettings): Promise<HandshakeResult> {
    throw new Error("not used in this test");
  }

  async call<T>(method: string, _params: Record<string, unknown>): Promise<T> {
    this.calls.push(method);
    if (method === "proposal.list") return [inspection("p", this.status)] as T;
    if (method === "proposal.inspect") return inspection("p", this.status) as T;
    if (method === "proposal.prepare") {
      return {
        token: "t",
        proposal_id: "p",
        action: "submit",
        review_digest: "d",
        expires_at: "x",
      } as T;
    }
    if (method === "proposal.execute") {
      this.status = "pending";
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
  assert.deepEqual(proposalActionsForStatus("draft"), ["submit"]);
  assert.deepEqual(proposalActionsForStatus("pending"), ["approve", "reject"]);
  assert.deepEqual(proposalActionsForStatus("approved"), ["apply", "reject"]);
  assert.deepEqual(proposalActionsForStatus("applied"), []);
});

test("proposal timestamps format locally and preserve malformed values", () => {
  assert.equal(
    formatProposalTimestamp("2026-08-22T12:23:09Z", "tr-TR", "Europe/Istanbul"),
    "22 Ağu 2026 15:23",
  );
  assert.equal(formatProposalTimestamp("not-a-date", "tr-TR"), "not-a-date");
});

test("proposal workspace loads, executes through confirmation, and refreshes", async () => {
  const client = new WorkspaceClient();
  const workspace = new ProposalWorkspaceController(client, async () => true);
  const announcements: string[] = [];
  const unsubscribe = workspace.subscribe(() => {
    if (workspace.state.announcement) announcements.push(workspace.state.announcement);
  });

  await workspace.load();
  assert.equal(workspace.state.kind, "ready");
  assert.equal(workspace.state.selected?.status, "draft");

  await workspace.execute("submit");

  assert.equal(workspace.state.kind, "ready");
  assert.equal(workspace.state.selected?.status, "pending");
  assert.deepEqual(client.calls, [
    "proposal.list",
    "proposal.inspect",
    "proposal.prepare",
    "proposal.inspect",
    "proposal.execute",
    "proposal.list",
  ]);
  assert.equal(announcements.at(-1), "Proposal p submit completed.");
  unsubscribe();
});

test("cancelled workspace confirmation makes no change and does not execute", async () => {
  const client = new WorkspaceClient();
  const workspace = new ProposalWorkspaceController(client, async () => false);
  await workspace.load();

  await workspace.execute("submit");

  assert.equal(workspace.state.kind, "ready");
  assert.equal(workspace.state.announcement, "Confirmation cancelled. No changes were made.");
  assert.equal(client.calls.includes("proposal.execute"), false);
});
