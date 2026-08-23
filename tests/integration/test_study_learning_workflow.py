from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from lifeos.context import build_context_pack
from lifeos.facade.authorization import AuthorizedPrincipal
from lifeos.facade.consequential_tools import (
    ApplyProposalRequest,
    ApproveProposalRequest,
    SubmitProposalRequest,
    apply_proposal_tool,
    approve_proposal_tool,
    submit_proposal_tool,
)
from lifeos.facade.proposal_tools import (
    EvolveStudyLearningProposalRequest,
    EvolveWikiCreateRequest,
    StudyFlashcardCreateRequest,
    evolve_study_learning_proposal,
)
from lifeos.registry import Registry
from lifeos.registry.file_tracking import register_scan
from lifeos.scanner import VaultFile
from lifeos.study import load_flashcards


class AllowAuthorizer:
    def authorize(self, request, /):  # noqa: ANN001
        return AuthorizedPrincipal("integration-user")


def test_context_aware_study_workflow_applies_wiki_and_flashcard_atomically(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    for root in ("study", "wiki", "flashcards", "goals", "system", "proposals"):
        (vault / root).mkdir(parents=True, exist_ok=True)
    (vault / "system/generated-ownership.json").write_text(
        json.dumps({"schema_version": 1, "owned_files": {}}), encoding="utf-8"
    )
    (vault / "system/instructions.yml").write_text(
        "schema_version: 1\n"
        "instructions:\n"
        "  - id: driving-exam\n"
        "    authority: system\n"
        "    scope: path\n"
        "    priority: 100\n"
        "    text: Prioritize MEB-style tested distinctions and confusing rules.\n"
        "    paths: [study/driving-licence/**]\n",
        encoding="utf-8",
    )
    source = vault / "study/driving-licence/intersections.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\ntitle: Intersections\ndescription: Driving licence intersection rules\n---\n"
        "Uncontrolled intersections and right-of-way distinctions.\n",
        encoding="utf-8",
    )
    goal = vault / "goals/pass-driving-licence.md"
    goal.write_text(
        "---\ntitle: Pass driving licence\ndescription: Pass the MEB driving licence exam\n---\n"
        "Prepare for the Turkish driving licence exam.\n",
        encoding="utf-8",
    )

    context = build_context_pack(
        vault_root=vault,
        question="What should I remember for the driving licence exam?",
        focus_paths=("study/driving-licence/intersections.md",),
    )
    assert context.sources[0].path == "study/driving-licence/intersections.md"
    assert "goals/pass-driving-licence.md" in {item.path for item in context.sources}
    assert [item.id for item in context.instructions] == ["driving-exam"]

    registry = Registry(vault / ".lifeos/registry.db")
    registry.initialize()
    register_scan(
        registry,
        vault,
        [
            VaultFile(Path("study/driving-licence/intersections.md"), ".md", source.stat().st_size),
            VaultFile(Path("goals/pass-driving-licence.md"), ".md", goal.stat().st_size),
        ],
    )

    result = evolve_study_learning_proposal(
        vault_root=vault,
        registry=registry,
        request=EvolveStudyLearningProposalRequest(
            source_path="study/driving-licence/intersections.md",
            wiki_creates=(
                EvolveWikiCreateRequest(
                    target_path="wiki/traffic/right-of-way.md",
                    title="Right of way",
                    body="A durable explanation of right-of-way distinctions.",
                    rationale="This concept is reusable beyond one study chapter.",
                ),
            ),
            flashcards=(
                StudyFlashcardCreateRequest(
                    target_path="flashcards/driving-licence/traffic/right-of-way.md",
                    card_id="driving-right-of-way",
                    topic="Driving licence",
                    question="What distinction determines priority at this intersection?",
                    answer="Apply the reviewed right-of-way rule for the intersection type.",
                    rationale="The rule is exam-relevant and easy to confuse.",
                    learning_context="Turkish driving licence exam",
                    knowledge_refs=("wiki/traffic/right-of-way.md",),
                ),
            ),
        ),
        clock_fn=lambda: datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
        random_suffix_fn=lambda: "abcdef12",
    )

    assert not (vault / "wiki/traffic").exists()
    assert not (vault / "flashcards/driving-licence").exists()

    authorizer = AllowAuthorizer()
    submit_proposal_tool(
        vault_root=vault,
        request=SubmitProposalRequest(result.proposal_id),
        authorizer=authorizer,
    )
    approve_proposal_tool(
        vault_root=vault,
        request=ApproveProposalRequest(result.proposal_id),
        authorizer=authorizer,
    )
    applied = apply_proposal_tool(
        vault_root=vault,
        request=ApplyProposalRequest(result.proposal_id),
        authorizer=authorizer,
    )

    assert applied.status == "applied"
    assert set(applied.changed_paths) >= {
        "wiki/traffic/right-of-way.md",
        "flashcards/driving-licence/traffic/right-of-way.md",
    }
    cards = load_flashcards(vault)
    assert len(cards) == 1
    assert cards[0].card_id == "driving-right-of-way"
    assert cards[0].source_refs == (
        "study/driving-licence/intersections.md",
        "wiki/traffic/right-of-way.md",
    )
