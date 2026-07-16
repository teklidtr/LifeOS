"""Stable errors for direct human interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DailyInteractionError(Exception):
    code: str
    message: str
    remediation: str
    data: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message
