"""Newline-delimited JSON-RPC STDIO server."""

from __future__ import annotations

from dataclasses import dataclass
import json
from queue import Queue
from threading import Lock, Thread
from typing import IO, Any

from lifeos.bridge.application import BridgeApplication
from lifeos.bridge.protocol import ProtocolError, error_frame, strict_object, success_frame

RequestId = str | int | None


@dataclass(frozen=True, slots=True)
class _QueuedRequest:
    request_id: RequestId
    method: str
    params: object


class StdioBridgeServer:
    def __init__(self, application: BridgeApplication, *, reader: IO[str], writer: IO[str]) -> None:
        self.application = application
        self.reader = reader
        self.writer = writer
        self._writer_lock = Lock()
        self.application.set_notification_sink(self._write)

    def _write(self, frame: dict[str, Any]) -> None:
        with self._writer_lock:
            self.writer.write(json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n")
            self.writer.flush()

    def _dispatch_queued(self, pending: Queue[_QueuedRequest | None]) -> None:
        while True:
            request = pending.get()
            try:
                if request is None:
                    return
                try:
                    result = self.application.dispatch_registered(
                        request.request_id,
                        request.method,
                        request.params,
                    )
                    self._write(success_frame(request.request_id, result))
                except ProtocolError as exc:
                    self._write(error_frame(request.request_id, exc))
                except Exception:
                    self._write(
                        error_frame(
                            request.request_id,
                            ProtocolError(
                                "internal_error",
                                "The LifeOS bridge could not complete the request.",
                            ),
                        )
                    )
            finally:
                pending.task_done()

    def _handle_control_request(
        self,
        request_id: RequestId,
        method: str,
        params: object,
    ) -> bool:
        if method != "request.cancel":
            return False
        try:
            result = self.application.dispatch(method, params)
            self._write(success_frame(request_id, result))
        except ProtocolError as exc:
            self._write(error_frame(request_id, exc))
        except Exception:
            self._write(
                error_frame(
                    request_id,
                    ProtocolError(
                        "internal_error",
                        "The LifeOS bridge could not complete the request.",
                    ),
                )
            )
        return True

    def serve(self) -> int:
        pending: Queue[_QueuedRequest | None] = Queue()
        worker = Thread(
            target=self._dispatch_queued,
            args=(pending,),
            name="lifeos-bridge-worker",
        )
        worker.start()
        explicit_shutdown = False
        try:
            for line in self.reader:
                if not line.strip():
                    continue
                request_id: RequestId = None
                try:
                    try:
                        decoded = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ProtocolError("parse_error", "Malformed JSON request.") from exc
                    request = strict_object(
                        decoded,
                        allowed={"jsonrpc", "id", "method", "params", "meta"},
                        required={"jsonrpc", "id", "method", "params"},
                    )
                    request_id = request["id"]
                    method = request["method"]
                    if request["jsonrpc"] != "2.0" or not isinstance(method, str):
                        raise ProtocolError("invalid_request", "Invalid JSON-RPC request.")
                    if self._handle_control_request(request_id, method, request["params"]):
                        continue
                    if method == "system.shutdown":
                        self.application.signal_shutdown()
                        explicit_shutdown = True
                    self.application.register_request(request_id, method)
                    pending.put(_QueuedRequest(request_id, method, request["params"]))
                    if explicit_shutdown:
                        break
                except ProtocolError as exc:
                    self._write(error_frame(request_id, exc))
                except Exception:
                    self._write(
                        error_frame(
                            request_id,
                            ProtocolError(
                                "internal_error",
                                "The LifeOS bridge could not complete the request.",
                            ),
                        )
                    )
        finally:
            if not explicit_shutdown:
                self.application.signal_disconnect()
            pending.put(None)
            worker.join()
        return 0
