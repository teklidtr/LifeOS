import assert from "node:assert/strict";
import test from "node:test";
import { BridgeClient, CaptureController, CheckInController, HandshakeResult, LifeOSSettings } from "../src/index.js";
class Client implements BridgeClient {
  calls: Array<[string, Record<string, unknown>]> = [];
  async start(_s: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }
  async call<T>(method: string, params: Record<string, unknown>): Promise<T> { this.calls.push([method, params]); return { operation:"quick_capture", reference:{path:"raw/x.md",content_hash:"h"}, created:true, data:{} } as T; }
  onNotification(): () => void { return () => {}; } async stop(): Promise<void> {}
}
test("capture validates domain fields and opens canonical result", async () => {
  const client = new Client(); const opened: string[] = []; const controller = new CaptureController(client, path => opened.push(path));
  assert.equal(controller.validate({idempotency_key:"x",kind:"task",title:"Task"}).length, 1);
  await controller.submit({idempotency_key:"x",kind:"thought",title:"Thought"});
  assert.deepEqual(opened, ["raw/x.md"]); assert.equal(client.calls[0]?.[0], "daily.capture");
});
test("check-in uses typed bridge action", async () => {
  const client = new Client(); const controller = new CheckInController(client);
  await controller.submit({idempotency_key:"m",day:"2026-07-16",period:"morning",metrics:{energy:6}});
  assert.equal(client.calls[0]?.[0], "daily.checkin");
});
