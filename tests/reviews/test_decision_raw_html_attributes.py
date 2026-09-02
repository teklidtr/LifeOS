from datetime import date, datetime, timezone
from pathlib import Path

from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.artifact import ReviewArtifactUpdate
from lifeos.reviews.decisions import artifact_item_fingerprints

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64


def marker(item_id: str, fingerprint: str) -> str:
    return f"<!-- lifeos:item {item_id} {fingerprint} -->"


def test_quoted_angle_brackets_keep_following_lines_inside_raw_html(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    artifacts = ReviewArtifactService(
        vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="me"
    )
    artifact = artifacts.open_or_create(
        kind="daily",
        day=date(2026, 7, 16),
        timezone="UTC",
        now=NOW,
        idempotency_key="open",
    )
    items = "\n".join(
        (
            "## Review items",
            "",
            '<review-example title=\">\" other=\'<\'>',
            f"- [ ] Fake item {marker('fake', FP_A)}",
            "</review-example>",
            "",
            f"- [ ] Real item {marker('real', FP_B)}",
        )
    )
    artifact = artifacts.update(
        review_id=artifact.metadata.review_id,
        expected_hash=artifact.content_hash,
        idempotency_key="raw-html-quoted-attribute",
        now=NOW,
        update=ReviewArtifactUpdate(managed_blocks={"items": items}),
    )

    assert artifact_item_fingerprints(artifact) == {"real": FP_B}
