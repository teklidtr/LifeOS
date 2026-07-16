from __future__ import annotations

from pathlib import Path

from lifeos.context import lexical_search, token_sequence


def _note(
    vault: Path,
    relative: str,
    *,
    title: str,
    description: str = "",
    body: str = "",
) -> None:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"title: {title}\n"
        f"description: {description}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_exact_lexical_search_does_not_match_substrings(tmp_path: Path) -> None:
    _note(tmp_path, "wiki/heart.md", title="Heart health", body="A healthy heart.")
    _note(tmp_path, "wiki/art.md", title="Art practice", body="Art history.")

    results = lexical_search(vault_root=tmp_path, query="art")

    assert [item.path for item in results] == ["wiki/art.md"]


def test_unicode_words_and_punctuation_tokenize_deterministically(tmp_path: Path) -> None:
    assert token_sequence("Café, ATP! naïve—öğrenme_ritmi") == (
        "café",
        "atp",
        "naïve",
        "öğrenme",
        "ritmi",
    )
    _note(tmp_path, "wiki/cafe.md", title="Café ATP", body="Naïve öğrenme ritmi.")

    results = lexical_search(vault_root=tmp_path, query="CAFÉ; öğrenme")

    assert [item.path for item in results] == ["wiki/cafe.md"]
    assert results[0].matched_terms == ("café", "öğrenme")


def test_field_weights_are_independently_observable_and_reproducible(tmp_path: Path) -> None:
    _note(
        tmp_path,
        "wiki/gamma.md",
        title="Alpha",
        description="Beta",
        body="Delta delta delta delta delta delta delta.",
    )

    result = lexical_search(
        vault_root=tmp_path,
        query="alpha beta gamma delta",
    )[0]

    contributions = {
        (item.term, item.field): (item.match_count, item.weight, item.score)
        for item in result.score_evidence
    }
    assert contributions == {
        ("alpha", "title"): (1, 8, 8),
        ("beta", "description"): (1, 5, 5),
        ("gamma", "path"): (1, 3, 3),
        ("delta", "body"): (5, 1, 5),
    }
    assert result.score == 21
    assert result.score == sum(item.score for item in result.score_evidence)


def test_equal_scores_use_stable_path_tie_breaking(tmp_path: Path) -> None:
    _note(tmp_path, "wiki/zeta.md", title="Shared")
    _note(tmp_path, "wiki/alpha.md", title="Shared")

    first = lexical_search(vault_root=tmp_path, query="shared")
    second = lexical_search(vault_root=tmp_path, query="shared")

    assert [item.path for item in first] == ["wiki/alpha.md", "wiki/zeta.md"]
    assert first == second
