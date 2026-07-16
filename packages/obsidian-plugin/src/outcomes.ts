import { BridgeClient } from "./protocol.js";
import { MutationResult } from "./capture.js";
export type TaskOutcome = "started" | "done" | "partial" | "skipped" | "deferred" | "cancelled";
export interface OutcomeDraft {
  idempotency_key: string; plan_path: string; task_id: string; outcome: TaskOutcome;
  day: string; expected_hash: string; planned_minutes?: number; actual_minutes?: number;
  energy_before?: "low"|"medium"|"high"; energy_after?: "low"|"medium"|"high";
  motivation_before?: "low"|"medium"|"high"; difficulty?: number; satisfaction?: number;
  reason?: string; note?: string; deferred_until?: string; started_at?: string; ended_at?: string; source_ref?: string;
}
export class OutcomeController {
  constructor(private readonly client: BridgeClient) {}
  validate(draft: OutcomeDraft): string[] {
    const errors: string[] = [];
    if (!draft.task_id) errors.push("Task is required.");
    for (const [name, value] of [["actual_minutes", draft.actual_minutes], ["planned_minutes", draft.planned_minutes]] as const) {
      if (value !== undefined && (!Number.isInteger(value) || value < 0 || value > 1440)) errors.push(`${name} is invalid.`);
    }
    if (draft.outcome === "deferred" && draft.deferred_until !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(draft.deferred_until)) errors.push("Deferred date is invalid.");
    return errors;
  }
  submit(draft: OutcomeDraft): Promise<MutationResult> {
    const errors = this.validate(draft); if (errors.length) throw new Error(errors.join(" "));
    return this.client.call<MutationResult>("daily.task_outcome", draft as unknown as Record<string, unknown>);
  }
}
