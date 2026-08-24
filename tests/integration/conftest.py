import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _initialize_mcp_lifecycle_vault_git(request: pytest.FixtureRequest) -> None:
    """Keep the legacy MCP lifecycle vault aligned with first-party bootstrap."""
    if Path(str(request.node.path)).name != "test_mcp_ingestion_lifecycle.py":
        return
    if "vault_root" not in request.fixturenames:
        return

    vault_root = request.getfixturevalue("vault_root")
    subprocess.run(
        ["git", "init", "-q"],
        cwd=vault_root,
        check=True,
        capture_output=True,
    )
