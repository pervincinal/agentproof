"""Token -> USD çevrilməsi (STACK.md M5 / R3).

Inspect token istifadəsini verir, dolları vermir. Cədvəl tarixlidir və
hesabatda `as_of` açıq göstərilir — köhnəlmiş qiymət gizli qalmasın.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agentproof.types import Usage

_DEFAULT_PATH = Path(__file__).with_name("models.yaml")


@dataclass(frozen=True)
class PriceTable:
    as_of: str
    currency: str
    models: dict[str, dict[str, float]]

    def cost_usd(self, usage: Usage | None) -> float | None:
        """Naməlum model və ya `usage=None` -> None (grader `skipped` verir)."""
        if usage is None:
            return None
        rates = self.models.get(usage.model)
        if rates is None:
            return None
        billed_input = max(usage.input_tokens - usage.cached_tokens, 0)
        return (
            billed_input * rates["input"]
            + usage.cached_tokens * rates.get("cached_input", rates["input"])
            + usage.output_tokens * rates["output"]
        ) / 1_000_000


@functools.lru_cache(maxsize=8)
def load_prices(path: str | None = None) -> PriceTable:
    data: dict[str, Any] = yaml.safe_load(Path(path or _DEFAULT_PATH).read_text())
    return PriceTable(
        as_of=str(data.get("as_of", "")),
        currency=data.get("currency", "USD"),
        models={k: {kk: float(vv) for kk, vv in v.items()} for k, v in data["models"].items()},
    )


def price_table_as_of(path: str | None = None) -> str:
    return load_prices(path).as_of
