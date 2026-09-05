import assert from "node:assert/strict";
import test from "node:test";

import {
  type BridgeClient,
  type HandshakeResult,
  type LifeOSSettings,
  ExploreWorkspaceController,
  type CapabilityEntryPoint,
} from "../src/index.js";

class FakeBridge implements BridgeClient {
  calls: Array<{ method: string; params: Record<string, unknown> }> = [];

  constructor(
    private readonly response: unknown,
    private readonly failure?: unknown,
  ) {}

  async start(_settings: LifeOSSettings): Promise<HandshakeResult> {
    return {
      protocol: "1.0",
      engine_version: "0.0.1",
      runtime_schema: 1,
      capabilities: ["capability.list"],
      actor_id: "test",
    };
  }

  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push({ method, params });
    if (this.failure) throw this.failure;
    return this.response as T;
  }

  onNotification(_listener: (method: string, params: Record<string, unknown>) => void): () => void {
    return () => undefined;
  }

  async stop(): Promise<void> {}
}

function capability(
  id: string,
  name: string,
  category: string,
  options: {
    visibility?: "explore" | "internal";
    maturity?: "stable" | "beta" | "experimental";
    requirements?: string[];
    entry_points?: CapabilityEntryPoint[];
    example_prompts?: string[];
  } = {},
): Record<string, unknown> {
  return {
    id,
    name,
    description: `${name} description`,
    category,
    visibility: options.visibility ?? "explore",
    maturity: options.maturity ?? "stable",
    requirements: options.requirements ?? [],
    backing: [{ kind: "bridge_method", ref: `${id}.read` }],
    entry_points: options.entry_points ?? [],
    example_prompts: options.example_prompts ?? [],
  };
}

function response(capabilities: Record<string, unknown>[]): Record<string, unknown> {
  return {
    semantic_capability_schema: 1,
    capabilities,
  };
}

test("Explore loads only visible capabilities and groups them deterministically", async () => {
  const bridge = new FakeBridge(response([
    capability("planning.today", "Plan today", "Planning", {
      requirements: ["A configured LifeOS vault"],
    }),
    capability("system.runtime", "Desktop runtime", "Setup", { visibility: "internal" }),
    capability("knowledge.ask", "Ask my notes", "Knowledge", { maturity: "beta" }),
  ]));
  const controller = new ExploreWorkspaceController(bridge);

  await controller.load();

  assert.equal(controller.state.stage, "ready");
  assert.deepEqual(controller.state.capabilities.map((item) => item.id), [
    "knowledge.ask",
    "planning.today",
  ]);
  assert.deepEqual(controller.categories, ["Knowledge", "Planning"]);
  assert.deepEqual(controller.groupedCapabilities.map((group) => group.category), [
    "Knowledge",
    "Planning",
  ]);
  assert.equal(controller.selected?.id, "knowledge.ask");
  assert.deepEqual(bridge.calls, [{ method: "capability.list", params: {} }]);
});

test("Explore search and category filters stay local to the returned registry payload", async () => {
  const bridge = new FakeBridge(response([
    capability("planning.today", "Plan today", "Planning", {
      requirements: ["A configured LifeOS vault"],
    }),
    capability("knowledge.ask", "Ask my notes", "Knowledge"),
    capability("knowledge.research", "Capture research", "Knowledge"),
  ]));
  const controller = new ExploreWorkspaceController(bridge);
  await controller.load();

  controller.setCategory("Knowledge");
  assert.deepEqual(controller.visibleCapabilities.map((item) => item.id), [
    "knowledge.ask",
    "knowledge.research",
  ]);

  controller.setQuery("research");
  assert.deepEqual(controller.visibleCapabilities.map((item) => item.id), ["knowledge.research"]);
  assert.equal(controller.selected?.id, "knowledge.research");

  controller.setQuery("configured");
  assert.deepEqual(controller.visibleCapabilities, []);
  assert.equal(controller.selected, undefined);

  controller.setCategory("Planning");
  assert.deepEqual(controller.visibleCapabilities.map((item) => item.id), ["planning.today"]);
  assert.equal(bridge.calls.length, 1, "filtering must not make new bridge calls");
});

test("Explore preserves details, copies prompts without running them, and dispatches declared Obsidian entry points", async () => {
  const opened: CapabilityEntryPoint[] = [];
  const copied: string[] = [];
  const prompt = "Use my LifeOS plans to show what I could focus on today.";
  const viewEntry: CapabilityEntryPoint = {
    kind: "obsidian_view",
    target: "lifeos-today",
    label: "Open LifeOS Today",
  };
  const commandEntry: CapabilityEntryPoint = {
    kind: "obsidian_command",
    target: "lifeos-open-today",
    label: "Open LifeOS Today",
  };
  const cliEntry: CapabilityEntryPoint = {
    kind: "cli",
    target: "lifeos.plan.today",
    label: "lifeos plan today",
  };
  const bridge = new FakeBridge(response([
    capability("planning.today", "Plan today", "Planning", {
      requirements: ["A configured LifeOS vault"],
      entry_points: [viewEntry, commandEntry, cliEntry],
      example_prompts: [prompt],
    }),
  ]));
  const controller = new ExploreWorkspaceController(
    bridge,
    (entryPoint) => opened.push(entryPoint),
    async (text) => { copied.push(text); },
  );
  await controller.load();

  assert.deepEqual(controller.selected?.requirements, ["A configured LifeOS vault"]);
  assert.equal(await controller.copyExamplePrompt(prompt), true);
  assert.deepEqual(copied, [prompt]);
  assert.match(controller.state.statusAnnouncement, /not submitted or run/i);

  assert.equal(controller.activateEntryPoint(viewEntry), true);
  assert.equal(controller.activateEntryPoint(commandEntry), true);
  assert.equal(controller.activateEntryPoint(cliEntry), false);
  assert.deepEqual(opened, [viewEntry, commandEntry]);
});

test("Explore rejects undeclared entry points instead of dispatching arbitrary commands", async () => {
  const opened: CapabilityEntryPoint[] = [];
  const declared: CapabilityEntryPoint = {
    kind: "obsidian_command",
    target: "lifeos-open-today",
    label: "Open LifeOS Today",
  };
  const controller = new ExploreWorkspaceController(
    new FakeBridge(response([
      capability("planning.today", "Plan today", "Planning", { entry_points: [declared] }),
    ])),
    (entryPoint) => opened.push(entryPoint),
  );
  await controller.load();

  assert.equal(controller.activateEntryPoint({
    kind: "obsidian_command",
    target: "editor:delete-paragraph",
    label: "Unexpected",
  }), false);
  assert.deepEqual(opened, []);
});

test("Explore exposes empty, malformed, and bridge-unavailable recovery states", async () => {
  const empty = new ExploreWorkspaceController(new FakeBridge(response([
    capability("system.runtime", "Desktop runtime", "Setup", { visibility: "internal" }),
  ])));
  await empty.load();
  assert.equal(empty.state.stage, "empty");

  const malformed = new ExploreWorkspaceController(new FakeBridge({
    semantic_capability_schema: 99,
    capabilities: [],
  }));
  await malformed.load();
  assert.equal(malformed.state.stage, "malformed");
  assert.match(malformed.state.detail, /schema/i);

  const unavailable = new ExploreWorkspaceController(new FakeBridge(
    response([]),
    { code: "bridge_unavailable", message: "Bridge is not running." },
  ));
  await unavailable.load();
  assert.equal(unavailable.state.stage, "bridge-unavailable");
  assert.match(unavailable.state.detail, /not running/i);
});

test("Explore reconnects and retries the semantic registry load", async () => {
  let reconnected = 0;
  const controller = new ExploreWorkspaceController(
    new FakeBridge(response([
      capability("planning.today", "Plan today", "Planning"),
    ])),
    () => undefined,
    async () => undefined,
    async () => { reconnected += 1; },
  );

  await controller.reconnect();

  assert.equal(reconnected, 1);
  assert.equal(controller.state.stage, "ready");
  assert.equal(controller.state.capabilities.length, 1);
});
