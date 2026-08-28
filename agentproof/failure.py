"""Hədəf xətalarının SƏBƏB SİNFİ — bir kodun altında iki fərqli hal olmasın.

AP-024. `reports/full-run-03`-də 25 case (75 sorğu) eyni kodla `skipped` oldu:

    dify_error.code    = "completion_request_error"
    dify_error.message = "[models] Bad Request Error, Error code: 400 - "
                         "{'type': 'error', 'error': {'type': 'invalid_request_error', "
                         "'message': 'Your credit balance is too low to access the "
                         "Anthropic API. ...'}, 'request_id': 'req_011Ce...'}"

Eyni `completion_request_error` kodu altında Dify loglarında ayrıca 429
(rate limit) və 529 (overloaded) da görünürdü. Qaçışa baxan adam bir kodla iki
tam fərqli qərar arasında qalır: **gözləsin, yoxsa balans doldursun?**

Ona görə kod (nə baş verdi) ilə SİNİF (nə etməli) ayrılır:

    rate_limit        gözləməklə həll olunur      -> backoff + yenidən cəhd
    credit_exhausted  gözləməklə həll OLUNMUR     -> qaçış dayanır, insan lazımdır
    auth              gözləməklə həll OLUNMUR     -> dərhal dayan
    bad_request       sorğunun özü xarabdır       -> dərhal dayan
    unknown           təsnif edilmədi             -> dərhal dayan (təxmin etmirik)

`credit_exhausted` və `auth`-u yenidən cəhd etmək pul və vaxt yandırır və heç
vaxt keçmir — ona görə onlar QƏSDƏN `RETRYABLE`-dan kənardadır.

Modul stdlib-dən başqa yalnız `agentproof.types`-dan asılıdır (o da heç nədən
asılı deyil) — adapter, runner və hesabat qatı eyni təsnifatı işlədir.
"""

from __future__ import annotations

import re
from typing import Any

#: Səbəb sinifləri.
RATE_LIMIT = "rate_limit"
CREDIT_EXHAUSTED = "credit_exhausted"
AUTH = "auth"
BAD_REQUEST = "bad_request"
UNKNOWN = "unknown"

REASONS: tuple[str, ...] = (RATE_LIMIT, CREDIT_EXHAUSTED, AUTH, BAD_REQUEST, UNKNOWN)

#: Gözləməklə keçə bilən YEGANƏ sinif. Siyahını genişləndirmək = pul yandırmaq.
RETRYABLE = frozenset({RATE_LIMIT})

#: Qaçışı BÜTÖVLÜKDƏ dayandıran sinif: növbəti 100 case-i də sındırmağın mənası
#: yoxdur, çünki səbəb hədəfdə deyil, hesabdadır.
HALTING = frozenset({CREDIT_EXHAUSTED})

#: İnsan üçün qısa izah — hesabatda səbəbin yanında görünür.
REASON_HINT = {
    RATE_LIMIT: "hədəf rate limit / overloaded qaytardı (gözləməklə keçir)",
    CREDIT_EXHAUSTED: "hesabda kredit qalmayıb — gözləmək kömək ETMİR, balans lazımdır",
    AUTH: "açar/icazə problemi — gözləmək kömək ETMİR",
    BAD_REQUEST: "sorğu hədəf tərəfindən rədd edildi (400)",
    UNKNOWN: "səbəb təsnif olunmadı — xam mesaja baxın",
}

# --- mesaj naxışları -------------------------------------------------------
# Hamısı REAL nümunə üzərində yoxlanıb (`reports/full-run-03-retry/*.json` ->
# `response.raw.dify_error.message`). Dify upstream xətanı MƏTN kimi sarır,
# ona görə strukturlu sahə yoxdur — mesajı oxumaqdan başqa yol yoxdur.

#: `... Error code: 400 - {...}` — upstream HTTP statusu mesajın İÇİNDƏdir.
#: Dify zərfinin öz statusu (400) ilə upstream statusu (429) FƏRQLİ ola bilər.
_UPSTREAM_STATUS = re.compile(r"error\s+code:\s*(\d{3})", re.IGNORECASE)

#: TƏSDİQLƏNMİŞ nümunə: "Your credit balance is too low to access the Anthropic
#: API. Please go to Plans & Billing to upgrade or purchase credits."
_CREDIT = re.compile(
    r"credit\s+balance\s+is\s+too\s+low"
    r"|purchase\s+credits"
    r"|insufficient[_\s]quota"
    r"|billing[_\s]error",
    re.IGNORECASE,
)

_RATE = re.compile(
    r"rate[_\s]?limit"
    r"|overloaded"
    r"|too\s+many\s+requests"
    r"|please\s+(?:slow\s+down|try\s+again\s+later)",
    re.IGNORECASE,
)

_AUTH = re.compile(
    r"authentication[_\s]error"
    r"|invalid\s+x-api-key"
    r"|invalid[_\s]api[_\s]key"
    r"|permission[_\s]error"
    r"|unauthorized"
    r"|forbidden",
    re.IGNORECASE,
)

#: Dify-ın ÖZ kodları (`SETUP.md §7.2`). `completion_request_error` qəsdən
#: yoxdur: o, zərfdir — həqiqi səbəb mesajın içindədir.
_CODE_REASON = {
    "too_many_requests": RATE_LIMIT,
    "rate_limit_error": RATE_LIMIT,
    "unauthorized": AUTH,
    "forbidden": AUTH,
    # model provayderi konfiqurasiya olunmayıb -> açar problemi, gözləməzlik
    "provider_not_initialize": AUTH,
    # Dify hostinq kvotası bitib -> gözləməklə qayıtmır, insan müdaxiləsi lazımdır
    "provider_quota_exceeded": CREDIT_EXHAUSTED,
    "invalid_param": BAD_REQUEST,
    "bad_request": BAD_REQUEST,
    "not_found": BAD_REQUEST,
}


def upstream_status(message: str) -> int | None:
    """Mesajın içindəki `Error code: NNN` — Dify zərfinin statusu DEYİL."""
    match = _UPSTREAM_STATUS.search(message or "")
    return int(match.group(1)) if match else None


def classify_failure(code: str = "", message: str = "", status: Any = None) -> str:
    """`(kod, mesaj, status)` -> səbəb sinfi.

    Sıralama TƏSADÜFİ deyil. Real kredit xətası `Error code: 400` daşıyır —
    yəni statusa görə təsnif edilsə `bad_request` çıxardı və "sorğunu düzəlt"
    kimi oxunardı. Ona görə mesaj naxışı statusdan ƏVVƏL yoxlanır.
    """
    code_key = str(code or "").strip().lower()
    text = str(message or "")

    if _CREDIT.search(text):
        return CREDIT_EXHAUSTED

    statuses = [s for s in (_opt_status(status), upstream_status(text)) if s is not None]
    # 429 rate limit, 529 overloaded — hər ikisi gözləməklə keçir.
    if any(s in (429, 529) for s in statuses):
        return RATE_LIMIT

    mapped = _CODE_REASON.get(code_key)
    if mapped:
        return mapped

    if _RATE.search(text):
        return RATE_LIMIT
    if _AUTH.search(text) or any(s in (401, 403) for s in statuses):
        return AUTH
    if any(400 <= s < 500 for s in statuses):
        return BAD_REQUEST
    return UNKNOWN


def reason_for_response(response: Any) -> str | None:
    """`AgentResponse` -> səbəb sinfi (xəta yoxdursa `None`).

    Köhnə artefaktlar (`schema_version` 1/2, `error_class` sahəsi olmayan)
    da təsnif olunur: sinif xam `dify_error`-dan YENİDƏN hesablanır. Beləcə
    `reports/full-run-03` bugünkü taksonomiya ilə oxuna bilir.
    """
    error = getattr(response, "error", None)
    if not error:
        return None
    existing = getattr(response, "error_class", None)
    if existing:
        return str(existing)
    raw = getattr(response, "raw", None) or {}
    dify_error = raw.get("dify_error") or {}
    if not dify_error:
        # Çoxnövbəli cavabda birləşdirilmiş `raw`-da `dify_error` YOXDUR — o,
        # zənciri qıran NÖVBƏNİN içindədir. Buna baxmasaq, `full-run-03`-dəki
        # çoxnövbəli case səbəbsiz ("unknown") görünərdi.
        for turn in getattr(response, "turns", None) or []:
            turn_reason = reason_for_response(turn)
            if turn_reason:
                return turn_reason
    return classify_failure(
        code=str(error),
        message=str(dify_error.get("message", "") or raw.get("message", "")),
        status=dify_error.get("status", raw.get("status")),
    )


def _opt_status(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RunHalt:
    """Qaçışı bütövlükdə dayandıran, geri qayıtmayan xəta (AP-024 §3).

    `credit_exhausted` görünəndə növbəti case-ləri hədəfə göndərmək mənasızdır:
    hamısı eyni cür sınacaq, hər biri gecikmə yaradacaq və hesabat 100 ədəd
    eyni "səbəbi bilinməyən" skipped ilə dolacaq. Bayraq qalxandan sonra
    adapter sorğu GÖNDƏRMİR — cavab dərhal, səbəb adı ilə qayıdır.

    Vəziyyət qaçış boyu qlobaldır (modul səviyyəsində `HALT`), çünki Inspect
    sample-ları paralel qaçırır və onların arasında ortaq yol yoxdur. `reset()`
    hər qaçışın əvvəlində çağırılır (`evals/run.py`).
    """

    def __init__(self) -> None:
        self._reason: str | None = None
        self._detail: str = ""
        self._case_id: str = ""

    @property
    def tripped(self) -> bool:
        return self._reason is not None

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def detail(self) -> str:
        return self._detail

    @property
    def case_id(self) -> str:
        return self._case_id

    def trip(self, reason: str, detail: str = "", case_id: str = "") -> bool:
        """İLK səbəb qalır — sonrakılar onun nəticəsidir, üstündən yazmamalıdır."""
        if self._reason is not None:
            return False
        self._reason = reason
        self._detail = detail
        self._case_id = case_id
        return True

    def reset(self) -> None:
        self._reason = None
        self._detail = ""
        self._case_id = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "halted": self.tripped,
            "reason": self._reason or "",
            "detail": self._detail,
            "case_id": self._case_id,
            "hint": REASON_HINT.get(self._reason or "", ""),
        }


#: Qaçış boyu ortaq bayraq.
HALT = RunHalt()
