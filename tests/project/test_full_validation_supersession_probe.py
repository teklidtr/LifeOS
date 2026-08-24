"""Temporary LIFEOS-1644 supersession probe.

Creating this harmless passing test while a full-validation run is active proves that the
new PR synchronize event cancels the now-stale full checkpoint through the shared concurrency
group. Remove this file after recording the cancellation.
"""


def test_supersession_probe_is_harmless() -> None:
    assert True
