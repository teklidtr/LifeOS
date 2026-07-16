"""Cautious, scale-aware personal-observation analysis."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from statistics import NormalDist

from lifeos.diagnostics import (
    DiagnosticError,
    diagnostic_error_message,
    diagnostics_from_findings,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown

_VARIANCE_EPSILON = 1e-12
_HEALTH_ADJACENT_TERMS = frozenset(
    {
        "blood_pressure",
        "heart_rate",
        "temperature",
        "weight",
        "glucose",
        "pain",
        "sleep",
        "sleep_hours",
        "mood",
        "anxiety",
        "depression",
    }
)


class ObservationError(DiagnosticError):
    """Raised when journal observations or analysis inputs are invalid."""


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    observed_on: date
    path: str
    metrics: dict[str, float]
    activities: tuple[str, ...]
    metric_units: dict[str, str] = field(default_factory=dict)
    metric_definitions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidatePattern:
    status: str
    outcome: str
    factor: str
    direction: str
    effect: float
    sample_count: int
    statement: str
    evidence: tuple[str, ...]
    caveats: tuple[str, ...]
    raw_effect: float
    standardized_effect: float
    uncertainty_interval: tuple[float, float]
    evidence_strength: str
    practical_magnitude: str
    missing_count: int
    date_range: tuple[str, str]
    freshness_days: int
    quality_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PatternReport:
    outcome: str
    factor: str
    record_count: int
    candidates: tuple[CandidatePattern, ...]
    gaps: tuple[str, ...]


def _parse_observed_date(value: object, path: Path) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ObservationError(f"{path}: date must be an ISO date") from exc
    if value is not None:
        raise ObservationError(f"{path}: date must be an ISO date")
    try:
        return date.fromisoformat(path.stem)
    except ValueError as exc:
        raise ObservationError(f"{path}: date is required") from exc


def _metrics(value: object, path: Path) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ObservationError(f"{path}: metrics must be a mapping")
    result: dict[str, float] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ObservationError(f"{path}: metric names must be non-empty strings")
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
        ):
            raise ObservationError(f"{path}: metric {key} must be a finite number")
        result[key.strip()] = float(raw)
    return result


def _metric_metadata(value: object, *, key: str, path: Path) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ObservationError(f"{path}: {key} must be a mapping")
    result: dict[str, str] = {}
    for metric, raw in value.items():
        if not isinstance(metric, str) or not metric.strip():
            raise ObservationError(f"{path}: {key} names must be non-empty strings")
        if not isinstance(raw, str) or not raw.strip():
            raise ObservationError(f"{path}: {key}.{metric} must be a non-empty string")
        result[metric.strip()] = raw.strip()
    return result


def _activities(value: object, path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ObservationError(f"{path}: activities must be a list of non-empty strings")
    return tuple(dict.fromkeys(item.strip() for item in value))


def load_observations(vault_root: Path) -> tuple[ObservationRecord, ...]:
    records: list[ObservationRecord] = []
    try:
        sources = iter_vault_markdown(vault_root, roots=("journal",))
    except VaultAccessError as exc:
        raise ObservationError(str(exc)) from exc
    for source in sources:
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
                path=path.relative_to(vault_root).as_posix(),
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


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _sample_variance(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _correlation(pairs: tuple[tuple[float, float], ...]) -> float:
    xs = tuple(pair[0] for pair in pairs)
    ys = tuple(pair[1] for pair in pairs)
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    return numerator / math.sqrt(variance_x * variance_y)


def _correlation_interval(effect: float, sample_count: int) -> tuple[float, float]:
    bounded = min(0.999999, max(-0.999999, effect))
    z = math.atanh(bounded)
    margin = NormalDist().inv_cdf(0.975) / math.sqrt(sample_count - 3)
    return (math.tanh(z - margin), math.tanh(z + margin))


def _standardized_mean_difference(
    tagged: tuple[float, ...], untagged: tuple[float, ...]
) -> tuple[float, float, float]:
    tagged_mean = _mean(tagged)
    untagged_mean = _mean(untagged)
    raw = tagged_mean - untagged_mean
    degrees = len(tagged) + len(untagged) - 2
    pooled_variance = (
        (len(tagged) - 1) * _sample_variance(tagged)
        + (len(untagged) - 1) * _sample_variance(untagged)
    ) / degrees
    if pooled_variance <= _VARIANCE_EPSILON:
        overall_variance = _sample_variance((*tagged, *untagged))
        if overall_variance <= _VARIANCE_EPSILON:
            raise ObservationError("outcome variance is too small for a standardized comparison")
        pooled_variance = overall_variance
    standardized = raw / math.sqrt(pooled_variance)
    standard_error = math.sqrt(
        (len(tagged) + len(untagged)) / (len(tagged) * len(untagged))
        + standardized**2 / (2 * degrees)
    )
    margin = NormalDist().inv_cdf(0.975) * standard_error
    return raw, standardized, margin


def _metric_signature(
    records: tuple[ObservationRecord, ...], metric: str
) -> tuple[str, str] | None:
    signatures = {
        (
            record.metric_units.get(metric, ""),
            record.metric_definitions.get(metric, ""),
        )
        for record in records
        if metric in record.metrics
    }
    if len(signatures) != 1:
        return None
    return next(iter(signatures))


def _duplicate_dates(records: tuple[ObservationRecord, ...]) -> tuple[date, ...]:
    counts: dict[date, int] = {}
    for record in records:
        counts[record.observed_on] = counts.get(record.observed_on, 0) + 1
    return tuple(sorted(day for day, count in counts.items() if count > 1))


def _date_quality(
    used_records: tuple[ObservationRecord, ...],
    *,
    all_records: tuple[ObservationRecord, ...],
    as_of: date | None,
) -> tuple[tuple[str, str], int]:
    first = min(record.observed_on for record in used_records)
    last = max(record.observed_on for record in used_records)
    reference = as_of or max(record.observed_on for record in all_records)
    return (first.isoformat(), last.isoformat()), max(0, (reference - last).days)


def _magnitude(effect: float) -> str:
    absolute = abs(effect)
    if absolute < 0.2:
        return "negligible"
    if absolute < 0.5:
        return "small"
    if absolute < 0.8:
        return "moderate"
    return "large"


def _strength(*, sample_count: int, interval: tuple[float, float]) -> str:
    crosses_zero = interval[0] <= 0 <= interval[1]
    if sample_count >= 20 and not crosses_zero:
        return "high"
    if sample_count >= 10 and not crosses_zero:
        return "medium"
    return "low"


def _health_caveat(outcome: str, factor: str) -> tuple[str, ...]:
    if outcome.casefold() in _HEALTH_ADJACENT_TERMS or factor.casefold() in _HEALTH_ADJACENT_TERMS:
        return (
            "Health-adjacent journal metrics are especially vulnerable to measurement and context bias; do not use this result for diagnosis or treatment decisions.",
        )
    return ()


def _withheld_report(
    *, outcome: str, factor: str, record_count: int, reasons: tuple[str, ...]
) -> PatternReport:
    return PatternReport(outcome, factor, record_count, (), reasons)


def analyze_numeric_pattern(
    *,
    records: tuple[ObservationRecord, ...],
    outcome: str,
    factor: str,
    min_samples: int = 5,
    as_of: date | None = None,
) -> PatternReport:
    if not isinstance(outcome, str) or not outcome.strip():
        raise ObservationError("outcome and factor must be non-empty")
    if not isinstance(factor, str) or not factor.strip():
        raise ObservationError("outcome and factor must be non-empty")
    outcome_name = outcome.strip()
    factor_name = factor.strip()
    if outcome_name.casefold() == factor_name.casefold():
        raise ObservationError("outcome and factor must be different metrics")
    if type(min_samples) is not int or min_samples < 4:
        raise ObservationError("min_samples must be an integer of at least 4")

    duplicates = _duplicate_dates(records)
    if duplicates:
        joined = ", ".join(day.isoformat() for day in duplicates)
        return _withheld_report(
            outcome=outcome_name,
            factor=factor_name,
            record_count=0,
            reasons=(f"Duplicate observation dates must be resolved before analysis: {joined}.",),
        )

    used_records = tuple(
        record
        for record in records
        if factor_name in record.metrics and outcome_name in record.metrics
    )
    missing_count = len(records) - len(used_records)
    if len(used_records) < min_samples:
        return _withheld_report(
            outcome=outcome_name,
            factor=factor_name,
            record_count=len(used_records),
            reasons=(
                f"Only {len(used_records)} paired observations were available; {min_samples} are required. Missing pairs: {missing_count}.",
            ),
        )
    if (
        _metric_signature(used_records, outcome_name) is None
        or _metric_signature(used_records, factor_name) is None
    ):
        return _withheld_report(
            outcome=outcome_name,
            factor=factor_name,
            record_count=len(used_records),
            reasons=("Metric units or definitions are incompatible across observations.",),
        )

    pairs = tuple(
        (record.metrics[factor_name], record.metrics[outcome_name]) for record in used_records
    )
    factor_values = tuple(pair[0] for pair in pairs)
    outcome_values = tuple(pair[1] for pair in pairs)
    if _sample_variance(factor_values) <= _VARIANCE_EPSILON:
        return _withheld_report(
            outcome=outcome_name,
            factor=factor_name,
            record_count=len(pairs),
            reasons=("Factor variance is too small to estimate an association.",),
        )
    if _sample_variance(outcome_values) <= _VARIANCE_EPSILON:
        return _withheld_report(
            outcome=outcome_name,
            factor=factor_name,
            record_count=len(pairs),
            reasons=("Outcome variance is too small to estimate an association.",),
        )

    effect = _correlation(pairs)
    interval = _correlation_interval(effect, len(pairs))
    date_range, freshness_days = _date_quality(used_records, all_records=records, as_of=as_of)
    if abs(effect) < 0.25:
        return _withheld_report(
            outcome=outcome_name,
            factor=factor_name,
            record_count=len(pairs),
            reasons=(
                "The standardized association was too weak to surface as a candidate pattern.",
                f"95% uncertainty interval: {interval[0]:.3f} to {interval[1]:.3f}.",
            ),
        )

    direction = "positive" if effect > 0 else "negative"
    strength = _strength(sample_count=len(pairs), interval=interval)
    quality_notes = (
        f"Missing paired observations: {missing_count} of {len(records)}.",
        f"Evidence spans {date_range[0]} through {date_range[1]}.",
        f"Latest evidence is {freshness_days} days before the analysis reference date.",
        "Repeated measurements from one person are not independent population samples.",
    )
    candidate = CandidatePattern(
        status="candidate",
        outcome=outcome_name,
        factor=factor_name,
        direction=direction,
        effect=round(effect, 3),
        sample_count=len(pairs),
        statement=(
            f"Higher {factor_name} was associated with "
            f"{'higher' if effect > 0 else 'lower'} {outcome_name} "
            f"across {len(pairs)} dated observations; evidence strength is {strength}."
        ),
        evidence=tuple(record.path for record in used_records),
        caveats=(
            "This is a candidate association, not evidence of causation.",
            "Unrecorded variables, repeated-measure dependence, and measurement noise may explain the pattern.",
            *_health_caveat(outcome_name, factor_name),
        ),
        raw_effect=round(effect, 3),
        standardized_effect=round(effect, 3),
        uncertainty_interval=(round(interval[0], 3), round(interval[1], 3)),
        evidence_strength=strength,
        practical_magnitude=_magnitude(effect),
        missing_count=missing_count,
        date_range=date_range,
        freshness_days=freshness_days,
        quality_notes=quality_notes,
    )
    return PatternReport(outcome_name, factor_name, len(pairs), (candidate,), ())


def analyze_activity_pattern(
    *,
    records: tuple[ObservationRecord, ...],
    outcome: str,
    activity: str,
    min_group_size: int = 3,
    as_of: date | None = None,
) -> PatternReport:
    if not isinstance(outcome, str) or not outcome.strip():
        raise ObservationError("outcome and activity must be non-empty")
    if not isinstance(activity, str) or not activity.strip():
        raise ObservationError("outcome and activity must be non-empty")
    outcome_name = outcome.strip()
    activity_name = activity.strip()
    if type(min_group_size) is not int or min_group_size < 3:
        raise ObservationError("min_group_size must be an integer of at least 3")

    duplicates = _duplicate_dates(records)
    if duplicates:
        joined = ", ".join(day.isoformat() for day in duplicates)
        return _withheld_report(
            outcome=outcome_name,
            factor=activity_name,
            record_count=0,
            reasons=(f"Duplicate observation dates must be resolved before analysis: {joined}.",),
        )

    outcome_records = tuple(record for record in records if outcome_name in record.metrics)
    missing_count = len(records) - len(outcome_records)
    if _metric_signature(outcome_records, outcome_name) is None:
        return _withheld_report(
            outcome=outcome_name,
            factor=activity_name,
            record_count=len(outcome_records),
            reasons=("Outcome metric units or definitions are incompatible across observations.",),
        )
    tagged_records = tuple(
        record for record in outcome_records if activity_name in record.activities
    )
    untagged_records = tuple(
        record for record in outcome_records if activity_name not in record.activities
    )
    if len(tagged_records) < min_group_size or len(untagged_records) < min_group_size:
        return _withheld_report(
            outcome=outcome_name,
            factor=activity_name,
            record_count=len(outcome_records),
            reasons=(
                f"Activity comparison requires at least {min_group_size} observations in both groups; found {len(tagged_records)} with and {len(untagged_records)} without. Missing outcomes: {missing_count}.",
            ),
        )

    tagged = tuple(record.metrics[outcome_name] for record in tagged_records)
    untagged = tuple(record.metrics[outcome_name] for record in untagged_records)
    try:
        raw_effect, standardized_effect, margin = _standardized_mean_difference(tagged, untagged)
    except ObservationError as exc:
        return _withheld_report(
            outcome=outcome_name,
            factor=activity_name,
            record_count=len(outcome_records),
            reasons=(str(exc),),
        )
    interval = (standardized_effect - margin, standardized_effect + margin)
    date_range, freshness_days = _date_quality(outcome_records, all_records=records, as_of=as_of)
    if abs(standardized_effect) < 0.2:
        return _withheld_report(
            outcome=outcome_name,
            factor=activity_name,
            record_count=len(outcome_records),
            reasons=(
                "The scale-adjusted group difference was too small to surface as a candidate pattern.",
                f"Standardized 95% uncertainty interval: {interval[0]:.3f} to {interval[1]:.3f}.",
            ),
        )

    direction = "higher" if raw_effect > 0 else "lower"
    strength = _strength(sample_count=min(len(tagged), len(untagged)), interval=interval)
    quality_notes = (
        f"Tagged observations: {len(tagged)}; untagged observations: {len(untagged)}.",
        f"Missing outcomes: {missing_count} of {len(records)}.",
        f"Evidence spans {date_range[0]} through {date_range[1]}.",
        f"Latest evidence is {freshness_days} days before the analysis reference date.",
        "Repeated days from one person are not independent population samples.",
    )
    candidate = CandidatePattern(
        status="candidate",
        outcome=outcome_name,
        factor=activity_name,
        direction=direction,
        effect=round(raw_effect, 3),
        sample_count=len(outcome_records),
        statement=(
            f"{outcome_name} averaged {abs(raw_effect):.2f} raw units {direction} on days "
            f"tagged {activity_name}; the standardized effect was {abs(standardized_effect):.2f} "
            f"and evidence strength is {strength}."
        ),
        evidence=tuple(record.path for record in (*tagged_records, *untagged_records)),
        caveats=(
            "Tagged and untagged days may differ in many other ways.",
            "This candidate association is a prompt for reflection, not a causal conclusion.",
            *_health_caveat(outcome_name, activity_name),
        ),
        raw_effect=round(raw_effect, 3),
        standardized_effect=round(standardized_effect, 3),
        uncertainty_interval=(round(interval[0], 3), round(interval[1], 3)),
        evidence_strength=strength,
        practical_magnitude=_magnitude(standardized_effect),
        missing_count=missing_count,
        date_range=date_range,
        freshness_days=freshness_days,
        quality_notes=quality_notes,
    )
    return PatternReport(outcome_name, activity_name, len(outcome_records), (candidate,), ())


def serialize_pattern_report(report: PatternReport) -> str:
    return json.dumps(asdict(report), sort_keys=True, indent=2)


def format_pattern_report(report: PatternReport) -> str:
    lines = [
        f"Candidate pattern report: {report.factor} → {report.outcome}",
        f"Observations: {report.record_count}",
        "",
    ]
    if not report.candidates:
        lines.append("No candidate pattern surfaced.")
        lines.extend(f"- Withheld: {gap}" for gap in report.gaps)
        return "\n".join(lines)
    for candidate in report.candidates:
        lines.append(f"[{candidate.status}] {candidate.statement}")
        lines.append(
            f"Raw effect: {candidate.raw_effect}; standardized effect: "
            f"{candidate.standardized_effect}; 95% interval: "
            f"{candidate.uncertainty_interval[0]} to {candidate.uncertainty_interval[1]}"
        )
        lines.append(
            f"Evidence: {candidate.evidence_strength}; samples: {candidate.sample_count}; "
            f"date range: {candidate.date_range[0]} to {candidate.date_range[1]}"
        )
        lines.extend(f"Quality: {item}" for item in candidate.quality_notes)
        lines.extend(f"Caveat: {item}" for item in candidate.caveats)
    return "\n".join(lines)
