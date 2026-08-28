"""AP-026 — xərc uçotunun kor nöqtəsi: sınan sorğu da token yandırır.

Faktiki qeydlər **$23.72** göstərirdi, hesabdan isə ~**$40** getmişdi. Səbəb:
`skipped` case-in `cost_usd`-i `null` yazılırdı, sanki sorğu göndərilməyib.
`full-run-03`-də belə 75 sorğu var idi.

Müştəri auditində "audit sizə nə qədər başa gəlir?" sualına "təxminən" cavabı
qəbuledilməzdir. Ona görə üç rəqəm AYRI saxlanılır və üçüncüsü SIFIR KİMİ
göstərilə bilməz:

    cost_usd            uğurlu cəhdlər
    wasted_cost_usd     uğursuz cəhdlər, ÖLÇÜLƏN
    unmeasured_attempts uğursuz cəhdlər, `usage` YOX -> NAMƏLUM
"""

from __future__ import annotations

import datetime

import pytest

from agentproof.adapters import create_adapter
from agentproof.pricing.table import load_prices
from agentproof.report.cost import account_case, coverage, summary_line
from agentproof.report.pr_comment import render_console
from agentproof.testing.mock_dify import (
    CREDIT_EXHAUSTED_MESSAGE,
    RATE_LIMIT_MESSAGE,
    MockDifyServer,
)
from agentproof.types import AgentRequest, AgentResponse, CaseResult, GradeResult, RunRecord, Usage

DAY = datetime.date(2026, 8, 27)
MODEL = "claude-sonnet-5"


@pytest.fixture
def prices():
    return load_prices()


def _usage(inp: int = 1000, out: int = 100) -> Usage:
    return Usage(input_tokens=inp, output_tokens=out, model=MODEL)


def _ok(**kw) -> AgentResponse:
    return AgentResponse(text="ok", usage=_usage(), **kw)


def _failed(usage: Usage | None = None, **kw) -> AgentResponse:
    return AgentResponse(
        text="", usage=usage, error="completion_request_error", error_class="rate_limit", **kw
    )


# ============================================== 1. sınan cəhd xərci İTMİR
def test_failed_attempt_with_usage_is_counted_as_wasted_not_dropped(prices):
    """DoD: sınan case `usage` qaytaranda xərc itmir."""
    account = account_case([_failed(usage=_usage(500, 20))], prices, DAY)

    assert account.wasted_cost_usd > 0
    assert account.cost_usd is None, "uğursuz cəhd 'uğurlu xərc' kimi sayılmamalıdır"
    assert account.unmeasured_attempts == 0


def test_failed_attempt_without_usage_is_unmeasured_not_zero(prices):
    """`full-run-03`-ün əsl halı: 75 sorğu sındı, heç birində `usage` yoxdur.

    Bunu 0.00 kimi göstərmək yalan olardı — rəqəm inandırıcı görünüb səhv
    olardı. Ona görə ayrıca sayılır.
    """
    account = account_case([_failed(), _failed(), _failed()], prices, DAY)

    assert account.wasted_cost_usd == 0.0
    assert account.unmeasured_attempts == 3
    assert coverage([account])["status"] == "unmeasured"
    assert coverage([account])["direction"] == "understates"


def test_successful_and_wasted_costs_do_not_mix(prices):
    """`--repeat 3`: 2 cavab uğurlu, 1 sındı (amma tokeni var)."""
    account = account_case(
        [_ok(), _ok(), _failed(usage=_usage(400, 10))], prices, DAY
    )
    ok_only = account_case([_ok(), _ok()], prices, DAY)

    assert account.cost_usd == pytest.approx(ok_only.cost_usd)
    assert account.wasted_cost_usd > 0
    assert coverage([account])["status"] == "complete"


def test_discarded_backoff_attempts_are_charged_as_wasted(prices):
    """Backoff-da atılan cəhdin tokenləri də yanmış puldur (AP-024 ilə əlaqə)."""
    response = _ok(attempts=3, retry_usage=Usage(input_tokens=2000, output_tokens=50, model=MODEL))
    response.raw = {"measured_retries": 2}
    account = account_case([response], prices, DAY)

    assert account.cost_usd is not None and account.cost_usd > 0
    assert account.wasted_cost_usd > 0
    assert account.attempts == 3
    assert account.unmeasured_attempts == 0


def test_discarded_attempts_without_usage_are_unmeasured(prices):
    """Təkrar cəhdlər olub, tokenləri bilinmirsə — NAMƏLUM, sıfır deyil."""
    response = _failed(attempts=4)
    response.raw = {"measured_retries": 0}
    account = account_case([response], prices, DAY)

    assert account.wasted_cost_usd == 0.0
    assert account.unmeasured_attempts == 4  # 1 son cəhd + 3 atılmış
    assert account.attempts == 4


def test_halted_case_costs_nothing_and_is_not_called_unmeasured(prices):
    """Qaçış dayandırılandan sonrakı case-lər hədəfə GÖNDƏRİLMİR (AP-024).

    Onları "ölçülməyən xərc" saymaq da yalan olardı: ölçüləcək bir şey yoxdur.
    """
    halted = AgentResponse(
        text="", error="halted:credit_exhausted", error_class="credit_exhausted",
        attempts=0, raw={"halted": True, "request_sent": False},
    )
    account = account_case([halted, halted], prices, DAY)
    assert account.attempts == 0
    assert account.unmeasured_attempts == 0
    assert account.wasted_cost_usd == 0.0
    assert account.cost_usd is None


def test_partial_coverage_is_named_partial(prices):
    ok = account_case([_ok()], prices, DAY)
    lost = account_case([_failed()], prices, DAY)
    cov = coverage([ok, lost])
    assert cov["status"] == "partial"
    assert cov["measured_attempts"] == 1 and cov["unmeasured_attempts"] == 1
    assert "NAMƏLUM" in cov["note"] or "naməlum" in cov["note"].lower()


def test_cost_without_model_label_stays_unmeasured(prices):
    """Model etiketi yoxdursa dollar hesablanmır — bu, sıfır DEYİL."""
    account = account_case([AgentResponse(text="ok", usage=Usage(100, 10))], prices, DAY)
    assert account.cost_usd is None
    assert account.unmeasured_attempts == 0  # uğurlu cəhd — "yandırılmış" da deyil


# ============================================== 2. hesabatda GÖRÜNÜR
def _record(totals: dict) -> RunRecord:
    return RunRecord(
        run_id="r", target="dify_http", target_version="1.17.0", model=MODEL,
        dataset_hash="abc", started_at="2026-08-28T00:00:00",
        results=[
            CaseResult(
                case_id="c1",
                response=AgentResponse(text=""),
                grade=GradeResult.skip("regex_match", "infrastruktur xətası"),
                cost_usd=None,
                wasted_cost_usd=0.0,
                unmeasured_attempts=3,
            )
        ],
        totals=totals,
    )


def test_console_shows_successful_wasted_and_unmeasured():
    record = _record(
        {
            "n_cases": 1, "n_graded": 0, "n_passed": 0, "n_failed": 0, "n_skipped": 1,
            "pass_rate": 0.0, "cost_usd": 9.32, "wasted_cost_usd": 1.5,
            "cost_coverage": {
                "attempts": 78, "measured_attempts": 3, "unmeasured_attempts": 75,
                "status": "partial", "note": "bir hissəsi ölçülmədi", "direction": "understates",
            },
            "skipped_by_reason": {"credit_exhausted": 1},
        }
    )
    out = render_console(record)

    assert "9.3200 uğurlu" in out
    assert "1.5000 yandırılmış" in out
    assert "75/78" in out and "ölçülmədi" in out
    assert "credit_exhausted: 1" in out


def test_console_names_the_halt_reason():
    record = _record(
        {
            "cost_usd": 0.0, "wasted_cost_usd": 0.0,
            "halted": {
                "halted": True, "reason": "credit_exhausted", "case_id": "base-g7",
                "detail": "completion_request_error: credit balance too low",
                "hint": "hesabda kredit qalmayıb",
            },
        }
    )
    out = render_console(record)
    assert "QAÇIŞ DAYANDIRILDI" in out and "credit_exhausted" in out
    assert "base-g7" in out


def test_summary_line_hides_nothing():
    line = summary_line(
        {"cost_usd": 2.0, "wasted_cost_usd": 0.0,
         "cost_coverage": {"unmeasured_attempts": 75, "attempts": 75}}
    )
    assert "ÖLÇÜLMƏDİ" in line


# ============================================== 3. köhnə artefakt sınmır
def test_old_case_result_without_cost_fields_still_loads():
    """`schema_version` 1/2 artefaktları oxunmağa davam edir."""
    old = CaseResult.from_dict(
        {
            "case_id": "c",
            "response": {"text": "x"},
            "grade": {"passed": True, "score": 1.0, "grader": "contains_all", "reason": ""},
            "cost_usd": 0.01,
            "latency_ms": 10,
            "attempt": 1,
        }
    )
    assert old.wasted_cost_usd == 0.0
    assert old.unmeasured_attempts == 0
    assert old.response.attempts == 1 and old.response.retry_usage is None


# ============================================== 4. ucdan-uca (mock hədəf)
@pytest.mark.asyncio
async def test_partial_usage_survives_a_failed_stream(prices):
    """`message_end` gəldi (tokenlər yandı), sonra axın xəta ilə bitdi.

    Köhnə davranışda bu case `cost_usd: null` olurdu — yanmış pul hesabatdan
    tamamilə düşürdü.
    """
    scripted = {
        "yarımçıq": {
            "answer": "başladı",
            "error_event": ("completion_request_error", CREDIT_EXHAUSTED_MESSAGE, 400),
            "usage_before_error": True,
            "usage": {"prompt_tokens": 1500, "completion_tokens": 60},
        }
    }
    with MockDifyServer(scripted=scripted) as srv:
        adapter = create_adapter(
            "dify_http", base_url=srv.base_url, api_key=srv.api_key,
            model=MODEL, backoff_base_s=0.01,
        )
        response = await adapter.invoke(
            AgentRequest(messages=[{"role": "user", "content": "yarımçıq sual"}], session_id="s")
        )

    assert response.error is not None
    assert response.usage is not None, "gələn `usage` xəta ucbatından atılmamalıdır"
    account = account_case([response], prices, DAY)
    assert account.wasted_cost_usd > 0
    assert account.cost_usd is None


@pytest.mark.asyncio
async def test_burned_tokens_of_retried_attempts_are_kept(prices):
    """Backoff-da atılan cəhd `usage` qaytarıbsa, tokeni hesabatda qalır."""
    scripted = {
        "sıx": {
            "error_event": ("completion_request_error", RATE_LIMIT_MESSAGE, 400),
            "usage_before_error": True,
            "usage": {"prompt_tokens": 800, "completion_tokens": 30},
            "times": 1,
            "answer": "nəhayət cavab",
        }
    }
    with MockDifyServer(scripted=scripted) as srv:
        adapter = create_adapter(
            "dify_http", base_url=srv.base_url, api_key=srv.api_key,
            model=MODEL, backoff_base_s=0.01,
        )
        response = await adapter.invoke(
            AgentRequest(messages=[{"role": "user", "content": "sıx sual"}], session_id="s")
        )

    assert response.error is None and response.attempts == 2
    assert response.retry_usage is not None
    assert response.retry_usage.input_tokens == 800
    account = account_case([response], prices, DAY)
    assert account.cost_usd > 0 and account.wasted_cost_usd > 0
