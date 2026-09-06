import json
from pathlib import Path
from typing import Any

import pytest

import lifeos.mcp.__main__ as mcp_main

main = mcp_main.main


def test_mcp_package_imports_without_sdk(monkeypatch) -> None:
    # Importing lifeos.mcp should not require `mcp` extra
    import builtins

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mcp":
            raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    import sys

    if "lifeos.mcp" in sys.modules:
        del sys.modules["lifeos.mcp"]

    import lifeos.mcp  # noqa: F401


def test_entrypoint_missing_extra_writes_only_to_stderr(capsys, monkeypatch, tmp_path) -> None:
    config_file = tmp_path / "lifeos.yml"
    config_file.write_text(
        "vault_root: .\nruntime_dir: .\nfeatures:\n  graphify: true\n  exports: false\n"
    )

    import builtins

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        # When _load_server_factory imports the composed runtime, mock mcp not found.
        if name == "lifeos.mcp.runtime_server":
            raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = main(["--actor-id", "test-actor", "--config", str(config_file)])

    assert result == 1
    out, err = capsys.readouterr()
    assert not out
    assert "requires the optional 'mcp' dependency group." in err


def test_entrypoint_unrelated_missing_module_propagates(capsys, monkeypatch, tmp_path) -> None:
    config_file = tmp_path / "lifeos.yml"
    config_file.write_text(
        "vault_root: .\nruntime_dir: .\nfeatures:\n  graphify: true\n  exports: false\n"
    )

    import builtins

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "lifeos.mcp.runtime_server":
            raise ModuleNotFoundError("No module named 'random_pkg'", name="random_pkg")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        main(["--actor-id", "test-actor", "--config", str(config_file)])

    assert exc_info.value.name == "random_pkg"


def test_stdio_output_contains_only_protocol_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config_file = tmp_path / "lifeos.yml"
    config_file.write_text(
        f"vault_root: {vault}\nruntime_dir: {tmp_path / '.lifeos'}\n",
        encoding="utf-8",
    )
    protocol_message = {"jsonrpc": "2.0", "id": 1, "result": {}}

    class FakeMCP:
        def run(self, *, transport: str) -> None:
            assert transport == "stdio"
            print(json.dumps(protocol_message, sort_keys=True))

    def create_server(**_kwargs: Any) -> FakeMCP:
        return FakeMCP()

    monkeypatch.setattr(mcp_main, "_load_server_factory", lambda: create_server)

    result = main(["--actor-id", "test-actor", "--config", str(config_file)])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out == json.dumps(protocol_message, sort_keys=True) + "\n"


def test_stdio_entrypoint_remains_transport_isolated() -> None:
    source = Path("src/lifeos/mcp/__main__.py").read_text(encoding="utf-8")

    forbidden = {
        "streamable-http",
        "streamable_http",
        "sse_app",
        "Starlette",
        "Uvicorn",
        "uvicorn",
        "httpx",
    }

    assert all(symbol not in source for symbol in forbidden)
    assert 'mcp.run(transport="stdio")' in source
