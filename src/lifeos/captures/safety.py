"""Conservative safety messages for meal and exercise capture text."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

SafetyDomain = Literal["meal", "exercise"]
SafetyLevel = Literal["ordinary", "caution", "urgent"]


@dataclass(frozen=True, slots=True)
class CaptureSafetyMessage:
    domain: SafetyDomain
    level: SafetyLevel
    code: str
    message: str
    stop_enrichment: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_MEAL_URGENT = (
    "difficulty breathing",
    "can't breathe",
    "cannot breathe",
    "throat closing",
    "swollen tongue",
    "fainted",
    "severe dehydration",
    "bloody vomit",
    "vomiting blood",
)
_MEAL_CAUTION = ("possible allerg", "food poisoning", "persistent vomiting", "severe diarrhea")
_EXERCISE_URGENT = (
    "chest pain",
    "fainted",
    "fainting",
    "can't breathe",
    "cannot breathe",
    "severe shortness of breath",
    "sudden weakness",
    "loss of feeling",
    "severe injury",
)
_EXERCISE_CAUTION = (
    "sharp pain",
    "severe pain",
    "numbness",
    "tingling",
    "dizziness",
    "joint gave way",
)


def evaluate_capture_safety(domain: SafetyDomain, text: str) -> tuple[CaptureSafetyMessage, ...]:
    normalized = text.casefold()
    urgent = _MEAL_URGENT if domain == "meal" else _EXERCISE_URGENT
    caution = _MEAL_CAUTION if domain == "meal" else _EXERCISE_CAUTION
    if any(term in normalized for term in urgent):
        message = (
            "This entry describes symptoms that may need urgent medical attention. Stop normal enrichment and seek immediate local emergency help."
            if domain == "meal"
            else "This entry describes a potentially dangerous exercise symptom. Stop activity and seek immediate local emergency help."
        )
        return (CaptureSafetyMessage(domain, "urgent", f"{domain}_urgent_symptoms", message, True),)
    if any(term in normalized for term in caution):
        message = (
            "The entry may describe an allergy, poisoning, or dehydration concern. Automated food recognition cannot confirm safety; consider prompt professional advice."
            if domain == "meal"
            else "The entry describes pain or neurological symptoms. Do not train through severe or worsening symptoms; consider professional assessment."
        )
        return (
            CaptureSafetyMessage(domain, "caution", f"{domain}_caution_symptoms", message, False),
        )
    return ()
