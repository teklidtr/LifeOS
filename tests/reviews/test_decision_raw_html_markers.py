from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.daily import DailyInteractionError
from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.artifact import ReviewArtifactUpdate
from lifeos.reviews.contracts import ReviewArtifact
from lifeos.reviews.decisions import ReviewDecisionService, artifact_item_fingerprints

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64


def marker(item_id: str, fingerprint: str = FP_A) -> str:
    return f"<!-- lifeos:item {item_id} {fingerprint} -->"


def setup_artifact(tmp_path: Path) -> tuple[Path, ReviewArtifactService, ReviewArtifact]:
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
    return vault, artifacts, artifact


def replace_items(
    artifacts: ReviewArtifactService,
    artifact: ReviewArtifact,
    content: str,
    *,
    idempotency_key: str,
) -> ReviewArtifact:
    return artifacts.update(
        review_id=artifact.metadata.review_id,
        expected_hash=artifact.content_hash,
        idempotency_key=idempotency_key,
        now=NOW,
        update=ReviewArtifactUpdate(managed_blocks={"items": content}),
    )


@pytest.mark.parametrize(
    "raw_block",
    (
        "<script>\n- [ ] Fake script item {marker}\n</script>",
        "<pre>\n- [ ] Fake pre item {marker}\n</pre>",
        "<style>\n- [ ] Fake style item {marker}\n</style>",
        "<!--\n- [ ] Fake comment item {marker}\n-->",
        "<?lifeos\n- [ ] Fake processing item {marker}\n?>",
        "<![CDATA[\n- [ ] Fake cdata item {marker}\n]]>",
        "<div>\n- [ ] Fake div item {marker}\n</div>\n",
    ),
)
def test_raw_html_blocks_do_not_authorize_review_items(
    tmp_path: Path, raw_block: str
) -> None:
    _, artifacts, artifact = setup_artifact(tmp_path)
    items = "\n".join(
        (
            "## Review items",
            "",
            raw_block.format(marker=marker("fake")),
            "",
            f"- [ ] Real item {marker('real', FP_B)}",
        )
    )
    artifact = replace_items(artifacts, artifact, items, idempotency_key="raw-html-items")

    assert artifact_item_fingerprints(artifact) == {"real": FP_B}


def test_raw_html_fake_marker_cannot_attach_proposal_reference(tmp_path: Path) -> None:
    vault, artifacts, artifact = setup_artifact(tmp_path)
    items = "\n".join(
        (
            "## Review items",
            "",
            "<script>",
            f"- [ ] Example only {marker('fake-proposal', FP_A)}",
            "</script>",
        )
    )
    artifact = replace_items(artifacts, artifact, items, idempotency_key="raw-proposal-items")
    path = vault / artifact.path
    before = path.read_bytes()
    before_decisions = artifact.metadata.item_decisions
    before_refs = artifact.metadata.proposal_refs

    with pytest.raises(DailyInteractionError) as error:
        ReviewDecisionService(artifacts).decide(
            review_id=artifact.metadata.review_id,
            item_id="fake-proposal",
            evidence_fingerprint=FP_A,
            decision="propose_change",
            proposal_id="proposal-fake",
            expected_hash=artifact.content_hash,
            idempotency_key="reject-raw-proposal",
            now=NOW,
        )

    assert error.value.code == "stale_review_item"
    assert path.read_bytes() == before
    reloaded = artifacts.load_id(artifact.metadata.review_id)
    assert reloaded.metadata.item_decisions == before_decisions
    assert reloaded.metadata.proposal_refs == before_refs
