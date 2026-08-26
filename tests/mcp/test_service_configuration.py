import argparse
from pathlib import Path

import pytest

from lifeos.mcp.service import (
    ServiceConfigurationError,
    _parse_port,
    build_transport_security,
    main,
)


def test_http_allowlists_reject_blank_or_untrimmed_values() -> None:
    with pytest.raises(ServiceConfigurationError, match="non-empty and trimmed"):
        build_transport_security(
            host="0.0.0.0",
            allowed_hosts=("   ",),
            allowed_origins=(),
        )
    with pytest.raises(ServiceConfigurationError, match="non-empty and trimmed"):
        build_transport_security(
            host="0.0.0.0",
            allowed_hosts=(" lifeos.example:8000",),
            allowed_origins=(),
        )


def test_port_parser_rejects_out_of_range_values() -> None:
    assert _parse_port("8000") == 8000
    with pytest.raises(argparse.ArgumentTypeError, match="between 1 and 65535"):
        _parse_port("0")
    with pytest.raises(argparse.ArgumentTypeError, match="between 1 and 65535"):
        _parse_port("65536")


def test_service_rejects_invalid_actor_without_starting_server(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = tmp_path / "lifeos.yml"
    config.write_text(
        f"vault_root: {vault}\nruntime_dir: {tmp_path / 'runtime'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LIFEOS_SERVICE_TOKEN", "x" * 32)

    result = main(["--config", str(config), "--actor-id", " bad-actor "])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "Service configuration error:" in captured.err
    assert "actor_id" in captured.err
