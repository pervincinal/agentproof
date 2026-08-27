"""Büdcə grader-ləri: cost_under, latency_under.

Müqavilə (STACK.md §8.2): hədəf `usage` vermirsə, `cost_under` `skipped`
qaytarır — SƏSSİZCƏ KEÇMİR. Eyni məntiq naməlum model üçün də işləyir.
"""

from __future__ import annotations

from agentproof.graders.base import grader, require
from agentproof.pricing.table import load_prices, pricing_date
from agentproof.types import AgentResponse, Case, GradeResult


@grader
class CostUnder:
    """Bir case-in dollar xərci həddin altında olmalıdır.

    expect:
      max_cost_usd: float   — məcburi
    """

    name = "cost_under"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        limit = float(require(case, "max_cost_usd", self.name))  # type: ignore[arg-type]
        prices = load_prices()
        # Dərəcə tarixlidir (introductory qiymətlər bitir) — hansı günün
        # dərəcəsi ilə hesablandığı sübutda görünməlidir.
        day = pricing_date()
        if response.usage is None:
            return GradeResult.skip(
                self.name,
                "hədəf `usage` qaytarmadı — xərc hesablana bilmir",
                {"limit_usd": limit, "price_table_as_of": prices.as_of},
            )
        cost = prices.cost_usd(response.usage, on=day)
        if cost is None:
            return GradeResult.skip(
                self.name,
                f"qiymət cədvəlində model yoxdur: {response.usage.model!r}",
                {
                    "limit_usd": limit,
                    "model": response.usage.model,
                    "known_models": sorted(prices.models),
                    "price_table_as_of": prices.as_of,
                },
            )
        passed = cost <= limit
        return GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            grader=self.name,
            reason=(
                f"xərc ${cost:.6f} <= hədd ${limit:.6f}"
                if passed
                else f"xərc ${cost:.6f} həddi aşdı (${limit:.6f})"
            ),
            evidence={
                "cost_usd": cost,
                "limit_usd": limit,
                "usage": response.usage.to_dict(),
                "price_table_as_of": prices.as_of,
                "priced_on": day.isoformat(),
                "rate_basis": prices.basis(response.usage.model, on=day),
            },
        )


@grader
class LatencyUnder:
    """Wall-clock gecikmə həddin altında olmalıdır.

    expect:
      max_latency_ms: int   — məcburi
    """

    name = "latency_under"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        limit = int(require(case, "max_latency_ms", self.name))  # type: ignore[arg-type]
        if response.latency_ms <= 0:
            return GradeResult.skip(
                self.name,
                "adapter gecikməni ölçmədi (latency_ms <= 0)",
                {"limit_ms": limit},
            )
        passed = response.latency_ms <= limit
        return GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            grader=self.name,
            reason=(
                f"gecikmə {response.latency_ms} ms <= hədd {limit} ms"
                if passed
                else f"gecikmə {response.latency_ms} ms həddi aşdı ({limit} ms)"
            ),
            evidence={"latency_ms": response.latency_ms, "limit_ms": limit},
        )
