"""Narrow policy exceptions for base-hash-bound human-file patches."""

from __future__ import annotations

from pathlib import Path


def allows_canonical_pattern_managed_patch(
    *,
    target_path: str,
    original_text: str,
    candidate_text: str,
) -> bool:
    """Allow managed-block mutation only for a canonical, identity-stable pattern candidate.

    ``patch_human_file`` normally rejects Markdown containing LifeOS-managed blocks. Personal
    patterns are the intentional exception: their canonical schema requires one derived
    ``personal-pattern-evidence`` block while LIFEOS-1703 requires existing pattern transitions
    to remain ordinary base-hash-bound human-file patches.

    Imports stay local so the proposal package does not create an import cycle with the pattern
    facade, which itself exposes proposal builders.
    """
    if not target_path.startswith("patterns/") or not target_path.casefold().endswith(".md"):
        return False

    from lifeos.patterns.artifact import parse_pattern, serialize_pattern
    from lifeos.patterns.contracts import PatternError

    path = Path(target_path)
    try:
        original = parse_pattern(path, target_path, original_text)
        candidate = parse_pattern(path, target_path, candidate_text)
    except PatternError:
        return False
    if original is None or candidate is None:
        return False
    if original.metadata.pattern_id != candidate.metadata.pattern_id:
        return False

    canonical_candidate = serialize_pattern(
        candidate.metadata,
        body_prefix=candidate.body_prefix,
        body_suffix=candidate.body_suffix,
    )
    return canonical_candidate == candidate_text
