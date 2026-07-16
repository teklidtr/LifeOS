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
  duplicate_detected: boolean;
  reused_existing: boolean;
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
