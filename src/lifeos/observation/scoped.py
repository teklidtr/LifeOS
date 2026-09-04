"""Policy-scoped observation loading that filters paths before opening content."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from lifeos.diagnostics import diagnostic_error_message, diagnostics_from_findings
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, read_vault_markdown
from lifeos.vault_paths import iter_vault_markdown_paths

from .patterns import (
    ObservationError,
    ObservationRecord,
    _activities,
    _metric_metadata,
    _metrics,
    _parse_observed_date,
)

PathPredicate = Callable[[str], bool]


def load_scoped_observations(
    vault_root: Path,
    *,
    allow_path: PathPredicate,
) -> tuple[ObservationRecord, ...]:
    """Load authorized journal observations without opening denied paths.

    The path-only walker evaluates ``allow_path`` before statting descendants or
    reading file bytes, so protected/excluded journal subtrees remain untouched.
    Parsing semantics are delegated to the canonical observation helpers.
    """

    def allowed_journal_path(path: str) -> bool:
        candidate = path.rstrip("/")
        if candidate != "journal" and not candidate.startswith("journal/"):
            return False
        return allow_path(candidate)

    try:
        paths = iter_vault_markdown_paths(vault_root, path_filter=allowed_journal_path)
    except VaultAccessError as exc:
        raise ObservationError(str(exc)) from exc

    records: list[ObservationRecord] = []
    for relative_path in paths:
        try:
            source = read_vault_markdown(vault_root, relative_path)
        except VaultAccessError as exc:
            raise ObservationError(str(exc)) from exc
        path = source.path
        parsed = parse_markdown_note(path, content=source.content)
        diagnostics = diagnostics_from_findings(parsed.findings, vault_root=vault_root)
        if diagnostics:
            raise ObservationError(
                diagnostic_error_message(diagnostics[0]), diagnostic=diagnostics[0]
            )
        if "metrics" not in parsed.frontmatter and "activities" not in parsed.frontmatter:
            continue
        records.append(
            ObservationRecord(
                observed_on=_parse_observed_date(parsed.frontmatter.get("date"), path),
                path=relative_path,
                metrics=_metrics(parsed.frontmatter.get("metrics"), path),
                activities=_activities(parsed.frontmatter.get("activities"), path),
                metric_units=_metric_metadata(
                    parsed.frontmatter.get("metric_units"), key="metric_units", path=path
                ),
                metric_definitions=_metric_metadata(
                    parsed.frontmatter.get("metric_definitions"),
                    key="metric_definitions",
                    path=path,
                ),
            )
        )
    records.sort(key=lambda item: (item.observed_on, item.path))
    return tuple(records)
