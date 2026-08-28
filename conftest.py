"""Repo kökünü sys.path-a əlavə edir ki, `pytest` quraşdırma olmadan qaçsın."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentproof.failure import HALT  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_run_halt():
    """`HALT` qaçış boyu QLOBALDIR (AP-024) — testlər arasında sızmamalıdır.

    Bir testdə `credit_exhausted` görünsə, bayraq qalxır və sonrakı bütün
    sorğular hədəfə getmədən "halted" qaytarardı; nəticədə əlaqəsiz testlər
    sınardı. `evals/run.py` da hər qaçışın əvvəlində eyni sıfırlamanı edir.
    """
    HALT.reset()
    yield
    HALT.reset()
