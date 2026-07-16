import { BridgeClient } from "./protocol.js";

export type AdaptiveMode = "off" | "shadow" | "active";
export interface AdaptivePreferences {
  schema_version: number;
  mode: AdaptiveMode;
  disabled_dimensions: string[];
  excluded_event_ids: string[];
  dismissed_diagnoses: Array<[string, string]>;
  reset_before?: string;
  reset_reason?: string;
  content_hash?: string;
}

export interface PreferencesMigrationResult {
  state: "missing" | "current" | "migratable" | "migrated";
  from_version?: number;
  to_version: number;
  changed: boolean;
  dry_run: boolean;
  mode: AdaptiveMode;
}
export interface ReplayContext {
  day: string;
  available_minutes?: number;
  energy?: "low" | "medium" | "high";
  motivation?: "low" | "medium" | "high";
  mode_filter?: string;
  time_window?: string;
}
export interface HistoricalReplayModel {
  schema_version: number;
  adaptive_policy_version: number;
  mode: AdaptiveMode;
  days: unknown[];
  source_fingerprint: string;
  caveat: string;
}

export interface AdaptivePlanModel {
  mode: AdaptiveMode;
  baseline: Record<string, unknown>;
  adaptive: Record<string, unknown>;
  returned: Record<string, unknown>;
  adjustments: unknown[];
  deltas: unknown[];
  feedback_status: string;
}

export class FeedbackController {
  constructor(private readonly client: BridgeClient) {}
  preferences(): Promise<AdaptivePreferences> {
    return this.client.call("feedback.preferences.get", {});
  }
  migratePreferences(dryRun = true): Promise<PreferencesMigrationResult> {
    return this.client.call("feedback.preferences.migrate", { dry_run: dryRun });
  }
  replay(contexts: ReplayContext[], mode?: AdaptiveMode): Promise<HistoricalReplayModel> {
    return this.client.call("feedback.replay", { contexts, ...(mode ? { mode } : {}) });
  }
  setMode(current: AdaptivePreferences, mode: AdaptiveMode, key: string): Promise<AdaptivePreferences> {
    return this.client.call("feedback.preferences.update", { idempotency_key: key, expected_hash: current.content_hash, mode });
  }
  disableDimensions(current: AdaptivePreferences, dimensions: string[], key: string): Promise<AdaptivePreferences> {
    return this.client.call("feedback.preferences.update", { idempotency_key: key, expected_hash: current.content_hash, disabled_dimensions: dimensions });
  }
  excludeEvent(current: AdaptivePreferences, eventId: string, key: string): Promise<AdaptivePreferences> {
    return this.client.call("feedback.preferences.update", { idempotency_key: key, expected_hash: current.content_hash, exclude_event_id: eventId });
  }
  dismissDiagnosis(current: AdaptivePreferences, diagnosisId: string, fingerprint: string, key: string): Promise<AdaptivePreferences> {
    return this.client.call("feedback.preferences.update", { idempotency_key: key, expected_hash: current.content_hash, dismiss_diagnosis_id: diagnosisId, dismiss_fingerprint: fingerprint });
  }
  reset(current: AdaptivePreferences, before: string, reason: string, key: string): Promise<AdaptivePreferences> {
    return this.client.call("feedback.preferences.update", { idempotency_key: key, expected_hash: current.content_hash, reset_before: before, reset_reason: reason });
  }
  baseline(plan: AdaptivePlanModel): Record<string, unknown> { return plan.baseline; }
  adaptive(plan: AdaptivePlanModel): Record<string, unknown> { return plan.adaptive; }
  ariaModeLabel(mode: AdaptiveMode): string { return `Adaptive planning mode: ${mode}`; }
  criticalActions(): Array<{ id: string; label: string; shortcut: string }> {
    return [
      { id: "why-this", label: "Explain why this task was selected", shortcut: "Enter" },
      { id: "show-baseline", label: "Show baseline plan", shortcut: "B" },
      { id: "correct-outcome", label: "Correct recorded outcome", shortcut: "C" },
      { id: "exclude-evidence", label: "Exclude evidence from adaptation", shortcut: "E" },
      { id: "reset-feedback", label: "Reset adaptive evidence boundary", shortcut: "R" },
    ];
  }
}
