export type PersonalModelStatus = "seed" | "active" | "needs-review" | "archived";
export type PersonalModelConfidence = "low" | "medium" | "high";
export type PersonalModelEvidenceRole = "supporting" | "contesting" | "contextual";
export type PersonalModelView = "active" | "needs_review" | "seeds" | "archived";
export type PersonalModelAction = "track" | "adopt" | "revise" | "contest" | "archive";

export interface PersonalModelEvidence {
  path: string;
  content_hash: string;
  role: PersonalModelEvidenceRole;
  source_id?: string;
  observation_id?: string;
  event_id?: string;
}

export interface PersonalModelEvidenceDiagnostic {
  reference: PersonalModelEvidence;
  state: string;
  current_path?: string | null;
  current_content_hash?: string | null;
  candidate_paths?: string[];
}

export interface PersonalModelReviewReason {
  code: string;
  summary: string;
  evidence_paths: string[];
}

export interface PersonalModelEvidenceChange {
  role: PersonalModelEvidenceRole;
  reviewed_path: string;
  reviewed_content_hash: string;
  state: string;
  current_path?: string | null;
  current_content_hash?: string | null;
}

export interface PersonalModelRelatedPath {
  path: string;
  kind: "review" | "experiment";
}

export interface PersonalModelItem {
  pattern_id: string;
  pattern_path: string;
  pattern_content_hash: string;
  title: string;
  description: string;
  statement: string;
  status: PersonalModelStatus;
  confidence: PersonalModelConfidence;
  review_reasons: string[];
  origin: { kind: string; source_ref?: string };
  last_reviewed_at?: string | null;
  review_due_at?: string | null;
  review_due: boolean;
  evidence_fingerprint: string;
  evidence: PersonalModelEvidence[];
  evidence_health: "none" | "healthy" | "attention" | "unavailable";
  evidence_diagnostics: PersonalModelEvidenceDiagnostic[];
  freshness_days?: number | null;
  review_recommendation: string;
  review_trigger_reasons: PersonalModelReviewReason[];
  evidence_changes: PersonalModelEvidenceChange[];
  related_paths: PersonalModelRelatedPath[];
}

export interface PersonalModelDocument {
  schema_version: number;
  source_hash: string;
  runtime_state: "ready";
  groups: Record<PersonalModelView, PersonalModelItem[]>;
  diagnostics: Array<{
    code: string;
    severity: string;
    source_path: string;
    line: number;
    message: string;
  }>;
}

export interface PersonalModelProposalPreview {
  proposal_id: string;
  action: string;
  pattern_id: string;
  target_path: string;
  operation: "create_file" | "patch_human_file";
  from_status?: string | null;
  to_status: string;
  base_hash?: string | null;
  evidence_fingerprint: string;
  transition_reason: string;
  candidate_content: string;
}

export interface PersonalModelProposalResult {
  proposal_id: string;
  proposal_path: string;
  preview: PersonalModelProposalPreview;
}

export interface PersonalModelProposalInput {
  action: PersonalModelAction;
  transitionReason: string;
  targetPath?: string;
  expectedTargetHash?: string;
  patternId?: string;
  title?: string;
  description?: string;
  statement?: string;
  confidence?: PersonalModelConfidence;
  evidence?: PersonalModelEvidence[];
  reviewReasons?: string[];
}

export const PERSONAL_MODEL_VIEWS: readonly PersonalModelView[] = [
  "active",
  "needs_review",
  "seeds",
  "archived",
] as const;

export const PERSONAL_MODEL_VIEW_LABELS: Record<PersonalModelView, string> = {
  active: "Active",
  needs_review: "Needs review",
  seeds: "Seeds",
  archived: "Archived",
};

export function actionsForPersonalModelItem(item: PersonalModelItem): PersonalModelAction[] {
  if (item.status === "archived") return [];
  if (item.status === "needs-review") return ["adopt", "revise", "archive"];
  if (item.status === "seed") return ["adopt", "revise", "contest", "archive"];
  return ["revise", "contest", "archive"];
}

export function nextPersonalModelView(
  current: PersonalModelView,
  key: "ArrowLeft" | "ArrowRight" | "Home" | "End",
): PersonalModelView {
  const index = PERSONAL_MODEL_VIEWS.indexOf(current);
  if (key === "Home") return PERSONAL_MODEL_VIEWS[0]!;
  if (key === "End") return PERSONAL_MODEL_VIEWS.at(-1)!;
  const offset = key === "ArrowRight" ? 1 : -1;
  return PERSONAL_MODEL_VIEWS[(index + offset + PERSONAL_MODEL_VIEWS.length) % PERSONAL_MODEL_VIEWS.length]!;
}
