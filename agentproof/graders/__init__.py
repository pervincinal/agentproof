"""Grader registry.

BU PAKET `inspect_ai` IMPORT ETMİR (STACK.md §6 pozulmaz qaydası).
Import edilməsi ilə bütün grader-lər registry-yə düşür.
"""

from agentproof.graders.base import AggregateGrader, Grader, registry

# qeydiyyat üçün import (side-effect) — sıra əlifba sırasıdır
from agentproof.graders import judge as _judge  # noqa: F401
from agentproof.graders.aggregate import consistency as _consistency  # noqa: F401
from agentproof.graders.deterministic import budget as _budget  # noqa: F401
from agentproof.graders.deterministic import leakage as _leakage  # noqa: F401
from agentproof.graders.deterministic import retrieval as _retrieval  # noqa: F401
from agentproof.graders.deterministic import structure as _structure  # noqa: F401
from agentproof.graders.deterministic import text as _text  # noqa: F401
from agentproof.graders.deterministic import tools as _tools  # noqa: F401

# LLM-as-judge qatı: `kind = "judge"`, yalnız `--stage judge` mərhələsində qaçır.
# Qeyd: `judge` modulu da `inspect_ai` import ETMİR; şəbəkəyə çıxış klient
# obyekti ilə kənardan verilir (`RubricJudge.bind`), ona görə import təhlükəsizdir.
from agentproof.graders.judge import (  # noqa: F401
    JudgeConfig,
    JudgeDecision,
    RubricJudge,
)

__all__ = [
    "registry",
    "Grader",
    "AggregateGrader",
    "RubricJudge",
    "JudgeConfig",
    "JudgeDecision",
]
