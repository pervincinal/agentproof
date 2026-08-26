"""Case izolyasiyası — hədəfin tool servisinin vəziyyəti sıfırlanır.

PLAN.md "⚠️ Runner tələbi — İZOLYASİYA":

> Hər case-dən sonra `POST /admin/reset` çağırılmalıdır. Əks halda case *n*-də
> yaradılan RMA case *n+1*-də `RMA_ALREADY_EXISTS` verər və nəticələr
> bir-birinə sızar. Bu, orta qaçışda susqun korlanmaya gətirir.

İki nəticəsi var və ikisi də açıq yazılmalıdır:

1. **Sıfırlama qlobaldır.** Tool servisinin vəziyyəti bütün case-lər üçün
   birdir, ona görə `reset + invoke` cütü ATOMİK olmalıdır. Bu, izolyasiya
   aktiv olanda qaçışı FAKTİKİ OLARAQ SERİALLAŞDIRIR — `--max-connections`
   artırmaq sürət vermir. (`docs/STACK.md` 6 dəqiqə qaydası ilə ziddiyyət
   təşkil edir; böyük qaçışda hədəfin tool servisi case başına ayrılmalıdır.)
2. **Sıfırlama uğursuz olarsa qaçış DAYANIR.** Səssizcə davam etmək
   nəticələri bir-birinə qarışdırır — bu, ən pis haldır, çünki hesabat
   yaşıl görünür.
"""

from __future__ import annotations

import asyncio
import weakref
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

# Hər event loop üçün ayrı kilid: `asyncio.Lock` yarandığı loop-a bağlanır,
# testlərdə isə hər `inspect_eval` öz loop-unu yaradır.
_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary()
)


def _lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[loop] = lock
    return lock


class ResetFailed(RuntimeError):
    """Sıfırlama alınmadı — case-lər bir-birini çirkləndirə bilər."""


class ToolStateReset:
    """`POST <reset_url>` — hədəfin tool servisini fixture vəziyyətinə qaytarır."""

    def __init__(self, url: str, timeout_s: float = 10.0) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self.calls = 0

    async def reset(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(self.url)
        except httpx.HTTPError as e:
            raise ResetFailed(
                f"tool servisi sıfırlanmadı ({self.url}): {type(e).__name__}. "
                "İzolyasiya olmadan qaçış davam etməməlidir."
            ) from e
        if r.status_code != 200:
            raise ResetFailed(
                f"tool servisi sıfırlanmadı ({self.url}): HTTP {r.status_code}. "
                "İzolyasiya olmadan qaçış davam etməməlidir."
            )
        self.calls += 1

    @asynccontextmanager
    async def case(self) -> AsyncIterator["ToolStateReset"]:
        """Bir case-i tam əhatə edir: kilid + sonda sıfırlama.

        Sıfırlama HƏM case-dən sonra, HƏM də hər cəhddən əvvəl edilir
        (`reset_before_attempt`). Sondakı çağırış PLAN.md tələbidir; əvvəldəki
        isə əvvəlki case xəta ilə bitdiyi halda da təmiz başlanğıcı zəmanətə
        çevirir.
        """
        async with _lock():
            try:
                yield self
            finally:
                await self.reset()
