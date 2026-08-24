"""Temporary LIFEOS-1644 full-validation supersession probe.

The fast PR path only collects this test. A full-validation shard executes it long enough
for a newer PR synchronize event to prove that the stale full checkpoint is cancelled by
the shared concurrency group. Remove this file immediately after the experiment.
"""

import time


def test_full_validation_supersession_probe() -> None:
    time.sleep(45)
