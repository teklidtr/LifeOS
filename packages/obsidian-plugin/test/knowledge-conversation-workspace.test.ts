import assert from "node:assert/strict";
import test from "node:test";
import {
  BridgeClient, HandshakeResult, KnowledgeConversationWorkspaceController, LifeOSSettings, emptyScope,
} from "../src/index.js";

const artifact = (hash = "sha256:a", state = "evidence-only") => ({
  path: "conversations/2026/energy-conv-x.md", content_hash: hash, human_body: "## Annotations\n",
  metadata: {
    type: "knowledge-conversation" as const, conversation_schema: 1, conversation_id: "conv-x", title: "Energy",
    created_at: "2026-07-16T00:00:00Z", updated_at: "2026-07-16T00:00:00Z", status: "active" as const,
    retrieval_scope: emptyScope(), pinned_sources: [], excluded_sources: [],
  },
  turns: state ? [{
    turn_id: "turn-001", created_at: "2026-07-16T00:00:00Z", query: "ATP", state,
    evidence: [{ evidence_id: "chunk:1", path: "wiki/source.md", heading: "Evidence", start_line: 3, end_line: 3,
      source_hash: "sha256:s", chunk_hash: "sha256:c", excerpt: "Mitochondria produce ATP.",
      ranking: { exact: 0, lexical: 1, semantic: 0, metadata: 0, link: 0, graph: 0, rerank: 0, total: .38 }, support: "direct" as const, stale: false }],
    answer: [], explanation: "Evidence only", provider_disclosure: {}, diagnostics: [],
  }] : [],
});

class Client implements BridgeClient {
  calls: Array<[string, Record<string, unknown>]> = [];
  failure?: { code: string; message: string };
  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }
  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push([method, params]); if (this.failure) throw this.failure;
    if (method === "retrieval.index.health") return { state: "healthy", active_usable: true, documents: 1, chunks: 1, embeddings: 0, stale_embeddings: 0, missing_embeddings: 0, stale_paths: [], missing_paths: [], orphaned_paths: [], diagnostics: [] } as T;
    if (method === "retrieval.index.rebuild") return { status: "complete" } as T;
    if (method === "retrieval.search") return { query: params.query, state: "ready", index_state: "healthy", semantic_state: "not-configured", rerank_state: "not-requested", context_characters: 20, scope: params.scope, diagnostics: [], provider_disclosure: {}, results: [{ evidence_id: "chunk:1", path: "wiki/source.md", heading: "Evidence", start_line: 3, end_line: 3, context_text: "ATP", ranking: { exact: 0, lexical: 1, semantic: 0, metadata: 0, link: 0, graph: 0, rerank: 0, total: .38 }, scope_reason: "allowed", duplicate_paths: [] }] } as T;
    if (method === "conversation.create") return artifact("sha256:a", "") as T;
    if (method === "conversation.load") return artifact() as T;
    if (method === "conversation.list") return [artifact()] as T;
    if (method === "conversation.ask") return artifact("sha256:b") as T;
    if (["conversation.scope.update", "conversation.source.pin", "conversation.source.exclude", "conversation.rename", "conversation.archive", "conversation.branch"].includes(method)) return artifact("sha256:c") as T;
    if (method === "conversation.stale.check") { const value = artifact().turns; value[0]!.evidence[0]!.stale = true; return value as T; }
    if (method === "conversation.proposal.preview") return { proposal_id: "prop-x", action: params.action, target_path: params.target_path, operation: "create_file", evidence: [{}] } as T;
    if (method === "conversation.proposal.create") return { proposal_id: "prop-x", proposal_path: "proposals/prop-x", preview: { proposal_id: "prop-x", action: params.action, target_path: params.target_path, operation: "create_file", evidence: [{}] } } as T;
    throw new Error(`unsupported ${method}`);
  }
  onNotification(): () => void { return () => undefined; }
  async stop(): Promise<void> {}
}

test("evidence-first workflow inspects scope, asks, pins, branches, and proposes without apply", async () => {
  const client = new Client(); const opened: string[] = [];
  const controller = new KnowledgeConversationWorkspaceController(client, (path) => opened.push(path));
  controller.prepare("active-note", { paths: ["wiki/source.md"] }, "ATP");
  assert.equal(controller.state.stage, "scope-review");
  await controller.inspectRetrieval();
  assert.equal(controller.state.evidence[0]?.path, "wiki/source.md");
  await controller.create("Energy");
  await controller.ask("ATP", true);
  await controller.pin("wiki/source.md");
  await controller.exclude("wiki/irrelevant.md");
  await controller.branch();
  const preview = await controller.previewProposal({ action: "draft_note", targetPath: "wiki/new.md", content: "Grounded." });
  assert.equal(preview.operation, "create_file");
  await controller.createProposal({ action: "draft_note", targetPath: "wiki/new.md", content: "Grounded." });
  controller.openEvidence(controller.state.conversation!.turns[0]!.evidence[0]!);
  assert.equal(opened[0], "wiki/source.md#Evidence");
  assert.equal(client.calls.some(([method]) => method.includes("apply")), false);
});

test("stale evidence and provider failures become explicit recoverable states", async () => {
  const client = new Client(); const controller = new KnowledgeConversationWorkspaceController(client);
  await controller.resume("conversations/x.md"); await controller.checkStale();
  assert.equal(controller.state.stage, "stale");
  client.failure = { code: "timeout", message: "timed out" };
  await assert.rejects(() => controller.ask("again"));
  assert.equal(controller.state.stage, "timeout");
  assert.equal((controller.state.recovery ?? "").includes("evidence-only"), true);
});

test("keyboard controls expose evidence and proposal actions but never direct mutation", () => {
  const actions = new KnowledgeConversationWorkspaceController(new Client()).keyboardActions();
  assert.deepEqual(actions.map((item) => item.shortcut), ["S", "Enter", "E", "P", "X", "B", "D"]);
  assert.equal(actions.some((item) => item.id === "apply"), false);
  assert.equal(actions.every((item) => item.ariaLabel.length > item.label.length), true);
});
