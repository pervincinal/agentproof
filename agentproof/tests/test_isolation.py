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
