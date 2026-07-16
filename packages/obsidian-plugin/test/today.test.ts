import assert from "node:assert/strict";
import test from "node:test";
import { BridgeClient, HandshakeResult, LifeOSSettings, TodayDashboardController } from "../src/index.js";

class Client implements BridgeClient {
  calls: Array<Record<string, unknown>> = [];
  async start(_s: LifeOSSettings): Promise<HandshakeResult> { return { protocol: "1.0", engine_version: "0", runtime_schema: 1, capabilities: [], actor_id: "me" }; }
  async call<T>(_method: string, params: Record<string, unknown>): Promise<T> { this.calls.push(params); return { day: params.day, journal: {state:"empty"}, planning:{state:"empty"}, study:{state:"empty"}, experiments:{state:"empty"}, inbox:{state:"empty"}, proposals:{state:"empty"}, attention:{state:"empty"}, diagnostics:{state:"empty"}, revision:"x" } as T; }
  onNotification(): () => void { return () => {}; }
  async stop(): Promise<void> {}
}

test("dashboard refresh preserves local state and sends capacity", async () => {
  const client = new Client(); const controller = new TodayDashboardController(client, "2026-07-16");
  controller.scrollTop = 240;
  await controller.refresh({ available_minutes: 45, energy: "low" });
  assert.equal(client.calls[0]?.available_minutes, 45);
  assert.equal(controller.scrollTop, 240);
  assert.equal(controller.model?.revision, "x");
});

test("only relevant canonical roots invalidate Today", () => {
  const controller = new TodayDashboardController(new Client(), "2026-07-16");
  assert.equal(controller.shouldRefresh("plans/a.md"), true);
  assert.equal(controller.shouldRefresh("wiki/a.md"), false);
  assert.equal(controller.sourceLink("plans/a.md", "Tasks"), "plans/a.md#Tasks");
});
