from __future__ import annotations

import json
from queue import Queue
from threading import Condition, Event, Thread
from time import monotonic
from pathlib import Path
from typing import Any

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, StdioBridgeServer
from lifeos.captures.extraction import ExtractionCancellation
from lifeos.retrieval import CancellationToken


class _BlockingReader:
    def __init__(self) -> None:
        self._lines: Queue[str | None] = Queue()

    def send(self, request_id: str, method: str, params: object) -> None:
        self._lines.put(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            + "\n"
        )

    def close(self) -> None:
        self._lines.put(None)

    def __iter__(self) -> _BlockingReader:
        return self

    def __next__(self) -> str:
        line = self._lines.get(timeout=5)
        if line is None:
            raise StopIteration
        return line


class _FrameWriter:
    def __init__(self) -> None:
        self._condition = Condition()
        self._frames: list[dict[str, Any]] = []

    def write(self, value: str) -> int:
        frame = json.loads(value)
        with self._condition:
            self._frames.append(frame)
            self._condition.notify_all()
        return len(value)

    def flush(self) -> None:
        return None

    def wait_for_id(self, request_id: str) -> dict[str, Any]:
        deadline = monotonic() + 5
        with self._condition:
            while True:
                for frame in self._frames:
                    if frame.get("id") == request_id:
                        return frame
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise AssertionError(f"response {request_id!r} was not written")
                self._condition.wait(remaining)

    @property
    def frames(self) -> tuple[dict[str, Any], ...]:
        with self._condition:
            return tuple(self._frames)


class _Result:
    def __init__(self, **values: object) -> None:
        self._values = values

    def to_dict(self) -> dict[str, object]:
        return self._values


def _application(tmp_path: Path) -> BridgeApplication:
    vault = tmp_path / "vault"
    vault.mkdir()
    return BridgeApplication(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        actor_id="local",
    )


def _start_server(
    application: BridgeApplication,
) -> tuple[_BlockingReader, _FrameWriter, Thread]:
    reader = _BlockingReader()
    writer = _FrameWriter()
    server = StdioBridgeServer(application, reader=reader, writer=writer)  # type: ignore[arg-type]
    thread = Thread(target=server.serve, name="test-bridge-server")
    thread.start()
    return reader, writer, thread


def _blocking_rebuild(
    started: Event,
    cancellation_seen: Event,
):
    def rebuild(
        *,
        cancellation: CancellationToken | None = None,
        progress: Any = None,
        **_kwargs: object,
    ) -> _Result:
        assert cancellation is not None
        assert progress is not None
        progress({"phase": "started"})
        started.set()
        deadline = monotonic() + 5
        while not cancellation.cancelled and monotonic() < deadline:
            cancellation_seen.wait(0.01)
        assert cancellation.cancelled
        cancellation_seen.set()
        progress({"phase": "interrupted"})
        return _Result(state="interrupted")

    return rebuild


def test_transport_cancel_reaches_active_work_and_server_remains_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application(tmp_path)
    started = Event()
    cancellation_seen = Event()
    monkeypatch.setattr(
        application.knowledge.retriever.index_service,
        "rebuild",
        _blocking_rebuild(started, cancellation_seen),
    )
    reader, writer, server_thread = _start_server(application)

    reader.send("work", "retrieval.index.rebuild", {})
    assert started.wait(5)
    reader.send("cancel", "request.cancel", {"request_id": "work"})
    cancel_frame = writer.wait_for_id("cancel")
    assert cancel_frame["result"] == {
        "request_id": "work",
        "outcome": "cancellation-requested",
        "accepted": True,
    }
    assert cancellation_seen.wait(5)
    assert writer.wait_for_id("work")["result"]["state"] == "interrupted"

    reader.send("health", "system.health", {})
    assert writer.wait_for_id("health")["result"]["status"] == "healthy"
    reader.send("shutdown", "system.shutdown", {})
    assert writer.wait_for_id("shutdown")["result"] == {"accepted": True}
    server_thread.join(5)
    assert not server_thread.is_alive()

    progress = [
        frame for frame in writer.frames if frame.get("method") == "retrieval.index.progress"
    ]
    assert [frame["params"]["phase"] for frame in progress] == ["started", "interrupted"]


def test_request_cancellation_reports_before_start_repeat_completed_and_unknown(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    application.register_request("queued", "retrieval.search")

    assert application.cancel_request("queued")["outcome"] == "cancelled-before-start"
    assert application.cancel_request("queued")["outcome"] == "already-requested"
    with pytest.raises(ProtocolError) as cancelled:
        application.dispatch_registered("queued", "retrieval.search", {"query": "x"})
    assert cancelled.value.code == "request_cancelled"
    assert application.cancel_request("queued")["outcome"] == "already-completed"
    assert application.cancel_request("different-id") == {
        "request_id": "different-id",
        "outcome": "unknown-request",
        "accepted": False,
    }


def test_active_non_cancellable_request_finishes_before_it_is_reported_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application(tmp_path)
    started = Event()
    release = Event()
    original_dispatch = application.dispatch

    def blocking_dispatch(method: str, params: object) -> object:
        started.set()
        assert release.wait(5)
        return original_dispatch(method, params)

    monkeypatch.setattr(application, "dispatch", blocking_dispatch)
    application.register_request("canonical", "system.health")
    thread = Thread(
        target=application.dispatch_registered,
        args=("canonical", "system.health", {}),
    )
    thread.start()
    assert started.wait(5)
    assert application.cancel_request("canonical")["outcome"] == "not-cancellable"
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert application.cancel_request("canonical")["outcome"] == "already-completed"


def test_transport_cancel_reaches_active_capture_processing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application(tmp_path)
    started = Event()
    poll = Event()

    def run_extraction(
        job_id: str,
        *,
        cancellation: ExtractionCancellation | None = None,
        **_kwargs: object,
    ) -> _Result:
        assert job_id == "job-1"
        assert cancellation is not None
        started.set()
        deadline = monotonic() + 5
        while not cancellation.cancelled and monotonic() < deadline:
            poll.wait(0.01)
        assert cancellation.cancelled
        return _Result(
            job_id=job_id,
            state="cancelled",
            completed_attachment_ids=[],
            failed_attachment_ids=[],
        )

    monkeypatch.setattr(application.capture_processing, "run_extraction", run_extraction)
    reader, writer, server_thread = _start_server(application)

    reader.send("capture-work", "capture.enrichment.run", {"job_id": "job-1"})
    assert started.wait(5)
    reader.send("capture-cancel", "request.cancel", {"request_id": "capture-work"})
    assert writer.wait_for_id("capture-cancel")["result"]["outcome"] == ("cancellation-requested")
    assert writer.wait_for_id("capture-work")["result"]["state"] == "cancelled"
    reader.send("shutdown", "system.shutdown", {})
    assert writer.wait_for_id("shutdown")["result"] == {"accepted": True}
    server_thread.join(5)
    assert not server_thread.is_alive()


@pytest.mark.parametrize("termination", ["shutdown", "disconnect"])
def test_shutdown_and_disconnect_signal_active_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    termination: str,
) -> None:
    application = _application(tmp_path)
    started = Event()
    cancellation_seen = Event()
    monkeypatch.setattr(
        application.knowledge.retriever.index_service,
        "rebuild",
        _blocking_rebuild(started, cancellation_seen),
    )
    reader, writer, server_thread = _start_server(application)

    reader.send("work", "retrieval.index.rebuild", {})
    assert started.wait(5)
    if termination == "shutdown":
        reader.send("shutdown", "system.shutdown", {})
    else:
        reader.close()

    assert cancellation_seen.wait(5)
    assert writer.wait_for_id("work")["result"]["state"] == "interrupted"
    if termination == "shutdown":
        assert writer.wait_for_id("shutdown")["result"] == {"accepted": True}
    server_thread.join(5)
    assert not server_thread.is_alive()
    assert application._requests == {}
