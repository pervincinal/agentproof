# ADAPTERS.md — öz sisteminizi necə qoşursunuz

**Rol:** harness-eng · **Tarix:** 2026-09-01 · **Tapşırıq:** AP-030 · AP-031
**Aidiyyat:** `agentproof/adapters/base.py` (müqavilə) ·
`agentproof/adapters/conformance.py` (25 yoxlama) · `docs/PREFLIGHT.md`

---

## 0. Hansı adapter sizindir

| Hədəfiniz | Adapter | Fayl |
|---|---|---|
| SSE axını verən Dify app-i | `dify_http` | `adapters/http_agent.py` |
| `POST` -> bir JSON cavab (FastAPI, Express, Vercel route, LangGraph `/invoke`) | `json_http` | `adapters/json_http.py` |
| Python obyekti — qraf, sinif, funksiya (LangGraph, LlamaIndex, öz kodunuz) | `callable` | `adapters/callable_agent.py` |
| Skriptləşdirilmiş determinist cavab (yalnız test) | `mock` | `adapters/mock_agent.py` |

Dördü də **eyni müqaviləni** doldurur və eyni 25 yoxlamaya qarşı qaçır
(`agentproof/tests/test_adapter_conformance.py`). Backoff, `HALT`, çoxnövbəli
zəncir və növbələrin birləşməsi hər üçündə **eyni koddur**
(`adapters/_http_core.py`) — adapter yalnız öz məftil formatını gətirir.

---

## 1. `json_http` — bloklayıcı JSON hədəfi

```python
from agentproof.adapters import create_adapter

adapter = create_adapter(
    "json_http",
    url="https://api.acme.internal/agent/invoke",
    api_key=os.environ["ACME_TOKEN"],     # Authorization: Bearer <...>
    query_field="message",                # sorğu gövdəsindəki sual sahəsi
    # cavab sahələri — hədəfin ÖZ adlandırması ilə
    text_path="data.reply",
    usage_path="data.tokens",
    usage_input_path="prompt",            # `usage` obyektinin İÇİ
    usage_output_path="generated",
    tool_calls_path="data.steps",
    retrieved_path="data.citations",
    chunk_id_path="ref",
    conversation_id_path="data.thread_id",   # VERİLMƏSƏ çoxnövbəli YOXDUR
    model="claude-sonnet-5",                 # `cost_under` üçün ŞƏRTDİR (§4)
)
```

Qaçışda mühit dəyişənləri ilə: `AGENTPROOF_JSON_URL`,
`AGENTPROOF_JSON_API_KEY`, `AGENTPROOF_JSON_QUERY_FIELD` və sahə xəritəsi üçün
`AGENTPROOF_JSON_MAP` (JSON fayl yolu və ya inline JSON).

**Yollar** nöqtəlidir; rəqəm seqmenti siyahı indeksidir
(`choices.0.message.content`), boş yol kökün özüdür. Hər sahə üçün namizəd
siyahısı da vermək olar (`text_path=["reply", "answer"]`). Tipik adlar
(`answer` / `output` / `usage` / `tool_calls` / `sources`) **konfiqurasiyasız**
tutulur — hansı yolun işlədiyi cavabın `raw["mapped_paths"]`-ında görünür.

---

## 2. `callable` — hədəfiniz Python obyektidirsə

```python
class MyGraph:
    def answer(self, query: str, conversation_id: str = "") -> dict:
        state = self.memory.setdefault(conversation_id, [])
        state.append(query)
        result = self.graph.invoke({"input": query, "history": state})
        return {
            "reply": result["output"],
            "spend": {"prompt": result["in_tokens"], "generated": result["out_tokens"]},
            "used_tools": [{"fn": s.name, "params": s.args} for s in result["steps"]],
            "refs": [{"anchor": c.id, "body": c.text} for c in result["sources"]],
        }

adapter = create_adapter(
    "callable", fn=MyGraph().answer, model="claude-sonnet-5",
    text_path="reply", usage_path="spend",
    usage_input_path="prompt", usage_output_path="generated",
    tool_calls_path="used_tools", tool_name_path="fn", tool_arguments_path="params",
    retrieved_path="refs", chunk_id_path="anchor", chunk_text_path="body",
)
```

* `fn` **sync və ya async** ola bilər. Sync funksiya ayrı thread-də qaçır ki,
  paralel lane-lər bloklanmasın.
* `fn` `dict` əvəzinə `str` və ya hazır `AgentResponse` qaytara bilər;
  başqa obyekt qaytarırsa `map_response=lambda r: {...}` verin.
* **Çoxnövbəlilik imzadan oxunur:** `fn` `conversation_id` qəbul edirsə söhbət
  zəncirlənir. Qəbul etmirsə çoxnövbəli case `multi_turn_unsupported` ilə
  qayıdır — səssizcə tək-növbəli **ölçülmür**.
* **Backoff YOXDUR** və bu qəsdəndir: şəbəkə olmadığı üçün gözləməklə keçən
  429 yoxdur, `fn`-in idempotentliyi isə bizə məlum deyil. `rate_limit` görsə
  səbəb ADI ilə qalır, sadəcə təkrar edilmir. Səbəb:
  `adapters/callable_agent.py` docstring-i.
* İstisna atılsa qaçış **sınmır**: xəta `callable_exception:<Tip>` adı ilə
  qeyd olunur və `status_code` / mesaj üzrə təsnif edilir. `credit_exhausted`
  görünsə bütün qaçış dayanır.

---

## 3. Sahə yoxdursa nə olur

Ən vacib qayda: **səssiz default yoxdur.**

| Vəziyyət | Nəticə |
|---|---|
| `usage` tapılmadı | `usage = None` (sıfır DEYİL) -> `cost_under` `skipped` |
| `usage` var, token adları tanınmadı | `None` + `raw["map_notes"]: usage_fields_unmapped` |
| `retrieved` tapılmadı | `[]` + `raw["fields_present"]["retrieved"] = False` |
| cavab mətni boş | `error = "empty_answer"` |
| `conversation_id_path` verilməyib | çoxnövbəli case `multi_turn_unsupported` |

`Usage(0, 0)` yazmaq hesabatda **"$0.00 — büdcədən aşağı, KEÇDİ"** kimi
görünərdi: inandırıcı və yalan. Ona görə ölçülməyən heç vaxt sıfır deyil.

---

## 4. Model etiketi `cost_under` üçün şərtdir

Hədəflərin əksəriyyəti `usage`-da model adı **vermir** (canlı Dify də vermir).
`cost_under` isə qiymət cədvəlində model tapmayanda `skipped` verir. Yəni
"token görünür" ilə "xərc ölçülür" eyni şey deyil — `model=` (və ya
`AGENTPROOF_SUT_MODEL`) verilməsə xərc ölçüsü SIRADAN ÇIXIR.

Bunu auditdən əvvəl görmək üçün: `docs/PREFLIGHT.md`.

---

## 5. Yeni adapter yazırsınızsa

1. Faylı `agentproof/adapters/` altına qoyun, **250 sətri keçməyin**
   (`test_adapter_layering.py` kilidləyir).
2. `_http_core`-dan `send_with_retry` / `run_conversation` / `merge_turns`
   işlədin — backoff və `HALT` yenidən yazılmır.
3. `test_adapter_conformance.py`-də ~40 sətirlik `ConformanceTarget` körpüsü
   yazın və `TARGETS`-ə əlavə edin; 25 yoxlama avtomatik qaçır.
4. Dəstəkləyə bilmədiyiniz ssenari varsa onu `supports`-dan çıxarın **və**
   `*_GAP` sabiti ilə adlandırın — susqun boşluq qadağandır.
