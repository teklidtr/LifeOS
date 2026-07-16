"""Meal and exercise capture contracts preserving uncertainty and actual outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .contracts import CaptureError, Confidence, DerivedValue, ValueSource

MealType = Literal["breakfast", "lunch", "dinner", "snack", "drink", "other", "unknown"]
WorkoutOutcome = Literal["planned", "performed", "partial", "skipped", "modified", "imported", "inferred"]


@dataclass(frozen=True, slots=True)
class FoodComponent:
    name: str
    portion: str | None = None
    preparation: str | None = None
    source: ValueSource = "user-entered"
    confidence: Confidence = "high"
    confirmed: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise CaptureError("invalid_meal", "Food component name must not be blank.")
        if self.source in {"image-estimate", "model-estimate"} and self.confirmed:
            raise CaptureError("invalid_meal", "Estimated food components must remain unconfirmed until accepted.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MealDetails:
    meal_type: MealType = "unknown"
    components: tuple[FoodComponent, ...] = ()
    context: str = ""
    hunger_before: int | None = None
    fullness_after: int | None = None
    satisfaction: int | None = None
    symptoms_or_observations: str = ""
    nutrition: tuple[DerivedValue, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (("hunger_before", self.hunger_before), ("fullness_after", self.fullness_after), ("satisfaction", self.satisfaction)):
            if value is not None and (type(value) is not int or not 0 <= value <= 10):
                raise CaptureError("invalid_meal", f"{name} must be between 0 and 10 or unknown.")
        for value in self.nutrition:
            if value.status == "confirmed" and value.source in {"image-estimate", "model-estimate"}:
                # Source is deliberately retained even when the user confirms it.
                continue

    def to_dict(self) -> dict[str, object]:
        return {
            "meal_type": self.meal_type,
            "components": [item.to_dict() for item in self.components],
            "context": self.context,
            "hunger_before": self.hunger_before,
            "fullness_after": self.fullness_after,
            "satisfaction": self.satisfaction,
            "symptoms_or_observations": self.symptoms_or_observations,
            "nutrition": [item.to_dict() for item in self.nutrition],
        }


@dataclass(frozen=True, slots=True)
class ExerciseSet:
    exercise: str
    repetitions: int | None = None
    load: float | None = None
    load_unit: str | None = None
    duration_seconds: int | None = None
    distance: float | None = None
    distance_unit: str | None = None
    perceived_exertion: int | None = None
    source: ValueSource = "user-entered"
    confirmed: bool = True

    def __post_init__(self) -> None:
        if not self.exercise.strip():
            raise CaptureError("invalid_exercise", "Exercise name must not be blank.")
        for name, value in (("repetitions", self.repetitions), ("duration_seconds", self.duration_seconds)):
            if value is not None and (type(value) is not int or value < 0):
                raise CaptureError("invalid_exercise", f"{name} must be non-negative or unknown.")
        if self.load is not None and self.load < 0:
            raise CaptureError("invalid_exercise", "load must be non-negative or unknown.")
        if self.perceived_exertion is not None and not 0 <= self.perceived_exertion <= 10:
            raise CaptureError("invalid_exercise", "perceived_exertion must be between 0 and 10.")
        if self.source in {"model-estimate", "image-estimate"} and self.confirmed:
            raise CaptureError("invalid_exercise", "Inferred exercise fields must remain unconfirmed until accepted.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExerciseDetails:
    activity_type: str
    outcome: WorkoutOutcome
    planned_source_path: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    duration_minutes: float | None = None
    distance: float | None = None
    distance_unit: str | None = None
    pace: str | None = None
    heart_rate: int | None = None
    perceived_exertion: int | None = None
    energy: int | None = None
    enjoyment: int | None = None
    pain_or_discomfort: str = ""
    deviations: str = ""
    sequence: tuple[ExerciseSet, ...] = ()

    def __post_init__(self) -> None:
        if not self.activity_type.strip():
            raise CaptureError("invalid_exercise", "activity_type must not be blank.")
        if self.outcome in {"performed", "partial", "modified"} and self.duration_minutes is not None and self.duration_minutes < 0:
            raise CaptureError("invalid_exercise", "duration_minutes must be non-negative.")
        if self.outcome == "planned" and any((self.start_at, self.end_at, self.duration_minutes, self.sequence)):
            # Planned details may exist, but they are not evidence of completion.
            pass
        for name, value in (("perceived_exertion", self.perceived_exertion), ("energy", self.energy), ("enjoyment", self.enjoyment)):
            if value is not None and (type(value) is not int or not 0 <= value <= 10):
                raise CaptureError("invalid_exercise", f"{name} must be between 0 and 10.")

    @property
    def counts_as_completed(self) -> bool:
        return self.outcome in {"performed", "partial", "modified", "imported"}

    def to_dict(self) -> dict[str, object]:
        return {
            "activity_type": self.activity_type,
            "outcome": self.outcome,
            "planned_source_path": self.planned_source_path,
            "start_at": self.start_at,
            "end_at": self.end_at,
            "duration_minutes": self.duration_minutes,
            "distance": self.distance,
            "distance_unit": self.distance_unit,
            "pace": self.pace,
            "heart_rate": self.heart_rate,
            "perceived_exertion": self.perceived_exertion,
            "energy": self.energy,
            "enjoyment": self.enjoyment,
            "pain_or_discomfort": self.pain_or_discomfort,
            "deviations": self.deviations,
            "sequence": [item.to_dict() for item in self.sequence],
            "counts_as_completed": self.counts_as_completed,
        }
