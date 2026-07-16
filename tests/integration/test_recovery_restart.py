import json
import subprocess
import sys
from pathlib import Path

import pytest

from lifeos.proposals.application import apply_proposal
from tests.proposals.test_recovery_orchestration import (
    _InjectedInterruption,
    _interrupt_at,
    _load_two_target_application,
)


def test_restart_recovers_interrupted_application_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_target_install:0")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    code = """
import json
import sys
from pathlib import Path
from lifeos.proposals.recovery_service import recover_interrupted_applications
result = recover_interrupted_applications(vault_root=Path(sys.argv[1]))
print(json.dumps({"count": result.recovered_count, "actions": [x.action.value for x in result.transactions]}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(vault_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload == {"count": 1, "actions": ["rolled_back"]}
    assert (vault_root / "test1.txt").read_bytes() == b"old_content"
    assert not (vault_root / "test2.txt").exists()
    proposal_text = (vault_root / "proposals" / meta.id / "proposal.md").read_text()
    assert "status: approved" in proposal_text
    assert not any((vault_root / ".lifeos" / "recovery").iterdir())
