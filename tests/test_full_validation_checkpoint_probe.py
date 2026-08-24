"""Temporary LIFEOS-1644 checkpoint probe.

This file deliberately fails only when the complete pytest suite executes. The ordinary
PR fast path should still collect it successfully without executing it. Remove this file
after recording the expected full-validation failure.
"""


def test_full_validation_checkpoint_probe() -> None:
    assert False, "temporary LIFEOS-1644 full validation checkpoint probe"
