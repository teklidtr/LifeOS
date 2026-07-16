"""Reference in-process client used by tests and non-Obsidian integrations."""

from __future__ import annotations

from typing import Any

from lifeos.bridge.application import BridgeApplication


class ReferenceBridgeClient:
    def __init__(self, application: BridgeApplication) -> None:
        self.application = application

    def call(self, method: str, **params: Any) -> object:
        return self.application.dispatch(method, params)
