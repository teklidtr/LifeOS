"""Newline-delimited JSON-RPC STDIO server."""

from __future__ import annotations

import json
from typing import IO, Any

from lifeos.bridge.application import BridgeApplication
from lifeos.bridge.protocol import ProtocolError, error_frame, strict_object, success_frame


class StdioBridgeServer:
    def __init__(self, application: BridgeApplication, *, reader: IO[str], writer: IO[str]) -> None:
        self.application = application
        self.reader = reader
        self.writer = writer

    def _write(self, frame: dict[str, Any]) -> None:
        self.writer.write(json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n")
        self.writer.flush()

    def serve(self) -> int:
        for line in self.reader:
            if not line.strip():
                continue
            request_id: str | int | None = None
            try:
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProtocolError("parse_error", "Malformed JSON request.") from exc
                request = strict_object(decoded, allowed={"jsonrpc", "id", "method", "params", "meta"}, required={"jsonrpc", "id", "method", "params"})
                request_id = request["id"]
                if request["jsonrpc"] != "2.0" or not isinstance(request["method"], str):
                    raise ProtocolError("invalid_request", "Invalid JSON-RPC request.")
                result = self.application.dispatch(request["method"], request["params"])
                self._write(success_frame(request_id, result))
            except ProtocolError as exc:
                self._write(error_frame(request_id, exc))
            except Exception:
                # STDIO is a long-lived request boundary. An implementation
                # failure must not terminate the child process or expose a
                # local traceback and filesystem paths to the UI.
                self._write(
                    error_frame(
                        request_id,
                        ProtocolError(
                            "internal_error",
                            "The LifeOS bridge could not complete the request.",
                        ),
                    )
                )
            if self.application.shutdown_requested:
                return 0
        return 0
