from pathlib import Path

import pytest

import lifeos.mcp.service as service
from lifeos.config import LifeOSConfig
from lifeos.mcp.service import (
    ServiceConfigurationError,
    _parse_port,
    build_transport_security,
    main,
    service_storage_issue,
    validate_service_storage,
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
    with pytest.raises(Exception, match="between 1 and 65535"):
        _parse_port("0")
    with pytest.raises(Exception, match="between 1 and 65535"):
        _parse_port("65536")


def test_service_storage_requires_writable_proposal_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    proposals.mkdir(parents=True)
    config = LifeOSConfig(vault_root=vault, runtime_dir=vault / ".lifeos")
    real_access = service.os.access

    def fake_access(path: str | Path, mode: int) -> bool:
        if Path(path) == proposals:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(service.os, "access", fake_access)

    assert service_storage_issue(config) is not None
    with pytest.raises(ServiceConfigurationError, match="proposal directory"):
        validate_service_storage(config)


def test_service_storage_accepts_creatable_runtime_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "proposals").mkdir(parents=True)
    config = LifeOSConfig(vault_root=vault, runtime_dir=vault / ".lifeos")

    assert service_storage_issue(config) is None
    validate_service_storage(config)


def test_service_token_invalid_utf8_is_configuration_error(tmp_path: Path) -> None:
    token_file = tmp_path / "service-token"
    token_file.write_bytes(b"\xff" * 40)

    with pytest.raises(ServiceConfigurationError, match="Could not read service token file"):
        service.load_service_token({service.SERVICE_TOKEN_FILE_ENV: str(token_file)})


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
