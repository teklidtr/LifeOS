from datetime import date
from pathlib import Path

from lifeos.daily.today import TodayInputs, build_today_dashboard


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_empty_dashboard_distinguishes_missing_from_zero(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    result = build_today_dashboard(vault_root=vault, runtime_dir=tmp_path / "runtime", inputs=TodayInputs(date(2026, 7, 16), available_minutes=0, study_minutes=0))
    assert result.journal.state == "empty"
    assert result.journal.data["missing"] is True
    assert result.planning.state == "empty"
    assert result.study.state == "empty"


def test_planner_failure_does_not_erase_other_cards(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    write(vault / "plans" / "bad.md", "---\ntype: plan\ntasks: broken\n---\n")
    write(vault / "raw" / "idea.md", "---\ntype: raw\ntitle: Idea\nstatus: inbox\n---\n")
    result = build_today_dashboard(vault_root=vault, runtime_dir=tmp_path / "runtime", inputs=TodayInputs(date(2026, 7, 16)))
    assert result.planning.state == "corrupt"
    assert result.inbox.data["count"] == 1
    assert result.diagnostics.data["count"] == 1


def test_dashboard_is_stable_and_traceable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    write(vault / "plans" / "p.md", """---
id: p
type: plan
title: Plan
status: active
tasks:
  - task_id: t
    title: Read
    status: todo
    duration: 20
    energy: low
    motivation: low
    mode: reading
---
""")
    inputs = TodayInputs(date(2026, 7, 16), available_minutes=30, energy="medium", motivation="medium")
    first = build_today_dashboard(vault_root=vault, runtime_dir=tmp_path / "runtime", inputs=inputs)
    second = build_today_dashboard(vault_root=vault, runtime_dir=tmp_path / "runtime", inputs=inputs)
    assert first == second
    item = first.planning.data["items"][0]
    assert item["task_id"] == "t"
    assert "selected" in item["reason"]
