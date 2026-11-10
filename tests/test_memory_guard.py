"""Idle memory telemetry helpers."""
import pytest

from jarvis.adapters import runtime as R


@pytest.mark.parametrize("priv,limit,over", [(5000, 4096, True), (3000, 4096, False), (9999, 0, False), (9999, None, False), (9999, "x", False)])
def test_memory_over_limit(priv, limit, over):
    assert R.memory_over_limit(priv, limit) is over


def test_idle_for():
    assert R.idle_for(100.0, 160.0) == 60.0 and R.idle_for(200.0, 160.0) == 0.0 and R.idle_for(0, 5) == 5.0
