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
    # --- Az\u0259rbaycanca (AZ) ---
    # N\u0130Y\u018f VAR. birmarket \u00abMirai\u00bb agenti az\u0259rbaycanca cavab verir. Z\u0259man\u0259t
    # sual\u0131na: \u00abBu sual\u0131n cavab\u0131n\u0131 m\u0259lumat bazas\u0131nda tapa bilm\u0259dim\u00bb \u2014 bu,
    # y\u00f6nl\u0259ndirm\u0259dir, amma ingilis nax\u0131\u015flar tutmad\u0131 v\u0259 YALAN\u00c7I-QIRMIZI verdi
    # (Acorn-dak\u0131 yalan\u00e7\u0131-ya\u015f\u0131l\u0131n \u0259ksi). Bir dild\u0259 iyn\u0259, ba\u015fqa dild\u0259 cavab \u2014
    # A-01 s\u0259hvinin eynisi.
    (
        "cannot_help_az",
        re.compile(
            r"cavab(?:\u0131n\u0131)?\s+(?:m\u0259lumat\s+bazas\u0131nda\s+)?tapa\s+bilm\u0259dim"
            r"|tapa\s+bilm\u0259dim"
            r"|(?:k\u00f6m\u0259k|yard\u0131m)\s+ed\u0259\s+bilm\u0259r\u0259m"
            r"|(?:bu\s+bar\u0259d\u0259\s+)?m\u0259lumat(?:\u0131m)?\s+yoxdur"
            r"|d\u0259qiq\s+(?:cavab|m\u0259lumat)\s+ver\u0259\s+bilm\u0259r\u0259m"
            r"|sual\u0131n\u0131z\u0131\s+daha\s+(?:\u0259trafl\u0131|d\u0259qiq)\s+ifad\u0259\s+edin",
            re.IGNORECASE,
        ),
    ),
    (
        "human_handoff_az",
        re.compile(
            r"operator(?:la|a)\s+(?:\u0259laq\u0259|m\u00fcraci\u0259t|dan\u0131\u015f)"
            r"|\u00e7a\u011fr\u0131\s+m\u0259rk\u0259zi(?:n\u0259)?\s+(?:m\u00fcraci\u0259t|z\u0259ng|\u0259laq\u0259)"
            r"|qaynar\s+x\u0259tt(?:\u0259|in\u0259)?\s*(?:m\u00fcraci\u0259t|z\u0259ng)?"
            r"|d\u0259st\u0259k\s+xidm\u0259tin\u0259\s+(?:m\u00fcraci\u0259t|yaz\u0131n)",
            re.IGNORECASE,
        ),
    ),
    (
        "login_required_az",
        re.compile(
            r"(?:\u015f\u0259xsi\s+)?hesab(?:\u0131n\u0131z)?(?:a|\u0131na)\s+daxil\s+ol"
            r"|\u00ab?M\u0259nim\s+sifari\u015fim\u00bb?\s+b\u00f6lm\u0259",
            re.IGNORECASE,
        ),
    ),
)

#: Yönləndirmə + REAL məlumat bir yerdə ola bilər. Cavabda ÖLÇÜLƏ BİLƏN dəyər
#: varsa, agent nəsə DEDİ — yönləndirmə sayılmır və normal qiymətləndirilir.
#:
#: «İstənilən rəqəm» DEYİL — rəqəm + VAHİD. Yoxsa «915 qaynar xəttinə müraciət
#: edin» kimi təmiz yönləndirmə telefon nömrəsinə görə «məzmun» sayılırdı və
#: yönləndirmə təsnifatından yayınırdı. Telefon nömrəsi qayda dəyəri deyil.
_HAS_SUBSTANCE = re.compile(
    r"\d[\s.,]*\s*(?:gün|ay|il|manat|₼|AZN|saat|dəqiqə|iş\s+günü|%|faiz|"
    r"day|days|month|months|year|years|hour|hours|week|weeks|£|\$|€|min\b)"
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
