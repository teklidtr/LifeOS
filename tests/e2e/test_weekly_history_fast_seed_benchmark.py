from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from lifeos.bridge import BridgeApplication


def _seed_weekly_review(root: Path, day: date) -> None:
    iso = day.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    timestamp = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    path = root / "reviews" / "weekly" / f"{label}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''---
type: review
review_schema: 1
review_id: weekly-{label}
review_kind: weekly
period_start: {day.isoformat()}
period_end: {(day + timedelta(days=6)).isoformat()}
timezone: UTC
status: open
created_at: "{timestamp}"
updated_at: "{timestamp}"
phases:
  - phase_id: weekly
    state: pending
    completed_sections: []
    skipped_sections: []
current_phase: weekly
item_decisions: []
answers: []
proposal_refs: []
migrated_from: []
snapshot_history: []
lifecycle_events: []
---

# Weekly review: {label}

<!-- lifeos:managed:start facts -->
## Review facts

Seeded history fixture.
<!-- lifeos:managed:end facts -->

<!-- lifeos:managed:start items -->
## Review items

No review items.
<!-- lifeos:managed:end items -->

<!-- lifeos:managed:start continuity -->
## Continuity

No previous review is linked.
<!-- lifeos:managed:end continuity -->

## Weekly reflection

<!-- lifeos:managed:start completion-summary -->
## Completion summary

Review is open.
<!-- lifeos:managed:end completion-summary -->
''',
        encoding="utf-8",
    )


def test_weekly_history_fast_seed_benchmark(tmp_path: Path) -> None:
    start = date(2024, 1, 1)
    for offset in range(120):
        _seed_weekly_review(tmp_path, start + timedelta(weeks=offset))

    app = BridgeApplication(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        actor_id="tester",
    )
    began = time.perf_counter()
    history = app.dispatch("review.artifact.history", {"kind": "weekly", "limit": 50})
    elapsed = time.perf_counter() - began

    assert len(history) == 50
    assert history[0]["period_start"] > history[-1]["period_start"]
    assert elapsed < 3.0
