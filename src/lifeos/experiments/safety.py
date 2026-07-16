"""Deterministic, visible safety boundaries for personal experiments."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ExperimentProtocol, SafetyClassification

_EMERGENCY = (
    "chest pain", "cannot breathe", "can't breathe", "severe bleeding", "suicidal", "kill myself",
    "loss of consciousness", "fainting repeatedly", "stroke symptoms",
)
_BLOCKED: dict[str, tuple[str, ...]] = {
    "prescription-medication": ("prescription", "dose", "taper", "stop medication", "start medication", "combine medication"),
    "dangerous-restriction": ("starve", "fast for days", "no water", "dehydrate", "extreme calorie", "purge"),
    "sleep-deprivation": ("sleep deprivation", "stay awake", "all-nighter every", "sleep less than 4"),
    "substance-misuse": ("overdose", "binge drinking", "illegal drug", "recreational drug experiment"),
    "self-harm": ("self harm", "self-harm", "cut myself"),
    "pregnancy": ("pregnant", "pregnancy"),
    "eating-disorder": ("anorexia", "bulimia", "eating disorder"),
    "dangerous-target": ("dangerously low blood pressure", "extreme heart rate", "overtraining", "train through injury"),
    "severe-symptoms": ("severe symptom", "severe pain", "blood in stool", "unexplained weight loss"),
    "illegal-activity": ("illegal activity",),
}
_CAUTION = ("supplement", "pain", "dizziness", "dietary restriction", "high intensity", "medical")


@dataclass(frozen=True, slots=True)
class ImmediateSafetyMessage:
    title: str
    message: str
    continue_workflow: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"title": self.title, "message": self.message, "continue_workflow": self.continue_workflow}


def classify_safety(protocol: ExperimentProtocol) -> SafetyClassification:
    text = " ".join(
        (
            protocol.question,
            protocol.hypothesis,
            protocol.intervention,
            protocol.rationale,
            *protocol.risks,
            *protocol.stop_rules,
        )
    ).casefold()
    emergency_codes = tuple(keyword for keyword in _EMERGENCY if keyword in text)
    if emergency_codes:
        return SafetyClassification(
            "emergency", ("emergency-or-severe-symptom",),
            "The description may involve an emergency or severe symptom. The experiment workflow must stop and immediate professional or emergency help should be considered.", True,
        )
    blocked = tuple(code for code, keywords in _BLOCKED.items() if any(keyword in text for keyword in keywords))
    if blocked:
        return SafetyClassification(
            "informational-only" if blocked == ("pregnancy",) else "blocked",
            blocked,
            "This topic is outside safe self-experiment scheduling. Keep only an informational planning note and seek appropriate professional guidance.",
            True,
        )
    if any(keyword in text for keyword in _CAUTION):
        return SafetyClassification(
            "caution", ("extra-care",),
            "The protocol may involve health or physical risk. Use conservative stop rules and consider professional guidance.", True,
        )
    return SafetyClassification()


def immediate_message(classification: SafetyClassification) -> ImmediateSafetyMessage | None:
    if classification.level != "emergency":
        return None
    return ImmediateSafetyMessage(
        "Stop the experiment workflow",
        "This description may involve an emergency or severe symptom. Contact local emergency services or an appropriate healthcare professional now rather than continuing the experiment.",
    )
