"""R1 — YOL (b) · SEÇİLƏN: Inspect Custom Agent qatından adapteri çağırmaq.

https://inspect.aisi.org.uk/agent-custom.html

Inspect-in paralellik / retry / limit / log maşını qalır, `Model`
abstraksiyası isə tamamilə atlanır — çünki hədəf model deyil, MƏHSULDUR.
Nəticədə `eval(model=None)` ilə heç bir model provayderi (və açar) lazım gəlmir.

İzolyasiya LANE hovuzu ilə aparılır (`runner/isolation.py`): hər case bir lane
icarəyə götürür, lane-in ad sahəsi case-dən sonra sıfırlanır. Tək lane =
köhnə (seriallaşan) davranış; N lane = N paralel case, izolyasiya pozulmadan.
"""

from __future__ import annotations

from typing import Any

from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.model import ChatMessageAssistant, ModelOutput

from agentproof.adapters.base import AgentAdapter, create_adapter
from agentproof.runner.bridge import push_response
from agentproof.runner.isolation import Lane, LanePool, build_lane_pool
from agentproof.types import AgentRequest


@agent(name="agentproof_target")
def target_agent(
    adapter: str,
    adapter_config: dict[str, Any] | None = None,
    repeat: int = 1,
    seed: int | None = None,
    reset_url: str | None = None,
    lanes: LanePool | None = None,
) -> Agent:
    """Hədəf sistemi bir Inspect agent-i kimi sarır.

    Args:
        adapter: adapter registry adı (`mock`, `dify_http`, ...)
        adapter_config: adapterə ötürülən konfiqurasiya (açar mühitdən gəlir)
        repeat: eyni case üçün neçə müstəqil cavab alınsın (consistency@k)
        seed: hədəfə ötürülən seed (dəstəkləyirsə)
        reset_url: tək lane-lik qısayol — hədəfin tool servisinin
            `POST /admin/reset` ünvanı. Verilmirsə izolyasiya YOXDUR; stateful
            tool-lu dataset-də bu susqun korlanma deməkdir.
        lanes: hazır lane hovuzu (`build_lane_pool`). Verilirsə `reset_url`
            nəzərə alınmır və paralellik lane sayı qədər olur.
    """
    base_config = dict(adapter_config or {})
    pool = lanes if lanes is not None else build_lane_pool(None, reset_url)
    # Hər lane öz adapter nüsxəsini alır: lane-ə xas konfiqurasiya (məs. həmin
    # lane-in Dify app açarı) qlobal konfiqurasiyanın üstünə yazılır.
    impls: dict[str, AgentAdapter] = {
        lane.name: create_adapter(adapter, **{**base_config, **lane.adapter_config})
        for lane in pool.lanes
    }

    async def run_case(
        lane: Lane, impl: AgentAdapter, state: AgentState, messages: list[dict[str, str]]
    ) -> ModelOutput | None:
        last: ModelOutput | None = None
        for attempt in range(max(repeat, 1)):
            if lane.resetter is not None:
                # hər cəhd təmiz vəziyyətdən başlayır (pass^k determinizmi)
                await lane.resetter.reset()
            req = AgentRequest(
                messages=messages,
                session_id=f"{id(state):x}-{attempt}",
                seed=None if seed is None else seed + attempt,
            )
            response = await impl.invoke(req)
            push_response(response)
            last = ModelOutput.from_content(
                model=f"{impl.name}@{impl.version}", content=response.text
            )
        return last

    async def execute(state: AgentState) -> AgentState:
        messages = [
            {"role": m.role, "content": m.text}
            for m in state.messages
            if getattr(m, "text", "")
        ]
        async with pool.lease() as lane:
            last = await run_case(lane, impls[lane.name], state, messages)
        # sonuncu cavab söhbətə yazılır; grader-lər tam siyahını store-dan alır
        if last is not None:
            state.output = last
            state.messages.append(ChatMessageAssistant(content=last.completion))
        return state

    return execute
