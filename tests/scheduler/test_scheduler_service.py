from datetime import datetime, timezone
from pathlib import Path

from lifeos.scheduler import (
    AttentionScheduler,
    BackgroundServiceInstaller,
    MemoryNotificationAdapter,
    ScheduleConfig,
    save_schedule,
)


def test_morning_duplicate_suppression_and_privacy(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    save_schedule(
        vault,
        ScheduleConfig(
            enabled=True,
            timezone="Europe/Istanbul",
            morning="08:30",
            evening="19:30",
            quiet_start="23:00",
            quiet_end="07:00",
            privacy="generic",
        ),
    )
    adapter = MemoryNotificationAdapter()
    scheduler = AttentionScheduler(
        vault_root=vault, runtime_dir=runtime, vault_name="Vault", adapter=adapter
    )
    now = datetime(2026, 7, 16, 5, 45, tzinfo=timezone.utc)
    first = scheduler.run(now)
    second = scheduler.run(now)
    assert first.delivered
    assert not second.delivered
    assert second.suppressed
    assert "outstanding item" in adapter.sent[0].body
    assert adapter.sent[0].open_uri.startswith("obsidian://")


def test_quiet_hours_and_timezone_change(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    save_schedule(
        vault,
        ScheduleConfig(
            enabled=True, timezone="UTC", quiet_start="22:00", quiet_end="07:00", morning="23:00"
        ),
    )
    result = AttentionScheduler(
        vault_root=vault, runtime_dir=runtime, vault_name="V", adapter=MemoryNotificationAdapter()
    ).run(datetime(2026, 7, 16, 23, tzinfo=timezone.utc))
    assert result.suppressed == ("quiet-hours",)


def test_service_install_is_explicit_and_reversible(tmp_path: Path) -> None:
    installer = BackgroundServiceInstaller(tmp_path)
    descriptor = installer.install(
        command=("python", "-m", "lifeos.scheduler"), platform_name="Darwin"
    )
    assert descriptor.exists() and installer.status()["installed"] is True
    installer.uninstall()
    assert installer.status()["installed"] is False
