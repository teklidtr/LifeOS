export const REVIEW_SCHEMA_VERSION = 1 as const;
export type ReviewKind = "daily" | "weekly";
export type ReviewStatus = "open" | "completed" | "skipped" | "superseded";
export type ReviewPhaseId = "morning" | "evening" | "weekly";
export type ReviewProgressState = "pending" | "completed" | "skipped";
export type ReviewSectionState = "ready" | "empty" | "unavailable";
export type ReviewDecisionKind = "acknowledge" | "carry" | "defer_review" | "clarify" | "dismiss_for_review" | "open_source" | "propose_change";

export interface ReviewSourceReference { path: string; content_hash?: string; detail?: string; observed_at?: string; }
export interface ReviewItemSnapshot { item_id: string; section_id: string; title: string; detail: string; evidence_fingerprint: string; state: ReviewSectionState; action?: string; sources: ReviewSourceReference[]; diagnostic?: string; }
export interface ReviewSectionSnapshot { section_id: string; title: string; optional: boolean; state: ReviewSectionState; items: ReviewItemSnapshot[]; diagnostic?: string; }
export interface ReviewSnapshot { snapshot_id: string; generated_at: string; content_hash: string; sections: ReviewSectionSnapshot[]; diagnostics: string[]; }
export interface ReviewLifecycleEvent { event_id: string; transition: string; at: string; actor_id: string; note?: string; }
export interface ReviewSnapshotRecord { snapshot_id: string; content_hash: string; generated_at: string; }
export interface ReviewPhaseProgress { phase_id: ReviewPhaseId; state: ReviewProgressState; completed_sections: string[]; skipped_sections: string[]; current_section?: string; completed_at?: string; }
export interface ReviewItemDecision { item_id: string; evidence_fingerprint: string; decision: ReviewDecisionKind; decided_at: string; note?: string; proposal_id?: string; }
export interface ReviewAnswer { prompt_id: string; value: string; answered_at: string; phase_id?: ReviewPhaseId; }
export interface ReviewArtifactMetadata { review_id: string; schema_version: number; review_kind: ReviewKind; period_start: string; period_end: string; timezone: string; status: ReviewStatus; created_at: string; updated_at: string; phases: ReviewPhaseProgress[]; current_phase?: ReviewPhaseId; item_decisions: ReviewItemDecision[]; answers: ReviewAnswer[]; proposal_refs: string[]; previous_review_id?: string; next_review_id?: string; migrated_from: string[]; snapshot_id?: string; snapshot_hash?: string; snapshot_history: ReviewSnapshotRecord[]; lifecycle_events: ReviewLifecycleEvent[]; }
export interface ReviewArtifact { path: string; content_hash: string; metadata: ReviewArtifactMetadata; body: string; snapshot?: ReviewSnapshot; }

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DAILY_ID = /^daily-\d{4}-\d{2}-\d{2}$/;
const WEEKLY_ID = /^weekly-\d{4}-W\d{2}$/;

function isoWeek(day: string): { year: number; week: number; monday: string; sunday: string } {
  if (!DATE.test(day)) throw new Error("day must be an ISO date");
  const source = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(source.getTime())) throw new Error("day must be an ISO date");
  const weekday = source.getUTCDay() || 7;
  const mondayDate = new Date(source);
  mondayDate.setUTCDate(source.getUTCDate() - weekday + 1);
  const thursday = new Date(mondayDate);
  thursday.setUTCDate(mondayDate.getUTCDate() + 3);
  const yearStart = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((thursday.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  const sundayDate = new Date(mondayDate);
  sundayDate.setUTCDate(mondayDate.getUTCDate() + 6);
  return { year: thursday.getUTCFullYear(), week, monday: mondayDate.toISOString().slice(0, 10), sunday: sundayDate.toISOString().slice(0, 10) };
}

export function reviewIdentity(kind: ReviewKind, day: string): { reviewId: string; periodStart: string; periodEnd: string } {
  if (!DATE.test(day)) throw new Error("day must be an ISO date");
  if (kind === "daily") return { reviewId: `daily-${day}`, periodStart: day, periodEnd: day };
  const iso = isoWeek(day);
  return { reviewId: `weekly-${iso.year}-W${String(iso.week).padStart(2, "0")}`, periodStart: iso.monday, periodEnd: iso.sunday };
}

export function reviewPath(kind: ReviewKind, day: string): string {
  const identity = reviewIdentity(kind, day);
  return `reviews/${kind}/${identity.reviewId.slice(kind.length + 1)}.md`;
}

export function phaseIdsForKind(kind: ReviewKind): ReviewPhaseId[] { return kind === "daily" ? ["morning", "evening"] : ["weekly"]; }

export function assertReviewArtifactMetadata(metadata: ReviewArtifactMetadata, path?: string): void {
  if (metadata.schema_version !== REVIEW_SCHEMA_VERSION) throw new Error(`Unsupported review schema: ${metadata.schema_version}`);
  const identity = reviewIdentity(metadata.review_kind, metadata.period_start);
  const idPattern = metadata.review_kind === "daily" ? DAILY_ID : WEEKLY_ID;
  if (!idPattern.test(metadata.review_id) || metadata.review_id !== identity.reviewId || metadata.period_end !== identity.periodEnd) throw new Error("Review identity or period is inconsistent");
  if (path && path !== reviewPath(metadata.review_kind, metadata.period_start)) throw new Error("Review path is inconsistent");
  const expectedPhases = phaseIdsForKind(metadata.review_kind);
  if (metadata.phases.map((phase) => phase.phase_id).join("|") !== expectedPhases.join("|")) throw new Error("Review phases are inconsistent");
  if (metadata.current_phase && !expectedPhases.includes(metadata.current_phase)) throw new Error("Current phase is invalid");
  const decisions = new Set<string>();
  for (const item of metadata.item_decisions) {
    const key = `${item.item_id}\0${item.evidence_fingerprint}`;
    if (decisions.has(key)) throw new Error("Duplicate review decision");
    decisions.add(key);
  }
}
