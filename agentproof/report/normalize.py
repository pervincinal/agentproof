"""Inspect `.eval` log -> `RunRecord` (STACK.md §8.5).

Bizi Inspect-in log formatı dəyişikliklərindən qoruyan YEGANƏ nöqtə (R2).
Token -> USD çevrilməsi burada `pricing/models.yaml` ilə edilir.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from inspect_ai.log import EvalLog, read_eval_log

from agentproof.failure import HALT, REASONS, reason_for_response
from agentproof.graders.calibration import judge_status
from agentproof.pricing.table import load_prices
from agentproof.report.cost import account_case, coverage
from agentproof.report.merge import RunOrigin, fingerprint_case
from agentproof.types import AgentResponse, CaseResult, GradeResult, RunRecord


def _run_date(log: EvalLog) -> date:
    """Qaçışın başlama tarixi — qiymət dərəcəsini seçən tarix."""
    created = getattr(log.eval, "created", "") or ""
    try:
        return datetime.fromisoformat(str(created)).date()
    except ValueError:
        return datetime.now(timezone.utc).date()


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(round((p / 100.0) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def normalize_log(
    log: EvalLog,
    target: str,
    target_version: str = "",
    model: str = "",
) -> RunRecord:
    prices = load_prices()
    # Dərəcə QAÇIŞ tarixinə görə seçilir, bugünkü tarixə görə yox: köhnə bir
    # logu yenidən normallaşdırmaq həmin qaçışın xərcini dəyişdirməməlidir
    # (`pricing/models.yaml`-da keçidli dərəcələr var).
    run_day = _run_date(log)
    results: list[CaseResult] = []
    accounts = []
    # Skipped case-lərin SƏBƏB SİNFİ (AP-024): 25 ədəd "completion_request_error"
    # bir yığın kimi görünürdü, halbuki 24-ü kredit, qalanı rate limit idi.
    skipped_by_reason: dict[str, int] = {}

    for sample in log.samples or []:
        score = next(iter(sample.scores.values())) if sample.scores else None
        meta: dict[str, Any] = (score.metadata or {}) if score else {}
        responses = [AgentResponse.from_dict(r) for r in meta.get("responses", [])]
        response = responses[-1] if responses else AgentResponse(text="")
        skipped = bool(meta.get("skipped", False))
        value = None if score is None else score.value
        passed = value == 1.0 or value is True

        # Xərc UĞURLU / YANDIRILMIŞ / ÖLÇÜLMƏYƏN kimi ayrılır (AP-026):
        # sınan sorğu da token yandırır, `null` yazmaq onu gizlədirdi.
        account = account_case(responses, prices, run_day)
        accounts.append(account)
        if skipped:
            reason = next(
                (reason_for_response(r) for r in responses if reason_for_response(r)),
                "unknown",
            )
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
        results.append(
            CaseResult(
                case_id=str(sample.id),
                response=response,
                grade=GradeResult(
                    passed=passed and not skipped,
                    score=float(meta.get("raw_score", 1.0 if passed else 0.0)),
                    grader=str(meta.get("grader", "")),
                    reason=(score.explanation if score and score.explanation else
                            ("" if passed or skipped else "səbəb loga yazılmayıb")),
                    evidence=meta.get("evidence", {}) or {},
                    skipped=skipped,
                ),
                cost_usd=account.cost_usd,
                wasted_cost_usd=account.wasted_cost_usd,
                unmeasured_attempts=account.unmeasured_attempts,
                latency_ms=sum(r.latency_ms for r in responses),
                attempt=len(responses) or 1,
                tags=list(meta.get("tags", [])),
                severity=str(meta.get("severity", "medium")),
            )
        )

    graded = [r for r in results if not r.grade.skipped]
    latencies = [float(r.latency_ms) for r in results if r.latency_ms > 0]
    costs = [r.cost_usd for r in results if r.cost_usd is not None]

    totals = {
        "n_cases": len(results),
        "n_graded": len(graded),
        "n_passed": sum(1 for r in graded if r.grade.passed),
        "n_failed": sum(1 for r in graded if not r.grade.passed),
        "n_skipped": len(results) - len(graded),
        # Skipped-lər SƏBƏB SİNFİ üzrə (AP-024). Boş lüğət = skipped yoxdur.
        # `rate_limit` gözləməklə keçir, `credit_exhausted` keçmir — qaçışa
        # baxan adam hansı olduğunu bilmədən qərar verə bilmir.
        "skipped_by_reason": {r: skipped_by_reason[r] for r in REASONS if r in skipped_by_reason},
        "pass_rate": (sum(1 for r in graded if r.grade.passed) / len(graded)) if graded else 0.0,
        "cost_usd": sum(costs),
        # UĞURSUZ cəhdlərə gedən ÖLÇÜLƏN xərc. Ölçülməyən hissə burada DEYİL —
        # `cost_coverage` onu ayrıca göstərir (sıfır kimi yazmaq yalan olardı).
        "wasted_cost_usd": sum(r.wasted_cost_usd for r in results),
        "cost_coverage": coverage(accounts),
        # Qaçış yarıda dayandırılıbmı və niyə (AP-024 §3).
        "halted": HALT.to_dict(),
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "price_table_as_of": prices.as_of,
        "priced_on": run_day.isoformat(),
        # Neçə case HƏQİQƏTƏN çoxnövbəli ölçüldü. Zəncirlənmə sükutla sınsa,
        # bu rəqəm sıfıra düşür və hesabatda dərhal görünür — əks halda 15
        # çoxnövbəli case tək-növbəli kimi ölçülüb yaşıl görünərdi.
        "multi_turn_cases": sum(1 for r in results if r.response.n_turns > 1),
        # Judge kalibrasiyası hesabata AVTOMATIK düşür — ayrıca addım tələb
        # etmədiyi üçün gizlədilə bilmir (grader-eng.md: kalibrasiya edilməmiş
        # judge nəticəsi elmi zibildir).
        "judge": judge_status(r.grade.grader for r in results),
    }

    task_meta = log.eval.metadata or {}
    return RunRecord(
        run_id=log.eval.run_id,
        target=target,
        target_version=target_version,
        model=model,
        dataset_hash=str(task_meta.get("dataset_hash", "")),
        started_at=log.eval.created or datetime.now(timezone.utc).isoformat(),
        results=results,
        totals=totals,
    )


def normalize_path(path: str, target: str, target_version: str = "", model: str = "") -> RunRecord:
    return normalize_log(read_eval_log(path), target, target_version, model)


def repeat_responses(log: EvalLog) -> list[tuple[dict[str, Any], list[AgentResponse]]]:
    """Hər case üçün `(case metadata, BÜTÜN --repeat cavabları)`.

    `normalize_log()` bilərəkdən yalnız SONUNCU cavabı saxlayır — yekun verdikt
    ona görə verilib. Reproduksiya qapısı (`report/reproduction.py`) isə hər
    cəhdi AYRICA qiymətləndirməlidir, ona görə tam siyahı buradan çıxarılır.

    Inspect-in log formatını bilən yeganə nöqtə yenə də bu fayldır (R2) —
    `reproduction.py` `inspect_ai` import etmir.
    """
    out: list[tuple[dict[str, Any], list[AgentResponse]]] = []
    for sample in log.samples or []:
        meta = dict(sample.metadata or {})
        score = next(iter(sample.scores.values()), None) if sample.scores else None
        score_meta: dict[str, Any] = (score.metadata or {}) if score else {}
        responses = [AgentResponse.from_dict(r) for r in score_meta.get("responses", [])]
        out.append((meta, responses))
    return out


def read_repeat_responses(
    log_path: str,
) -> list[tuple[dict[str, Any], list[AgentResponse]]]:
    """`.eval` faylını oxuyub `repeat_responses()` qaytarır."""
    return repeat_responses(read_eval_log(log_path))


def log_origin(log: EvalLog, source: str = "") -> RunOrigin:
    """Logun MƏNŞƏYİ: hansı qaçış, nə vaxt, hansı dataset imzası ilə.

    AP-042: bir neçə log birlikdə oxunanda əvəzləmə məhz bu tarixə görə
    aparılır — fayl adına və ya arqument sırasına görə yox.
    """
    meta = log.eval.metadata or {}
    return RunOrigin(
        run_id=log.eval.run_id or "",
        started_at=str(log.eval.created or ""),
        dataset_hash=str(meta.get("dataset_hash", "")),
        source=source,
    )


def read_case_fingerprints(log_path: str) -> dict[str, str]:
    """`.eval` logundakı hər case-in TƏRİF barmaq izi: `{case_id: fingerprint}`.

    RunRecord case mətnini saxlamır, `.eval` logu isə saxlayır. Fərqli
    `dataset_hash`-lı iki qaçışı birləşdirməyin YEGANƏ obyektiv sübutu budur:
    "eyni id" yox, "eyni sual" (AP-042).
    """
    log = read_eval_log(log_path)
    return {
        str(sample.id): fingerprint_case(dict(sample.metadata or {}))
        for sample in (log.samples or [])
    }


def read_repeat_samples(
    log_path: str,
) -> tuple[RunOrigin, list[tuple[dict[str, Any], list[AgentResponse]]]]:
    """`(mənşə, [(case metadata, cavablar)])` — `reproduce.py` bunu işlədir."""
    log = read_eval_log(log_path)
    return log_origin(log, source=log_path), repeat_responses(log)
