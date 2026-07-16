from datetime import datetime, timezone
from pathlib import Path

from lifeos.attention import evaluate_attention, save_preference
from lifeos.daily import DailyInteractionService, TaskOutcomeRequest, content_hash


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)


def test_unaccounted_is_stable_unknown_and_resolves_after_outcome(tmp_path: Path) -> None:
    vault=tmp_path/"vault";vault.mkdir();runtime=tmp_path/"runtime"
    plan=vault/"plans"/"p.md"
    write(plan,"""---
id: p
type: plan
title: P
status: active
tasks:
  - task_id: t
    title: Work
    status: todo
    duration: 20
    energy: low
    motivation: low
    mode: writing
    planned_for: 2026-07-15
---
""")
    now=datetime(2026,7,16,12,tzinfo=timezone.utc)
    first=evaluate_attention(vault_root=vault,runtime_dir=runtime,as_of=now)
    second=evaluate_attention(vault_root=vault,runtime_dir=runtime,as_of=now)
    item=next(item for item in first.items if item.kind=="unaccounted_task")
    assert item==next(item for item in second.items if item.kind=="unaccounted_task")
    assert "unknown" in item.explanation
    app=DailyInteractionService(vault_root=vault,runtime_dir=runtime)
    app.record_task_outcome(TaskOutcomeRequest("event-1","plans/p.md","t","done",now.date(),content_hash(plan.read_text())))
    assert not any(item.kind=="unaccounted_task" for item in evaluate_attention(vault_root=vault,runtime_dir=runtime,as_of=now).items)


def test_checkin_preferences_snooze_and_dismiss(tmp_path: Path) -> None:
    vault=tmp_path/"vault";vault.mkdir();runtime=tmp_path/"runtime";now=datetime(2026,7,16,22,tzinfo=timezone.utc)
    result=evaluate_attention(vault_root=vault,runtime_dir=runtime,as_of=now)
    assert {item.title for item in result.items} >= {"Morning check-in is missing","Evening reconciliation is missing"}
    morning=next(item for item in result.items if item.title.startswith("Morning"))
    save_preference(runtime,item_id=morning.item_id,snooze_until="2026-07-17T12:00:00+00:00")
    assert morning.item_id not in {item.item_id for item in evaluate_attention(vault_root=vault,runtime_dir=runtime,as_of=now).items}
    evening=next(item for item in result.items if item.title.startswith("Evening"))
    save_preference(runtime,item_id=evening.item_id,dismiss=True)
    assert evening.item_id not in {item.item_id for item in evaluate_attention(vault_root=vault,runtime_dir=runtime,as_of=now).items}


def test_independent_items_survive_bad_planning(tmp_path: Path) -> None:
    vault=tmp_path/"vault";vault.mkdir();runtime=tmp_path/"runtime"
    write(vault/"plans"/"bad.md","---\ntype: plan\ntasks: broken\n---\n")
    write(vault/"raw"/"old.md","---\ntype: raw\nstatus: inbox\ndate: 2026-07-01\n---\n")
    result=evaluate_attention(vault_root=vault,runtime_dir=runtime,as_of=datetime(2026,7,16,22,tzinfo=timezone.utc))
    assert any(item.kind=="old_inbox" for item in result.items)
    assert result.diagnostics
