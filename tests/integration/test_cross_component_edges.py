from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from lifeos.config import FeatureFlags, LifeOSConfig
from lifeos.context import ContextSearchError, build_context_pack
from lifeos.exports import ExportError, build_export, export_status
from lifeos.graph import GraphError, build_graph_document, build_graph_view
from lifeos.observation import load_observations
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.planning import load_plan_actions
from lifeos.proposals.application import apply_proposal
from lifeos.proposals.lifecycle import (
    approve_proposal,
    serialize_proposal_markdown,
    submit_proposal_for_review,
)
from lifeos.proposals.loader import LoadedProposal, load_proposal_directory
from lifeos.proposals.patches import CreateFile, PatchDocumentV2, serialize_patch_json_bytes
from lifeos.proposals.schema import ProposalMetadata, validate_metadata
from lifeos.publication import active_generation_path
from lifeos.registry import Registry
from lifeos.status import collect_status
from lifeos.study import load_flashcards


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _proposal_metadata(proposal_id: str) -> ProposalMetadata:
    return validate_metadata(
        {
            "id": proposal_id,
            "schema_version": 1,
            "patch_schema_version": 2,
            "lifecycle_schema_version": None,
            "title": "Cross-component proposal",
            "description": "Create a canonical wiki note for integration testing.",
            "status": "draft",
            "risk": "low",
            "created_at": "2026-07-16T00:00:00Z",
            "created_by": "integration-test",
            "submitted_at": None,
            "submitted_by": None,
            "review_digest": None,
            "approved_at": None,
            "approved_by": None,
            "rejected_at": None,
            "rejected_by": None,
            "rejection_reason": None,
            "applied_at": None,
            "applied_by": None,
            "related_goals": [],
            "related_sources": [],
            "extensions": {},
        }
    )


def _load_proposal(proposal_dir: Path, proposals_root: Path) -> LoadedProposal:
    result = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
    assert result.findings == ()
    assert result.proposal is not None
    return result.proposal


def _create_applied_wiki_note(vault_root: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=vault_root, check=True)
    proposals_root = vault_root / "proposals"
    proposals_root.mkdir()
    (vault_root / "wiki").mkdir()
    system_root = vault_root / "system"
    system_root.mkdir()
    (system_root / "generated-ownership.json").write_bytes(serialize_generated_ownership_bytes({}))

    proposal_id = "prop-20260716T000000Z-a1b2c3d4"
    content = (
        "---\n"
        "id: integrated-note\n"
        "type: concept\n"
        "title: Integrated Energy Note\n"
        "description: Evidence about sleep and energy.\n"
        "visibility: public\n"
        "---\n"
        "Sleep supports energy regulation.\n"
    )
    metadata = _proposal_metadata(proposal_id)
    proposal_dir = proposals_root / proposal_id
    proposal_dir.mkdir()
    (proposal_dir / "proposal.md").write_bytes(
        serialize_proposal_markdown(metadata, "Integration proposal body.")
    )
    (proposal_dir / "patches.json").write_bytes(
        serialize_patch_json_bytes(
            PatchDocumentV2(
                2,
                proposal_id,
                (CreateFile("op-create-note", "wiki/integrated.md", "absent", content),),
            )
        )
    )
    subprocess.run(
        [
            "git",
            "add",
            f"proposals/{proposal_id}/proposal.md",
            f"proposals/{proposal_id}/patches.json",
        ],
        cwd=vault_root,
        check=True,
    )

    draft = _load_proposal(proposal_dir, proposals_root)
    submit_proposal_for_review(
        draft,
        proposals_root=proposals_root,
        submitted_by="reviewer",
        submitted_at="2026-07-16T00:01:00Z",
    )
    pending = _load_proposal(proposal_dir, proposals_root)
    approve_proposal(
        pending,
        proposals_root=proposals_root,
        approved_by="approver",
        approved_at="2026-07-16T00:02:00Z",
    )
    approved = _load_proposal(proposal_dir, proposals_root)
    result = apply_proposal(
        approved,
        vault_root=vault_root,
        applied_by="operator",
        applied_at="2026-07-16T00:03:00Z",
    )
    assert result.changed_paths == ("wiki/integrated.md",)
    return content


def test_applied_note_is_immediately_available_to_context_graph_and_export(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = tmp_path / "runtime"
    vault_root.mkdir()
    expected_content = _create_applied_wiki_note(vault_root)
    _write(
        vault_root / "system" / "instructions.yml",
        "schema_version: 1\n"
        "instructions:\n"
        "  - id: prefer-direct-energy-evidence\n"
        "    authority: system\n"
        "    scope: domain\n"
        "    priority: 50\n"
        "    text: Prefer direct evidence about energy.\n"
        "    domains: [wiki]\n"
        "    query_terms: [energy]\n",
    )

    pack = build_context_pack(
        vault_root=vault_root,
        question="sleep energy regulation",
    )
    graph = build_graph_document(vault_root=vault_root, view_name="knowledge")
    export = build_export(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        kind="public-wiki",
    )

    assert [source.path for source in pack.sources] == ["wiki/integrated.md"]
    assert [instruction.id for instruction in pack.instructions] == [
        "prefer-direct-energy-evidence"
    ]
    assert pack.instructions[0].applicable_sources == ("wiki/integrated.md",)
    assert [node.id for node in graph.nodes] == ["integrated-note"]
    assert graph.nodes[0].description == "Evidence about sleep and energy."
    assert export.file_count == 1

    active = active_generation_path(runtime_dir / "exports" / "public-wiki")
    assert active is not None
    assert (active / "wiki" / "integrated.md").read_text(encoding="utf-8") == expected_content


def test_malformed_note_is_diagnosed_consistently_and_public_export_fails_closed(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = tmp_path / "runtime"
    _write(
        vault_root / "wiki" / "good.md",
        "---\nid: good\ntitle: Good\nvisibility: public\n---\nEnergy evidence.\n",
    )
    _write(
        vault_root / "wiki" / "bad.md",
        "---\ntitle: [\n---\nEnergy but malformed.\n",
    )

    pack = build_context_pack(vault_root=vault_root, question="energy")
    graph = build_graph_document(vault_root=vault_root, view_name="knowledge")

    assert [source.path for source in pack.sources] == ["wiki/good.md"]
    assert [(item.code, item.source_path) for item in pack.diagnostics] == [
        ("frontmatter-invalid-yaml", "wiki/bad.md")
    ]
    assert [node.path for node in graph.nodes] == ["wiki/good.md"]
    assert [(item.code, item.source_path) for item in graph.diagnostics] == [
        ("frontmatter-invalid-yaml", "wiki/bad.md")
    ]

    with pytest.raises(ExportError) as captured:
        build_export(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            kind="public-wiki",
        )

    assert captured.value.diagnostic is not None
    assert captured.value.diagnostic.code == "frontmatter-invalid-yaml"
    assert captured.value.diagnostic.source_path == "wiki/bad.md"
    assert active_generation_path(runtime_dir / "exports" / "public-wiki") is None


def test_symlink_attack_is_rejected_consistently_across_vault_consumers(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = tmp_path / "runtime"
    _write(vault_root / "wiki" / "safe.md", "---\ntitle: Safe\n---\nenergy\n")
    outside = tmp_path / "outside.md"
    _write(outside, "---\ntitle: Outside\n---\nenergy\n")
    (vault_root / "wiki" / "escape.md").symlink_to(outside)

    with pytest.raises(ContextSearchError, match="Unsafe symlink was rejected: wiki/escape.md"):
        build_context_pack(vault_root=vault_root, question="energy")
    with pytest.raises(GraphError, match="Unsafe symlink was rejected: wiki/escape.md"):
        build_graph_document(vault_root=vault_root, view_name="knowledge")
    with pytest.raises(ExportError, match="Unsafe symlink was rejected: wiki/escape.md"):
        build_export(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            kind="public-wiki",
        )

    assert active_generation_path(runtime_dir / "exports" / "public-wiki") is None


def test_domain_loaders_are_isolated_to_their_canonical_roots(tmp_path: Path) -> None:
    _write(
        tmp_path / "plans" / "week.md",
        "---\n"
        "id: week-plan\n"
        "type: plan\n"
        "tasks:\n"
        "  - task_id: plan-task\n"
        "    title: Review notes\n"
        "    status: active\n"
        "    duration: 20\n"
        "    energy: low\n"
        "    motivation: medium\n"
        "    mode: study\n"
        "---\n",
    )
    _write(
        tmp_path / "flashcards" / "card.md",
        "---\n"
        "id: card-1\n"
        "type: flashcard\n"
        "status: active\n"
        "topic: Biology\n"
        "question: What is ATP?\n"
        "answer: Cellular energy currency.\n"
        "due: 2026-07-16\n"
        "estimated_seconds: 30\n"
        "---\n",
    )
    _write(
        tmp_path / "journal" / "2026-07-16.md",
        "---\ndate: 2026-07-16\nmetrics:\n  energy: 4\nactivities: [walking]\n---\n",
    )
    _write(tmp_path / "wiki" / "broken.md", "---\ntitle: [\n---\n")

    actions = load_plan_actions(tmp_path)
    cards = load_flashcards(tmp_path)
    observations = load_observations(tmp_path)

    assert [action.task_id for action in actions] == ["plan-task"]
    assert [card.card_id for card in cards] == ["card-1"]
    assert [record.observed_on for record in observations] == [date(2026, 7, 16)]


def test_private_wikilink_stays_internal_but_is_redacted_from_public_export(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = tmp_path / "runtime"
    _write(
        vault_root / "wiki" / "public.md",
        "---\nid: public\ntitle: Public\nvisibility: public\n---\nSee [[secret|Hidden details]].\n",
    )
    _write(
        vault_root / "wiki" / "secret.md",
        "---\nid: secret\ntitle: Secret\nvisibility: private\n---\nPrivate evidence.\n",
    )

    pack = build_context_pack(vault_root=vault_root, question="private evidence hidden")
    graph = build_graph_document(vault_root=vault_root, view_name="knowledge")
    export = build_export(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        kind="public-wiki",
    )

    assert [source.path for source in pack.sources] == [
        "wiki/secret.md",
        "wiki/public.md",
    ]
    assert [(edge.source, edge.target, edge.relation) for edge in graph.edges] == [
        ("public", "secret", "wikilink")
    ]
    assert [(item.code, item.source_path) for item in export.diagnostics] == [
        ("export-link-private", "wiki/public.md")
    ]

    active = active_generation_path(runtime_dir / "exports" / "public-wiki")
    assert active is not None
    rendered = (active / "wiki" / "public.md").read_text(encoding="utf-8")
    assert "Hidden details" in rendered
    assert "secret" not in rendered.casefold()
    assert not (active / "wiki" / "secret.md").exists()


def test_graph_publication_failure_does_not_change_existing_export_generation(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = tmp_path / "runtime"
    _write(
        vault_root / "wiki" / "note.md",
        "---\nid: note\ntitle: Note\nvisibility: public\n---\nold\n",
    )
    export = build_export(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        kind="public-wiki",
    )
    export_generation = Path(export.output_dir).name
    build_graph_view(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        view_name="knowledge",
    )
    _write(
        vault_root / "wiki" / "note.md",
        "---\nid: note\ntitle: Note\nvisibility: public\n---\nnew\n",
    )

    def fail_graph(checkpoint: str) -> None:
        if checkpoint == "after-generation-install":
            raise RuntimeError("graph interruption")

    with pytest.raises(RuntimeError, match="graph interruption"):
        build_graph_view(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            view_name="knowledge",
            _fault_injector=fail_graph,
        )

    state = export_status(vault_root=vault_root, runtime_dir=runtime_dir, kind="public-wiki")
    assert state.status == "stale"
    assert state.active_generation == export_generation
    active_export = active_generation_path(runtime_dir / "exports" / "public-wiki")
    assert active_export is not None
    assert (active_export / "wiki" / "note.md").read_text(encoding="utf-8").endswith("old\n")


def test_status_combines_graph_staleness_and_export_corruption(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = tmp_path / "runtime"
    vault_root.mkdir()
    _write(
        vault_root / "wiki" / "note.md",
        "---\nid: note\ntitle: Note\nvisibility: public\n---\nold\n",
    )
    _write(
        vault_root / "system" / "generated-ownership.json",
        '{"schema_version": 1, "owned_files": {}}',
    )
    registry = Registry(runtime_dir / "registry.db")
    registry.initialize()
    build_graph_view(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        view_name="knowledge",
    )
    build_export(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        kind="public-wiki",
    )

    _write(
        vault_root / "wiki" / "note.md",
        "---\nid: note\ntitle: Note\nvisibility: public\n---\nnew\n",
    )
    active_export = active_generation_path(runtime_dir / "exports" / "public-wiki")
    assert active_export is not None
    manifest_path = active_export / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["kind"] = "study-bundle"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    config = LifeOSConfig(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        features=FeatureFlags(graphify=True, exports=True),
    )
    status = collect_status(config, registry)
    checks = {check.subsystem: check for check in status.checks}

    assert checks["graph"].state == "stale"
    assert checks["graph"].code == "graph-stale"
    assert checks["exports"].state == "corrupt"
    assert checks["exports"].code == "exports-publication-corrupt"
    assert status.overall_state == "degraded"
