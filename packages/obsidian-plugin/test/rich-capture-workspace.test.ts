import assert from "node:assert/strict";
import test from "node:test";
import {
  BridgeClient,
  CaptureArtifact,
  CaptureMergePreview,
  HandshakeResult,
  LifeOSSettings,
  RichCaptureWorkspaceController,
} from "../src/index.js";

function artifact(overrides: Partial<CaptureArtifact["metadata"]> = {}): CaptureArtifact {
  return {
    path: "captures/2026/lunch-cap-123.md",
    content_hash: "sha256:abc",
    human_body: "## User annotations\n",
    metadata: {
      id: "cap-123",
      type: "rich-capture",
      schema_version: 1,
      title: "Lunch",
      description: "Soup",
      capture_type: "meal",
      state: "captured",
      captured_at: "2026-07-16T12:00:00Z",
      event_at: "2026-07-16T12:00:00Z",
      timezone: "Europe/Istanbul",
      source_entry_point: "ribbon",
      privacy_scope: "standard",
      sensitive: false,
      tags: [],
      attachments: [],
      links: [],
      derived_values: [],
      domain_data: {},
      extraction_status: "not-requested",
      enrichment_status: "not-requested",
      exclude_from_semantic: false,
      exclude_from_conversations: false,
      exclude_from_reviews: false,
      exclude_from_experiments: false,
      provenance: [],
      lifecycle: [],
      merged_from: [],
      created_at: "2026-07-16T12:00:00Z",
      updated_at: "2026-07-16T12:00:00Z",
      ...overrides,
    },
  };
}

class Client implements BridgeClient {
  calls: Array<[string, Record<string, unknown>]> = [];
  current = artifact();
  failure?: { code: string; message: string };
  async start(_settings: LifeOSSettings): Promise<HandshakeResult> { throw new Error("unused"); }
  async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    this.calls.push([method, params]);
    if (this.failure) throw this.failure;
    if (method === "capture.create" || method === "capture.read" || method === "capture.update" || method === "capture.inference.decide" || method === "capture.link") {
      this.current = { ...this.current, content_hash: `sha256:${this.calls.length}` };
      return this.current as T;
    }
    if (method === "capture.filter") return [this.current] as T;
    if (method === "capture.attachment.add") {
      this.current = {
        ...this.current,
        content_hash: "sha256:attached",
        metadata: {
          ...this.current.metadata,
          attachments: [{
            attachment_id: "att-1", manifest_path: "attachments/manifests/att-1.md",
            content_hash: "sha256:file", media_type: "image/png", byte_size: 10,
            original_filename: "meal.png", canonical_path: "attachments/originals/meal.png",
            relationship: "evidence",
          }],
        },
      };
      return { capture: this.current, attachment: { reference: this.current.metadata.attachments[0], manifest_path: "attachments/manifests/att-1.md", duplicate_detected: false, reused_existing: false } } as T;
    }
    if (method === "capture.attachment.audit") return { attachment_id: "att-1", status: "ok", canonical_path: "attachments/originals/meal.png", expected_hash: "sha256:file", details: "" } as T;
    if (method === "capture.enrichment.start") return { job_id: "job-1", capture_path: this.current.path, attachment_ids: ["att-1"], state: "queued", completed_attachment_ids: [], failed_attachment_ids: [], created_at: "now", updated_at: "now" } as T;
    if (method === "capture.enrichment.run") return { job_id: "job-1", capture_path: this.current.path, attachment_ids: ["att-1"], state: "completed", completed_attachment_ids: ["att-1"], failed_attachment_ids: [], created_at: "now", updated_at: "now" } as T;
    if (method === "capture.enrichment.cancel") return { job_id: "job-1", capture_path: this.current.path, attachment_ids: ["att-1"], state: "cancelled", completed_attachment_ids: [], failed_attachment_ids: [], created_at: "now", updated_at: "now" } as T;
    if (method === "capture.enrichment.retry") return { job_id: "job-1", capture_path: this.current.path, attachment_ids: ["att-1"], state: "queued", completed_attachment_ids: [], failed_attachment_ids: [], created_at: "now", updated_at: "now" } as T;
    if (method === "capture.merge.preview") return { source_paths: [this.current.path, "captures/other.md"], source_hashes: [this.current.content_hash, "sha256:other"], title: "Merged", capture_type: "meal", attachment_ids: ["att-1"], link_paths: [], warnings: ["Review"] } as T;
    if (method === "capture.merge.apply") return artifact({ title: "Merged", merged_from: ["cap-1", "cap-2"] }) as T;
    if (method === "capture.proposal.preview") return { proposal_id: "prop-1", target_path: "notes/x.md", operation: "create_file", source_capture_id: "cap-123", source_capture_hash: this.current.content_hash, attachment_ids: [], included_actions: [], excluded_actions: [] } as T;
    if (method === "capture.proposal.create") return { proposal_id: "prop-1", proposal_path: "proposals/prop-1", preview: { proposal_id: "prop-1", target_path: "notes/x.md", operation: "create_file", source_capture_id: "cap-123", source_capture_hash: this.current.content_hash, attachment_ids: [], included_actions: [], excluded_actions: [] } } as T;
    throw new Error(`unhandled ${method}`);
  }
  onNotification(_listener: (method: string, params: Record<string, unknown>) => void): () => void { return () => undefined; }
  async stop(): Promise<void> {}
}

test("quick capture saves first and supports delayed attachment processing", async () => {
  const client = new Client(); const opened: string[] = [];
  const controller = new RichCaptureWorkspaceController(client, (path) => opened.push(path));
  controller.prepare("mobile-share", "meal", "Soup photo");
  assert.equal(controller.state.stage, "quick-capture");
  assert.equal(controller.state.mobile.touchTargetMinPx, 44);
  await controller.saveQuick("2026-07-16T12:00:00Z");
  await controller.attachFiles(["/tmp/meal.png"]);
  const job = await controller.startProcessing();
  assert.equal(job.state, "queued");
  await controller.runProcessing();
  assert.equal(controller.state.stage, "ready");
  controller.openArtifact();
  controller.openOriginal("att-1");
  assert.deepEqual(opened, ["captures/2026/lunch-cap-123.md", "attachments/originals/meal.png"]);
  assert.equal(client.calls[0]?.[0], "capture.create");
});

test("review supports explicit inference decisions, links, filters, merge previews, and proposals", async () => {
  const client = new Client(); const controller = new RichCaptureWorkspaceController(client);
  await controller.load("captures/2026/lunch-cap-123.md");
  await controller.decideInference("calories", "reject");
  await controller.link({ path: "experiments/walk.md", relation: "evidence", artifact_type: "experiment" });
  await controller.list("meal", ["meal"], ["captured"]);
  const preview: CaptureMergePreview = await controller.previewMerge([client.current.path, "captures/other.md"]);
  assert.equal(preview.warnings[0], "Review");
  await controller.applyMerge(preview);
  await controller.previewProposal({ action: "create-note", targetPath: "notes/x.md", content: "# X", createTarget: true });
  await controller.createProposal({ action: "create-note", targetPath: "notes/x.md", content: "# X", createTarget: true });
  assert.equal(controller.state.stage, "proposal-created");
  assert.equal(client.calls.some(([method]) => method.includes("execute") || method.includes("apply-proposal")), false);
});

test("degraded states remain explicit and preserve recovery guidance", async () => {
  const client = new Client(); const controller = new RichCaptureWorkspaceController(client);
  for (const [code, expected] of [
    ["stale_capture", "stale-artifact"], ["missing_attachment", "missing-attachment"],
    ["sensitive_content_blocked", "sensitive-blocked"], ["timeout", "provider-timeout"],
    ["unsupported_schema", "unsupported-schema"], ["stale_merge", "merge-conflict"],
  ] as const) {
    client.failure = { code, message: code };
    await assert.rejects(() => controller.load("captures/x.md"));
    assert.equal(controller.state.stage, expected);
    assert.equal(Boolean(controller.state.recovery), true);
  }
});

test("keyboard and mobile contracts are accessible and avoid direct external mutation", () => {
  const controller = new RichCaptureWorkspaceController(new Client());
  const actions = controller.keyboardActions();
  assert.deepEqual(actions.map((item) => item.shortcut), ["S", "A", "R", "P", "L", "F", "M", "O"]);
  assert.equal(actions.every((item) => item.ariaLabel.length > item.label.length), true);
  assert.equal(actions.some((item) => item.id === "apply-external"), false);
  assert.deepEqual(controller.state.mobile, { columns: 1, touchTargetMinPx: 44, enrichmentDeferred: true });
});
