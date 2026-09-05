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
  notify(method: string, params: Record<string, unknown> = {}): void { for (const listener of this.listeners) listener(method, params); }
}

class FakeHost implements ObsidianHost {
  opened: string[] = []; executed: string[] = []; copied: string[] = []; disposers = 0; commands = new Map<string, () => void>();
  addRibbonIcon(_i: string, _t: string, cb: () => void): () => void { this.ribbon = cb; return () => { this.disposers++; }; }
  addCommand(id: string, _name: string, cb: () => void): () => void { this.commands.set(id, cb); return () => { this.disposers++; }; }
  registerView(_type: string, _factory: () => unknown): () => void { return () => { this.disposers++; }; }
  openView(type: string): void { this.opened.push(type); }
  executeCommand(id: string): void { this.executed.push(id); }
  async copyText(text: string): Promise<void> { this.copied.push(text); }
  async saveSettings(_settings: LifeOSSettings): Promise<void> {}
  ribbon?: () => void;
}

const settings: LifeOSSettings = { configPath: "lifeos.yml", pythonPath: "python3", actorId: "me", startOnLoad: true, diagnostics: "normal" };

test("plugin loads, opens views including Explore, invalidates, and unloads cleanly", async () => {
  const host = new FakeHost(); const bridge = new FakeBridge(); const plugin = new LifeOSPlugin(host, bridge, settings);
  await plugin.load();
  assert.equal(plugin.connection.current, "connected");
  plugin.openToday(); host.commands.get("lifeos-open-explore")?.(); host.commands.get("lifeos-open-goal-plan")?.(); host.commands.get("lifeos-open-knowledge-conversation")?.(); host.commands.get("lifeos-open-experiments")?.(); host.commands.get("lifeos-open-rich-capture")?.(); host.commands.get("lifeos-open-personal-model")?.(); host.commands.get("lifeos-open-proposals")?.();
  assert.deepEqual(host.opened, [LifeOSPlugin.VIEW_TYPE, LifeOSPlugin.EXPLORE_VIEW_TYPE, LifeOSPlugin.COPILOT_VIEW_TYPE, LifeOSPlugin.KNOWLEDGE_CONVERSATION_VIEW_TYPE, LifeOSPlugin.EXPERIMENT_VIEW_TYPE, LifeOSPlugin.RICH_CAPTURE_VIEW_TYPE, LifeOSPlugin.PERSONAL_MODEL_VIEW_TYPE, LifeOSPlugin.PROPOSAL_VIEW_TYPE]);
  bridge.notify("vault.changed");
  assert.equal(plugin.view.refreshCount, 1);
  await plugin.unload();
  assert.equal(bridge.stops, 1); assert.equal(bridge.listeners.size, 0); assert.equal(host.disposers, 40);
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

test("unexpected bridge exit changes the plugin to an actionable unavailable state", async () => {
  const bridge = new FakeBridge(); const plugin = new LifeOSPlugin(new FakeHost(), bridge, settings);
  await plugin.load();
  bridge.notify("system.bridge_stopped", { detail: "The bridge exited with code 1." });
  assert.equal(plugin.connection.current, "unavailable");
  assert.equal(plugin.view.state.kind, "error");
  await plugin.unload();
});
