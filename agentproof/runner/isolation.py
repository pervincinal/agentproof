"""Case izolyasiyası — hədəfin tool servisinin vəziyyəti sıfırlanır.

PLAN.md "⚠️ Runner tələbi — İZOLYASİYA":

> Hər case-dən sonra `POST /admin/reset` çağırılmalıdır. Əks halda case *n*-də
> yaradılan RMA case *n+1*-də `RMA_ALREADY_EXISTS` verər və nəticələr
> bir-birinə sızar. Bu, orta qaçışda susqun korlanmaya gətirir.

**Nə dəyişdi (sürət düzəlişi).** Əvvəl sıfırlama QLOBAL idi: tool servisinin
vəziyyəti bütün case-lər üçün bir idi, ona görə `reset + invoke` cütü bütün
qaçışı seriallaşdırırdı — ölçülən 7.3 s/case, 450 sorğu ≈ 55 dəqiqə, yəni
harness-in 6 dəqiqə qaydasının 9 qatı.

İndi tool servisi vəziyyəti `X-AG-Session` başlığına görə AD SAHƏSİNƏ bölür
(`target/tools/service.py`). Bir *lane* = bir ad sahəsi + (lazım olduqda) öz
hədəf konfiqurasiyası. Lane-lər bir-birinə toxunmadığı üçün N lane paralel
qaçır; lane-in İÇİNDƏ `reset + invoke` hələ də ATOMİKDİR.

⚠️ Dify tərəfi (mənbədən yoxlanılıb, uydurma deyil):
`api/core/tools/custom_tool/tool.py::assembling_request` custom tool-un
başlıqlarını YALNIZ provider credential-larından yığır; `do_http_request`
əlavə olaraq yalnız openapi-də elan edilmiş `in: header` parametrlərini qoyur,
onların dəyəri isə LLM-in tool arqumentlərindən gəlir. Yəni case-dən case-ə
DƏYİŞƏN dəyəri Dify öz-özünə ötürə bilmir — nə conversation id, nə `user`.
Deməli bir lane = bir Dify app-i, həmin app-in tool provider-i `X-AG-Session`
başlığını SABİT dəyərlə göndərir. Bax `docs/STACK.md` və `target/app/IMPORT.md`.

İki zəmanət pozulmadan qalır və ikisi də açıq yazılır:

1. **Lane daxilində sıfırlama + çağırış atomikdir.** Lane pool-dan icarəyə
   götürülür, sıfırlanır, geri qaytarılır. İki case eyni ad sahəsini eyni
   vaxtda görə bilmir.
2. **Sıfırlama uğursuz olarsa qaçış DAYANIR.** Səssizcə davam etmək
   nəticələri bir-birinə qarışdırır — bu, ən pis haldır, çünki hesabat
   yaşıl görünür. Üstəlik sıfırlanmayan lane pool-dan ÇIXARILIR: çirkli
   ad sahəsi növbəti case-ə verilmir.
"""

from __future__ import annotations

import asyncio
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

#: Tool servisinin ad sahəsi başlığı — `target/tools/service.py::SESSION_HEADER`
#: ilə eyni olmalıdır.
SESSION_HEADER = "X-AG-Session"


class ResetFailed(RuntimeError):
    """Sıfırlama alınmadı — case-lər bir-birini çirkləndirə bilər."""


class ToolStateReset:
    """`POST <reset_url>` — hədəfin tool servisini fixture vəziyyətinə qaytarır.

    `session` verilirsə sıfırlama YALNIZ həmin ad sahəsini əhatə edir; başqa
    lane-in işləyən vəziyyətinə toxunmur.
    """

    def __init__(self, url: str, timeout_s: float = 10.0, session: str | None = None) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self.session = session
        self.calls = 0

    @property
    def headers(self) -> dict[str, str]:
        return {SESSION_HEADER: self.session} if self.session else {}

    def _fail(self, detail: str) -> ResetFailed:
        where = f"{self.url}" + (f" [{SESSION_HEADER}: {self.session}]" if self.session else "")
        return ResetFailed(
            f"tool servisi sıfırlanmadı ({where}): {detail}. "
            "İzolyasiya olmadan qaçış davam etməməlidir."
        )

    async def reset(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(self.url, headers=self.headers)
        except httpx.HTTPError as e:
            raise self._fail(type(e).__name__) from e
        if r.status_code != 200:
            raise self._fail(f"HTTP {r.status_code}")
        self.calls += 1


@dataclass
class Lane:
    """Bir paralel zolaq: öz ad sahəsi, öz sıfırlayıcısı, öz hədəf konfiqurasiyası.

    `adapter_config` lane-ə xas üstünləmələrdir (məs. həmin lane-in Dify
    app-inin API açarı). Boşdursa qlobal konfiqurasiya olduğu kimi işlədilir.
    """

    name: str
    resetter: ToolStateReset | None = None
    adapter_config: dict[str, Any] = field(default_factory=dict)
    #: sıfırlama uğursuz olubsa lane ÖLÜDÜR və bir daha case-ə verilmir
    dead: bool = False

    @property
    def session(self) -> str | None:
        return self.resetter.session if self.resetter else None


class LaneExhausted(ResetFailed):
    """Bütün lane-lər çirklənib — davam etmək nəticələri etibarsız edər."""


class LanePool:
    """N lane arasında case paylayan hovuz.

    Paralellik lane sayı ilə məhdudlaşır — Inspect-in `max_connections`-i daha
    böyük olsa belə, artıq case-lər burada növbəyə düşür. Yəni sürət həddi
    AÇIQDIR: `pool.size` qədər paralel, artıq deyil.
    """

    def __init__(self, lanes: list[Lane]) -> None:
        if not lanes:
            raise ValueError("LanePool ən azı bir lane tələb edir")
        _reject_shared_namespaces(lanes)
        self.lanes = lanes
        # `asyncio.Queue` yarandığı loop-a bağlanır; testlərdə hər `inspect_eval`
        # öz loop-unu yaradır, ona görə loop üzrə saxlanılır.
        self._queues: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Queue[Lane]]" = (
            weakref.WeakKeyDictionary()
        )

    @property
    def size(self) -> int:
        return len(self.lanes)

    @property
    def isolated(self) -> bool:
        return any(lane.resetter is not None for lane in self.lanes)

    def _queue(self) -> "asyncio.Queue[Lane]":
        loop = asyncio.get_running_loop()
        queue = self._queues.get(loop)
        if queue is None:
            queue = asyncio.Queue()
            for lane in self.lanes:
                queue.put_nowait(lane)
            self._queues[loop] = queue
        return queue

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[Lane]:
        """Bir lane-i eksklüziv icarəyə götürür; sonda ad sahəsini sıfırlayır."""
        queue = self._queue()
        lane = await queue.get()
        if lane.dead:
            queue.put_nowait(lane)  # deadlock olmasın — sadəcə səs-küylə dayan
            raise LaneExhausted(
                f"lane {lane.name!r} əvvəlki sıfırlama xətasından sonra çirkli sayılır; "
                "qaçış davam etməməlidir."
            )
        try:
            yield lane
        finally:
            if lane.resetter is None:
                queue.put_nowait(lane)
            else:
                try:
                    await lane.resetter.reset()
                except ResetFailed:
                    # Çirkli ad sahəsi növbəti case-ə VERİLMİR.
                    lane.dead = True
                    raise
                finally:
                    queue.put_nowait(lane)


def _reject_shared_namespaces(lanes: list[Lane]) -> None:
    """İki lane eyni (reset_url, ad sahəsi) cütünü bölüşə bilməz.

    Bölüşsəydilər paralel qaçış SƏSSİZCƏ sızardı: lane A-nın sıfırlaması
    lane B-nin işləyən vəziyyətini silərdi. Bu, konfiqurasiya səhvidir və
    qaçış başlamazdan əvvəl tutulur.
    """
    names = [lane.name for lane in lanes]
    dupe_names = sorted({n for n in names if names.count(n) > 1})
    if dupe_names:
        raise ValueError(f"lane adları təkrarlanır: {dupe_names}")

    seen: dict[tuple[str, str | None], str] = {}
    for lane in lanes:
        if lane.resetter is None:
            continue
        key = (lane.resetter.url, lane.resetter.session)
        if key in seen:
            raise ValueError(
                f"lane {lane.name!r} və {seen[key]!r} eyni tool ad sahəsini bölüşür "
                f"({key[0]}, {SESSION_HEADER}={key[1]!r}). Paralel qaçışda bu, "
                "susqun sızma deməkdir — hər lane-ə fərqli `tool_session` ver."
            )
        seen[key] = lane.name


def build_lane_pool(
    lanes: list[dict[str, Any]] | None,
    reset_url: str | None = None,
    reset_timeout_s: float = 10.0,
) -> LanePool:
    """Konfiqurasiyadan hovuz qurur.

    `lanes` verilməsə tək lane qurulur — köhnə davranışın eynisi (`reset_url`
    varsa izolyasiya var, yoxsa yoxdur).
    """
    if not lanes:
        resetter = ToolStateReset(reset_url, timeout_s=reset_timeout_s) if reset_url else None
        return LanePool([Lane(name="lane-1", resetter=resetter)])

    built: list[Lane] = []
    for i, spec in enumerate(lanes, start=1):
        if not isinstance(spec, dict):
            raise ValueError(f"lane #{i}: obyekt gözlənilir, alındı {type(spec).__name__}")
        name = str(spec.get("name") or f"lane-{i}")
        url = str(spec.get("tool_reset_url") or reset_url or "")
        session = spec.get("tool_session")
        session = str(session) if session else None
        resetter = ToolStateReset(url, timeout_s=reset_timeout_s, session=session) if url else None
        adapter_config = spec.get("adapter") or {}
        if not isinstance(adapter_config, dict):
            raise ValueError(f"lane {name!r}: `adapter` obyekt olmalıdır")
        built.append(Lane(name=name, resetter=resetter, adapter_config=dict(adapter_config)))

    if len(built) > 1 and any(lane.resetter is None for lane in built):
        raise ValueError(
            "çox lane-li qaçışda hər lane-in `tool_reset_url`-i olmalıdır — "
            "izolyasiyasız lane paralel qaçışda bütün nəticələri etibarsız edir."
        )
    return LanePool(built)
