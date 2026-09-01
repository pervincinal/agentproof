"""Baseline müqayisəsi və CI qapısı (STACK.md §8.5, M4).

"87%" faydasız; "91% -> 87%, bu 4 case sındı" faydalıdır.
Bu modul Inspect import ETMİR — girişi `RunRecord`-dur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from agentproof.types import CaseResult, RepeatCheck, RunDelta, RunRecord


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

    fail_on_repeat_mismatch: bool = False
    """Cari qaçış baseline-dan AZ təkrarla qaçırılıbsa qapını bloklа (AP-043).

    Default `False`: qapı bloklamır, amma müqayisə TƏSDİQLƏNMƏMİŞ işarələnir və
    xəbərdarlıq konsolda, PR şərhində və artefaktda görünür. CI eyni təkrarı
    MƏCBUR etmək istəyirsə bunu `True` edir (`--fail-on-repeat-mismatch`).
    """


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


# ----------------------------------------------------------- `--repeat` (AP-043)
#: `attempt` sahəsi case üçün alınmış MÜSTƏQİL cavabların sayıdır
#: (`normalize.py`: `attempt=len(responses)`), yəni qaçışın faktiki `--repeat`-i.


def declared_repeat(record: RunRecord) -> int | None:
    """Qaçışın ÖZÜNÜN yazdığı `--repeat` (`totals["repeat"]`) və ya `None`.

    Köhnə artefaktlarda bu açar YOXDUR — onda `None` qayıdır və çağıran
    tərəf ölçülən dəyərə keçir. Səssiz `1` YAZILMIR: məhz "1 saydıq" fərziyyəsi
    tək cəhdlik qaçışı baseline ilə eyni səviyyədə göstərərdi.
    """
    value = record.totals.get("repeat")
    if isinstance(value, bool):
        return None
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def observed_repeat(record: RunRecord) -> int | None:
    """Nəticələrdən ÖLÇÜLƏN təkrar sayı — `report/reproduction.py` ilə eyni qayda.

    Ən çox cəhd sayı götürülür: yarıda dayandırılmış tək case bütün qaçışı
    "tək cəhdlik" göstərməsin. Nəticə yoxdursa ölçmə də yoxdur -> `None`.
    """
    attempts = [int(r.attempt) for r in record.results if int(r.attempt) >= 1]
    return max(attempts) if attempts else None


def repeat_of(record: RunRecord) -> tuple[int | None, str]:
    """`(təkrar sayı, mənbə)` — `declared` | `observed` | `unknown`."""
    declared = declared_repeat(record)
    if declared is not None:
        return declared, "declared"
    observed = observed_repeat(record)
    if observed is not None:
        return observed, "observed"
    return None, "unknown"


_SOURCE_LABEL = {
    "declared": "qaçışın yazdığı",
    "observed": "nəticələrdən ölçülən",
    "unknown": "naməlum",
}


def _side(n: int | None, source: str) -> str:
    return "naməlum" if n is None else f"{n}× ({_SOURCE_LABEL[source]})"


def check_repeat(current: RunRecord, baseline: RunRecord) -> RepeatCheck:
    """İki qaçış EYNİ sayda təkrarla ölçülübmü (AP-043).

    Az təkrarla qaçırılmış qapı «düzəldi» deyə bilər, halbuki flaky case
    sadəcə bu dəfə keçib. Müqayisənin özü qadağan olunmur — amma nəticə
    TƏSDİQLƏNMƏMİŞ kimi işarələnir və səbəb yazılır.
    """
    cur, cur_src = repeat_of(current)
    base, base_src = repeat_of(baseline)
    check = RepeatCheck(
        current=cur, baseline=base, current_source=cur_src, baseline_source=base_src
    )
    check.detail = f"cari {_side(cur, cur_src)} · baseline {_side(base, base_src)}"

    if cur is None or base is None:
        check.status = "unknown"
        missing = [
            name
            for name, value in (("cari qaçış", cur), ("baseline", base))
            if value is None
        ]
        check.warnings.append(
            f"`--repeat` NAMƏLUM ({' və '.join(missing)}) — {check.detail}. "
            "«düzəldi/sındı» iddiaları TƏSDİQLƏNMƏMİŞDİR: iki qaçışın eyni "
            "sayda təkrarla ölçüldüyü SÜBUT EDİLƏ BİLMİR."
        )
        return check

    if cur < base:
        check.status = "fewer"
        check.warnings.append(
            f"`--repeat` UYĞUNSUZLUĞU — {check.detail}. Cari qaçış baseline-dan "
            "AZ təkrarla ölçüldü, ona görə «düzəldi/sındı» iddiaları "
            "TƏSDİQLƏNMƏMİŞDİR: flaky case tək cəhddə təsadüfən keçə (və ya "
            f"sına) bilər. Yenidən qaçır: `--repeat {base}`."
        )
        return check

    check.status = "match" if cur == base else "more"
    return check


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
    # Müqayisə HANSI ölçmə gücü ilə aparıldı (AP-043) — `fixed`/`broken`
    # siyahıları bundan asılıdır və oxucu bunu görmədən onlara güvənməməlidir.
    delta.repeat_check = check_repeat(current, baseline)
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

    if policy.fail_on_repeat_mismatch and not delta.repeat_check.verified:
        reasons.append(
            f"`--repeat` uyğunsuzluğu ({delta.repeat_check.status}): "
            f"{delta.repeat_check.detail} — müqayisə təsdiqlənmir"
        )

    if policy.treat_flaky_as_regression and delta.flaky:
        reasons.append(f"qeyri-sabit (flaky) case: {', '.join(delta.flaky)}")

    return GateResult(passed=not reasons, reasons=reasons)
