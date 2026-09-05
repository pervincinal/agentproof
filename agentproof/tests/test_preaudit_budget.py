"""Ön-audit sorğu büdcəsi HƏQİQƏTƏN sorğunu dayandırırmı (AP-054).

`site/rules.html` üçüncü qaydası ictimai vəddir: ≤ 30 sorğu. Vədi sənəddə
saxlamaq kifayət deyil, ona görə bu testlər hasarın özünü sınayır — sayğacın
artdığını yox, **sorğunun getmədiyini**.

`callable` adapteri seçilib, çünki `dify_http` və `json_http` ilə eyni
`send_with_retry` yolundan keçir, amma şəbəkə tələb etmir: hədəfə neçə sorğu
çatdığını birbaşa saymaq olur.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentproof.adapters import create_adapter
from agentproof.types import AgentRequest
from agentproof.failure import HALT
from agentproof.preaudit import BUDGET, BUDGET_EXHAUSTED, RequestBudget


@pytest.fixture(autouse=True)
def _clean_state():
    BUDGET.reset()
    HALT.reset()
    yield
    BUDGET.reset()
    HALT.reset()


def _counting_adapter():
    """Hədəfə çatan sorğuları sayan adapter — sayğac hasarın o üzündədir."""
    hits: list[str] = []

    def fn(query: str, conversation_id: str | None = None) -> dict:
        hits.append(query)
        return {"reply": f"cavab {len(hits)}"}

    return create_adapter("callable", fn=fn, text_path="reply"), hits


async def _ask(adapter, n: int) -> list:
    out = []
    for i in range(n):
        req = AgentRequest(
            messages=[{"role": "user", "content": f"sual {i}"}],
            session_id=f"s{i}",
            metadata={"case_id": f"c{i}"},
        )
        out.append(await adapter.invoke(req))
    return out


@pytest.mark.asyncio
async def test_requests_stop_at_the_budget_not_merely_counted() -> None:
    adapter, hits = _counting_adapter()
    BUDGET.arm(3)

    responses = await _ask(adapter, 6)

    # Əsas iddia: hədəf 6 yox, 3 sorğu gördü.
    assert len(hits) == 3, "büdcə aşıldıqdan sonra sorğu GÖNDƏRİLİB"
    assert BUDGET.spent == 3 and BUDGET.remaining == 0
    assert BUDGET.exceeded is True
    # Artıq sorğular səssiz keçmir — hər biri xəta ilə qayıdır.
    assert all(r.error is not None for r in responses[3:])


@pytest.mark.asyncio
async def test_exhausted_budget_halts_the_run_with_its_own_reason() -> None:
    adapter, _ = _counting_adapter()
    BUDGET.arm(1)

    await _ask(adapter, 3)

    assert HALT.tripped
    assert HALT.reason == BUDGET_EXHAUSTED
    assert "1/1" in HALT.detail


@pytest.mark.asyncio
async def test_budget_is_shared_across_invocations_through_the_file(tmp_path) -> None:
    """İki mərhələli ön-audit büdcəni bölüşür — yoxsa 30 vədi 60 olur."""
    path = tmp_path / "budget.json"

    adapter_a, hits_a = _counting_adapter()
    BUDGET.arm(4, path)
    await _ask(adapter_a, 3)
    assert len(hits_a) == 3

    # İkinci çağırış — yeni proses kimi.
    BUDGET.reset()
    HALT.reset()
    adapter_b, hits_b = _counting_adapter()
    BUDGET.arm(4, path)
    assert BUDGET.spent == 3, "fayldan oxunmadı — büdcə sıfırlandı"

    await _ask(adapter_b, 3)
    assert len(hits_b) == 1, "ikinci çağırış büdcəni yenidən xərclədi"

    stored = json.loads(pathlib.Path(path).read_text())
    assert stored["spent"] == 4 and stored["limit"] == 4


@pytest.mark.asyncio
async def test_unarmed_budget_does_not_touch_normal_runs() -> None:
    """Adi audit qaçışı bu moduldan təsirlənmir."""
    adapter, hits = _counting_adapter()
    await _ask(adapter, 5)
    assert len(hits) == 5
    assert not HALT.tripped
    assert BUDGET.armed is False


def test_budget_rejects_a_meaningless_limit() -> None:
    with pytest.raises(ValueError):
        RequestBudget().arm(0)


def test_published_rule_and_default_agree() -> None:
    """Saytdakı rəqəm dəyişsə, bu test onu görməlidir."""
    rules = (pathlib.Path(__file__).resolve().parents[2] / "site" / "rules.html").read_text()
    assert "thirty requests" in rules
    run_py = (pathlib.Path(__file__).resolve().parents[2] / "evals" / "run.py").read_text()
    assert "else 30" in run_py, "profil defoltu dərc olunmuş 30 həddi ilə uyğun deyil"
