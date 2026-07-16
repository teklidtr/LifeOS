export type ExperimentState =
  | "idea" | "drafting" | "baseline" | "scheduled" | "active" | "paused"
  | "completed" | "abandoned" | "analyzed" | "archived";

export type ObservationState = "measured" | "not-measured" | "not-applicable" | "skipped" | "unavailable";
export type SafetyLevel = "ordinary" | "caution" | "informational-only" | "blocked" | "emergency";

export interface SourceReference {
  path: string;
  relation: string;
  content_hash?: string;
}

export interface ExperimentMeasure {
  measure_id: string;
  display_name: string;
  kind: "count" | "duration" | "rating" | "percentage" | "continuous" | "completion" | "qualitative";
  role: "primary" | "secondary" | "adherence" | "contextual";
  cadence: string;
  unit?: string;
  source: string;
  direction: "increase" | "decrease" | "neutral" | "unknown";
  valid_min?: number;
  valid_max?: number;
  missing_behavior: "exclude" | "report" | "carry-none";
  aggregation: "mean" | "median" | "sum" | "rate" | "latest" | "none";
}

export interface ExperimentPhase {
  phase_id: string;
  name: string;
  kind: "baseline" | "intervention" | "washout" | "follow-up";
  start_date: string;
  end_date: string;
  intervention: string;
}

export interface ExperimentProtocol {
  question: string;
  hypothesis: string;
  rationale: string;
  intervention: string;
  constants: string[];
  comparison: string;
  baseline_requirements: string;
  outcome_measures: ExperimentMeasure[];
  phases: ExperimentPhase[];
  adherence_expectation: string;
  confounders: string[];
  risks: string[];
  stop_rules: string[];
  success_criteria: string[];
  failure_criteria: string[];
  inconclusive_criteria: string[];
  schedule: Record<string, unknown>;
}

export interface SafetyClassification {
  level: SafetyLevel;
  codes: string[];
  explanation: string;
  professional_guidance_recommended: boolean;
  allows_activation: boolean;
}

export interface ExperimentObservation {
  observation_id: string;
  measure_id: string;
  observed_at: string;
  phase_id: string;
  state: ObservationState;
  value?: number | boolean | string;
  note: string;
  source_refs: SourceReference[];
  context: string[];
}

export interface ProtocolAmendment {
  amendment_id: string;
  created_at: string;
  reason: string;
  changes: string[];
  prior_protocol_hash: string;
}

export interface AnalysisRecord {
  analysis_id: string;
  created_at: string;
  status: "ready" | "insufficient-evidence" | "confounded" | "stopped-for-safety";
  summaries: Array<Record<string, unknown>>;
  observation_ids: string[];
  assumptions: string[];
  missing_data_treatment: string;
  limitations: string[];
  evidence_kind: "descriptive" | "inferential";
}

export interface ExperimentMetadata {
  type: "personal-experiment";
  experiment_schema: number;
  experiment_id: string;
  title: string;
  description: string;
  state: ExperimentState;
  category: string;
  created_at: string;
  updated_at: string;
  protocol: ExperimentProtocol;
  safety: SafetyClassification;
  origins: SourceReference[];
  linked_habits: string[];
  linked_metrics: string[];
  linked_tasks: string[];
  linked_diary: string[];
  linked_checkins: string[];
  linked_reviews: string[];
  source_refs: SourceReference[];
  observations: ExperimentObservation[];
  amendments: ProtocolAmendment[];
  lifecycle: Array<Record<string, unknown>>;
  analyses: AnalysisRecord[];
  conclusion?: string;
  conclusion_notes: string;
  follow_up_decisions: string[];
  parent_experiment_id?: string;
  repeated_from_experiment_id?: string;
}

export interface ExperimentArtifact {
  path: string;
  content_hash: string;
  metadata: ExperimentMetadata;
  human_body: string;
}

export interface ExperimentDesignWarning {
  code: string;
  severity: "recommendation" | "warning" | "blocking";
  title: string;
  explanation: string;
  recommendation: string;
  acknowledgeable: boolean;
  evidence: string[];
}

export interface ExperimentDueWindow {
  measure_id: string;
  phase_id: string;
  opens_at: string;
  due_at: string;
  closes_at: string;
  status: "upcoming" | "open" | "overdue" | "paused";
}

export interface ExperimentIndexEntry {
  experiment_id: string;
  path: string;
  content_hash: string;
  title: string;
  state: ExperimentState;
  category: string;
  updated_at: string;
  conclusion?: string;
  parent_experiment_id?: string;
  repeated_from_experiment_id?: string;
  measure_ids: string[];
}

export interface ExperimentIndexReport {
  state: "ready" | "missing-index" | "corrupt-index" | "interrupted" | string;
  entries: ExperimentIndexEntry[];
  diagnostics: Array<Record<string, unknown>>;
  checkpoint_path?: string;
}

export interface ExperimentComparison {
  left: ExperimentIndexEntry;
  right: ExperimentIndexEntry;
  compatible: boolean;
  warning?: string;
}

export interface ExperimentProposalPreview {
  proposal_id: string;
  action: string;
  target_path: string;
  operation: string;
  base_hash?: string;
  unified_diff?: string;
  new_content?: string;
  source_experiment_id: string;
  source_experiment_hash: string;
  analysis_id?: string;
  analysis_limitations: string[];
  included_actions: string[];
  excluded_actions: string[];
}

export interface ExperimentProposalResult {
  proposal_id: string;
  proposal_path: string;
  preview: ExperimentProposalPreview;
}

export interface ExperimentMigrationCandidate {
  source: { path: string; content_hash: string; title: string; source_type: string };
  target_path?: string;
  experiment_id?: string;
  state: "ready" | "already-migrated" | "conflict" | "malformed";
  diagnostics: string[];
  planned_frontmatter?: Record<string, unknown>;
}

export interface ExperimentMigrationPreview {
  candidates: ExperimentMigrationCandidate[];
}

export interface ExperimentMigrationResult {
  state: string;
  migrated: string[];
  already_migrated: string[];
  conflicts: ExperimentMigrationCandidate[];
  preserved_sources: string[];
  audit_path: string;
}

export interface ExperimentContextPreview {
  experiment_path: string;
  local_analysis_only: boolean;
  provider_payload_paths: string[];
  items: Array<{
    path: string; content_hash: string; inclusion_reason: string; excerpt: string;
    byte_count: number; included_bytes: number; truncated: boolean;
    redactions: Array<{ label: string; occurrences: number }>;
  }>;
  omissions: Array<{ path: string; reason: string; detail: string }>;
  total_bytes: number;
  truncated: boolean;
  disclosure: string;
}

export interface ExperimentRecoveryReport {
  state: string;
  index: ExperimentIndexReport;
  diagnostics: Array<Record<string, unknown>>;
}
