"""Grader registry.

BU PAKET `inspect_ai` IMPORT ETMİR (STACK.md §6 pozulmaz qaydası).
Import edilməsi ilə bütün grader-lər registry-yə düşür.
"""

from agentproof.graders.base import AggregateGrader, Grader, registry

# qeydiyyat üçün import (side-effect) — sıra əlifba sırasıdır
from agentproof.graders.aggregate import consistency as _consistency  # noqa: F401
from agentproof.graders.deterministic import budget as _budget  # noqa: F401
from agentproof.graders.deterministic import leakage as _leakage  # noqa: F401
from agentproof.graders.deterministic import retrieval as _retrieval  # noqa: F401
from agentproof.graders.deterministic import structure as _structure  # noqa: F401
from agentproof.graders.deterministic import text as _text  # noqa: F401
from agentproof.graders.deterministic import tools as _tools  # noqa: F401

__all__ = ["registry", "Grader", "AggregateGrader"]
