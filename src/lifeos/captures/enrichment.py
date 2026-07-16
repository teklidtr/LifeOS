"""Optional provider-neutral capture enrichment and deterministic no-provider fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol, runtime_checkable

from .artifact import CaptureArtifactService, utc_now
from .contracts import CaptureArtifact, CaptureError, DerivedValue
from .domains import ExerciseDetails, ExerciseSet, FoodComponent, MealDetails
from .safety import CaptureSafetyMessage, evaluate_capture_safety


@dataclass(frozen=True, slots=True)
class EnrichmentCapabilities:
    adapter_key: str
    model_key: str
    local_only: bool
    supports_images: bool = False
    supports_ocr: bool = False
    supports_transcription: bool = False
    max_characters: int = 12_000
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class EnrichmentRequest:
    capture_id: str
    capture_type: str
    user_text: str
    attachment_ids: tuple[str, ...]
    requested_operations: tuple[str, ...]
    redacted: bool = False


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    suggestions: tuple[DerivedValue, ...] = ()
    meal: MealDetails | None = None
    exercise: ExerciseDetails | None = None
    tags: tuple[str, ...] = ()
    explanation: str = ""
    safety_messages: tuple[CaptureSafetyMessage, ...] = ()
    provider_used: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "suggestions": [item.to_dict() for item in self.suggestions],
            "meal": self.meal.to_dict() if self.meal else None,
            "exercise": self.exercise.to_dict() if self.exercise else None,
            "tags": list(self.tags),
            "explanation": self.explanation,
            "safety_messages": [item.to_dict() for item in self.safety_messages],
            "provider_used": self.provider_used,
        }


@runtime_checkable
class CaptureEnrichmentProvider(Protocol):
    @property
    def capabilities(self) -> EnrichmentCapabilities: ...

    def enrich(
        self, request: EnrichmentRequest, *, timeout_seconds: float | None
    ) -> EnrichmentResult: ...


class DeterministicCaptureEnricher:
    """Small parser that is useful without any model and never invents nutrition."""

    _DURATION = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:min|mins|minutes)\b", re.I)
    _DISTANCE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(km|kilometers?|mi|miles?)\b", re.I)

    def enrich(self, request: EnrichmentRequest) -> EnrichmentResult:
        safety = (
            evaluate_capture_safety(
                "meal" if request.capture_type == "meal" else "exercise", request.user_text
            )
            if request.capture_type in {"meal", "exercise"}
            else ()
        )
        if any(item.stop_enrichment for item in safety):
            return EnrichmentResult(
                explanation="Normal enrichment stopped because an urgent safety message was triggered.",
                safety_messages=safety,
            )
        text = request.user_text.strip()
        if request.capture_type == "meal":
            component = FoodComponent(text, source="user-entered", confirmed=True) if text else None
            return EnrichmentResult(
                meal=MealDetails(components=(component,) if component else ()),
                explanation="Saved user text locally. Nutrition remains unknown unless entered or explicitly estimated.",
                safety_messages=safety,
            )
        if request.capture_type == "exercise":
            duration = self._DURATION.search(text)
            distance = self._DISTANCE.search(text)
            exercise = ExerciseDetails(
                activity_type=self._activity(text),
                outcome="performed",
                duration_minutes=float(duration.group(1)) if duration else None,
                distance=float(distance.group(1)) if distance else None,
                distance_unit=distance.group(2).lower() if distance else None,
                sequence=(ExerciseSet(self._activity(text), source="user-entered", confirmed=True),)
                if text
                else (),
            )
            return EnrichmentResult(
                exercise=exercise,
                explanation="Parsed only explicit duration, distance, and activity words from the user text.",
                safety_messages=safety,
            )
        return EnrichmentResult(
            explanation="No model is configured. The attachment remains preserved and linkable."
        )

    @staticmethod
    def _activity(text: str) -> str:
        normalized = text.casefold()
        for activity in (
            "running",
            "run",
            "walking",
            "walk",
            "cycling",
            "mobility",
            "boxing",
            "kickboxing",
            "muay thai",
            "squat",
            "deadlift",
            "bench press",
        ):
            if activity in normalized:
                return activity
        return "unstructured activity"


class CaptureEnrichmentService:
    def __init__(
        self, *, captures: CaptureArtifactService, provider: CaptureEnrichmentProvider | None = None
    ) -> None:
        self.captures = captures
        self.provider = provider
        self.fallback = DeterministicCaptureEnricher()

    def preview(
        self,
        artifact: CaptureArtifact,
        *,
        operations: tuple[str, ...] = ("classify", "parse"),
        timeout_seconds: float | None = None,
        allow_external: bool = False,
    ) -> EnrichmentResult:
        request = EnrichmentRequest(
            artifact.metadata.capture_id,
            artifact.metadata.capture_type,
            artifact.metadata.description,
            tuple(item.attachment_id for item in artifact.metadata.attachments),
            operations,
        )
        if self.provider is None:
            return self.fallback.enrich(request)
        capabilities = self.provider.capabilities
        if (
            not capabilities.local_only
            and (artifact.metadata.privacy_scope == "protected" or artifact.metadata.sensitive)
            and not allow_external
        ):
            raise CaptureError(
                "sensitive_content_blocked",
                "Protected or sensitive captures require explicit external-processing intent.",
            )
        if len(request.user_text) > capabilities.max_characters:
            request = replace(request, user_text=request.user_text[: capabilities.max_characters])
        try:
            result = self.provider.enrich(request, timeout_seconds=timeout_seconds)
        except TimeoutError:
            return replace(
                self.fallback.enrich(request),
                explanation="Provider timed out; deterministic local fallback was used.",
            )
        except Exception as exc:
            return replace(
                self.fallback.enrich(request),
                explanation=f"Provider output was unavailable ({type(exc).__name__}); deterministic local fallback was used.",
            )
        if not isinstance(result, EnrichmentResult):
            raise CaptureError(
                "malformed_provider_output",
                "Capture enrichment provider returned an invalid result.",
            )
        return replace(result, provider_used=True)

    def apply(
        self,
        path: str,
        result: EnrichmentResult,
        *,
        expected_hash: str,
        now: datetime | None = None,
    ) -> CaptureArtifact:
        artifact = self.captures.load(path)
        if artifact.content_hash != expected_hash:
            raise CaptureError("stale_capture", "Capture changed before enrichment was applied.")
        domain_data: dict[str, object] = dict(artifact.metadata.domain_data)
        if result.meal is not None:
            if artifact.metadata.capture_type != "meal":
                raise CaptureError(
                    "capture_type_mismatch",
                    "Meal enrichment cannot be applied to this capture type.",
                )
            domain_data["meal"] = result.meal.to_dict()
        if result.exercise is not None:
            if artifact.metadata.capture_type != "exercise":
                raise CaptureError(
                    "capture_type_mismatch",
                    "Exercise enrichment cannot be applied to this capture type.",
                )
            domain_data["exercise"] = result.exercise.to_dict()
        metadata = replace(
            artifact.metadata,
            domain_data=domain_data,
            derived_values=(*artifact.metadata.derived_values, *result.suggestions),
            tags=tuple(dict.fromkeys((*artifact.metadata.tags, *result.tags))),
            enrichment_status="completed" if not result.safety_messages else "needs-review",
            updated_at=utc_now(now).isoformat(),
        )
        return self.captures.save(artifact, metadata, expected_hash=expected_hash)

    def decide_value(
        self,
        path: str,
        field_name: str,
        decision: str,
        *,
        expected_hash: str,
        corrected_value: object | None = None,
        now: datetime | None = None,
    ) -> CaptureArtifact:
        artifact = self.captures.load(path)
        if artifact.content_hash != expected_hash:
            raise CaptureError("stale_capture", "Capture changed before the suggestion decision.")
        found = False
        values = []
        for item in artifact.metadata.derived_values:
            if item.field_name != field_name:
                values.append(item)
                continue
            found = True
            if decision == "confirm":
                values.append(replace(item, status="confirmed"))
            elif decision == "reject":
                values.append(replace(item, status="rejected"))
            elif decision == "correct":
                values.append(replace(item, value=corrected_value, status="corrected"))
            else:
                raise CaptureError(
                    "invalid_decision", "Decision must be confirm, reject, or correct."
                )
        if not found:
            raise CaptureError("field_not_found", "Suggested field was not found.")
        return self.captures.save(
            artifact,
            replace(
                artifact.metadata, derived_values=tuple(values), updated_at=utc_now(now).isoformat()
            ),
            expected_hash=expected_hash,
        )
