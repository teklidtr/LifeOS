import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeClient,
  ConfirmationChallenge,
  HandshakeResult,
  LifeOSSettings,
  ProposalController,
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
