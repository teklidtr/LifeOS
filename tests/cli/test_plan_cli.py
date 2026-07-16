from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.cli import main


def test_plan_today_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    plans = vault / "plans"
    plans.mkdir(parents=True)
    (plans / "plan.md").write_text(
        "---\ntype: plan\nid: plan-one\ntasks:\n"
        "  - task_id: task-one\n"
        "    title: Read notes\n"
        "    status: active\n"
        "    duration: 30\n"
        "    energy: low\n"
        "    motivation: medium\n"
        "    mode: desk\n"
        "    blocked_by: []\n"
        "---\n",
        encoding="utf-8",
    )
    (tmp_path / "lifeos.yml").write_text(f"vault_root: {vault}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(
        [
            "plan",
            "today",
            "--date",
            "2026-07-15",
            "--minutes",
            "30",
            "--energy",
            "low",
            "--motivation",
            "medium",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["items"][0]["task_id"] == "task-one"


def test_plan_today_reports_plan_validation_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    plans = vault / "plans"
    plans.mkdir(parents=True)
    (plans / "plan.md").write_text(
        "---\ntype: plan\ntasks:\n"
        "  - task_id: task-one\n"
        "    title: Broken task\n"
        "    status: active\n"
        "    duration: 0\n"
        "    mode: desk\n"
        "---\n",
        encoding="utf-8",
    )
    (tmp_path / "lifeos.yml").write_text(f"vault_root: {vault}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(
        [
            "plan",
            "today",
            "--energy",
            "low",
            "--motivation",
            "medium",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "Planning error:" in captured.err
    assert "action duration" in captured.err
    assert "invalid planning date" not in captured.err
