"""Authenticated Streamable HTTP service for an always-on LifeOS home node."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Protocol

from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from lifeos._secure_io import SecureIOError, open_directory_secure
from lifeos.config import ConfigError, LifeOSConfig, load_config
from lifeos.facade.authorization import (
    AuthorizationDeniedError,
    AuthorizationUnavailableError,
    AuthorizedPrincipal,
    ConsequentialAction,
    ConsequentialAuthorizationRequest,
)
from lifeos.registry import Registry
from lifeos.runtime.activity import push_activity_actor, reset_activity_actor
from lifeos.runtime.authority import RuntimeAuthorityError, RuntimeDirectoryAuthority

SERVICE_TOKEN_ENV = "LIFEOS_SERVICE_TOKEN"
SERVICE_TOKEN_FILE_ENV = "LIFEOS_SERVICE_TOKEN_FILE"
_MIN_TOKEN_LENGTH = 32
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_REMOTE_ACTOR: ContextVar[str | None] = ContextVar("lifeos_remote_actor", default=None)
logger = logging.getLogger(__name__)


class ServiceConfigurationError(RuntimeError):
    """Raised when home-node service configuration is unsafe or incomplete."""


class ReadinessProbe(Protocol):
    """Minimal readiness contract used by auth and HTTP probes."""

    def ready(self) -> bool:
        ...


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def service_storage_issue(
    config: LifeOSConfig,
    *,
    runtime_authority: RuntimeDirectoryAuthority | None = None,
) -> str | None:
    """Return a fail-closed, policy-neutral storage issue for this service process."""
    if not config.vault_root.is_dir():
        return f"canonical vault root does not exist or is not a directory: {config.vault_root}"
    if not os.access(config.vault_root, os.R_OK | os.W_OK | os.X_OK):
        return (
            "canonical vault root is not readable/writable by the service process: "
            f"{config.vault_root}"
        )

    proposals_root = config.vault_root / "proposals"
    proposals_fd = -1
    try:
        proposals_fd = open_directory_secure(proposals_root)
    except SecureIOError:
        return (
            "proposal directory does not exist, is not a directory, or is a symlink: "
            f"{proposals_root}"
        )
    finally:
        if proposals_fd != -1:
            os.close(proposals_fd)
    if not os.access(proposals_root, os.R_OK | os.W_OK | os.X_OK):
        return f"proposal directory is not readable/writable by the service process: {proposals_root}"

    runtime_dir = config.runtime_dir
    if runtime_authority is not None:
        if not runtime_authority.path_is_current():
            return (
                "runtime directory path no longer identifies the pinned service runtime: "
                f"{runtime_dir}"
            )
        if not os.access(runtime_dir, os.R_OK | os.W_OK | os.X_OK, follow_symlinks=False):
            return f"runtime directory is not readable/writable by the service process: {runtime_dir}"
        return None

    try:
        runtime_state = os.lstat(runtime_dir)
    except FileNotFoundError:
        parent = _nearest_existing_parent(runtime_dir.parent)
        if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
            return f"runtime directory cannot be created by the service process: {runtime_dir}"
    except OSError:
        return f"runtime directory cannot be inspected safely: {runtime_dir}"
    else:
        if stat.S_ISLNK(runtime_state.st_mode):
            return f"runtime directory must not be a symlink: {runtime_dir}"
        if not stat.S_ISDIR(runtime_state.st_mode):
            return f"runtime directory is not a directory: {runtime_dir}"
        if not os.access(runtime_dir, os.R_OK | os.W_OK | os.X_OK, follow_symlinks=False):
            return f"runtime directory is not readable/writable by the service process: {runtime_dir}"
    return None


def validate_service_storage(
    config: LifeOSConfig,
    *,
    runtime_authority: RuntimeDirectoryAuthority | None = None,
) -> None:
    """Require write authority needed for remote draft/submission and runtime state."""
    issue = service_storage_issue(config, runtime_authority=runtime_authority)
    if issue is not None:
        raise ServiceConfigurationError(issue)


class ServiceReadiness:
    """Report policy-neutral service storage readiness without traversing Markdown."""

    def __init__(
        self,
        config: LifeOSConfig,
        config_path: Path,
        *,
        runtime_authority: RuntimeDirectoryAuthority | None = None,
    ) -> None:
        self._config = config
        self._config_path = config_path
        self._runtime_authority = runtime_authority

    def ready(self) -> bool:
        return (
            service_storage_issue(
                self._config,
                runtime_authority=self._runtime_authority,
            )
            is None
        )


class AuthenticatedSubmitAuthorizer:
    """Allow authenticated remote proposal submission, but never remote approval/application."""

    def __init__(self, *, actor_id: str, readiness: ReadinessProbe) -> None:
        self._principal = AuthorizedPrincipal(actor_id=actor_id)
        self._readiness = readiness

    def authorize(self, request: ConsequentialAuthorizationRequest) -> AuthorizedPrincipal:
        if _REMOTE_ACTOR.get() != self._principal.actor_id:
            raise AuthorizationUnavailableError("Authenticated service request is unavailable")
        if request.action is not ConsequentialAction.SUBMIT:
            raise AuthorizationDeniedError(
                "Headless service mode does not authorize proposal approval or application"
            )
        if request.review_digest is not None:
            raise AuthorizationDeniedError("Consequential operation was not authorized")
        if not self._readiness.ready():
            raise AuthorizationUnavailableError("LifeOS service is not ready for mutation")
        return self._principal


class AuthenticatedServiceApp:
    """ASGI boundary adding bearer auth plus bounded liveness/readiness probes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        actor_id: str,
        readiness: ReadinessProbe,
    ) -> None:
        self._app = app
        self._token = token
        self._actor_id = actor_id
        self._readiness = readiness

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return

        path = str(scope.get("path", ""))
        if path == "/healthz":
            await _send_json(send, 200, {"status": "ok"})
            return

        if not _request_has_token(scope, self._token):
            await _send_json(
                send,
                401,
                {"error": "authentication-required"},
                extra_headers=((b"www-authenticate", b"Bearer"),),
            )
            return

        if path == "/readyz":
            ready = self._readiness.ready()
            await _send_json(
                send,
                200 if ready else 503,
                {"status": "ready" if ready else "blocked"},
            )
            return

        actor_token = _REMOTE_ACTOR.set(self._actor_id)
        activity_actor_token = push_activity_actor(self._actor_id)
        try:
            await self._app(scope, receive, send)
        finally:
            reset_activity_actor(activity_actor_token)
            _REMOTE_ACTOR.reset(actor_token)


def load_service_token(env: Mapping[str, str] | None = None) -> str:
    """Load one bearer secret from environment or an environment-selected secret file."""
    source = os.environ if env is None else env
    inline = source.get(SERVICE_TOKEN_ENV)
    token_file = source.get(SERVICE_TOKEN_FILE_ENV)
    if inline and token_file:
        raise ServiceConfigurationError(
            f"Set only one of {SERVICE_TOKEN_ENV} or {SERVICE_TOKEN_FILE_ENV}"
        )
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ServiceConfigurationError("Could not read service token file") from error
    elif inline:
        token = inline.strip()
    else:
        raise ServiceConfigurationError(
            f"Set {SERVICE_TOKEN_ENV} or {SERVICE_TOKEN_FILE_ENV} before starting the service"
        )

    if len(token) < _MIN_TOKEN_LENGTH:
        raise ServiceConfigurationError(
            f"Service bearer token must contain at least {_MIN_TOKEN_LENGTH} characters"
        )
    return token


def build_transport_security(
    *,
    host: str,
    allowed_hosts: Sequence[str],
    allowed_origins: Sequence[str],
) -> TransportSecuritySettings | None:
    """Keep loopback defaults safe and require an explicit Host allowlist for remote binds."""
    values = (*allowed_hosts, *allowed_origins)
    if any(not value.strip() or value != value.strip() for value in values):
        raise ServiceConfigurationError("HTTP allowlist values must be non-empty and trimmed")
    if host in _LOOPBACK_HOSTS and not allowed_hosts and not allowed_origins:
        return None
    if not allowed_hosts:
        raise ServiceConfigurationError(
            "Non-default HTTP exposure requires at least one --allowed-host value"
        )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(allowed_hosts),
        allowed_origins=list(allowed_origins),
    )


def _request_has_token(scope: Scope, expected_token: str) -> bool:
    headers = scope.get("headers", [])
    authorization: bytes | None = None
    for key, value in headers:
        if key.lower() == b"authorization":
            authorization = value
            break
    if authorization is None:
        return False
    try:
        scheme, candidate = authorization.decode("utf-8").split(" ", 1)
    except (UnicodeDecodeError, ValueError):
        return False
    return scheme.lower() == "bearer" and hmac.compare_digest(candidate, expected_token)


async def _send_json(
    send: Send,
    status: int,
    payload: Mapping[str, object],
    *,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers = (
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        *extra_headers,
    )
    await send({"type": "http.response.start", "status": status, "headers": list(headers)})
    await send({"type": "http.response.body", "body": body})


def _load_runtime_server_factory() -> Callable[..., Any]:
    from lifeos.mcp.runtime_server import create_mcp_server

    return create_mcp_server


def _run_uvicorn(app: ASGIApp, *, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lifeos serve",
        description="Run the authenticated long-lived LifeOS Streamable HTTP service.",
    )
    parser.add_argument("--config", default=Path("lifeos.yml"), type=Path)
    parser.add_argument(
        "--actor-id",
        required=True,
        help="Stable actor identity for remote proposals",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", default=8000, type=_parse_port, help="Bind port (default: 8000)")
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Allowed HTTP Host header; repeat for remote binds (for example lifeos.home.arpa:*)",
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help=(
            "Allowed Origin for MCP transport security; repeat as needed. "
            "This validates Origin but does not enable browser CORS."
        ),
    )
    args = parser.parse_args(argv)

    runtime_authority: RuntimeDirectoryAuthority | None = None
    try:
        config = load_config(args.config)
        token = load_service_token()
        transport_security = build_transport_security(
            host=args.host,
            allowed_hosts=args.allowed_host,
            allowed_origins=args.allowed_origin,
        )
        # Preserve the established CLI error precedence: malformed actor identity is rejected
        # before storage inspection or runtime-directory creation.
        preflight_readiness = ServiceReadiness(config, args.config)
        authorizer = AuthenticatedSubmitAuthorizer(
            actor_id=args.actor_id,
            readiness=preflight_readiness,
        )
        validate_service_storage(config)
        runtime_authority = RuntimeDirectoryAuthority.open(config.runtime_dir)
        if not Path(f"/proc/self/fd/{runtime_authority.fd}").exists():
            raise ServiceConfigurationError(
                "Home-node descriptor-bound registry access requires Linux /proc/self/fd"
            )
        readiness = ServiceReadiness(
            config,
            args.config,
            runtime_authority=runtime_authority,
        )
        authorizer = AuthenticatedSubmitAuthorizer(actor_id=args.actor_id, readiness=readiness)
        validate_service_storage(config, runtime_authority=runtime_authority)
    except (ConfigError, RuntimeAuthorityError, ServiceConfigurationError, ValueError) as error:
        if runtime_authority is not None:
            runtime_authority.close()
        print(f"Service configuration error: {error}", file=sys.stderr)
        return 1

    try:
        registry = Registry(
            config.runtime_dir / "registry.db",
            directory_fd=runtime_authority.fd,
        )
        create_mcp_server = _load_runtime_server_factory()
        mcp = create_mcp_server(
            vault_root=config.vault_root,
            registry=registry,
            authorizer=authorizer,
            runtime_dir=config.runtime_dir,
            runtime_dir_fd=runtime_authority.fd,
            host=args.host,
            port=args.port,
            transport_security=transport_security,
            stateless_http=True,
            json_response=True,
            excluded_core_tools=frozenset({"proposal_approve", "proposal_apply"}),
        )
        app = AuthenticatedServiceApp(
            mcp.streamable_http_app(),
            token=token,
            actor_id=args.actor_id,
            readiness=readiness,
        )
        _run_uvicorn(app, host=args.host, port=args.port)
        return 0
    finally:
        runtime_authority.close()


if __name__ == "__main__":
    raise SystemExit(main())
