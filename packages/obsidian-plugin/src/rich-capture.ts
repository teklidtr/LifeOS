export type CaptureType = "meal" | "exercise" | "attachment" | "mixed";
export type CaptureState =
  | "captured" | "processing" | "needs-review" | "enriched"
  | "linked" | "completed" | "failed" | "archived";
export type PrivacyScope = "standard" | "private" | "protected";
export type ProcessingState =
  | "not-requested" | "queued" | "processing" | "completed"
  | "needs-review" | "failed" | "cancelled" | "unavailable" | "stale";
export type DerivedStatus = "suggested" | "confirmed" | "corrected" | "rejected";

export interface ArtifactLink {
  path: string;
  relation: string;
  artifact_type: string;
  content_hash?: string;
}

export interface AttachmentReference {
  attachment_id: string;
  manifest_path: string;
  content_hash: string;
  media_type: string;
  byte_size: number;
  original_filename: string;
  canonical_path: string;
  relationship: string;
}

export interface DerivedValue {
  field_name: string;
  value?: unknown;
  unit?: string;
  source: string;
  confidence: "high" | "medium" | "low" | "unknown";
  range_low?: number;
  range_high?: number;
  assumptions: string[];
  evidence_refs: string[];
  status: DerivedStatus;
}

export interface CaptureMetadata {
  id: string;
  type: "rich-capture";
  schema_version: number;
  title: string;
  description: string;
  capture_type: CaptureType;
  state: CaptureState;
  captured_at: string;
  event_at: string;
  timezone: string;
  source_entry_point: string;
  privacy_scope: PrivacyScope;
  sensitive: boolean;
  location?: string;
  tags: string[];
  attachments: AttachmentReference[];
  links: ArtifactLink[];
  derived_values: DerivedValue[];
  domain_data: Record<string, unknown>;
  extraction_status: ProcessingState;
  enrichment_status: ProcessingState;
  exclude_from_semantic: boolean;
  exclude_from_conversations: boolean;
  exclude_from_reviews: boolean;
  exclude_from_experiments: boolean;
  provenance: Array<Record<string, unknown>>;
  lifecycle: Array<Record<string, unknown>>;
  merged_from: string[];
  split_from?: string;
  created_at: string;
  updated_at: string;
}

export interface CaptureArtifact {
  path: string;
  content_hash: string;
  metadata: CaptureMetadata;
  human_body: string;
}

export interface AttachmentImportResult {
  reference: AttachmentReference;
  manifest_path: string;
  duplicate: boolean;
  reused_original: boolean;
}

export interface AttachmentAudit {
  attachment_id: string;
  status: "ok" | "missing" | "changed" | string;
  canonical_path: string;
  expected_hash: string;
  actual_hash?: string;
  details: string;
}

export interface ProcessingJob {
  job_id: string;
  capture_path: string;
  attachment_ids: string[];
  state: string;
  completed_attachment_ids: string[];
  failed_attachment_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface CaptureMergePreview {
  source_paths: string[];
  source_hashes: string[];
  title: string;
  capture_type: CaptureType;
  attachment_ids: string[];
  link_paths: string[];
  warnings: string[];
}

export interface CaptureProposalPreview {
  proposal_id: string;
  target_path: string;
  operation: string;
  base_hash?: string;
  source_capture_id: string;
  source_capture_hash: string;
  attachment_ids: string[];
  included_actions: string[];
  excluded_actions: string[];
}

export interface CaptureProposalResult {
  proposal_id: string;
  proposal_path: string;
  preview: CaptureProposalPreview;
}

export interface CaptureContextPreview {
  capture_path: string;
  requested_operations: string[];
  external_processing_intent: boolean;
  local_analysis_only: boolean;
  provider_payload_paths: string[];
  items: Array<{
    path: string;
    kind: string;
    content_hash: string;
    inclusion_reason: string;
    transfer: string;
    byte_count: number;
    included_bytes: number;
    truncated: boolean;
    excerpt: string;
    attachment_id?: string;
    media_type?: string;
    redactions: Array<{ label: string; occurrences: number }>;
  }>;
  omissions: Array<{ path: string; reason: string; detail: string }>;
  total_bytes: number;
  truncated: boolean;
  disclosure: string;
}

export interface CaptureMigrationPreview {
  candidates: Array<Record<string, unknown>>;
  legacy_formats_found: string[];
  finding: string;
}

export interface CaptureMigrationResult {
  state: string;
  migrated: string[];
  already_migrated: string[];
  conflicts: Array<Record<string, unknown>>;
  preserved_sources: string[];
  audit_path: string;
  finding: string;
}

export interface CaptureRecoveryReport {
  state: string;
  index: {
    state: string;
    entries: Array<Record<string, unknown>>;
    diagnostics: Array<Record<string, unknown>>;
    checkpoint_path?: string;
  };
  diagnostics: Array<Record<string, unknown>>;
  rebuilt_manifests: string[];
}

export interface CaptureVisualization {
  timeline: Array<{
    capture_id: string; path: string; event_at: string; title: string; capture_type: string;
    state: string; attachment_count: number; confirmed_value_count: number; suggested_value_count: number;
  }>;
  counts_by_type: Record<string, number>;
  counts_by_state: Record<string, number>;
  activity_calendar: Record<string, number>;
  processing_status: Record<string, number>;
  exercise_trends: Array<{
    capture_id: string; path: string; event_at: string; outcome: string;
    duration_minutes?: number; distance?: number; distance_unit?: string; missing_fields: string[];
  }>;
  experiment_linked: Array<Record<string, unknown>>;
  missing_data: Record<string, number>;
  warnings: string[];
}
