import asyncio
from pathlib import Path
from typing import Any

import pytest

from lifeos.facade.authorization import (
    AuthorizationDeniedError,
    AuthorizationUnavailableError,
    ConsequentialAction,
    ConsequentialAuthorizationRequest,
)
from lifeos.mcp.service import (
    MAX_MCP_REQUEST_BYTES,
    AuthenticatedServiceApp,
    AuthenticatedSubmitAuthorizer,
    ServiceConfigurationError,
    build_transport_security,
    load_service_token,
)


class FakeReadiness:
    def __init__(self, ready: bool = True) -> None:
        self.value = ready

    def ready(self) -> bool:
        return self.value


def _request(
    action: ConsequentialAction,
    review_digest: str | None = None,
) -> ConsequentialAuthorizationRequest:
    return ConsequentialAuthorizationRequest(
        action=action,
        proposal_id="prop-20260826T120000Z-abcdef12",
        review_digest=review_digest,
    )


def _http_scope(*, path: str = "/mcp", token: str | None = None) -> dict[str, Any]:
    headers: list[tuple[bytes, bytes]] = [(b"host", b"localhost")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }


def test_service_token_requires_exactly_one_secret_source(tmp_path: Path) -> None:
    token = "a" * 32
    secret_file = tmp_path / "token"
    secret_file.write_text(token, encoding="utf-8")

    assert load_service_token({"LIFEOS_SERVICE_TOKEN": token}) == token
    assert load_service_token({"LIFEOS_SERVICE_TOKEN_FILE": str(secret_file)}) == token

    with pytest.raises(ServiceConfigurationError, match="Set only one"):
        load_service_token(
            {
                "LIFEOS_SERVICE_TOKEN": token,
                "LIFEOS_SERVICE_TOKEN_FILE": str(secret_file),
            }
        )
    with pytest.raises(ServiceConfigurationError, match="at least 32"):
        load_service_token({"LIFEOS_SERVICE_TOKEN": "too-short"})


def test_non_loopback_bind_requires_allowed_host() -> None:
    with pytest.raises(ServiceConfigurationError, match="--allowed-host"):
        build_transport_security(host="0.0.0.0", allowed_hosts=(), allowed_origins=())

    settings = build_transport_security(
        host="0.0.0.0",
        allowed_hosts=("lifeos.home.arpa:*",),
        allowed_origins=(),
    )
    assert settings is not None
    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == ["lifeos.home.arpa:*"]


def test_loopback_bind_keeps_sdk_safe_default() -> None:
    assert build_transport_security(
        host="127.0.0.1", allowed_hosts=(), allowed_origins=()
    ) is None


def test_headless_authorizer_requires_authenticated_request_context() -> None:
    authorizer = AuthenticatedSubmitAuthorizer(
        actor_id="remote-user",
        readiness=FakeReadiness(),
    )
    with pytest.raises(AuthorizationUnavailableError, match="Authenticated service request"):
        authorizer.authorize(_request(ConsequentialAction.SUBMIT))


def test_authenticated_request_can_submit_but_not_approve() -> None:
    token = "t" * 32
    readiness = FakeReadiness()
    authorizer = AuthenticatedSubmitAuthorizer(
        actor_id="remote-user",
        readiness=readiness,
    )
    observed: list[str] = []

    async def downstream(scope, receive, send) -> None:
        principal = authorizer.authorize(_request(ConsequentialAction.SUBMIT))
        observed.append(principal.actor_id)
        with pytest.raises(AuthorizationDeniedError, match="does not authorize"):
            authorizer.authorize(_request(ConsequentialAction.APPROVE, "sha256:digest"))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AuthenticatedServiceApp(
        downstream,
        token=token,
        actor_id="remote-user",
        readiness=readiness,
    )
    events: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event: dict[str, Any]) -> None:
        events.append(event)

    asyncio.run(app(_http_scope(token=token), receive, send))

    assert observed == ["remote-user"]
    assert events[0]["status"] == 200


def test_authenticated_request_rejects_declared_oversize_before_dispatch() -> None:
    token = "t" * 32
    called = False
    receive_called = False

    async def downstream(scope, receive, send) -> None:
        nonlocal called
        called = True

    app = AuthenticatedServiceApp(
        downstream,
        token=token,
        actor_id="remote-user",
        readiness=FakeReadiness(),
    )
    scope = _http_scope(token=token)
    scope["headers"].append(
        (b"content-length", str(MAX_MCP_REQUEST_BYTES + 1).encode("ascii"))
    )
    events: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal receive_called
        receive_called = True
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(event: dict[str, Any]) -> None:
        events.append(event)

    asyncio.run(app(scope, receive, send))

    assert called is False
    assert receive_called is False
    assert events[0]["status"] == 413


def test_authenticated_request_rejects_chunked_oversize_before_dispatch() -> None:
    token = "t" * 32
    called = False
    chunks = [
        {
            "type": "http.request",
            "body": b"x" * MAX_MCP_REQUEST_BYTES,
            "more_body": True,
        },
        {"type": "http.request", "body": b"y", "more_body": False},
    ]

    async def downstream(scope, receive, send) -> None:
        nonlocal called
        called = True

    app = AuthenticatedServiceApp(
        downstream,
        token=token,
        actor_id="remote-user",
        readiness=FakeReadiness(),
    )
    events: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return chunks.pop(0)

    async def send(event: dict[str, Any]) -> None:
        events.append(event)

    asyncio.run(app(_http_scope(token=token), receive, send))

    assert called is False
    assert events[0]["status"] == 413


def test_authenticated_request_replays_bounded_body_to_mcp_app() -> None:
    token = "t" * 32
    payload = b'{"jsonrpc":"2.0","method":"tools/list"}'
    chunks = [
        {"type": "http.request", "body": payload[:10], "more_body": True},
        {"type": "http.request", "body": payload[10:], "more_body": False},
    ]
    observed: list[bytes] = []

    async def downstream(scope, receive, send) -> None:
        event = await receive()
        observed.append(event["body"])
        assert event["more_body"] is False
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AuthenticatedServiceApp(
        downstream,
        token=token,
        actor_id="remote-user",
        readiness=FakeReadiness(),
    )
    events: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return chunks.pop(0)

    async def send(event: dict[str, Any]) -> None:
        events.append(event)

    asyncio.run(app(_http_scope(token=token), receive, send))

    assert observed == [payload]
    assert events[0]["status"] == 200


def test_unauthenticated_request_is_rejected_before_mcp_app() -> None:
    called = False

    async def downstream(scope, receive, send) -> None:
        nonlocal called
        called = True

    app = AuthenticatedServiceApp(
        downstream,
        token="t" * 32,
        actor_id="remote-user",
        readiness=FakeReadiness(),
    )
    events: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event: dict[str, Any]) -> None:
        events.append(event)

    asyncio.run(app(_http_scope(), receive, send))

    assert called is False
    assert events[0]["status"] == 401
    assert (b"www-authenticate", b"Bearer") in events[0]["headers"]


def test_health_is_public_but_readiness_requires_authentication() -> None:
    async def downstream(scope, receive, send) -> None:
        raise AssertionError("probe should not reach MCP app")

    token = "t" * 32
    readiness = FakeReadiness(ready=False)
    app = AuthenticatedServiceApp(
        downstream,
        token=token,
        actor_id="remote-user",
        readiness=readiness,
    )

    async def run_probe(path: str, bearer: str | None = None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(event: dict[str, Any]) -> None:
            events.append(event)

        await app(_http_scope(path=path, token=bearer), receive, send)
        return events

    assert asyncio.run(run_probe("/healthz"))[0]["status"] == 200
    assert asyncio.run(run_probe("/readyz"))[0]["status"] == 401
    assert asyncio.run(run_probe("/readyz", token))[0]["status"] == 503


def test_readiness_blocks_authenticated_submission() -> None:
    token = "t" * 32
    readiness = FakeReadiness(ready=False)
    authorizer = AuthenticatedSubmitAuthorizer(
        actor_id="remote-user",
        readiness=readiness,
    )

    async def downstream(scope, receive, send) -> None:
        with pytest.raises(AuthorizationUnavailableError, match="not ready"):
            authorizer.authorize(_request(ConsequentialAction.SUBMIT))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AuthenticatedServiceApp(
        downstream,
        token=token,
        actor_id="remote-user",
        readiness=readiness,
    )

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event: dict[str, Any]) -> None:
        pass

    asyncio.run(app(_http_scope(token=token), receive, send))
