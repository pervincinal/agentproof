"""Hədəf sistem müqaviləsi (STACK.md §8.2).

Müqavilə şərtləri:
  - Adapter retry ETMİR və paralellik idarə ETMİR — bunlar Inspect-in işidir.
  - Adapter `latency_ms`-i özü ölçür (wall-clock).
  - Hədəf token istifadəsini vermirsə `usage = None` olur (grader `skipped` verir).
  - Yeni müştəri = bir adapter faylı, < 150 sətir.
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
