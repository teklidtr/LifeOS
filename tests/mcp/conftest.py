from pathlib import Path

import pytest

import lifeos.mcp.server as server_module
from lifeos.facade.registry_tools import RegistryRefreshResult


@pytest.fixture(autouse=True)
def _isolate_registry_refresh_in_server_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Keep legacy server delegation tests focused on their mocked facade boundary."""
    if Path(str(request.node.path)).name != "test_server.py":
        return

    monkeypatch.setattr(
        server_module,
        "refresh_registry",
        lambda **_kwargs: RegistryRefreshResult(
            new=(),
            modified=(),
            unchanged=(),
            deleted=(),
            proposals_indexed=0,
        ),
    )
