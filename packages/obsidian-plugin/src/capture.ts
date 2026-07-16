import { BridgeClient } from "./protocol.js";

export type CaptureKind = "thought" | "task" | "project" | "journal" | "flashcard" | "metric";
export interface CaptureDraft {
  idempotency_key: string;
  kind: CaptureKind;
  title: string;
  content?: string;
  target_path?: string;
  plan_path?: string;
  task?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  expected_hash?: string;
}
export interface MutationReference { path: string; content_hash: string; note_id?: string; block?: string; }
export interface MutationResult { operation: string; reference: MutationReference; created: boolean; data: Record<string, unknown>; }

export class CaptureController {
  constructor(private readonly client: BridgeClient, private readonly openPath: (path: string) => void) {}
  validate(draft: CaptureDraft): string[] {
    const errors: string[] = [];
    if (!draft.title.trim()) errors.push("Title is required.");
    if (draft.kind === "task" && (!draft.plan_path || !draft.task)) errors.push("Choose a plan and task details.");
    if (draft.kind === "flashcard" && (!draft.metadata?.answer || !draft.metadata?.question)) errors.push("Question and answer are required.");
    if (draft.kind === "metric" && (!draft.metadata?.metric || draft.metadata.value === undefined)) errors.push("Metric and value are required.");
    return errors;
  }
  async submit(draft: CaptureDraft): Promise<MutationResult> {
    const errors = this.validate(draft);
    if (errors.length) throw new Error(errors.join(" "));
    const result = await this.client.call<MutationResult>("daily.capture", draft as unknown as Record<string, unknown>);
    this.openPath(result.reference.path);
    return result;
  }
}

export interface CheckInDraft {
  idempotency_key: string;
  day: string;
  period: "morning" | "evening";
  metrics: Record<string, string | number>;
  activities?: string[];
  note?: string;
  expected_hash?: string;
}
export class CheckInController {
  constructor(private readonly client: BridgeClient) {}
  submit(draft: CheckInDraft): Promise<MutationResult> {
    return this.client.call<MutationResult>("daily.checkin", draft as unknown as Record<string, unknown>);
  }
}
