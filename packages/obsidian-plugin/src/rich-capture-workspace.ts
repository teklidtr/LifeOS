import { BridgeClient } from "./protocol.js";
import {
  ArtifactLink,
  AttachmentAudit,
  AttachmentImportResult,
  CaptureArtifact,
  CaptureMergePreview,
  CaptureProposalPreview,
  CaptureProposalResult,
  CaptureState,
  CaptureType,
  PrivacyScope,
  ProcessingJob,
} from "./rich-capture.js";

export type RichCaptureOrigin =
  | "ribbon" | "command-palette" | "active-note" | "selection" | "clipboard"
  | "paste" | "drag-drop" | "folder-drop" | "mobile-share" | "daily-review"
  | "weekly-review" | "experiment" | "knowledge-conversation" | "goal" | "plan"
  | "task" | "habit" | "diary";

export type RichCaptureMode =
  | "quick" | "review" | "timeline" | "gallery" | "list" | "meal"
  | "exercise" | "attachment" | "unresolved" | "failed" | "archived";

export type RichCaptureStage =
  | "idle" | "quick-capture" | "saving" | "ready" | "empty" | "needs-review"
  | "processing-queued" | "processing" | "processing-cancelled" | "failed-processing"
  | "archived" | "missing-attachment" | "changed-attachment" | "unsupported-file"
  | "oversized-file" | "duplicate-file" | "malformed-artifact" | "stale-artifact"
  | "unsupported-schema" | "provider-unavailable" | "provider-timeout"
  | "sensitive-blocked" | "index-unavailable" | "index-stale" | "migration-required"
  | "proposal-created" | "proposal-stale" | "merge-conflict" | "storage-failure" | "error";

export interface QuickCaptureDraft {
  title: string;
  captureType: CaptureType;
  description: string;
  eventAt?: string;
  timezone: string;
  privacyScope: PrivacyScope;
  sensitive: boolean;
  tags: string[];
  sourcePath?: string;
}

export interface RichCaptureWorkspaceState {
  stage: RichCaptureStage;
  mode: RichCaptureMode;
  origin: RichCaptureOrigin;
  draft: QuickCaptureDraft;
  artifact?: CaptureArtifact;
  captures: CaptureArtifact[];
  selectedPaths: string[];
  processingJob?: ProcessingJob;
  mergePreview?: CaptureMergePreview;
  proposalPreview?: CaptureProposalPreview;
  attachmentAudits: AttachmentAudit[];
  focusTarget: string;
  statusAnnouncement: string;
  detail?: string;
  recovery?: string;
  mobile: { columns: 1; touchTargetMinPx: 44; enrichmentDeferred: boolean };
}

export interface CaptureProposalInput {
  action: string;
  targetPath: string;
  content: string;
  createTarget?: boolean;
  attachmentIds?: string[];
  includedActions?: string[];
  excludedActions?: string[];
  now?: string;
}

export interface RichCaptureAction {
  id: string;
  label: string;
  shortcut: string;
  ariaLabel: string;
}

function blankDraft(captureType: CaptureType = "attachment", description = ""): QuickCaptureDraft {
  return {
    title: captureType === "meal" ? "Meal" : captureType === "exercise" ? "Exercise" : "Capture",
    captureType,
    description,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    privacyScope: "standard",
    sensitive: false,
    tags: [],
  };
}

function errorState(current: RichCaptureWorkspaceState, error: unknown): RichCaptureWorkspaceState {
  const value = error as { code?: string; message?: string };
  const code = value.code ?? "unknown";
  const detail = value.message ?? String(error);
  const common = { ...current, detail, focusTarget: "rich-capture-status", statusAnnouncement: detail };
  const mapped: Partial<Record<string, [RichCaptureStage, string]>> = {
    stale_capture: ["stale-artifact", "Reload canonical Markdown before retrying the edit."],
    stale_manifest: ["stale-artifact", "Reload the attachment manifest before retrying."],
    stale_merge: ["merge-conflict", "Refresh the merge preview because a source capture changed."],
    malformed_artifact: ["malformed-artifact", "Repair the canonical Markdown or inspect it outside managed editing."],
    unsupported_schema: ["unsupported-schema", "Preview migration or open the canonical Markdown read-only."],
    missing_attachment: ["missing-attachment", "Locate the original file or remove the broken reference deliberately."],
    changed_attachment: ["changed-attachment", "Re-run extraction after reviewing the changed original bytes."],
    unsupported_file: ["unsupported-file", "Keep the file preserved and skip unsupported processing."],
    oversized_for_extraction: ["oversized-file", "Keep the original and skip or narrow enrichment."],
    sensitive_content_blocked: ["sensitive-blocked", "Review the exact external payload and grant explicit scope, or stay local-only."],
    provider_unavailable: ["provider-unavailable", "Continue with manual fields and deterministic local extraction."],
    timeout: ["provider-timeout", "Retry optional enrichment or continue without it."],
    proposal_stale: ["proposal-stale", "Refresh the target and create a new proposal preview."],
    storage_write_failure: ["storage-failure", "The original capture remains safe; retry storage after checking disk access."],
  };
  const match = mapped[code];
  return match
    ? { ...common, stage: match[0], recovery: match[1] }
    : { ...common, stage: "error", recovery: "Retry, rebuild derived state, or open canonical Markdown directly." };
}

export class RichCaptureWorkspaceController {
  state: RichCaptureWorkspaceState = {
    stage: "idle",
    mode: "quick",
    origin: "command-palette",
    draft: blankDraft(),
    captures: [],
    selectedPaths: [],
    attachmentAudits: [],
    focusTarget: "rich-capture-title",
    statusAnnouncement: "Rich capture workspace is ready.",
    mobile: { columns: 1, touchTargetMinPx: 44, enrichmentDeferred: true },
  };

  constructor(
    private readonly client: BridgeClient,
    private readonly openPath: (path: string) => void = () => undefined,
  ) {}

  prepare(origin: RichCaptureOrigin, captureType: CaptureType = "attachment", description = "", sourcePath?: string): void {
    this.state = {
      ...this.state,
      stage: "quick-capture",
      mode: "quick",
      origin,
      draft: { ...blankDraft(captureType, description), sourcePath },
      detail: "Only a title or description is needed. Save first; enrich later.",
      recovery: undefined,
      focusTarget: "rich-capture-description",
      statusAnnouncement: "Quick capture opened. Original input will be saved before processing.",
    };
  }

  setDraft(fields: Partial<QuickCaptureDraft>): void {
    this.state = { ...this.state, draft: { ...this.state.draft, ...fields } };
  }

  async saveQuick(now?: string): Promise<CaptureArtifact> {
    this.loading("Saving canonical capture Markdown.");
    const draft = this.state.draft;
    try {
      const artifact = await this.client.call<CaptureArtifact>("capture.create", {
        title: draft.title,
        capture_type: draft.captureType,
        description: draft.description,
        event_at: draft.eventAt,
        timezone: draft.timezone,
        source_entry_point: this.state.origin,
        privacy_scope: draft.privacyScope,
        sensitive: draft.sensitive,
        tags: draft.tags,
        now,
      });
      return this.accept(artifact, "Capture saved. Optional enrichment can happen later.");
    } catch (error) { return this.fail(error); }
  }

  async load(path: string, origin = this.state.origin): Promise<CaptureArtifact> {
    this.loading("Loading canonical capture Markdown.", origin);
    try {
      return this.accept(await this.client.call<CaptureArtifact>("capture.read", { path }), "Capture loaded from canonical Markdown.");
    } catch (error) { return this.fail(error); }
  }

  async list(mode: RichCaptureMode = "list", captureTypes?: CaptureType[], states?: CaptureState[]): Promise<CaptureArtifact[]> {
    this.loading("Loading captures.");
    try {
      const captures = await this.client.call<CaptureArtifact[]>("capture.filter", {
        capture_types: captureTypes,
        states,
      });
      this.state = {
        ...this.state,
        mode,
        stage: captures.length ? "ready" : "empty",
        captures,
        detail: captures.length ? undefined : "No captures match these filters.",
        recovery: captures.length ? undefined : "Change filters or make a quick capture.",
        focusTarget: captures.length ? "rich-capture-results" : "rich-capture-empty",
        statusAnnouncement: captures.length ? `${captures.length} captures loaded.` : "No captures found.",
      };
      return captures;
    } catch (error) { return this.fail(error); }
  }

  async update(fields: {
    title?: string; description?: string; eventAt?: string; tags?: string[]; location?: string;
    privacyScope?: PrivacyScope; sensitive?: boolean; now?: string;
  }): Promise<CaptureArtifact> {
    return this.mutate("capture.update", {
      title: fields.title,
      description: fields.description,
      event_at: fields.eventAt,
      tags: fields.tags,
      location: fields.location,
      privacy_scope: fields.privacyScope,
      sensitive: fields.sensitive,
      now: fields.now,
    }, "Capture updated.");
  }

  async attachFiles(paths: string[], independentCopy = false, now?: string): Promise<CaptureArtifact> {
    let artifact = this.requireArtifact();
    this.loading(`Importing ${paths.length} attachment${paths.length === 1 ? "" : "s"}.`);
    try {
      for (const sourcePath of paths) {
        const result = await this.client.call<{ capture: CaptureArtifact; attachment: AttachmentImportResult }>("capture.attachment.add", {
          path: artifact.path,
          expected_hash: artifact.content_hash,
          source_path: sourcePath,
          independent_copy: independentCopy,
          now,
        });
        artifact = result.capture;
      }
      return this.accept(artifact, "Original attachments preserved and linked.");
    } catch (error) { return this.fail(error); }
  }

  async removeAttachment(attachmentId: string, now?: string): Promise<CaptureArtifact> {
    return this.mutate("capture.attachment.remove", { attachment_id: attachmentId, now }, "Attachment reference removed. Original bytes were not silently deleted.");
  }

  async auditAttachments(): Promise<AttachmentAudit[]> {
    const artifact = this.requireArtifact();
    try {
      const audits: AttachmentAudit[] = [];
      for (const attachment of artifact.metadata.attachments) {
        audits.push(await this.client.call<AttachmentAudit>("capture.attachment.audit", { attachment_id: attachment.attachment_id }));
      }
      const broken = audits.find((item) => item.status === "missing" || item.status === "changed");
      this.state = {
        ...this.state,
        attachmentAudits: audits,
        stage: broken?.status === "missing" ? "missing-attachment" : broken?.status === "changed" ? "changed-attachment" : this.state.stage,
        detail: broken?.details,
        focusTarget: "rich-capture-attachment-status",
        statusAnnouncement: broken ? "Attachment integrity needs review." : "Attachment integrity verified.",
      };
      return audits;
    } catch (error) { return this.fail(error); }
  }

  async startProcessing(now?: string): Promise<ProcessingJob> {
    const artifact = this.requireArtifact();
    this.loading("Queueing optional extraction.");
    try {
      const job = await this.client.call<ProcessingJob>("capture.enrichment.start", {
        path: artifact.path, expected_hash: artifact.content_hash, now,
      });
      this.state = { ...this.state, stage: "processing-queued", processingJob: job, focusTarget: "rich-capture-processing", statusAnnouncement: "Processing queued. The capture is already safe." };
      return job;
    } catch (error) { return this.fail(error); }
  }

  async runProcessing(now?: string): Promise<ProcessingJob> {
    const job = this.requireJob();
    this.state = { ...this.state, stage: "processing", statusAnnouncement: "Processing started.", focusTarget: "rich-capture-processing" };
    try {
      const result = await this.client.call<ProcessingJob>("capture.enrichment.run", { job_id: job.job_id, now });
      this.state = {
        ...this.state,
        processingJob: result,
        stage: result.state === "completed" ? "ready" : result.state === "cancelled" ? "processing-cancelled" : "failed-processing",
        detail: result.failed_attachment_ids.length ? `${result.failed_attachment_ids.length} attachments need review.` : undefined,
        recovery: result.state === "completed" ? undefined : "Retry processing or continue with the original capture.",
        statusAnnouncement: result.state === "completed" ? "Processing completed." : `Processing ${result.state}. Original files remain preserved.`,
      };
      return result;
    } catch (error) { return this.fail(error); }
  }

  async cancelProcessing(now?: string): Promise<ProcessingJob> {
    const job = this.requireJob();
    const result = await this.client.call<ProcessingJob>("capture.enrichment.cancel", { job_id: job.job_id, now });
    this.state = { ...this.state, stage: "processing-cancelled", processingJob: result, statusAnnouncement: "Processing cancelled. Capture remains saved.", focusTarget: "rich-capture-processing" };
    return result;
  }

  async retryProcessing(now?: string): Promise<ProcessingJob> {
    const job = this.requireJob();
    const result = await this.client.call<ProcessingJob>("capture.enrichment.retry", { job_id: job.job_id, now });
    this.state = { ...this.state, stage: "processing-queued", processingJob: result, statusAnnouncement: "Processing queued again.", focusTarget: "rich-capture-processing" };
    return result;
  }

  decideInference(fieldName: string, decision: "confirm" | "reject" | "correct", correctedValue?: unknown, now?: string): Promise<CaptureArtifact> {
    return this.mutate("capture.inference.decide", {
      field_name: fieldName, decision, corrected_value: correctedValue, now,
    }, `Suggestion ${decision === "confirm" ? "confirmed" : decision === "reject" ? "rejected" : "corrected"}.`);
  }

  link(link: ArtifactLink, now?: string): Promise<CaptureArtifact> {
    return this.mutate("capture.link", {
      target_path: link.path,
      relation: link.relation,
      artifact_type: link.artifact_type,
      content_hash: link.content_hash,
      now,
    }, "Capture linked explicitly.");
  }

  unlink(targetPath: string, now?: string): Promise<CaptureArtifact> {
    return this.mutate("capture.unlink", { target_path: targetPath, now }, "Capture link removed.");
  }

  async previewMerge(sourcePaths: string[]): Promise<CaptureMergePreview> {
    try {
      const preview = await this.client.call<CaptureMergePreview>("capture.merge.preview", { source_paths: sourcePaths });
      this.state = { ...this.state, mergePreview: preview, focusTarget: "rich-capture-merge-preview", statusAnnouncement: "Merge preview ready. Sources are unchanged." };
      return preview;
    } catch (error) { return this.fail(error); }
  }

  async applyMerge(preview = this.state.mergePreview, now?: string): Promise<CaptureArtifact> {
    if (!preview) throw new Error("A merge preview is required.");
    try {
      return this.accept(await this.client.call<CaptureArtifact>("capture.merge.apply", { preview, now }), "Captures merged with source history preserved.");
    } catch (error) { return this.fail(error); }
  }

  async split(groups: string[][], now?: string): Promise<CaptureArtifact[]> {
    const artifact = this.requireArtifact();
    try {
      const created = await this.client.call<CaptureArtifact[]>("capture.split", {
        path: artifact.path, expected_hash: artifact.content_hash, groups, now,
      });
      this.state = { ...this.state, captures: created, artifact: created[0], mode: "review", stage: "ready", focusTarget: "rich-capture-split-result", statusAnnouncement: `${created.length} captures created; source archived.` };
      return created;
    } catch (error) { return this.fail(error); }
  }

  async previewProposal(input: CaptureProposalInput): Promise<CaptureProposalPreview> {
    const artifact = this.requireArtifact();
    try {
      const preview = await this.client.call<CaptureProposalPreview>("capture.proposal.preview", this.proposalParams(artifact, input));
      this.state = { ...this.state, proposalPreview: preview, focusTarget: "rich-capture-proposal-preview", statusAnnouncement: "Proposal preview ready. Nothing has been applied." };
      return preview;
    } catch (error) { return this.fail(error); }
  }

  async createProposal(input: CaptureProposalInput): Promise<CaptureProposalResult> {
    const artifact = this.requireArtifact();
    try {
      const result = await this.client.call<CaptureProposalResult>("capture.proposal.create", this.proposalParams(artifact, input));
      this.state = { ...this.state, stage: "proposal-created", proposalPreview: result.preview, detail: `Proposal ${result.proposal_id} created.`, focusTarget: "rich-capture-proposal-created", statusAnnouncement: "Proposal created. External canonical data remains unchanged." };
      return result;
    } catch (error) { return this.fail(error); }
  }

  select(paths: string[]): void {
    this.state = { ...this.state, selectedPaths: [...new Set(paths)], statusAnnouncement: `${new Set(paths).size} captures selected.` };
  }

  selectedEvidence(): { capturePaths: string[]; evidenceOnly: true } {
    return { capturePaths: [...this.state.selectedPaths], evidenceOnly: true };
  }

  openArtifact(): void { this.openPath(this.requireArtifact().path); }
  openOriginal(attachmentId: string): void {
    const attachment = this.requireArtifact().metadata.attachments.find((item) => item.attachment_id === attachmentId);
    if (attachment) this.openPath(attachment.canonical_path);
  }

  keyboardActions(): RichCaptureAction[] {
    return [
      { id: "save", label: "Save", shortcut: "S", ariaLabel: "Save the original quick capture immediately" },
      { id: "attach", label: "Attach", shortcut: "A", ariaLabel: "Add files while preserving original bytes" },
      { id: "review", label: "Review", shortcut: "R", ariaLabel: "Review derived information and confirmation states" },
      { id: "process", label: "Process", shortcut: "P", ariaLabel: "Start optional cancelable attachment processing" },
      { id: "link", label: "Link", shortcut: "L", ariaLabel: "Link the capture to another LifeOS artifact" },
      { id: "proposal", label: "Proposal", shortcut: "F", ariaLabel: "Preview a follow-up proposal without applying it" },
      { id: "markdown", label: "Markdown", shortcut: "M", ariaLabel: "Open the canonical rich capture Markdown" },
      { id: "original", label: "Original", shortcut: "O", ariaLabel: "Open the selected original attachment file" },
    ];
  }

  private loading(announcement: string, origin = this.state.origin): void {
    this.state = { ...this.state, stage: "saving", origin, detail: undefined, recovery: undefined, focusTarget: "rich-capture-status", statusAnnouncement: announcement };
  }

  private accept(artifact: CaptureArtifact, announcement: string): CaptureArtifact {
    const stage: RichCaptureStage = artifact.metadata.state === "needs-review" ? "needs-review" : artifact.metadata.state === "archived" ? "archived" : "ready";
    this.state = {
      ...this.state,
      stage,
      mode: "review",
      artifact,
      detail: undefined,
      recovery: undefined,
      focusTarget: "rich-capture-artifact",
      statusAnnouncement: announcement,
    };
    return artifact;
  }

  private requireArtifact(): CaptureArtifact {
    if (!this.state.artifact) throw new Error("A rich capture artifact is not loaded.");
    return this.state.artifact;
  }

  private requireJob(): ProcessingJob {
    if (!this.state.processingJob) throw new Error("A processing job is not available.");
    return this.state.processingJob;
  }

  private async mutate(method: string, fields: Record<string, unknown>, announcement: string): Promise<CaptureArtifact> {
    const artifact = this.requireArtifact();
    this.loading(announcement);
    try {
      return this.accept(await this.client.call<CaptureArtifact>(method, {
        path: artifact.path,
        expected_hash: artifact.content_hash,
        ...fields,
      }), announcement);
    } catch (error) { return this.fail(error); }
  }

  private proposalParams(artifact: CaptureArtifact, input: CaptureProposalInput): Record<string, unknown> {
    return {
      capture_path: artifact.path,
      action: input.action,
      target_path: input.targetPath,
      content: input.content,
      create_target: input.createTarget ?? false,
      attachment_ids: input.attachmentIds ?? [],
      included_actions: input.includedActions ?? [],
      excluded_actions: input.excludedActions ?? [],
      now: input.now,
    };
  }

  private fail(error: unknown): never {
    this.state = errorState(this.state, error);
    throw error;
  }
}
