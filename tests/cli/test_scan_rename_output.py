import json
from pathlib import Path
from types import SimpleNamespace

import lifeos.cli as cli_module
import lifeos.facade.registry_tools as registry_tools
from lifeos.facade.registry_tools import RegistryRefreshResult


def _result() -> RegistryRefreshResult:
    return RegistryRefreshResult(
        new=(),
        modified=(),
        unchanged=(),
        deleted=(),
        proposals_indexed=0,
        renamed=(("wiki/old.md", "wiki/new.md"),),
    )


def _configure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "load_config",
        lambda _path: SimpleNamespace(
            vault_root=tmp_path / "vault",
            runtime_dir=tmp_path / "runtime",
        ),
    )
    monkeypatch.setattr(registry_tools, "refresh_registry", lambda **_kwargs: _result())


def test_scan_json_exposes_pure_rename(tmp_path: Path, monkeypatch, capsys) -> None:
    _configure(tmp_path, monkeypatch)

    assert cli_module.main(["scan", "--config", str(tmp_path / "lifeos.yml"), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["new"] == []
    assert payload["deleted"] == []
    assert payload["renamed"] == [
        {"from_path": "wiki/old.md", "to_path": "wiki/new.md"}
    ]


def test_scan_text_exposes_pure_rename(tmp_path: Path, monkeypatch, capsys) -> None:
    _configure(tmp_path, monkeypatch)

    assert cli_module.main(["scan", "--config", str(tmp_path / "lifeos.yml")]) == 0

    output = capsys.readouterr().out
    assert "Renamed: wiki/old.md -> wiki/new.md" in output
