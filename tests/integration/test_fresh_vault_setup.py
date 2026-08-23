from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from lifeos.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
MANUAL = REPO_ROOT / "docs/user-manual/04-setup-and-installation.md"

VAULT_ROOTS = (
    "journal",
    "raw",
    "study",
    "wiki",
    "flashcards",
    "patterns",
    "profile",
    "goals",
    "plans",
    "experiments",
    "metrics",
    "reviews",
    "proposals",
    "system",
)


def _bootstrap_vault(root: Path) -> None:
    root.mkdir()
    for name in VAULT_ROOTS:
        (root / name).mkdir()
    (root / ".gitignore").write_text(
        ".lifeos/\n.obsidian/workspace*.json\n.DS_Store\n", encoding="utf-8"
    )
    (root / "AGENTS.md").write_text(
        "# LifeOS Vault Agent Bootstrap\n\n"
        "This directory is a LifeOS vault, not the LifeOS application source repository.\n\n"
        "Use the configured LifeOS MCP server for canonical search, context, proposals, and "
        "consequential mutations. Obtain universal runtime policy from the MCP server and "
        "vault-specific instructions through LifeOS. Folder names provide semantic context; "
        "do not infer permission or a universal ontology from them.\n",
        encoding="utf-8",
    )
    (root / "lifeos.yml").write_text(
        "vault_root: .\n"
        "runtime_dir: .lifeos\n"
        "features:\n"
        "  graphify: true\n"
        "  exports: true\n",
        encoding="utf-8",
    )
    (root / "system/generated-ownership.json").write_text(
        json.dumps({"owned_files": {}, "schema_version": 1}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "system/instructions.yml").write_text(
        "schema_version: 1\ninstructions: []\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg-config")
    env["XDG_CACHE_HOME"] = str(tmp_path / "xdg-cache")
    env["XDG_STATE_HOME"] = str(tmp_path / "xdg-state")
    env["PYTHONPATH"] = str(SRC_ROOT)
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    return env


def _run_lifeos(
    *args: str,
    cwd: Path,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = (
        ["lifeos", *args]
        if env.get("LIFEOS_INTEGRATION_CONSOLE_SCRIPT") == "1"
        else [sys.executable, "-m", "lifeos.cli", *args]
    )
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )


def test_documented_fresh_vault_setup_runs_from_isolated_home(tmp_path: Path) -> None:
    vault = tmp_path / "LifeOS-vault"
    _bootstrap_vault(vault)
    env = _isolated_env(tmp_path)

    version = _run_lifeos("--version", cwd=REPO_ROOT, env=env)
    assert version.returncode == 0
    help_result = _run_lifeos("--help", cwd=REPO_ROOT, env=env)
    assert "LifeOS" in help_result.stdout

    config = load_config(vault / "lifeos.yml")
    assert config.vault_root == vault.resolve()
    assert config.runtime_dir == (vault / ".lifeos").resolve()
    assert not config.runtime_dir.exists()

    # The explicit --config path must work even when the application cwd is elsewhere.
    scan = _run_lifeos(
        "scan",
        "--config",
        str(vault / "lifeos.yml"),
        "--json",
        cwd=REPO_ROOT,
        env=env,
    )
    payload = json.loads(scan.stdout)
    assert "AGENTS.md" in payload["new"]
    assert (vault / "system/instructions.yml").is_file()
    assert (vault / ".lifeos/registry.db").is_file()

    status = _run_lifeos("status", "--json", cwd=vault, env=env)
    status_payload = json.loads(status.stdout)
    assert isinstance(status_payload, dict)

    source = vault / "study/driving-licence/intersections.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\n"
        "title: Intersections\n"
        "description: Rules for the Turkish driving licence exam\n"
        "---\n"
        "Right-of-way at uncontrolled intersections.\n",
        encoding="utf-8",
    )
    (vault / "goals/pass-driving-licence.md").write_text(
        "---\n"
        "title: Pass driving licence\n"
        "description: Pass the Turkish driving licence exam\n"
        "---\n"
        "Prepare for the exam.\n",
        encoding="utf-8",
    )
    (vault / "system/instructions.yml").write_text(
        "schema_version: 1\n"
        "instructions:\n"
        "  - id: driving-exam\n"
        "    authority: system\n"
        "    scope: path\n"
        "    priority: 100\n"
        "    text: Prioritize exam-relevant distinctions and confusing rules.\n"
        "    paths: [study/driving-licence/**]\n",
        encoding="utf-8",
    )

    _run_lifeos(
        "scan",
        "--config",
        str(vault / "lifeos.yml"),
        "--json",
        cwd=REPO_ROOT,
        env=env,
    )

    # Commands without --config deliberately resolve vault-root lifeos.yml from cwd.
    context = _run_lifeos(
        "context",
        "build",
        "What should I prioritize for this exam?",
        "--focus-path",
        "study/driving-licence/intersections.md",
        "--json",
        cwd=vault,
        env=env,
    )
    pack = json.loads(context.stdout)
    assert pack["sources"][0]["path"] == "study/driving-licence/intersections.md"
    assert "goals/pass-driving-licence.md" in {item["path"] for item in pack["sources"]}
    assert [item["id"] for item in pack["instructions"]] == ["driving-exam"]

    # Restart-like behavior: a second independent subprocess resolves the same vault only
    # from its vault-root config and sees the persisted disposable registry.
    scan_again = _run_lifeos(
        "scan",
        "--config",
        "lifeos.yml",
        "--json",
        cwd=vault,
        env=env,
    )
    second = json.loads(scan_again.stdout)
    assert "study/driving-licence/intersections.md" in second["unchanged"]


def test_setup_guide_contains_the_tested_vault_and_codex_contract() -> None:
    text = MANUAL.read_text(encoding="utf-8")
    assert "Create `~/LifeOS-vault/lifeos.yml` **inside the vault root**" in text
    assert "vault_root: ." in text
    assert "runtime_dir: .lifeos" in text
    assert "system/instructions.yml" in text
    assert "Create a minimal vault-root `AGENTS.md`" in text
    assert "codex mcp add lifeos --" in text
    assert "/absolute/path/to/lifeos-application/.venv/bin/lifeos-mcp" in text
    assert "--config /absolute/path/to/LifeOS-vault/lifeos.yml" in text
    assert "application repository's `AGENTS.md`" not in text
