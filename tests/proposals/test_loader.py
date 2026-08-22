import json
import os
from pathlib import Path

from lifeos.proposals.loader import load_proposals
from lifeos.proposals.patches import PatchDocument, serialize_patch_json_bytes
from lifeos.proposals.review_snapshot import (
    build_review_snapshot,
    serialize_review_snapshot_bytes,
)

def test_load_empty_proposals(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    res = load_proposals(root)
    assert not res.proposals
    assert not res.findings

    root.mkdir()
    res2 = load_proposals(root)
    assert not res2.proposals
    assert not res2.findings

def test_load_valid_proposal(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    pid = "prop-20260712T120000Z-abcdef12"
    pdir = root / pid
    pdir.mkdir()

    md = f"---\nid: '{pid}'\ntitle: test\ndescription: d\nstatus: pending\nrisk: low\ncreated_at: '2026-07-12T12:00:00Z'\ncreated_by: 'system'\nrelated_goals: []\nrelated_sources: []\nextensions: {{}}\nschema_version: 1\npatch_schema_version: 1\n---\nBody\n"
    (pdir / "proposal.md").write_bytes(md.encode("utf-8"))

    pd = {"proposal_id": pid, "schema_version": 1, "operations": []}
    json_bytes = (json.dumps(pd, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    (pdir / "patches.json").write_bytes(json_bytes)

    res = load_proposals(root)
    assert not res.findings
    assert len(res.proposals) == 1
    p = res.proposals[0]
    assert p.proposal_dir == pid
    assert p.body == "Body\n"
    assert p.metadata.id == pid
    assert p.patch_document.proposal_id == pid

def test_symlink_rejection(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    pid = "prop-20260712T120000Z-abcdef12"

    target = tmp_path / "target"
    target.mkdir()

    md = f"---\nid: '{pid}'\ntitle: test\ndescription: d\nstatus: pending\nrisk: low\ncreated_at: '2026-07-12T12:00:00Z'\ncreated_by: 'system'\nrelated_goals: []\nrelated_sources: []\nextensions: {{}}\nschema_version: 1\npatch_schema_version: 1\n---\nBody\n"
    (target / "proposal.md").write_bytes(md.encode("utf-8"))
    pd = {"proposal_id": pid, "schema_version": 1, "operations": []}
    json_bytes = (json.dumps(pd, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    (target / "patches.json").write_bytes(json_bytes)

    link_dir = root / pid
    os.symlink(target, link_dir)

    res = load_proposals(root)
    assert len(res.proposals) == 0
    assert len(res.findings) == 1
    assert res.findings[0].code == "symlink_entry"

def test_json_duplicate_keys(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    pid = "prop-20260712T120000Z-abcdef12"
    pdir = root / pid
    pdir.mkdir()

    md = f"---\nid: '{pid}'\ntitle: test\ndescription: d\nstatus: pending\nrisk: low\ncreated_at: '2026-07-12T12:00:00Z'\ncreated_by: 'system'\nrelated_goals: []\nrelated_sources: []\nextensions: {{}}\nschema_version: 1\npatch_schema_version: 1\n---\nBody\n"
    (pdir / "proposal.md").write_bytes(md.encode("utf-8"))

    json_bytes = b'{"operations":[],"proposal_id":"prop-20260712T120000Z-abcdef12","schema_version":1,"schema_version":1}\n'
    (pdir / "patches.json").write_bytes(json_bytes)

    res = load_proposals(root)
    assert len(res.proposals) == 0
    errs = [f for f in res.findings if f.code == "malformed_json"]
    assert errs
    assert "duplicate key" in errs[0].message

def test_crlf_preservation(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    pid = "prop-20260712T120000Z-abcdef12"
    pdir = root / pid
    pdir.mkdir()

    md = f"---\r\nid: '{pid}'\r\ntitle: test\r\ndescription: d\r\nstatus: pending\r\nrisk: low\r\ncreated_at: '2026-07-12T12:00:00Z'\r\ncreated_by: 'system'\r\nrelated_goals: []\r\nrelated_sources: []\r\nextensions: {{}}\r\nschema_version: 1\r\npatch_schema_version: 1\r\n---\r\nLine1\r\nLine2"
    (pdir / "proposal.md").write_bytes(md.encode("utf-8"))

    pd = {"proposal_id": pid, "schema_version": 1, "operations": []}
    json_bytes = (json.dumps(pd, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    (pdir / "patches.json").write_bytes(json_bytes)

    res = load_proposals(root)
    assert len(res.proposals) == 1
    assert res.proposals[0].body == "Line1\r\nLine2"

def test_cross_document_invariants(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    pid = "prop-20260712T120000Z-abcdef12"
    pdir = root / pid
    pdir.mkdir()

    pid2 = "prop-20260712T120000Z-deadbeef"
    md = f"---\nid: '{pid2}'\ntitle: test\ndescription: d\nstatus: pending\nrisk: low\ncreated_at: '2026-07-12T12:00:00Z'\ncreated_by: 'system'\nrelated_goals: []\nrelated_sources: []\nextensions: {{}}\nschema_version: 1\npatch_schema_version: 2\n---\nBody\n"
    (pdir / "proposal.md").write_bytes(md.encode("utf-8"))

    pd = {"proposal_id": pid, "schema_version": 1, "operations": []}
    json_bytes = (json.dumps(pd, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    (pdir / "patches.json").write_bytes(json_bytes)

    res = load_proposals(root)
    assert len(res.proposals) == 0
    codes = {f.code for f in res.findings}
    assert "id_mismatch" in codes
    assert "version_mismatch" in codes

def test_v2_loader_integration(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    pid = "prop-20260713T090000Z-abcdef12"
    pdir = root / pid
    pdir.mkdir()

    md_v2 = f"---\nid: '{pid}'\ntitle: test\ndescription: d\nstatus: pending\nrisk: low\ncreated_at: '2026-07-13T09:00:00Z'\ncreated_by: 'system'\nrelated_goals: []\nrelated_sources: []\nextensions: {{}}\nschema_version: 1\npatch_schema_version: 2\n---\nBody\n"
    md_v1 = md_v2.replace("patch_schema_version: 2", "patch_schema_version: 1")

    pd = {
        "proposal_id": pid,
        "schema_version": 2,
        "operations": [
            {
                "id": "op-1",
                "op": "create_generated_file",
                "target_path": "gen1.txt",
                "expected_target_state": "absent",

                "generator_id": "gen-1",
                "generator_version": "v1.0.0",
                "new_content": "data"
            }
        ]
    }
    json_bytes = (json.dumps(pd, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")

    # 1. metadata v2 + document v2 succeeds
    (pdir / "proposal.md").write_bytes(md_v2.encode("utf-8"))
    (pdir / "patches.json").write_bytes(json_bytes)
    res = load_proposals(root)
    assert not res.findings
    assert len(res.proposals) == 1
    assert res.proposals[0].patch_document.schema_version == 2

    # 2. metadata v1 + document v2 fails
    (pdir / "proposal.md").write_bytes(md_v1.encode("utf-8"))
    res = load_proposals(root)
    assert len(res.proposals) == 0
    assert any(f.code == "version_mismatch" for f in res.findings)

    # 3. noncanonical v2 JSON fails
    (pdir / "proposal.md").write_bytes(md_v2.encode("utf-8"))
    bad_json = json_bytes.replace(b":", b": ") # add space
    (pdir / "patches.json").write_bytes(bad_json)
    res = load_proposals(root)
    assert len(res.proposals) == 0
    assert any(f.code == "noncanonical_json" for f in res.findings)


def test_loader_validates_optional_review_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    pid = "prop-20260712T120000Z-abcdef12"
    proposal_dir = root / pid
    proposal_dir.mkdir()
    proposal_dir.joinpath("proposal.md").write_text(
        f"---\nid: '{pid}'\ntitle: test\ndescription: d\nstatus: draft\nrisk: low\n"
        "created_at: '2026-07-12T12:00:00Z'\ncreated_by: system\n"
        "related_goals: []\nrelated_sources: []\nextensions: {}\n"
        "schema_version: 1\npatch_schema_version: 1\n---\nBody\n",
        encoding="utf-8",
    )
    document = PatchDocument(1, pid, ())
    proposal_dir.joinpath("patches.json").write_bytes(
        serialize_patch_json_bytes(document)
    )
    snapshot = build_review_snapshot(vault_root=tmp_path, patch_document=document)
    proposal_dir.joinpath("review.json").write_bytes(
        serialize_review_snapshot_bytes(snapshot)
    )

    loaded = load_proposals(root)

    assert not loaded.findings
    assert loaded.proposals[0].review_snapshot == snapshot
    assert loaded.proposals[0].review_snapshot_source_hash is not None

    content = proposal_dir.joinpath("review.json").read_text(encoding="utf-8")
    proposal_dir.joinpath("review.json").write_text(
        content.replace('"proposal_id":"', '"proposal_id":"tampered-'),
        encoding="utf-8",
    )
    rejected = load_proposals(root)
    assert rejected.proposals == ()
    assert any(f.code == "proposal_id_mismatch" for f in rejected.findings)
