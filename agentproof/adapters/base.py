"""Hədəf sistem müqaviləsi (STACK.md §8.2).

Müqavilə şərtləri:
  - Adapter retry ETMİR və paralellik idarə ETMİR — bunlar Inspect-in işidir.
    YEGANƏ istisna `rate_limit` sinfidir (AP-024): 429/529 hədəfin İÇİNDƏN,
    200 statuslu SSE axınında `error` event-i kimi gəlir, yəni Inspect onu
    ümumiyyətlə görmür. Digər bütün siniflər (`credit_exhausted`, `auth`,
    `bad_request`, `unknown`) DƏRHAL qaytarılır — təkrar pul yandırır və
    heç vaxt keçmir.
  - Adapter `latency_ms`-i özü ölçür (wall-clock).
  - Hədəf token istifadəsini vermirsə `usage = None` olur (grader `skipped` verir).

MÜQAVİLƏ BURADA BİTMİR — DAVAMI KODDADIR (AP-028)
-------------------------------------------------
Aşağıdakı Protocol cəmi dörd üzv tələb edir. Şərtlərin ÖZÜ isə yuxarıdakı mətn
idi, yəni sürüşürdü. İndi hər biri icra olunan yoxlamadır:
`agentproof/adapters/conformance.py`. Yeni adapter üçün ~40 sətirlik
`ConformanceTarget` körpüsü yazılır və bütün dəst ona qarşı qaçır
(`agentproof/tests/test_adapter_conformance.py`).

YENİ MÜŞTƏRİ NƏ QƏDƏR KOD DEMƏKDİR (AP-029)
-------------------------------------------
Backoff/təkrar, çoxnövbəli `conversation_id` zənciri, növbələrin birləşməsi və
yanan tokenlərin yığımı hədəfə XAS DEYİL — onlar `adapters/_http_core.py`-dədir
və yenidən yazılmır. Adapter yalnız öz məftil formatını gətirir; ölçü nümunəsi:

    http_agent.py    196 sətir   HTTP müştərisi + konfiqurasiya
    _dify_wire.py    334 sətir   Dify SSE formatı (event adları, `dify_error`)
    mock_agent.py     95 sətir   şəbəkəsiz in-process hədəf

Hədd `test_adapter_layering.py`-də kilidlənib: `http_agent.py` <= 250 sətir.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from agentproof.types import AgentRequest, AgentResponse


@runtime_checkable
class AgentAdapter(Protocol):
    name: str
    version: str

    async def invoke(self, req: AgentRequest) -> AgentResponse: ...

    async def health(self) -> bool: ...


_REGISTRY: dict[str, Callable[..., AgentAdapter]] = {}


def register_adapter(name: str) -> Callable[[Callable[..., AgentAdapter]], Callable[..., AgentAdapter]]:
    def wrap(factory: Callable[..., AgentAdapter]) -> Callable[..., AgentAdapter]:
        _REGISTRY[name] = factory
        return factory

    return wrap


def create_adapter(name: str, **config: Any) -> AgentAdapter:
    if name not in _REGISTRY:
        raise KeyError(f"naməlum adapter: {name!r}; mövcud: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**config)


def adapter_names() -> list[str]:
    return sorted(_REGISTRY)
