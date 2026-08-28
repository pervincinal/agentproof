"""Xərc uçotu: uğurlu · yandırılmış · ÖLÇÜLMƏYƏN (AP-026).

Problem. `full-run-03` qeydləri **$23.72** göstərdi, hesabdan isə ~**$40**
getdi. Səbəb bir sətirdə idi (`report/normalize.py`):

    cost_usd = cost if any(r.usage for r in responses) else None

Yəni sınan cəhd `usage` qaytarmırsa, case-in xərci `null` olurdu — sanki
sorğu heç göndərilməyib. Halbuki sınan sorğu da token yandırır: modelə çatıb,
cavab yarımçıq kəsilib. `full-run-03`-də belə 75 sorğu var.

Üç rəqəm ayrı-ayrı saxlanılır, çünki üçü üç FƏRQLİ sual cavablandırır:

    cost_usd            "ölçmə nəyə başa gəldi"     -> uğurlu cəhdlər
    wasted_cost_usd     "nə yandı"                  -> uğursuz cəhdlər, ÖLÇÜLƏN
    unmeasured_attempts "nə qədəri bilinmir"        -> uğursuz, `usage` YOX

Üçüncüsü sıfır kimi göstərilə BİLMƏZ. Müştəri auditində "audit sizə nə qədər
başa gəlir?" sualına "təxminən" cavabı qəbuledilməzdir; "$X ölçüldü, N cəhdin
xərci ölçülmədi" isə dürüst cavabdır. Bu modul `inspect_ai` import etmir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Sequence

from agentproof.types import AgentResponse

#: `cost_coverage.status` dəyərləri.
COMPLETE = "complete"      # bütün cəhdlərin `usage`-ı gəldi
PARTIAL = "partial"        # bir hissəsi ölçülmədi -> xərc AŞAĞI göstərilir
UNMEASURED = "unmeasured"  # heç bir cəhd ölçülmədi


@dataclass(frozen=True)
class CostAccount:
    """Bir case-in xərc uçotu."""

    cost_usd: float | None
    """Uğurlu cəhdlərin xərci. `None` = ölçülmədi (sıfır deyil)."""

    wasted_cost_usd: float
    """Uğursuz cəhdlərin ÖLÇÜLƏN xərci (backoff-da atılan cəhdlər daxil)."""

    attempts: int
    measured_attempts: int
    unmeasured_attempts: int
    """Uğursuz, amma `usage` qaytarmayan cəhdlər — xərci NAMƏLUM."""


def _price(prices: Any, usage: Any, on: date) -> float | None:
    return None if usage is None else prices.cost_usd(usage, on=on)


def account_case(
    responses: Sequence[AgentResponse],
    prices: Any,
    on: date,
) -> CostAccount:
    """Bir case-in bütün cəhdlərini uğurlu / yandırılmış / ölçülməyənə ayırır.

    Bir cavab = bir cəhd (`--repeat N` -> N cavab). `attempts` sahəsi
    adapterin backoff-da atdığı cəhdləri də sayır; onların tokenləri
    `retry_usage`-dadır.
    """
    ok_costs: list[float] = []
    wasted = 0.0
    attempts = 0
    measured = 0
    unmeasured = 0

    for response in responses:
        # Adapter neçə HTTP sorğusu göndərdiyini bilir (backoff təkrarları ilə).
        sent = max(int(getattr(response, "attempts", 1) or 0), 0)
        if sent == 0:
            # Qaçış dayandırılıb: sorğu ÜMUMİYYƏTLƏ getmədi. Nə xərc var, nə
            # "ölçülməyən xərc" — bunu naməlum saymaq da yalan olardı.
            continue
        attempts += sent

        cost = _price(prices, response.usage, on)
        failed = response.error is not None
        if cost is None:
            # `usage` yoxdur. Uğursuz cəhddirsə xərc NAMƏLUMDUR — sıfır yox.
            if failed:
                unmeasured += 1
        else:
            measured += 1
            if failed:
                wasted += cost
            else:
                ok_costs.append(cost)

        # Backoff-da ATILAN cəhdlərin tokenləri: cavab uğurlu olsa da bu pul yanıb.
        retry_cost = _price(prices, getattr(response, "retry_usage", None), on)
        if retry_cost is not None:
            wasted += retry_cost
        discarded = max(sent - 1, 0)
        if discarded:
            # Atılan cəhdlərin NEÇƏSİ `usage` qaytardı — adapter sayır. Sahə
            # yoxdursa (köhnə artefakt) ehtiyatlı təxmin: token gəlibsə hamısı
            # ölçülüb, gəlməyibsə heç biri.
            raw = getattr(response, "raw", None) or {}
            recorded = raw.get("measured_retries")
            known = (
                discarded if (recorded is None and retry_cost is not None) else int(recorded or 0)
            )
            known = min(known, discarded)
            measured += known
            unmeasured += discarded - known

    return CostAccount(
        cost_usd=sum(ok_costs) if ok_costs else None,
        wasted_cost_usd=wasted,
        attempts=attempts,
        measured_attempts=measured,
        unmeasured_attempts=unmeasured,
    )


def coverage(accounts: Iterable[CostAccount]) -> dict[str, Any]:
    """Xərc ölçmə əhatəsi — hesabatda AÇIQ görünməlidir."""
    items = list(accounts)
    attempts = sum(a.attempts for a in items)
    unmeasured = sum(a.unmeasured_attempts for a in items)
    measured = sum(a.measured_attempts for a in items)
    if attempts and unmeasured == 0:
        status = COMPLETE
    elif measured == 0:
        status = UNMEASURED
    else:
        status = PARTIAL
    return {
        "attempts": attempts,
        "measured_attempts": measured,
        "unmeasured_attempts": unmeasured,
        "status": status,
        "note": _NOTE[status],
        # İstiqamət həmişə eynidir: ölçülməyən cəhd xərci AŞAĞI göstərir.
        "direction": "understates" if unmeasured else "exact",
    }


_NOTE = {
    COMPLETE: "bütün cəhdlərin token istifadəsi ölçüldü",
    PARTIAL: (
        "bəzi uğursuz cəhdlər `usage` qaytarmadı — onların xərci NAMƏLUMDUR "
        "(sıfır deyil). Yekun xərc AŞAĞI göstərilir"
    ),
    UNMEASURED: (
        "heç bir cəhdin `usage`-ı gəlmədi — xərc ümumiyyətlə ölçülmədi "
        "(sıfır deyil, naməlum)"
    ),
}


def summary_line(totals: dict[str, Any]) -> str:
    """Konsol / PR üçün tək sətir: uğurlu, yandırılmış, ölçülməyən."""
    cost = float(totals.get("cost_usd", 0.0) or 0.0)
    wasted = float(totals.get("wasted_cost_usd", 0.0) or 0.0)
    cov = totals.get("cost_coverage") or {}
    line = f"${cost:.4f} uğurlu + ${wasted:.4f} yandırılmış"
    unmeasured = int(cov.get("unmeasured_attempts", 0) or 0)
    if unmeasured:
        line += f" · {unmeasured} cəhdin xərci ÖLÇÜLMƏDİ (naməlum, sıfır deyil)"
    return line
