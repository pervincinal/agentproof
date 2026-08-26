"""Repo kökünü sys.path-a əlavə edir ki, `pytest` quraşdırma olmadan qaçsın."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
