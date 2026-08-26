"""R1 — YOL (b) · SEÇİLƏN: Inspect Custom Agent qatından adapteri çağırmaq.

https://inspect.aisi.org.uk/agent-custom.html

Inspect-in paralellik / retry / limit / log maşını qalır, `Model`
abstraksiyası isə tamamilə atlanır — çünki hədəf model deyil, MƏHSULDUR.
Nəticədə `eval(model=None)` ilə heç bir model provayderi (və açar) lazım gəlmir.
"""

from __future__ import annotations

from typing import Any

from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.model import ChatMessageAssistant, ModelOutput

from agentproof.adapters.base import create_adapter
from agentproof.runner.bridge import push_response
from agentproof.runner.isolation import ToolStateReset
from agentproof.types import AgentRequest


@agent(name="agentproof_target")
def target_agent(
    adapter: str,
    adapter_config: dict[str, Any] | None = None,
    repeat: int = 1,
    seed: int | None = None,
    reset_url: str | None = None,
) -> Agent:
    """Hədəf sistemi bir Inspect agent-i kimi sarır.

    Args:
        adapter: adapter registry adı (`mock`, `dify_http`, ...)
        adapter_config: adapterə ötürülən konfiqurasiya (açar mühitdən gəlir)
        repeat: eyni case üçün neçə müstəqil cavab alınsın (consistency@k)
        seed: hədəfə ötürülən seed (dəstəkləyirsə)
        reset_url: hədəfin tool servisinin `POST /admin/reset` ünvanı.
            Verilirsə hər case ATOMİK olur (bax `runner/isolation.py`) —
            case *n*-in yaratdığı RMA case *n+1*-ə sızmır. Verilmirsə
            izolyasiya YOXDUR; stateful tool-lu dataset-də bu susqun
            korlanma deməkdir.
    """
    impl = create_adapter(adapter, **(adapter_config or {}))
    resetter = ToolStateReset(reset_url) if reset_url else None

    async def run_case(state: AgentState, messages: list[dict[str, str]]) -> ModelOutput | None:
        last: ModelOutput | None = None
        for attempt in range(max(repeat, 1)):
            if resetter is not None:
                # hər cəhd təmiz vəziyyətdən başlayır (pass^k determinizmi)
                await resetter.reset()
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
        if resetter is None:
            last = await run_case(state, messages)
        else:
            async with resetter.case():
                last = await run_case(state, messages)
        # sonuncu cavab söhbətə yazılır; grader-lər tam siyahını store-dan alır
        if last is not None:
            state.output = last
            state.messages.append(ChatMessageAssistant(content=last.completion))
        return state

    return execute
