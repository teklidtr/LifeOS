#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
python3 scripts/validate_manual_links.py
PYTHONPATH=src python3 -m pytest --import-mode=importlib \
  tests/reviews \
  tests/bridge/test_review_artifact_bridge.py \
  tests/e2e/test_first_class_reviews.py -q
PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from lifeos.bridge.protocol import CAPABILITIES
from lifeos.reviews import REVIEW_SCHEMA_VERSION

required = {
    "review.artifact.open",
    "review.artifact.load",
    "review.artifact.refresh",
    "review.artifact.history",
    "review.artifact.migration.preview",
    "review.artifact.migration.apply",
    "review.artifact.rebuild",
    "review.proposal.create",
}
missing = sorted(required - set(CAPABILITIES))
assert not missing, f"Missing review bridge capabilities: {missing}"
assert REVIEW_SCHEMA_VERSION == 1
paths = [
    Path("src/lifeos/reviews/contracts.py"),
    Path("src/lifeos/reviews/artifact.py"),
    Path("src/lifeos/reviews/snapshot.py"),
    Path("packages/obsidian-plugin/src/review-artifact.ts"),
    Path("packages/obsidian-plugin/src/review-workspace.ts"),
]
joined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
assert "anthropic" not in joined and "claude" not in joined
assert Path("docs/user-manual/10-first-class-reviews.md").exists()
assert not Path("tasks/backlog/1311-first-class-reviews-e2e-release.md").exists(), "Release task is not completed."
print("First-class review release surface is compatible and provider-neutral.")
PY
