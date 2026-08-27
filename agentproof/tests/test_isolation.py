"""Case izolyasiyası — sənədə deyil, TESTƏ güvənirik (PLAN.md "Runner tələbi").

Ssenari birbaşa PLAN.md-dəki tələdir:

    ardıcıl iki case EYNİ sifarişə `initiate_return` edir;
    ikincisi TƏMİZ vəziyyət görməlidir (`RMA_ALREADY_EXISTS` almamalıdır).

Burada saxta tool servisi YOXDUR: `target/tools/service.py`-nin ÖZÜ real
portda qaldırılır və mock Dify stub-u ona real HTTP sorğusu göndərir.
Yəni test həm runner-in `POST /admin/reset` çağırdığını, həm də bunun real
servisin vəziyyətini həqiqətən təmizlədiyini yoxlayır.

Testin özü də yoxlanılır: izolyasiya SÖNDÜRÜLƏNDƏ ikinci case SINMALIDIR.
Əks halda test boş yerə yaşıl olardı.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from inspect_ai import eval as inspect_eval

from agentproof.report.normalize import normalize_log
from agentproof.runner.isolation import ResetFailed, ToolStateReset
from agentproof.runner.task import build_task
from agentproof.testing.mock_dify import MockDifyServer

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "target" / "tools"

# T-01 baş tələsi: çatdırılmış sifariş, tək sətir (canlı sistemdə də yoxlanılıb)
ORDER_ID = "ORD-10015"
SKU = "AG-PRT-660"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _ToolService:
    """`target/tools/service.py` — real FastAPI app, real portda."""

    def __init__(self) -> None:
        import uvicorn

        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))
        import service  # type: ignore[import-not-found]

        self.port = _free_port()
        config = uvicorn.Config(
            service.app, host="127.0.0.1", port=self.port, log_level="critical"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def reset_url(self) -> str:
        return f"{self.base_url}/admin/reset"

    def start(self) -> "_ToolService":
        self._thread.start()
        deadline = threading.Event()
        for _ in range(200):
            try:
                if httpx.get(f"{self.base_url}/health", timeout=1.0).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            deadline.wait(0.05)
        raise RuntimeError("tool servisi qalxmadı")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def audit(self) -> dict[str, Any]:
        return httpx.get(f"{self.base_url}/admin/audit", timeout=5.0).json()


@pytest.fixture(scope="module")
def tools():
    service = _ToolService().start()
    try:
        yield service
    finally:
        service.stop()


def _returning_agent(tools: _ToolService) -> dict[str, dict[str, Any]]:
    """Hər sorğuda REAL `initiate_return` çağıran skript.

    Nəticə (RMA id və ya xəta kodu) cavab mətninə yazılır ki, grader onu görsün.
    """

    def call(_body: dict[str, Any]) -> dict[str, Any]:
        r = httpx.post(
            f"{tools.base_url}/tools/initiate_return",
            json={
                "order_id": ORDER_ID,
                "sku": SKU,
                "reason": "changed_mind",
                "customer_confirmed": True,
            },
            timeout=10.0,
        )
        payload = r.json()
        if r.status_code == 200:
            return {"answer": f"RMA yaradıldı: {payload['rma_id']}"}
        code = (payload.get("error") or {}).get("code") or payload.get("code", "UNKNOWN")
        return {"answer": f"Tool xətası: {code}"}

    return {
        ORDER_ID.lower(): {
            "side_effect": call,
            "tool_calls": [
                {
                    "name": "initiate_return",
                    "arguments": {"order_id": ORDER_ID, "sku": SKU},
                    "result": {"ok": True},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }
    }


def _dataset(tmp_path: Path) -> Path:
    """İki case, EYNİ sifariş — ikincisi təmiz vəziyyət görməlidir."""
    lines = [
        (
            '{"id":"iso-01","input":"%s sifarişini qaytar","grader":"contains_none",'
            '"severity":"high","expect":{"none":["RMA_ALREADY_EXISTS"]}}' % ORDER_ID
        ),
        (
            '{"id":"iso-02","input":"%s sifarişini yenə qaytar","grader":"contains_none",'
            '"severity":"high","expect":{"none":["RMA_ALREADY_EXISTS"]}}' % ORDER_ID
        ),
    ]
    path = tmp_path / "isolation.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(tools: _ToolService, tmp_path: Path, reset_url: str | None):
    httpx.post(tools.reset_url, timeout=5.0)  # qaçışdan əvvəl təmiz start
    with MockDifyServer(scripted=_returning_agent(tools)) as dify:
        task, _ = build_task(
            dataset_path=_dataset(tmp_path),
            adapter="dify_http",
            adapter_config={"base_url": dify.base_url, "api_key": dify.api_key},
            reset_url=reset_url,
        )
        logs = inspect_eval(
            task,
            model=None,
            log_dir=str(tmp_path / "logs"),
            display="none",
            log_level="error",
            # ardıcıllığı təmin etmək üçün — izolyasiyasız qaçışın sızmasını
            # deterministik göstərmək lazımdır
            max_connections=1,
            max_samples=1,
        )
    assert logs[0].status == "success", getattr(logs[0], "error", None)
    return normalize_log(logs[0], target="dify_http")


def test_second_case_sees_clean_state_when_reset_is_wired(tools, tmp_path):
    """İZOLYASİYA AKTİV: iki case eyni sifarişə RMA açır, ikisi də uğurludur."""
    record = _run(tools, tmp_path, reset_url=tools.reset_url)
    answers = [r.response.text for r in record.results]
    assert all(a.startswith("RMA yaradıldı") for a in answers), answers
    assert record.totals["n_passed"] == 2


def test_without_reset_the_second_case_is_contaminated(tools, tmp_path):
    """İZOLYASİYA YOXDUR: ikinci case `RMA_ALREADY_EXISTS` alır.

    Bu test yuxarıdakının BOŞ YAŞIL olmadığını sübut edir.
    """
    record = _run(tools, tmp_path, reset_url=None)
    answers = [r.response.text for r in record.results]
    assert answers[0].startswith("RMA yaradıldı"), answers
    assert "RMA_ALREADY_EXISTS" in answers[1], answers
    assert record.totals["n_passed"] == 1


def test_reset_is_called_once_per_attempt_and_once_after_the_case(tools, tmp_path):
    """`--repeat` ilə hər cəhd təmiz başlayır; case-dən sonra da sıfırlanır."""
    httpx.post(tools.reset_url, timeout=5.0)
    with MockDifyServer(scripted=_returning_agent(tools)) as dify:
        task, _ = build_task(
            dataset_path=_dataset(tmp_path),
            adapter="dify_http",
            adapter_config={"base_url": dify.base_url, "api_key": dify.api_key},
            filter_expr="id=iso-01",
            repeat=3,
            reset_url=tools.reset_url,
        )
        logs = inspect_eval(
            task, model=None, log_dir=str(tmp_path / "logs"), display="none",
            log_level="error", max_connections=1, max_samples=1,
        )
    assert logs[0].status == "success", getattr(logs[0], "error", None)
    record = normalize_log(logs[0], target="dify_http")
    # 3 cəhdin hər biri təmiz vəziyyət gördü -> heç birində ALREADY_EXISTS yoxdur
    assert record.totals["n_passed"] == 1
    assert record.results[0].attempt == 3


def test_task_metadata_records_whether_isolation_was_active(tools, tmp_path):
    """Hesabatda izolyasiyanın olub-olmadığı görünməlidir — gizli qalmamalıdır."""
    on, _ = build_task(_dataset(tmp_path), adapter="mock", reset_url=tools.reset_url)
    off, _ = build_task(_dataset(tmp_path), adapter="mock")
    assert on.metadata["isolation"] == "admin_reset"
    assert off.metadata["isolation"] == "none"


@pytest.mark.asyncio
async def test_failed_reset_raises_instead_of_contaminating_silently():
    """Sıfırlama alınmırsa qaçış DAYANMALIDIR — susqun davam etməməlidir."""
    resetter = ToolStateReset("http://127.0.0.1:1/admin/reset", timeout_s=1.0)
    with pytest.raises(ResetFailed, match="sıfırlanmadı"):
        await resetter.reset()


@pytest.mark.asyncio
async def test_non_200_reset_is_also_fatal(tools):
    resetter = ToolStateReset(f"{tools.base_url}/admin/bele-endpoint-yoxdur")
    with pytest.raises(ResetFailed, match="HTTP 40"):
        await resetter.reset()


# ===========================================================================
# PARALEL REJİM — lane başına tool ad sahəsi (`X-AG-Session`).
#
# Serial rejimin (yuxarıdakı testlər) zəmanəti dəyişmir; burada həmin zəmanət
# PARALEL qaçış üçün yenidən, eyni iki istiqamətdə qurulur:
#
#   müsbət — N case eyni sifarişə EYNİ ANDA RMA açır və hamısı uğurludur;
#   mənfi  — hədəf `X-AG-Session` göndərmirsə, həmin qaçış SINIR
#            (`RMA_ALREADY_EXISTS`), yəni ad sahəsi həqiqətən yükdaşıyandır.
#
# "Eyni anda" iddiası da yoxlanılır: yan təsir `threading.Barrier`-dədir.
# Lane-lər seriallaşsaydı bariyer heç vaxt dolmazdı və test qırmızı olardı.
# ===========================================================================

import re
import time

from agentproof.runner.isolation import (
    Lane,
    LaneExhausted,
    LanePool,
    build_lane_pool,
)

LANE_RE = re.compile(r"^(lane-\d+)")
BARRIER_TIMEOUT_S = 20.0


def _lane_of(body: dict[str, Any]) -> str:
    """Sorğunun hansı lane-dən gəldiyini `user` sahəsindən çıxarır.

    REALLIQDA bu ötürmə Dify-ın İÇİNDƏ olmur: `core/tools/custom_tool/tool.py`
    custom tool başlıqlarını yalnız provider credential-larından yığır, yəni
    case-dən case-ə dəyişən dəyər ötürmək mümkün deyil. Bir lane = bir Dify
    app-i, həmin app-in provider-i `X-AG-Session`-u SABİT dəyərlə göndərir.
    Burada stub həmin sabit başlığı təqlid edir.
    """
    match = LANE_RE.match(str(body.get("user", "")))
    return match.group(1) if match else "unknown"


def _concurrent_returning_agent(
    tools: _ToolService,
    parties: int,
    send_session_header: bool,
    delay_ms: int = 0,
) -> dict[str, dict[str, Any]]:
    """`parties` sorğu bariyerdə görüşür, SONRA hamısı `initiate_return` edir."""
    barrier = threading.Barrier(parties)

    def call(body: dict[str, Any]) -> dict[str, Any]:
        lane = _lane_of(body)
        try:
            barrier.wait(timeout=BARRIER_TIMEOUT_S)
        except threading.BrokenBarrierError:
            return {"answer": "BARIYER DOLMADI — lane-lər paralel qaçmadı"}
        headers = {"X-AG-Session": lane} if send_session_header else {}
        r = httpx.post(
            f"{tools.base_url}/tools/initiate_return",
            json={
                "order_id": ORDER_ID,
                "sku": SKU,
                "reason": "changed_mind",
                "customer_confirmed": True,
            },
            headers=headers,
            timeout=10.0,
        )
        payload = r.json()
        if r.status_code == 200:
            return {"answer": f"RMA yaradıldı: {payload['rma_id']} ({lane})"}
        code = (payload.get("error") or {}).get("code") or payload.get("code", "UNKNOWN")
        return {"answer": f"Tool xətası: {code} ({lane})"}

    spec: dict[str, Any] = {
        "side_effect": call,
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    if delay_ms:
        spec["delay_ms"] = delay_ms
    return {ORDER_ID.lower(): spec}


def _parallel_dataset(tmp_path: Path, n: int, name: str = "parallel") -> Path:
    lines = [
        '{"id":"par-%02d","input":"%s sifarişini qaytar","grader":"contains_none",'
        '"severity":"high","expect":{"none":["RMA_ALREADY_EXISTS"]}}' % (i, ORDER_ID)
        for i in range(1, n + 1)
    ]
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _lane_specs(tools: _ToolService, n: int) -> list[dict[str, Any]]:
    return [
        {
            "name": f"lane-{i}",
            "tool_reset_url": tools.reset_url,
            "tool_session": f"lane-{i}",
            # lane-ə xas hədəf konfiqurasiyası: realda həmin lane-in Dify
            # app-inin API açarı olardı.
            "adapter": {"user": f"lane-{i}"},
        }
        for i in range(1, n + 1)
    ]


def _run_parallel(
    tools: _ToolService,
    tmp_path: Path,
    n_lanes: int,
    n_cases: int,
    send_session_header: bool = True,
    parties: int | None = None,
    delay_ms: int = 0,
    dataset_name: str = "parallel",
):
    httpx.post(tools.reset_url, params={"all": "true"}, timeout=5.0)
    scripted = _concurrent_returning_agent(
        tools, parties if parties is not None else n_lanes, send_session_header, delay_ms
    )
    with MockDifyServer(scripted=scripted) as dify:
        task, _ = build_task(
            dataset_path=_parallel_dataset(tmp_path, n_cases, dataset_name),
            adapter="dify_http",
            adapter_config={"base_url": dify.base_url, "api_key": dify.api_key},
            lanes=_lane_specs(tools, n_lanes),
        )
        started = time.perf_counter()
        logs = inspect_eval(
            task,
            model=None,
            log_dir=str(tmp_path / f"logs-{dataset_name}"),
            display="none",
            log_level="error",
            max_connections=n_lanes,
            max_samples=n_lanes,
        )
        elapsed = time.perf_counter() - started
    assert logs[0].status == "success", getattr(logs[0], "error", None)
    return normalize_log(logs[0], target="dify_http"), elapsed


def test_parallel_lanes_all_see_clean_state(tools, tmp_path):
    """MÜSBƏT: 3 case EYNİ ANDA eyni sifarişə RMA açır və üçü də uğurludur.

    Bariyer sübut edir ki, üçü həqiqətən eyni anda tool servisindədir; ad
    sahəsi sübut edir ki, bu, bir-birini korlamır.
    """
    record, _ = _run_parallel(tools, tmp_path, n_lanes=3, n_cases=3)
    answers = [r.response.text for r in record.results]
    assert all(a.startswith("RMA yaradıldı") for a in answers), answers
    assert record.totals["n_passed"] == 3


def test_parallel_lanes_leak_without_the_session_header(tools, tmp_path):
    """MƏNFİ: hədəf `X-AG-Session` göndərmirsə, hamısı `default`-a düşür və sınır.

    Bu test yuxarıdakının BOŞ YAŞIL olmadığını sübut edir: paralelliyi
    təhlükəsiz edən ad sahəsidir, təsadüf deyil.
    """
    record, _ = _run_parallel(
        tools, tmp_path, n_lanes=3, n_cases=3,
        send_session_header=False, dataset_name="leak",
    )
    answers = [r.response.text for r in record.results]
    contaminated = [a for a in answers if "RMA_ALREADY_EXISTS" in a]
    assert len(contaminated) == 2, answers
    assert record.totals["n_passed"] == 1


def test_parallel_lanes_reuse_after_reset(tools, tmp_path):
    """Lane-lər case-dən çox olduqda təkrar istifadə olunur və hər dəfə təmizdir.

    6 case / 3 lane: hər lane iki dəfə işlədilir. İkinci dövrədə də
    `RMA_ALREADY_EXISTS` görünməməlidir — yəni lane qaytarılanda ad sahəsi
    həqiqətən sıfırlanıb.
    """
    record, _ = _run_parallel(
        tools, tmp_path, n_lanes=3, n_cases=6, parties=3, dataset_name="reuse"
    )
    answers = [r.response.text for r in record.results]
    assert all(a.startswith("RMA yaradıldı") for a in answers), answers
    assert record.totals["n_passed"] == 6


def test_parallel_run_is_measurably_faster_than_serial(tools, tmp_path):
    """6 dəqiqə qaydası: lane sayı wall-clock-u həqiqətən bölməlidir."""
    _, serial = _run_parallel(
        tools, tmp_path, n_lanes=1, n_cases=8, parties=1,
        delay_ms=500, dataset_name="serial-timing",
    )
    _, parallel = _run_parallel(
        tools, tmp_path, n_lanes=4, n_cases=8, parties=4,
        delay_ms=500, dataset_name="parallel-timing",
    )
    # 8 case / 4 lane -> nəzəri nisbət 0.25. Hədd 0.6 qoyulur ki, yüklü CI
    # maşınında flaky olmasın; canlı sistemdə ölçülən real nisbət
    # `docs/STACK.md §12.1`-dədir (85 s -> 22 s, 5 lane).
    assert parallel < serial * 0.6, f"serial={serial:.2f}s parallel={parallel:.2f}s"


def test_pool_refuses_two_lanes_on_the_same_namespace(tools):
    """Konfiqurasiya səhvi qaçış BAŞLAMAZDAN ƏVVƏL tutulur.

    İki lane eyni ad sahəsini bölüşsəydi, biri digərinin işləyən vəziyyətini
    silərdi — susqun sızma. Ona görə bu, xətadır, xəbərdarlıq deyil.
    """
    with pytest.raises(ValueError, match="ad sahəsini bölüşür"):
        build_lane_pool([
            {"name": "a", "tool_reset_url": tools.reset_url, "tool_session": "ns"},
            {"name": "b", "tool_reset_url": tools.reset_url, "tool_session": "ns"},
        ])


def test_pool_refuses_multiple_lanes_without_isolation(tools):
    with pytest.raises(ValueError, match="`tool_reset_url`-i olmalıdır"):
        build_lane_pool([{"name": "a", "tool_reset_url": tools.reset_url,
                          "tool_session": "ns"},
                         {"name": "b"}])


def test_single_lane_pool_is_the_old_behaviour(tools):
    pool = build_lane_pool(None, tools.reset_url)
    assert pool.size == 1
    assert pool.isolated
    assert pool.lanes[0].session is None  # başlıqsız = `default` ad sahəsi


@pytest.mark.asyncio
async def test_reset_is_scoped_to_its_own_namespace(tools):
    """Lane A-nın sıfırlaması lane B-nin vəziyyətinə TOXUNMAMALIDIR."""
    httpx.post(tools.reset_url, params={"all": "true"}, timeout=5.0)
    body = {"order_id": ORDER_ID, "sku": SKU, "reason": "changed_mind",
            "customer_confirmed": True}
    for lane in ("ns-a", "ns-b"):
        r = httpx.post(f"{tools.base_url}/tools/initiate_return", json=body,
                       headers={"X-AG-Session": lane}, timeout=5.0)
        assert r.status_code == 200

    await ToolStateReset(tools.reset_url, session="ns-a").reset()

    again_a = httpx.post(f"{tools.base_url}/tools/initiate_return", json=body,
                         headers={"X-AG-Session": "ns-a"}, timeout=5.0)
    again_b = httpx.post(f"{tools.base_url}/tools/initiate_return", json=body,
                         headers={"X-AG-Session": "ns-b"}, timeout=5.0)
    assert again_a.status_code == 200, "ns-a sıfırlanmalı idi"
    assert again_b.status_code == 409, "ns-b-yə toxunulmamalı idi"


@pytest.mark.asyncio
async def test_a_lane_whose_reset_failed_is_retired_not_reused(tools):
    """Sıfırlanmayan lane bir daha case-ə VERİLMİR.

    Əks halda ilk sıfırlama xətasından sonra hər növbəti case çirkli ad
    sahəsində qaçardı və hesabat yaşıl görünə bilərdi.
    """
    broken = Lane(name="lane-1", resetter=ToolStateReset(
        "http://127.0.0.1:1/admin/reset", timeout_s=0.5, session="lane-1"))
    pool = LanePool([broken])

    with pytest.raises(ResetFailed):
        async with pool.lease():
            pass
    assert broken.dead

    with pytest.raises(LaneExhausted):
        async with pool.lease():
            pass


@pytest.mark.asyncio
async def test_task_metadata_reports_lane_count(tools, tmp_path):
    task, _ = build_task(
        _parallel_dataset(tmp_path, 2, "meta"),
        adapter="mock",
        lanes=[{"name": f"lane-{i}", "tool_reset_url": tools.reset_url,
                "tool_session": f"lane-{i}"} for i in (1, 2, 3)],
    )
    assert task.metadata["isolation"] == "admin_reset"
    assert task.metadata["lanes"] == 3
    assert task.metadata["lane_sessions"] == ["lane-1", "lane-2", "lane-3"]


# ===========================================================================
# ÇOXNÖVBƏLİ CASE × LANE × SIFIRLAMA
#
# İki tələb burada bağlanır:
#   (3) çoxnövbəli case BÜTÖV bir lane-də qalır — növbələri fərqli ad
#       sahələrinə dağılmır;
#   (4) `/admin/reset` case-in ƏVVƏLİNDƏ çağırılır, növbələr ARASINDA YOX.
#       Növbələr arasında sıfırlansaydı, söhbətin ortasında tool vəziyyəti
#       silinərdi və agent SÜNİ uğursuzluq alardı — ölçmə yalan olardı.
# ===========================================================================

MT_TURNS = 3


def _multi_turn_writing_agent(tools: _ToolService) -> dict[str, dict[str, Any]]:
    """Hər növbədə REAL `initiate_return` çağırır və nəticəni cavaba yazır.

    Söhbət id-si üzrə növbə sayılır; `user`-dən lane ad sahəsi çıxarılır
    (realda bunu lane-in Dify app-inin sabit provider başlığı edir).
    """
    turns: dict[str, int] = {}
    #: (söhbət -> hansı ad sahələrində görüldü) — lane bütövlüyünün sübutu
    seen_sessions: dict[str, set[str]] = {}

    def call(body: dict[str, Any]) -> dict[str, Any]:
        conv = str(body.get("conversation_id") or "")
        lane = _lane_of(body)
        index = turns[conv] = turns.get(conv, 0) + 1
        seen_sessions.setdefault(conv, set()).add(lane)

        r = httpx.post(
            f"{tools.base_url}/tools/initiate_return",
            json={"order_id": ORDER_ID, "sku": SKU,
                  "reason": "changed_mind", "customer_confirmed": True},
            headers={"X-AG-Session": lane},
            timeout=10.0,
        )
        payload = r.json()
        if r.status_code == 200:
            return {"answer": f"növbə {index}: RMA yaradıldı {payload['rma_id']}"}
        code = (payload.get("error") or {}).get("code") or payload.get("code", "UNKNOWN")
        return {"answer": f"növbə {index}: Tool xətası {code}"}

    scripted = {"": {"side_effect": call,
                     "usage": {"prompt_tokens": 50, "completion_tokens": 10}}}
    scripted[""]["_sessions"] = seen_sessions  # testin oxuması üçün
    return scripted


def _multi_turn_dataset(tmp_path: Path, n_cases: int, name: str) -> Path:
    turns = ", ".join(
        '{"role":"user","content":"%s növbə %d"}' % (ORDER_ID, i + 1)
        for i in range(MT_TURNS)
    )
    lines = [
        '{"id":"mt-%02d","input":[%s],"grader":"contains_none","severity":"high",'
        '"expect":{"none":["HEC-VAXT-OLMAYAN-IFADE"]},"tags":["multi-turn"]}'
        % (i, turns)
        for i in range(1, n_cases + 1)
    ]
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run_multi_turn(tools: _ToolService, tmp_path: Path, n_lanes: int, n_cases: int,
                    name: str):
    httpx.post(tools.reset_url, params={"all": "true"}, timeout=5.0)
    scripted = _multi_turn_writing_agent(tools)
    sessions = scripted[""].pop("_sessions")
    with MockDifyServer(scripted=scripted) as dify:
        task, _ = build_task(
            dataset_path=_multi_turn_dataset(tmp_path, n_cases, name),
            adapter="dify_http",
            adapter_config={"base_url": dify.base_url, "api_key": dify.api_key},
            lanes=_lane_specs(tools, n_lanes),
        )
        logs = inspect_eval(task, model=None, log_dir=str(tmp_path / f"logs-{name}"),
                            display="none", log_level="error",
                            max_connections=n_lanes, max_samples=n_lanes)
    assert logs[0].status == "success", getattr(logs[0], "error", None)
    return normalize_log(logs[0], target="dify_http"), sessions


def test_tool_state_is_not_reset_between_turns_of_one_case(tools, tmp_path):
    """Söhbətin ORTASINDA sıfırlama YOXDUR: 1-ci növbənin yaratdığı RMA 3-cü
    növbədə hələ də oradadır.

    Əks halda agent öz yaratdığı RMA-nı "yoxdur" görərdi — bu, hədəfin səhvi
    deyil, harness-in uydurduğu uğursuzluq olardı.
    """
    record, _ = _run_multi_turn(tools, tmp_path, n_lanes=1, n_cases=1, name="mt-single")
    texts = record.results[0].response.turn_texts
    assert len(texts) == MT_TURNS, texts
    assert "RMA yaradıldı" in texts[0], texts
    assert "RMA_ALREADY_EXISTS" in texts[1], texts
    assert "RMA_ALREADY_EXISTS" in texts[2], texts


def test_next_case_still_starts_clean_after_a_multi_turn_case(tools, tmp_path):
    """Case-lər arasında sıfırlama qalır: 2-ci case yenidən təmiz başlayır."""
    record, _ = _run_multi_turn(tools, tmp_path, n_lanes=1, n_cases=2, name="mt-two")
    for result in record.results:
        assert "RMA yaradıldı" in result.response.turn_texts[0], result.response.turn_texts


def test_all_turns_of_a_case_stay_in_one_lane(tools, tmp_path):
    """Bir söhbətin bütün növbələri EYNİ ad sahəsində olmalıdır.

    Növbələr fərqli lane-lərə düşsəydi, agent öz yaratdığı vəziyyəti itirərdi
    və çoxnövbəli ölçmə mənasız olardı.
    """
    record, sessions = _run_multi_turn(tools, tmp_path, n_lanes=3, n_cases=6,
                                       name="mt-lanes")
    assert len(record.results) == 6
    assert sessions, "heç bir söhbət qeydə alınmadı"
    for conversation, lanes in sessions.items():
        assert len(lanes) == 1, f"{conversation}: növbələr {lanes} lane-lərinə dağıldı"
    # hər case bütöv qaldığı üçün 2-ci növbə həmişə öz RMA-sını görür
    for result in record.results:
        assert "RMA_ALREADY_EXISTS" in result.response.turn_texts[1]
