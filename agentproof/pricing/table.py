"""Token -> USD çevrilməsi (STACK.md M5 / R3).

Inspect token istifadəsini verir, dolları vermir. Cədvəl tarixlidir və
hesabatda `as_of` açıq göstərilir — köhnəlmiş qiymət gizli qalmasın.

**Tarixə həssas dərəcə.** Bəzi dərəcələr müəyyən tarixdən sonra dəyişir
(məs. `claude-sonnet-5` üçün introductory qiymət 2026-08-31-də bitir). Cədvəl
bunu `effective_until` + `after` ilə saxlayır və dərəcə QAÇIŞ TARİXİNƏ görə
seçilir. Belə olmasa, keçid günündən sonra bütün xərc hesabatı səssizcə
50% aşağı çıxardı.
"""

from __future__ import annotations

import datetime
import functools
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

from agentproof.types import Usage

_DEFAULT_PATH = Path(__file__).with_name("models.yaml")

#: Qaçış tarixini kənardan pinləmək üçün (test və köhnə qaçışın yenidən
#: qiymətləndirilməsi). Verilməsə sistem tarixi işlədilir.
PRICING_DATE_ENV = "AGENTPROOF_PRICING_DATE"

_RATE_KEYS = ("input", "output", "cached_input")


def pricing_date(on: datetime.date | str | None = None) -> datetime.date:
    if isinstance(on, datetime.date):
        return on
    raw = on or os.environ.get(PRICING_DATE_ENV, "")
    if raw:
        return datetime.date.fromisoformat(str(raw))
    return datetime.date.today()


@dataclass(frozen=True)
class Rate:
    input: float
    output: float
    cached_input: float

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback: "Rate | None" = None) -> "Rate":
        inp = float(data["input"]) if "input" in data else (fallback.input if fallback else 0.0)
        out = float(data["output"]) if "output" in data else (fallback.output if fallback else 0.0)
        cached = data.get("cached_input")
        return cls(
            input=inp,
            output=out,
            cached_input=float(cached) if cached is not None else inp,
        )

    def to_dict(self) -> dict[str, float]:
        return {"input": self.input, "output": self.output, "cached_input": self.cached_input}


@dataclass(frozen=True)
class ModelPricing:
    """Bir modelin dərəcəsi — lazım gələrsə iki dövrlü."""

    name: str
    rate: Rate
    effective_until: datetime.date | None = None
    after: Rate | None = None
    note: str = ""

    def rate_on(self, day: datetime.date) -> Rate:
        if self.after is not None and self.effective_until is not None and day > self.effective_until:
            return self.after
        return self.rate

    def basis_on(self, day: datetime.date) -> str:
        """Hansı dövrün dərəcəsi işlədildi — hesabatda görünsün deyə."""
        if self.effective_until is None or self.after is None:
            return "flat"
        return "current" if day <= self.effective_until else f"after {self.effective_until}"


@dataclass(frozen=True)
class PriceTable:
    as_of: str
    currency: str
    models: dict[str, ModelPricing]

    def __contains__(self, model: str) -> bool:
        return model in self.models

    def __iter__(self) -> Iterator[str]:
        return iter(self.models)

    def rate_for(
        self, model: str, on: datetime.date | str | None = None
    ) -> Rate | None:
        pricing = self.models.get(model)
        return None if pricing is None else pricing.rate_on(pricing_date(on))

    def cost_usd(
        self, usage: Usage | None, on: datetime.date | str | None = None
    ) -> float | None:
        """Naməlum model və ya `usage=None` -> None (grader `skipped` verir).

        `on` — qaçış tarixi. Verilməsə `AGENTPROOF_PRICING_DATE`, o da yoxdursa
        bugünkü tarix. Tarix dərəcəni seçir, çünki bəzi dərəcələr keçidlidir.
        """
        if usage is None:
            return None
        rates = self.rate_for(usage.model, on)
        if rates is None:
            return None
        billed_input = max(usage.input_tokens - usage.cached_tokens, 0)
        return (
            billed_input * rates.input
            + usage.cached_tokens * rates.cached_input
            + usage.output_tokens * rates.output
        ) / 1_000_000

    def basis(self, model: str, on: datetime.date | str | None = None) -> str:
        pricing = self.models.get(model)
        return "" if pricing is None else pricing.basis_on(pricing_date(on))


def _parse_model(name: str, data: dict[str, Any]) -> ModelPricing:
    rate = Rate.from_dict(data)
    until = data.get("effective_until")
    after_raw = data.get("after")
    after = Rate.from_dict(after_raw, fallback=rate) if isinstance(after_raw, dict) else None
    if (until is None) != (after is None):
        raise ValueError(
            f"{name}: `effective_until` və `after` birlikdə verilməlidir — "
            "yarımçıq cədvəl keçid günündə səssizcə yanlış dərəcə seçər."
        )
    parsed_until: datetime.date | None = None
    if until is not None:
        parsed_until = until if isinstance(until, datetime.date) else datetime.date.fromisoformat(str(until))
    return ModelPricing(
        name=name,
        rate=rate,
        effective_until=parsed_until,
        after=after,
        note=str(data.get("note", "")),
    )


@functools.lru_cache(maxsize=8)
def load_prices(path: str | None = None) -> PriceTable:
    data: dict[str, Any] = yaml.safe_load(Path(path or _DEFAULT_PATH).read_text())
    return PriceTable(
        as_of=str(data.get("as_of", "")),
        currency=data.get("currency", "USD"),
        models={name: _parse_model(name, spec) for name, spec in data["models"].items()},
    )


def price_table_as_of(path: str | None = None) -> str:
    return load_prices(path).as_of
