import assert from "node:assert/strict";
import test from "node:test";
import { BridgeClient, HandshakeResult, LifeOSPlugin, LifeOSSettings, ObsidianHost } from "../src/index.js";

class FakeBridge implements BridgeClient {
  starts = 0; stops = 0; listeners = new Set<(method: string, params: Record<string, unknown>) => void>();
  constructor(private readonly handshake: HandshakeResult = { protocol: "1.0", engine_version: "0.0.1", runtime_schema: 1, capabilities: [], actor_id: "me" }, private readonly failure?: Error) {}
  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { this.starts++; if (this.failure) throw this.failure; return this.handshake; }
  async call<T>(_method: string, _params: Record<string, unknown>): Promise<T> { throw new Error("unused"); }
  onNotification(listener: (method: string, params: Record<string, unknown>) => void): () => void { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  async stop(): Promise<void> { this.stops++; }
  notify(method: string): void { for (const listener of this.listeners) listener(method, {}); }
}

class FakeHost implements ObsidianHost {
  opened: string[] = []; disposers = 0;
  addRibbonIcon(_i: string, _t: string, cb: () => void): () => void { this.ribbon = cb; return () => { this.disposers++; }; }
  addCommand(_id: string, _name: string, cb: () => void): () => void { this.command = cb; return () => { this.disposers++; }; }
  registerView(_type: string, _factory: () => unknown): () => void { return () => { this.disposers++; }; }
  openView(type: string): void { this.opened.push(type); }
  async saveSettings(_settings: LifeOSSettings): Promise<void> {}
  ribbon?: () => void; command?: () => void;
}

const settings: LifeOSSettings = { configPath: "lifeos.yml", pythonPath: "python3", actorId: "me", startOnLoad: true, diagnostics: "normal" };

test("plugin loads, opens view, invalidates, and unloads cleanly", async () => {
  const host = new FakeHost(); const bridge = new FakeBridge(); const plugin = new LifeOSPlugin(host, bridge, settings);
  await plugin.load();
  assert.equal(plugin.connection.current, "connected");
  host.ribbon?.(); host.command?.();
  assert.deepEqual(host.opened, [LifeOSPlugin.VIEW_TYPE, LifeOSPlugin.VIEW_TYPE]);
  bridge.notify("vault.changed");
  assert.equal(plugin.view.refreshCount, 1);
  await plugin.unload();
  assert.equal(bridge.stops, 1); assert.equal(bridge.listeners.size, 0); assert.equal(host.disposers, 3);
});

test("missing Python is actionable and non-destructive", async () => {
  const plugin = new LifeOSPlugin(new FakeHost(), new FakeBridge(undefined, new Error("Python executable not found")), settings);
  await plugin.load();
  assert.equal(plugin.connection.current, "unavailable");
  assert.equal(plugin.view.state.kind, "error");
  await plugin.unload();
});

test("protocol mismatch becomes blocked", async () => {
  const bridge = new FakeBridge({ protocol: "2.0", engine_version: "2", runtime_schema: 1, capabilities: [], actor_id: "me" });
  const plugin = new LifeOSPlugin(new FakeHost(), bridge, settings);
  await plugin.load();
  assert.equal(plugin.connection.current, "incompatible");
  assert.equal(plugin.view.state.kind, "blocked");
  await plugin.unload();
});

test("runtime schema mismatch becomes blocked", async () => {
  const bridge = new FakeBridge({ protocol: "1.0", engine_version: "2", runtime_schema: 2, capabilities: [], actor_id: "me" });
  const plugin = new LifeOSPlugin(new FakeHost(), bridge, settings);
  await plugin.load();
  assert.equal(plugin.connection.current, "incompatible");
  assert.equal(plugin.view.state.kind, "blocked");
  await plugin.unload();
});

test("repeated load call does not start duplicate process", async () => {
  const bridge = new FakeBridge(); const plugin = new LifeOSPlugin(new FakeHost(), bridge, settings);
  await plugin.load(); await plugin.connection.start(settings);
  assert.equal(bridge.starts, 1);
  await plugin.unload();
});
