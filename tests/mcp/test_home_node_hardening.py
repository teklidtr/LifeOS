from pathlib import Path

from lifeos.config import LifeOSConfig
from lifeos.mcp.service import ServiceReadiness, service_storage_issue


def test_service_storage_rejects_symlinked_proposal_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "proposals").symlink_to(outside, target_is_directory=True)
    config = LifeOSConfig(vault_root=vault, runtime_dir=vault / ".lifeos")

    issue = service_storage_issue(config)

    assert issue is not None
    assert "proposal directory" in issue
    assert "symlink" in issue


def test_service_readiness_does_not_depend_on_markdown_identity_scan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "proposals").mkdir(parents=True)
    protected = vault / "journal" / "private"
    protected.mkdir(parents=True)
    duplicate = "---\nid: duplicate-private-id\n---\nsecret\n"
    (protected / "one.md").write_text(duplicate, encoding="utf-8")
    (protected / "two.md").write_text(duplicate, encoding="utf-8")
    config_path = vault / "lifeos.yml"
    config = LifeOSConfig(vault_root=vault, runtime_dir=vault / ".lifeos")

    assert ServiceReadiness(config, config_path).ready()
