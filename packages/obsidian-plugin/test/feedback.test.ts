import assert from "node:assert/strict";
import test from "node:test";
import { BridgeClient, FeedbackController, HandshakeResult, LifeOSSettings } from "../src/index.js";

class Client implements BridgeClient {
  calls: Array<[string, Record<string, unknown>]> = [];
  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }
  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push([method, params]);
    return { schema_version: 1, mode: params.mode ?? "off", disabled_dimensions: params.disabled_dimensions ?? [], excluded_event_ids: [], dismissed_diagnoses: [], content_hash: "next" } as T;
  }
  onNotification(): () => void { return () => {}; }
  async stop(): Promise<void> {}
}

test("feedback controls use typed bridge mutations and preserve baseline access", async () => {
  const client = new Client();
  const controller = new FeedbackController(client);
  const current = { schema_version: 1, mode: "off" as const, disabled_dimensions: [], excluded_event_ids: [], dismissed_diagnoses: [], content_hash: "old" };
  await controller.setMode(current, "shadow", "key");
  await controller.disableDimensions(current, ["energy"], "key-2");
  assert.equal(client.calls[0]?.[0], "feedback.preferences.update");
  assert.equal(client.calls[0]?.[1].expected_hash, "old");
  assert.deepEqual(controller.baseline({ mode: "shadow", baseline: { items: [] }, adaptive: {}, returned: {}, adjustments: [], deltas: [], feedback_status: "available" }), { items: [] });
  assert.equal(controller.ariaModeLabel("active"), "Adaptive planning mode: active");
});


test("adaptive replay, migration, and keyboard paths stay on typed bridge methods", async () => {
  const client = new Client();
  const controller = new FeedbackController(client);
  await controller.migratePreferences(true);
  await controller.replay([{ day: "2026-07-16", available_minutes: 60 }], "shadow");
  assert.equal(client.calls.at(-2)?.[0], "feedback.preferences.migrate");
  assert.equal(client.calls.at(-1)?.[0], "feedback.replay");
  const actions = controller.criticalActions();
  assert.deepEqual(actions.map((item) => item.shortcut), ["Enter", "B", "C", "E", "R"]);
  assert.equal(actions.every((item) => item.label.length > 8), true);
});
