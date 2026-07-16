import assert from "node:assert/strict";
import test from "node:test";
import { assertReviewArtifactMetadata, phaseIdsForKind, reviewIdentity, reviewPath, ReviewArtifactMetadata } from "../src/review-artifact.js";

const base = (): ReviewArtifactMetadata => ({
  review_id: "daily-2026-07-16", schema_version: 1, review_kind: "daily", period_start: "2026-07-16", period_end: "2026-07-16", timezone: "Europe/Istanbul", status: "open", created_at: "2026-07-16T09:00:00+03:00", updated_at: "2026-07-16T09:00:00+03:00", phases: [
    { phase_id: "morning", state: "pending", completed_sections: [], skipped_sections: [] },
    { phase_id: "evening", state: "pending", completed_sections: [], skipped_sections: [] },
  ], item_decisions: [], answers: [], proposal_refs: [], migrated_from: [], snapshot_history: [], lifecycle_events: [],
});

test("review artifact identity and paths match Python rules", () => {
  assert.deepEqual(reviewIdentity("weekly", "2026-01-01"), { reviewId: "weekly-2026-W01", periodStart: "2025-12-29", periodEnd: "2026-01-04" });
  assert.equal(reviewPath("daily", "2026-07-16"), "reviews/daily/2026-07-16.md");
  assert.deepEqual(phaseIdsForKind("daily"), ["morning", "evening"]);
});

test("review artifact metadata rejects path and phase mismatches", () => {
  assertReviewArtifactMetadata(base(), "reviews/daily/2026-07-16.md");
  let pathError = "";
  try { assertReviewArtifactMetadata(base(), "reviews/daily/2026-07-15.md"); } catch (error) { pathError = String(error); }
  assert.equal(pathError.includes("path"), true);
  const wrong = base(); wrong.phases = [wrong.phases[0]!];
  let phaseError = "";
  try { assertReviewArtifactMetadata(wrong); } catch (error) { phaseError = String(error); }
  assert.equal(phaseError.includes("phases"), true);
});
