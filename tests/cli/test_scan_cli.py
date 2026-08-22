import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lifeos.cli import main
from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.registry_tools import RegistryRefreshResult


def result() -> RegistryRefreshResult:
    return RegistryRefreshResult(
        new=("study/ehliyet/example.md",),
        modified=(),
        unchanged=("wiki/example.md",),
        deleted=("study/example.md",),
        proposals_indexed=2,
    )


@patch("lifeos.facade.registry_tools.refresh_registry")
@patch("lifeos.cli.Registry")
@patch("lifeos.cli.load_config")
def test_scan_delegates_to_shared_facade_and_prints_summary(
    mock_load_config: MagicMock,
    mock_registry_type: MagicMock,
    mock_refresh: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = SimpleNamespace(vault_root=Path("/vault"), runtime_dir=Path("/runtime"))
    registry = MagicMock()
    mock_load_config.return_value = config
    mock_registry_type.return_value = registry
    mock_refresh.return_value = result()

    assert main(["scan", "--config", "custom.yml"]) == 0

    mock_load_config.assert_called_once_with(Path("custom.yml"))
    mock_registry_type.assert_called_once_with(Path("/runtime/registry.db"))
    mock_refresh.assert_called_once_with(vault_root=Path("/vault"), registry=registry)
    captured = capsys.readouterr()
    assert "1 new, 0 modified, 1 unchanged, 1 deleted" in captured.out
    assert "New: study/ehliyet/example.md" in captured.out
    assert "Deleted: study/example.md" in captured.out
    assert captured.err == ""


@patch("lifeos.facade.registry_tools.refresh_registry", return_value=result())
@patch("lifeos.cli.Registry")
@patch("lifeos.cli.load_config")
def test_scan_json_output_is_structured(
    mock_load_config: MagicMock,
    _mock_registry_type: MagicMock,
    _mock_refresh: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_load_config.return_value = SimpleNamespace(
        vault_root=Path("/vault"), runtime_dir=Path("/runtime")
    )

    assert main(["scan", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "deleted": ["study/example.md"],
        "modified": [],
        "new": ["study/ehliyet/example.md"],
        "proposals_indexed": 2,
        "unchanged": ["wiki/example.md"],
    }


@patch(
    "lifeos.facade.registry_tools.refresh_registry",
    side_effect=ToolExecutionError("Could not refresh the disposable registry"),
)
@patch("lifeos.cli.Registry")
@patch("lifeos.cli.load_config")
def test_scan_failure_returns_nonzero_without_traceback(
    mock_load_config: MagicMock,
    _mock_registry_type: MagicMock,
    _mock_refresh: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_load_config.return_value = SimpleNamespace(
        vault_root=Path("/vault"), runtime_dir=Path("/runtime")
    )

    assert main(["scan"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Scan error: Could not refresh the disposable registry\n"
