"""R1 SPIKE — YOL (a): AgentAdapter-i Inspect `ModelAPI` provayderi kimi qoşmaq.

Status: **QİYMƏTLƏNDİRİLDİ VƏ RƏDD EDİLDİ** (bax `docs/R1-SPIKE.md`).
Kod sənəd kimi saxlanır: qərarın təkrar yoxlanması üçün spike burada qaçır.

Rədd səbəbləri qısaca:
  1. `ModelOutput` `retrieved[]` üçün yer vermir -> `metadata` içinə soxmaq lazımdır.
  2. Inspect ModelAPI-ni "model" sayır: `--model` sahəsi, token limitləri,
     usage aqreqasiyası hədəfin DAXİLİ modelinə aid olmalı ikən adapterə yazılır.
  3. Çoxaddımlı agent (tool döngəsi hədəfin öz içindədir) bir `generate()`
     çağırışına yığılır — Inspect-in tool/message maşını boş yerə işləyir.
  4. Hesabatda "model" sütunu hədəfin adı ilə çirklənir; `target` və `model`
     ayrı sahələr olmalıdır (RunRecord sxemi).
"""

from __future__ import annotations

import asyncio
from typing import Any

from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
    modelapi,
)
from inspect_ai.tool import ToolCall as InspectToolCall
from inspect_ai.tool import ToolChoice, ToolInfo

from agentproof.adapters.base import AgentAdapter, create_adapter
from agentproof.runner.bridge import push_response
from agentproof.types import AgentRequest


class AgentProofModelAPI(ModelAPI):
    """Hədəf agent-i Inspect-ə "model" kimi təqdim edir."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(model_name=model_name, base_url=base_url, api_key=api_key, config=config)
        # ⚠️ R1 sürtünmə nöqtəsi: `ModelAPI.__init__` `base_url`/`api_key`-i MODEL
        # provayderi üçün mənimsəyir; bizdə isə bunlar HƏDƏF MƏHSULUN ünvanı və
        # açarıdır. `**model_args`-a düşmədikləri üçün əl ilə geri ötürmək lazımdır.
        if base_url is not None:
            model_args.setdefault("base_url", base_url)
        if api_key is not None:
            model_args.setdefault("api_key", api_key)
        # model_name = adapter adı (məs. "agentproof/dify_http")
        self.adapter: AgentAdapter = create_adapter(model_name, **model_args)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        req = AgentRequest(
            messages=[
                {"role": m.role, "content": m.text} for m in input if getattr(m, "text", None)
            ],
            session_id="",
            seed=config.seed,
        )
        response = await self.adapter.invoke(req)
        push_response(response)

        message = ChatMessageAssistant(
            content=response.text,
            tool_calls=[
                InspectToolCall(id=f"{i}", function=tc.name, arguments=tc.arguments)
                for i, tc in enumerate(response.tool_calls)
            ]
            or None,
            model=self.model_name,
        )
        return ModelOutput(
            model=self.model_name,
            choices=[ChatCompletionChoice(message=message, stop_reason="stop")],
            usage=ModelUsage(
                input_tokens=response.usage.input_tokens if response.usage else 0,
                output_tokens=response.usage.output_tokens if response.usage else 0,
                total_tokens=(response.usage.input_tokens + response.usage.output_tokens)
                if response.usage
                else 0,
            ),
            time=response.latency_ms / 1000.0,
            # ⚠️ R1 sürtünmə nöqtəsi: `retrieved[]`-in ModelOutput-da evi yoxdur
            metadata={"agentproof_response": response.to_dict()},
            error=response.error,
        )

    def connection_key(self) -> str:
        return f"agentproof/{self.model_name}"

    async def aclose(self) -> None:
        close = getattr(self.adapter, "aclose", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


@modelapi(name="agentproof")
def agentproof_provider() -> type[ModelAPI]:
    return AgentProofModelAPI
