from pathlib import Path

import pytest

from lifeos.retrieval import (
    AnswerEvidence,
    CancellationToken,
    DeterministicEmbeddingProvider,
    ProviderCapabilities,
    RetrievalError,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalScope,
    build_provider_disclosure,
    load_retrieval_policy,
    scope_decision,
)


def test_scope_filters_and_protected_prefixes_fail_closed() -> None:
    scope = RetrievalScope(folders=("wiki",), excluded_paths=("wiki/drafts",))
    policy = RetrievalPolicy(protected_prefixes=("wiki/private",))
    assert scope_decision("wiki/public.md", scope=scope, policy=policy, mode="local").allowed
    assert (
        scope_decision("wiki/drafts/a.md", scope=scope, policy=policy, mode="local").reason
        == "excluded-by-request"
    )
    protected = scope_decision("wiki/private/a.md", scope=scope, policy=policy, mode="local")
    assert not protected.allowed and protected.protected
    assert (
        scope_decision("journal/a.md", scope=scope, policy=policy, mode="local").reason
        == "outside-selected-folders"
    )


def test_external_protected_content_requires_policy_and_explicit_scope() -> None:
    policy = RetrievalPolicy(
        protected_prefixes=("profile",), external_allowed_prefixes=("profile/shareable",)
    )
    denied = RetrievalScope(allow_protected=False)
    assert not scope_decision(
        "profile/shareable/a.md", scope=denied, policy=policy, mode="external"
    ).allowed
    allowed = RetrievalScope(allow_protected=True)
    assert scope_decision(
        "profile/shareable/a.md", scope=allowed, policy=policy, mode="external"
    ).allowed
    assert (
        scope_decision("profile/private.md", scope=allowed, policy=policy, mode="external").reason
        == "protected-external-deny"
    )


def test_provider_disclosure_lists_exact_content_and_budget() -> None:
    capability = ProviderCapabilities("generation", "fixture", "answer-v1", False, 8)
    evidence = (AnswerEvidence("e1", "wiki/a.md", "Section", "abc", "sha256:a", "sha256:b"),)
    disclosure = build_provider_disclosure(
        evidence=evidence,
        capabilities=capability,
        scope=RetrievalScope(),
        policy=RetrievalPolicy(max_external_characters=2),
    )
    assert disclosure.total_characters == 3
    assert not disclosure.allowed
    assert disclosure.reason == "external-context-budget-exceeded"
    assert disclosure.items[0].path == "wiki/a.md"


def test_deterministic_embedding_adapter_is_bounded_and_cancellable() -> None:
    provider = DeterministicEmbeddingProvider(
        dimensions=4, phrase_vectors={"same meaning": [1, 0, 0, 0]}
    )
    result = provider.embed(
        ["same meaning", "other"], timeout_seconds=1, cancellation=CancellationToken()
    )
    assert len(result.vectors) == 2
    assert result.vectors[0] == (1.0, 0.0, 0.0, 0.0)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(RetrievalError, match="cancelled"):
        provider.embed(["text"], timeout_seconds=1, cancellation=token)


def test_policy_loading_is_strict_and_defaults_are_protective(tmp_path: Path) -> None:
    assert "secrets" in load_retrieval_policy(tmp_path).protected_prefixes
    policy_file = tmp_path / "system" / "retrieval-policy.yml"
    policy_file.parent.mkdir()
    policy_file.write_text(
        "schema_version: 1\nprotected_prefixes: [private]\nexternal_allowed_prefixes: []\n",
        encoding="utf-8",
    )
    assert load_retrieval_policy(tmp_path).protected_prefixes == ("private",)
    policy_file.write_text("unknown: true\n", encoding="utf-8")
    with pytest.raises(RetrievalError, match="Unknown"):
        load_retrieval_policy(tmp_path)


def test_request_contract_rejects_unbounded_or_empty_inputs() -> None:
    with pytest.raises(RetrievalError):
        RetrievalRequest("")
    with pytest.raises(RetrievalError):
        RetrievalRequest("query", limit=101)
    with pytest.raises(RetrievalError):
        RetrievalScope(paths=("../escape.md",))
