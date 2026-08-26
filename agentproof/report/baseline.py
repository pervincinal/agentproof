"""Baseline müqayisəsi və CI qapısı (STACK.md §8.5, M4).

"87%" faydasız; "91% -> 87%, bu 4 case sındı" faydalıdır.
Bu modul Inspect import ETMİR — girişi `RunRecord`-dur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from agentproof.types import CaseResult, RunDelta, RunRecord


@dataclass
class GatePolicy:
    """CI-ın nə vaxt fail olacağı."""

    max_pass_rate_drop: float = 0.02
    """Ümumi keçmə dərəcəsinin icazə verilən düşməsi (mütləq, 0.02 = 2 punkt)."""

    fail_on_high_severity_break: bool = True
    """high severity case sınıqsa dərhal fail."""

    max_cost_increase_usd: float | None = None
    max_p95_increase_ms: float | None = None
    treat_flaky_as_regression: bool = False


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


def _by_case(record: RunRecord) -> dict[str, list[CaseResult]]:
    out: dict[str, list[CaseResult]] = {}
    for r in record.results:
        out.setdefault(r.case_id, []).append(r)
    return out


def _verdict(results: Iterable[CaseResult]) -> str:
    """`pass` | `fail` | `flaky` | `skip` — case-in yekun vəziyyəti."""
    graded = [r for r in results if not r.grade.skipped]
    if not graded:
        return "skip"
    outcomes = {r.grade.passed for r in graded}
    if len(outcomes) > 1:
        return "flaky"
    return "pass" if outcomes.pop() else "fail"


def compare(current: RunRecord, baseline: RunRecord) -> RunDelta:
    cur, base = _by_case(current), _by_case(baseline)
    delta = RunDelta(
        pass_rate_before=float(baseline.totals.get("pass_rate", 0.0)),
        pass_rate_after=float(current.totals.get("pass_rate", 0.0)),
        cost_delta=float(current.totals.get("cost_usd", 0.0))
        - float(baseline.totals.get("cost_usd", 0.0)),
        p50_delta_ms=float(current.totals.get("p50_latency_ms", 0.0))
        - float(baseline.totals.get("p50_latency_ms", 0.0)),
        p95_delta_ms=float(current.totals.get("p95_latency_ms", 0.0))
        - float(baseline.totals.get("p95_latency_ms", 0.0)),
    )

    delta.new_cases = sorted(set(cur) - set(base))
    delta.removed_cases = sorted(set(base) - set(cur))

    severity = {cid: results[0].severity for cid, results in cur.items()}

    for case_id in sorted(set(cur) & set(base)):
        now, then = _verdict(cur[case_id]), _verdict(base[case_id])
        if now == "flaky":
            # flaky reqressiya SAYILMIR, amma ayrıca göstərilir (PLAN.md qayda 1)
            delta.flaky.append(case_id)
        elif now == "pass" and then in ("fail", "flaky"):
            delta.fixed.append(case_id)
        elif now == "fail" and then in ("pass", "flaky"):
            delta.broken.append(case_id)
            if severity.get(case_id) == "high":
                delta.broken_high_severity.append(case_id)
        elif now == "fail" and then == "fail":
            delta.still_failing.append(case_id)

    # yeni əlavə olunmuş və dərhal sınan case reqressiya deyil, amma gizlənməməlidir
    for case_id in delta.new_cases:
        if _verdict(cur[case_id]) == "fail":
            delta.still_failing.append(case_id)
    delta.still_failing = sorted(set(delta.still_failing))
    return delta


def gate(delta: RunDelta, policy: GatePolicy | None = None) -> GateResult:
    policy = policy or GatePolicy()
    reasons: list[str] = []

    if policy.fail_on_high_severity_break and delta.broken_high_severity:
        reasons.append(
            f"high severity case sındı: {', '.join(delta.broken_high_severity)}"
        )

    drop = delta.pass_rate_before - delta.pass_rate_after
    if drop > policy.max_pass_rate_drop:
        reasons.append(
            f"keçmə dərəcəsi {delta.pass_rate_before:.1%} -> {delta.pass_rate_after:.1%} "
            f"({drop:.1%} düşüş, hədd {policy.max_pass_rate_drop:.1%})"
        )

    if policy.max_cost_increase_usd is not None and delta.cost_delta > policy.max_cost_increase_usd:
        reasons.append(
            f"xərc +${delta.cost_delta:.2f} (hədd +${policy.max_cost_increase_usd:.2f})"
        )

    if policy.max_p95_increase_ms is not None and delta.p95_delta_ms > policy.max_p95_increase_ms:
        reasons.append(
            f"p95 +{delta.p95_delta_ms:.0f} ms (hədd +{policy.max_p95_increase_ms:.0f} ms)"
        )

    if policy.treat_flaky_as_regression and delta.flaky:
        reasons.append(f"qeyri-sabit (flaky) case: {', '.join(delta.flaky)}")

    return GateResult(passed=not reasons, reasons=reasons)
