"""AP-024 — xəta növləri ayrılır, YALNIZ rate limit-də geri çəkilirik.

Niyə bu fayl var. `reports/full-run-03`-də 25 case (75 sorğu) eyni kod altında
`skipped` oldu: `completion_request_error`. Səbəblər isə fərqli idi — 24 case
"credit balance is too low" (gözləməklə HEÇ VAXT keçmir, insan lazımdır), Dify
loglarında ayrıca 429/529 (gözləməklə keçir). Qaçışa baxan adam bir kodla iki
tam fərqli qərar arasında qalırdı.

Bu testlər dörd şeyi kilidləyir:
  1. hər sinif REAL mesaj üzərində düzgün təsnif olunur;
  2. `rate_limit` -> backoff artır və hədəf özünə gələndə case UĞUR qazanır;
  3. `credit_exhausted` -> təkrar YOXDUR (ayrıca yoxlanılır) və qaçış dayanır;
  4. cəhdlər bitəndə case `skipped` qalır, amma səbəb `rate_limit` kimi kodlanır.
"""

from __future__ import annotations

import pytest

from agentproof.adapters import create_adapter
from agentproof.failure import (
    AUTH,
    BAD_REQUEST,
    CREDIT_EXHAUSTED,
    HALT,
    RATE_LIMIT,
    RETRYABLE,
    UNKNOWN,
    classify_failure,
    reason_for_response,
)
from agentproof.testing.mock_dify import (
    CREDIT_EXHAUSTED_MESSAGE,
    OVERLOADED_MESSAGE,
    RATE_LIMIT_MESSAGE,
    MockDifyServer,
)
from agentproof.types import AgentRequest, AgentResponse


@pytest.fixture
def server():
    srv = MockDifyServer().start()
    try:
        yield srv
    finally:
        srv.stop()


def _adapter(server: MockDifyServer, **kw):
    kw.setdefault("backoff_base_s", 0.01)  # test saatı, real qaçışda 2 s
    return create_adapter("dify_http", base_url=server.base_url, api_key=server.api_key, **kw)


def _req(query: str, case_id: str = "case-x") -> AgentRequest:
    return AgentRequest(
        messages=[{"role": "user", "content": query}],
        session_id="t",
        metadata={"case_id": case_id},
    )


# =========================================================== 1. təsnifat
# Nümunələr FƏRZİYYƏ deyil: `reports/full-run-03-retry/*.json` ->
# `response.raw.dify_error.message` sahəsindən götürülüb.
def test_real_credit_message_is_not_read_as_a_bad_request():
    """Ən vacib hal: mesaj `Error code: 400` daşıyır, amma səbəb 400 DEYİL.

    Statusa görə təsnif etsək `bad_request` çıxardı və "sorğunu düzəlt" kimi
    oxunardı — halbuki edilməli olan şey balans doldurmaqdır.
    """
    assert classify_failure(
        code="completion_request_error", message=CREDIT_EXHAUSTED_MESSAGE, status=400
    ) == CREDIT_EXHAUSTED


@pytest.mark.parametrize(
    "code,message,status,expected",
    [
        ("completion_request_error", RATE_LIMIT_MESSAGE, 400, RATE_LIMIT),
        ("completion_request_error", OVERLOADED_MESSAGE, 400, RATE_LIMIT),
        ("too_many_requests", "slow down", 429, RATE_LIMIT),
        ("completion_request_error", CREDIT_EXHAUSTED_MESSAGE, 400, CREDIT_EXHAUSTED),
        ("provider_quota_exceeded", "quota bitdi", 400, CREDIT_EXHAUSTED),
        ("unauthorized", "Access token is invalid", 401, AUTH),
        ("provider_not_initialize", "model provider yoxdur", 400, AUTH),
        (
            "completion_request_error",
            "[models] Error code: 401 - {'type': 'authentication_error'}",
            400,
            AUTH,
        ),
        ("invalid_param", "user is required", 400, BAD_REQUEST),
        ("some_new_dify_code", "gözlənilməyən", 500, UNKNOWN),
        ("stream_timeout", "", None, UNKNOWN),
    ],
)
def test_each_class_is_recognised(code, message, status, expected):
    assert classify_failure(code=code, message=message, status=status) == expected


def test_only_rate_limit_is_retryable():
    """Siyahını genişləndirmək = pul yandırmaq. Müqavilə testdə kilidlənir."""
    assert RETRYABLE == {RATE_LIMIT}
    assert CREDIT_EXHAUSTED not in RETRYABLE and AUTH not in RETRYABLE


def test_old_artifacts_are_classified_retroactively():
    """`full-run-03` (schema 2, `error_class` YOXDUR) bugünkü sinfi alır."""
    old = AgentResponse.from_dict(
        {
            "text": "",
            "error": "completion_request_error",
            "raw": {"dify_error": {"code": "completion_request_error",
                                   "message": CREDIT_EXHAUSTED_MESSAGE}},
        }
    )
    assert old.error_class is None            # köhnə artefaktda sahə yoxdur
    assert reason_for_response(old) == CREDIT_EXHAUSTED


def test_multi_turn_reason_is_read_from_the_failing_turn():
    """Çoxnövbəli cavabın birləşmiş `raw`-ında `dify_error` YOXDUR.

    `full-run-03`-də məhz buna görə bir case səbəbsiz ("unknown") görünürdü,
    halbuki zənciri qıran növbənin xətası kredit xətası idi.
    """
    merged = AgentResponse.from_dict(
        {
            "text": "",
            "error": "completion_request_error",
            "raw": {"multi_turn": True, "turn_errors": ["completion_request_error"]},
            "turns": [
                {
                    "text": "",
                    "error": "completion_request_error",
                    "raw": {"dify_error": {"code": "completion_request_error",
                                           "message": CREDIT_EXHAUSTED_MESSAGE}},
                }
            ],
        }
    )
    assert reason_for_response(merged) == CREDIT_EXHAUSTED


def test_no_error_means_no_reason():
    assert reason_for_response(AgentResponse(text="ok")) is None


# =========================================================== 2. backoff
@pytest.mark.asyncio
async def test_rate_limit_is_retried_with_growing_backoff_then_succeeds(server):
    """DoD: mock 429 qaytarır -> adapter geri çəkilir -> sonra UĞUR qazanır."""
    server.scripted["sıx sual"] = {
        "error": ("too_many_requests", RATE_LIMIT_MESSAGE, 429),
        "times": 2,  # ilk 2 sorğu 429, üçüncüsü normal
        "answer": "Qaytarma pəncərəsi 30 gündür.",
    }
    response = await _adapter(server).invoke(_req("sıx sual"))

    assert response.error is None, "hədəf özünə gəldi — case skipped QALMAMALIDIR"
    assert "30 gün" in response.text
    assert len(server.request_log) == 3
    assert response.attempts == 3
    waits = response.raw["retry_waits_s"]
    assert len(waits) == 2
    assert waits[1] > waits[0], f"backoff eksponensial olmalıdır: {waits}"


@pytest.mark.asyncio
async def test_overloaded_529_is_treated_as_rate_limit(server):
    """529 (overloaded) da gözləməklə keçir — 429 ilə eyni yolla."""
    server.scripted["yüklü"] = {
        "error_event": ("completion_request_error", OVERLOADED_MESSAGE, 400),
        "times": 1,
        "answer": "hazır cavab",
    }
    response = await _adapter(server).invoke(_req("yüklü sual"))
    assert response.error is None
    assert len(server.request_log) == 2


@pytest.mark.asyncio
async def test_retry_after_header_is_respected(server):
    """Hədəf nə qədər gözləməyi ÖZÜ deyirsə, bizim təxminimiz yox, ONUN rəqəmi."""
    server.scripted["gözlə"] = {
        "error": ("too_many_requests", RATE_LIMIT_MESSAGE, 429),
        "times": 1,
        "retry_after": "0.05",
        "answer": "ok",
    }
    response = await _adapter(server, backoff_base_s=10.0).invoke(_req("gözlə"))
    assert response.error is None
    # 10 s eksponensial yox, başlıqdakı 0.05 s tətbiq olundu
    assert response.raw["retry_waits_s"] == [0.05]


@pytest.mark.asyncio
async def test_exhausted_retries_stay_skipped_but_named_rate_limit(server):
    """N cəhddən sonra da alınmırsa case `skipped` qalır — AMMA səbəbi ilə.

    Əvvəl bu hal `completion_request_error` yığınında itirdi; indi hesabatda
    `rate_limit` kimi ayrıca sayılır və "gözləmək lazımdır" qərarı görünür.
    """
    server.scripted["dayanmayan"] = {
        "error": ("too_many_requests", RATE_LIMIT_MESSAGE, 429)
    }
    response = await _adapter(server, max_rate_limit_retries=2).invoke(_req("dayanmayan"))

    assert response.error == "too_many_requests"
    assert response.error_class == RATE_LIMIT
    assert response.raw["retry_exhausted"] is True
    assert len(server.request_log) == 3
    assert response.attempts == 3


# ================================================== 3. gözləməklə keçməyənlər
@pytest.mark.asyncio
async def test_credit_exhausted_is_not_retried_at_all(server):
    """AYRICA yoxlanır: kredit xətasında YENİDƏN CƏHD YOXDUR.

    Hər təkrar pul və vaxt yandırır və heç vaxt keçmir. `full-run-03`-də
    `--repeat 3` ilə 25 case × 3 = 75 belə sorğu getdi.
    """
    server.scripted["kredit"] = {
        "error_event": ("completion_request_error", CREDIT_EXHAUSTED_MESSAGE, 400)
    }
    before = len(server.request_log)
    response = await _adapter(server).invoke(_req("kredit sualı", case_id="case-kredit"))

    assert len(server.request_log) - before == 1, "kredit xətası TƏKRARLANMAMALIDIR"
    assert response.attempts == 1
    assert "retry_waits_s" not in response.raw
    assert response.error_class == CREDIT_EXHAUSTED


@pytest.mark.asyncio
async def test_auth_error_is_not_retried(server):
    """Açar səhvdirsə gözləmək kömək etmir — dərhal dayanırıq."""
    adapter = create_adapter(
        "dify_http", base_url=server.base_url, api_key="app-yanlis", backoff_base_s=0.01
    )
    response = await adapter.invoke(_req("istənilən"))
    assert response.error == "unauthorized"
    assert response.error_class == AUTH
    # 401 stub-da `request_log`-a düşmür (auth yoxlaması gövdədən əvvəldir),
    # ona görə cəhd sayı adapterin öz qeydindən yoxlanılır.
    assert response.attempts == 1
    assert "retry_waits_s" not in response.raw


@pytest.mark.asyncio
async def test_credit_exhausted_halts_the_whole_run(server):
    """Növbəti case-lər hədəfə GÖNDƏRİLMİR — səbəb hədəfdə deyil, hesabdadır."""
    server.scripted["kredit"] = {
        "error_event": ("completion_request_error", CREDIT_EXHAUSTED_MESSAGE, 400)
    }
    adapter = _adapter(server)
    await adapter.invoke(_req("kredit sualı", case_id="case-01"))

    assert HALT.tripped and HALT.reason == CREDIT_EXHAUSTED
    assert HALT.case_id == "case-01"

    sent = len(server.request_log)
    later = await adapter.invoke(_req("tamam başqa sual", case_id="case-02"))
    assert len(server.request_log) == sent, "qaçış dayanıb — sorğu getməməlidir"
    assert later.error == "halted:credit_exhausted"
    assert later.error_class == CREDIT_EXHAUSTED
    assert later.raw["request_sent"] is False
    assert later.raw["halt_first_case"] == "case-01"


@pytest.mark.asyncio
async def test_rate_limit_does_not_halt_the_run(server):
    """Rate limit keçicidir — qaçışı dayandırmır."""
    server.scripted["sıx"] = {"error": ("too_many_requests", RATE_LIMIT_MESSAGE, 429)}
    await _adapter(server, max_rate_limit_retries=1).invoke(_req("sıx sual"))
    assert not HALT.tripped
