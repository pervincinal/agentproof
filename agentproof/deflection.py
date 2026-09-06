"""Agent cavab vermədi — yönləndirdi. Bu, keçid DEYİL.

NİYƏ VAR. Acorn-un agenti «Does my Acorn car insurance policy have no excess?»
sualına belə cavab verdi:

    «To help me answer your question as accurately as possible, please log
     into the Customer Portal and start a new chat with me.»

Bu cavab **qadağan olunmuş ifadələrin heç birini** ehtiva etmir, yəni
`contains_none` qraderi onu **KEÇDİ** sayır. Halbuki agent heç nə demədi.

Bu, layihənin bütün mövcudluq səbəbi olan səhv sinfidir: **yalançı yaşıl.**
Daha pisi miqyaslanır — əgər agent bütün müştəriyə xas sualları girişin
arxasına yönləndirirsə, 12 sualdan 12 «keçid» alarsan və sıfır məlumat.

NƏ EDİR. Yönləndirmə aşkarlananda nəticə `skipped` olur — nə keçid, nə
uğursuzluq. Səbəb adlandırılır və hesabatda ayrıca sayılır.

NƏ ETMİR. Bu, agentin qüsuru deyil. Şəxsi polis haqqında sualı girişin
arxasına göndərmək **düzgün davranışdır**. Ölçü sadəcə deyir: bu sualla bu
şeyi ölçə bilmədik — sualı ümumi formaya sal.
"""

from __future__ import annotations

import re

from agentproof.types import AgentResponse, GradeResult

#: Yönləndirmə naxışları. Hər biri REAL cavabda görülüb və ya sənaydə adi
#: formadır. Söz sərhədləri qəsdəndir — A-01/A-08 dərsi.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "login_required",
        re.compile(
            # «log in», «login», «log into», «sign in», «signing into»
            r"(?:\blog(?:ging)?\s*in(?:to)?\b|\bsign(?:ing)?\s*in(?:to)?\b|\blogin\b)"
            r"[^.]{0,70}"
            r"\b(?:portal|account|app|dashboard|my\s?acorn)\b"
            r"|\b(?:customer|client|member)\s+portal\b",
            re.IGNORECASE,
        ),
    ),
    (
        "human_handoff",
        re.compile(
            r"\b(?:transfer|connect|put|pass)\s+you\s+(?:through\s+|over\s+)?to\b"
            r"|\bspeak\s+(?:to|with)\s+(?:one\s+of\s+)?(?:our\s+)?"
            r"(?:advis[oe]rs?|team|colleagues?|agents?|someone)\b"
            r"|\b(?:an?\s+)?(?:advis[oe]rs?|colleagues?)\s+will\s+(?:be\s+)?"
            r"(?:in\s+touch|contact|help)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "call_us",
        re.compile(
            r"\b(?:give\s+us\s+a\s+call|call\s+us|phone\s+us|ring\s+us)\b"
            r"|\bcontact\s+(?:our|the)\s+(?:team|customer\s+service|support)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cannot_help",
        re.compile(
            r"\bI(?:'m|\u2019m| am)\s+(?:not\s+able|unable)\s+to\s+(?:help|answer|assist)\b"
            r"|\bI\s+(?:can'?t|cannot|don'?t)\s+(?:help|answer|assist)\b"
            r"|\bI\s+don'?t\s+have\s+(?:that|the)\s+information\b",
            re.IGNORECASE,
        ),
    ),
)

#: Yönləndirmə + REAL məlumat bir yerdə ola bilər. Cavabda bunlardan biri
#: varsa, agent nəsə DEDİ — yönləndirmə sayılmır və normal qiymətləndirilir.
_HAS_SUBSTANCE = re.compile(
    r"\d"                       # istənilən rəqəm: müddət, haqq, hədd
    r"|\bno\s+excess\b"
    r"|\b(?:covered|not\s+covered|eligible|not\s+eligible)\b",
    re.IGNORECASE,
)


def classify(text: str) -> str | None:
    """Yönləndirmə növünü qaytarır; cavab əsl məlumat daşıyırsa `None`."""
    if not text or not text.strip():
        return None
    if _HAS_SUBSTANCE.search(text):
        # Rəqəm və ya verdikt var — agent nəsə dedi. Yönləndirmə cümləsi
        # yanında olsa belə, ölçüləcək məzmun mövcuddur.
        return None
    for name, pattern in _PATTERNS:
        if pattern.search(text):
            return name
    return None


def as_skip(kind: str, grader: str) -> GradeResult:
    return GradeResult(
        passed=False,
        score=0.0,
        grader=grader,
        reason=(
            f"agent cavab vermədi — yönləndirdi ({kind}). "
            "Bu, keçid DEYİL və uğursuzluq DEYİL: bu sualla bu davranış "
            "ölçülə bilmədi. Sualı ümumi formaya sal və təkrarla."
        ),
        evidence={"deflection": kind},
        skipped=True,
    )


def check(response: AgentResponse, grader: str) -> GradeResult | None:
    """Yönləndirmədirsə `skipped` nəticə, əks halda `None`."""
    kind = classify(response.text or "")
    return as_skip(kind, grader) if kind else None
