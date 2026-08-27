# ARCHITECTURE.md — hədəf sistemin memarlığı və hücum səthi

**Hədəf:** Dify 1.17.0 · `agent-chat` app `4daef326-beb5-4c36-88a4-167d20194729`
("Aurora Goods Support Agent") · lokal Docker, `~/agentproof-stack/dify`, port 8088.
**Tarix:** 2026-08-28 · **Müəllif rolu:** analyst · **Tapşırıq:** AP-014

---

## 0. Bu sənəd necə oxunmalıdır

Bu, nəzəri memarlıq təsviri deyil. Tam qaçış (`reports/full-run-02`) artıq bitib
və tapıntılar məlumdur, ona görə sənədin məqsədi bir sualdır:

> **Müşahidə etdiyimiz uğursuzluqlar hansı memarlıq qərarından doğur?**

**Metod və doğruluq qaydası.** Hər iddianın arxasında ya kod istinadı
(`fayl:sətir`), ya canlı sistem sorğusu (postgres / `docker exec`), ya da qaçış
artefaktı (`reports/full-run-02/VmH7QgPBAE7PwcMo6Xwz7Q.json`) durur. Kod
sitatları **işlək konteynerdən** oxunub (`docker exec docker-api-1 …
/app/api/…`), repo checkout-undan deyil — yollar `api/…` prefiksi ilə yazılır.
Yoxlaya bilmədiyim hər şey `[təsdiqlənməyib]` işarəsi daşıyır.

**Ton qaydası (PLAN.md §4).** Aşağıdakıların böyük hissəsi **dizayn qərarıdır,
qüsur deyil** — agent app-ının bilik bazasını tool kimi verməsi şüurlu seçimdir
və modelə öz alətini seçmək imkanı verir; biz məhz onu ölçürük. Fərqi hər
bənddə açıq göstərirəm:

| İşarə | Mənası |
|---|---|
| **[dizayn]** | Şüurlu memarlıq qərarı. Tənqid deyil; nəticəsi sadəcə bilinməlidir. |
| **[sənədsiz tələ]** | Davranış sənədləşdirilməyib və növbəti adamı ilişdirir. |
| **[ölçmə riski]** | Bizim öz ölçməmizi (grader / artefakt) səhv göstərir. |

---

## 1. Sistem xəritəsi — canlı vəziyyət

Stack-də **15 işlək konteyner** var (`docker ps | grep '^docker-'`; FINDINGS.md
§2.1 compose-un elan etdiyi 16 servisə istinad edir). Sorğu yolunda iştirak
edənlər:

| Konteyner | Image | Rolu |
|---|---|---|
| `docker-nginx-1` | `nginx:latest` | 8088 → api/web |
| `docker-api-1` | `langgenius/dify-api:1.17.0` | Service API + agent runner |
| `docker-plugin_daemon-1` | `dify-plugin-daemon:0.6.10-local` | model provider plugin-ləri (Anthropic, Ollama, Gemini) |
| `docker-ssrf_proxy-1` | `ubuntu/squid:latest` | custom (API) tool çağırışları buradan keçir |
| `docker-weaviate-1` | `weaviate:1.27.0` | vektor indeksi |
| `docker-db_postgres-1` | `postgres:15-alpine` | app / dataset / message metadatası |

Xaricdə: `target/tools/` FastAPI mock servisi (`host.docker.internal:8099`,
5 tool) və Anthropic API.

### 1.1 Canlı konfiqurasiya (postgres-dən oxundu, 2026-08-28)

```sql
select id, name, mode, enable_api from apps;
-- 4daef326-… | Aurora Goods Support Agent | agent-chat | t
```

| Sahə | Canlı dəyər | Mənbə |
|---|---|---|
| `model` | `claude-sonnet-5`, `thinking:false`, `effort:high`, `max_tokens:4096` | `app_model_configs.model` |
| `prompt_type` | `simple` | `app_model_configs.prompt_type` |
| `agent_mode` | `function_call`, `max_iteration: 5`, 5 API tool | `app_model_configs.agent_mode` |
| `retriever_resource` | `{"enabled": true}` | `app_model_configs.retriever_resource` |
| **App-in `dataset_configs`** | `top_k: 4`, **`reranking_enable: true`**, `jina-reranker-v3`, dataset `1623dd7e-…` | `app_model_configs.dataset_configs` |
| **Dataset-in `retrieval_model`** | **`top_k: 8`**, `semantic_search`, **`reranking_enable: false`** | `datasets.retrieval_model` |

İki sətir bir-birinə ziddir. **Hökm dataset-indir** — səbəbi §5 FP-03/FP-04-dədir.

### 1.2 Bilik bazası

İki dataset var; app **v2**-yə bağlıdır:

| Dataset | Embedder | `top_k` | App bağlıdırmı |
|---|---|---:|---|
| `e1471e22-…` "Aurora Goods Policies" | `gemini-embedding-001` | 4 | xeyr |
| `1623dd7e-…` "Aurora Goods Policies v2" | `bge-m3` (Ollama) | **8** | **bəli** |

Chunking (`dataset_process_rules`, `mode: custom`):
`separator: "\n## "` · `max_tokens: 900` · `chunk_overlap: 100` ·
`remove_extra_spaces: true`.

Nəticə: 8 sənəd → **86 seqment** (`returns-and-refunds.md` 13,
`international-shipping.md` 11, `payments-and-billing.md` 11,
`shipping-and-delivery.md` 11, `warranty-policy.md` 11,
`privacy-and-data.md` 10, `promotions-and-price-match.md` 10,
`account-and-membership.md` 9).

`top_k = 8` → model bir retrieval çağırışında korpusun **~9%**-ni görür.

**Seqment sərhədi haqqında iki müşahidə** (postgres-dən oxundu):

1. `## ` ayırıcısı **udulur** — başlıq mətn kimi qalır ("5. Items damaged,
   defective, or missing on arrival"), markdown işarəsi yox. Bənd nömrələri
   (§5.1, §6.1) yalnız gövdə mətnində olduğu üçün sağ qalır.
2. Sənədin başlıq bloku (`Document ID`, `Version`, `Effective from`,
   `Supersedes`) **yalnız 1-ci seqmentdədir**. Qalan 85 seqment versiya
   metadatası olmadan gəlir. Bayat bəndlərin özündə xəbərdarlıq var
   (Appendix A seqmentləri *«⚠️ no longer in force»* ilə başlayır) — bu,
   korpusun öz dizayn qərarıdır və hədəf sistemin xidməti deyil.

---

## 2. Sorğu yolu — istifadəçi girişindən cavaba

```mermaid
flowchart TD
    A["POST /v1/chat-messages<br/>Bearer app-…"] --> B["ChatApi.post<br/>service_api/app/completion.py:367"]
    B --> C{"_resolve_agent_app_streaming<br/>completion.py:60-66"}
    C -- "response_mode=blocking" --> C1["streaming=False"]
    C -- "response_mode=streaming" --> C2["streaming=True"]
    C1 --> D
    C2 --> D["AppGenerateService.generate<br/>app_generate_service.py:190-193"]
    D --> E["AgentChatAppGenerator.generate<br/>agent_chat/app_generator.py:93-94<br/>❌ blocking → ValueError"]
    E --> F["query.replace(chr 0)<br/>app_generator.py:103<br/>yeganə sanitizasiya"]
    F --> G["AgentChatAppRunner.run<br/>agent_chat/app_runner.py:33"]
    G --> H["organize_prompt_messages<br/>app_runner.py:180-188<br/>context=None"]
    H --> I["SimplePromptTransform<br/>simple_prompt_transform.py:214,229<br/>system=pre_prompt · user=query"]
    I --> J["strategy → FUNCTION_CALLING<br/>app_runner.py:196-197"]
    J --> K["FunctionCallAgentRunner.run<br/>fc_agent_runner.py:103"]
    K --> L["_init_prompt_tools<br/>base_agent_runner.py:191-217<br/>5 API tool + 1 dataset tool"]
    L --> M{"iterasiya ≤ 6<br/>fc_agent_runner.py:147"}
    M --> N["invoke_llm<br/>fc_agent_runner.py:178"]
    N --> O{"tool_calls?"}
    O -- "yox" --> Z
    O -- "API tool" --> P["ToolEngine.agent_invoke<br/>tool_engine.py:49"]
    P --> Q["custom_tool/tool.py:283-300<br/>ssrf_proxy.post"]
    Q --> R["squid<br/>host.docker.internal:8099"]
    R --> S["ToolPromptMessage<br/>fc_agent_runner.py:367-372"]
    O -- "dataset tool" --> T["DatasetRetrieverTool._run<br/>dataset_retriever/dataset_retriever_tool.py:60"]
    T --> U["RetrievalService.retrieve<br/>weaviate · semantic_search · top_k=8"]
    U --> V["chunk mətnləri sətir-sonu ilə birləşdirilir<br/>provenans YOX<br/>dataset_retriever_tool.py:244"]
    V --> S
    S --> M
    Z["QueueMessageEndEvent<br/>fc_agent_runner.py:415-425"] --> AA["SSE: agent_message / agent_thought / message_end<br/>easy_ui_based_generate_task_pipeline.py"]
    AA --> AB["metadata.usage + metadata.retriever_resources"]
```

### 2.1 Nömrəli axın

1. **Giriş.** `POST /v1/chat-messages`, `Authorization: Bearer app-…`.
   Marşrut `ChatApi.post` — `api/controllers/service_api/app/completion.py:367`.
   App rejimi `{CHAT, AGENT_CHAT, ADVANCED_CHAT, AGENT}` içində olmalıdır
   (`:374-375`), yoxsa `not_chat_app`.
2. **Rejim həlli.** `_resolve_agent_app_streaming` (`completion.py:60-66`)
   yalnız **yeni** `agent` rejimi üçün `blocking`-i açıq rədd edir. Bizim
   `agent-chat` üçün funksiya sadəcə `response_mode == "streaming"` qaytarır —
   yəni `blocking` burada **keçir** və aşağıda sınır (§7 CT-04).
3. **Generator.** `AppGenerateService.generate` → `AgentChatAppGenerator`
   (`api/services/app_generate_service.py:190-193`).
4. **Blocking rəddi.** `api/core/app/apps/agent_chat/app_generator.py:93-94` —
   `if not streaming: raise ValueError("Agent Chat App does not support blocking mode")`.
   Canlı təsdiq: `400 {"code":"invalid_param"}` (PLAN.md "DÜZƏLİŞ").
5. **Yeganə sanitizasiya.** `app_generator.py:103` — `query.replace("\x00", "")`.
   Başqa heç bir filtr yoxdur. Bu, §4 TB-1-in bütün məzmunudur.
6. **Runner.** `api/core/app/apps/agent_chat/app_runner.py:33`. Ardıcıllıq:
   moderation (`:92`, DSL-də `sensitive_word_avoidance.enabled: false` →
   effektiv deyil) → annotation reply (`:112`, söndürülüb) → external data tools
   (`:140`, boş) → hosting moderation (`:163`).
7. **Prompt yığılması.** `organize_prompt_messages` üç dəfə çağırılır
   (`:79`, `:152`, `:180`) və **heç birində `context` ötürülmür** → `None`.
   `SimplePromptTransform` (`api/core/prompt/simple_prompt_transform.py`):
   - `:214` → `SystemPromptMessage(content=prompt)`; `has_context=False`
     olduğu üçün Dify-ın `context_prompt` boilerplate-i **əlavə olunmur**
     (`:165-166`). Yəni sistem mesajı **hərfbəhərf `pre_prompt`**-dur.
   - `:229` → `UserPromptMessage(query)` — istifadəçi mətni **olduğu kimi**.
8. **Strategiya.** `app_runner.py:196-197` — model sxemi `TOOL_CALL` və ya
   `MULTI_TOOL_CALL` elan edirsə, strategiya **məcburi** `FUNCTION_CALLING`
   olur. DSL-dəki `strategy: function_call` sadəcə eyni nəticəni yazır.
9. **Tool reyestri.** `api/core/agent/base_agent_runner.py:191-217` —
   5 API tool + hər dataset üçün 1 `dataset_<uuid>` tool. Bilik bazası modelə
   **adi tool kimi** görünür; təsviri dataset-in `description` sahəsidir
   (`dataset_retriever/dataset_retriever_tool.py:46-50`), parametri tək
   sərbəst mətn `query` (`:29-31`).
10. **Dövr.** `fc_agent_runner.py:147` — `max_iteration_steps = min(5, 99) + 1 = 6`.
    Sonuncu iterasiyada tool siyahısı boşaldılır (`:150-152`); model hələ də
    tool istəyirsə `AgentMaxIterationError` (`:310-311`).
11. **Tool icrası.** `ToolEngine.agent_invoke` (`api/core/tools/tool_engine.py:49`)
    → `custom_tool/tool.py:283-300` → `ssrf_proxy.post` → squid → mock servis.
    Nəticə `ToolPromptMessage(content=str(tool_response))` kimi kontekstə
    qayıdır (`fc_agent_runner.py:361, 367-372`).
12. **Retrieval.** `DatasetRetrieverTool._run`
    (`api/core/tools/utils/dataset_retriever/dataset_retriever_tool.py:60`) →
    `RetrievalService.retrieve` (`:146-160`) → Weaviate. Nəticə `:244`-də
    **yalnız chunk mətnləri, `"\n"` ilə birləşdirilmiş** sətir kimi qayıdır.
13. **Cavab.** `QueueMessageEndEvent` (`fc_agent_runner.py:415-425`) → SSE.
    `InvokeFrom.SERVICE_API` üçün **tam** cavab konverteri işləyir
    (`base_app_generate_response_converter.py:27-35`), yəni
    `metadata.usage` və `metadata.retriever_resources` gəlir.

---

## 3. RAG boru xətti — dəqiq davranış

| Addım | Harada | Faktiki davranış |
|---|---|---|
| Sorğu mətni | model özü yazır | `DatasetRetrieverToolInput.query` — tək sərbəst mətn sahəsi (`dataset_retriever/dataset_retriever_tool.py:29-31`) |
| Metadata filtri | `dataset_configs.metadata_filtering_mode` | canlı dəyər `disabled` |
| Axtarış | `RetrievalService.retrieve` (`:146-160`) | `semantic_search`, `top_k=8`, threshold yox |
| Rerank | həmin blok `:154-157` | `retrieval_model["reranking_enable"]` **dataset-dən** oxunur → `false` → rerank **yoxdur** |
| Sıralama | `:243` | yalnız `score` azalan |
| Kontekstə yığılma | `:244` | `"\n".join(chunk.content)` — **sənəd adı yox, bal yox, mövqe yox, ayırıcı yox** |
| Provenans | `:206-230` | toplanır, amma yalnız `retriever_resources` metadatasına (çağırıcıya) gedir — **prompt-a yox** |

**Bu cədvəlin ən vacib sətri sonuncudan əvvəlkidir.** Model 8 bəndi bir-birinə
yapışdırılmış mətn blokunda görür. Hansı bəndin hansı sənəddən gəldiyini yalnız
bəndin öz mətnindən çıxara bilər. Sitat gətirdiyi §5.1 / §6.1 nömrələri
korpusun gövdə mətnindən gəlir, sistemdən yox.

---

## 4. Etibar sərhədləri — istifadəçi mətninin prompt-a düşdüyü nöqtələr

| # | Sərhəd | Kod | Sanitizasiya |
|---|---|---|---|
| **TB-1** | `query` → `UserPromptMessage` | `app_generator.py:103` (`\x00` silinir) → `simple_prompt_transform.py:229` | **NUL baytdan başqa heç nə**. `<\|…\|>` xüsusi tokenləri belə silinmir — o filtr yalnız şablon dəyişənlərinə tətbiq olunur (`prompt_template_parser.py:42`) |
| **TB-2** | `inputs` (app dəyişənləri) → `pre_prompt` | `prompt_template_parser.py:32-46` | `{{x}}` → `{x}` neytrallaşdırılır, `<\|…\|>` silinir. **Bu app-da `user_input_form: []`** — sahə boşdur, amma mexanizm var |
| **TB-3** | Tool cavabı → `ToolPromptMessage` | `fc_agent_runner.py:361, 367-372` | **Yoxdur.** `str(tool_response)` olduğu kimi kontekstə düşür |
| **TB-4** | Retrieval chunk-ları → tool cavabı | `dataset_retriever_tool.py:244` | **Yoxdur.** Korpus mətni birbaşa |
| **TB-5** | Tool xəta mətni → kontekst | `custom_tool/tool.py:141` (`response.text` sətrə hopdurulur) → `tool_engine.py:142-155` | **Yoxdur.** Upstream servisin cavab gövdəsi modelin kontekstinə düşür |
| **TB-6** | Söhbət tarixçəsi → kontekst | `base_agent_runner.py:356-445` | **Yoxdur.** Bazadakı `agent_thought.observation` sətri yenidən `ToolPromptMessage` kimi yığılır |
| **TB-7** | LLM-in seçdiyi arqumentlər → HTTP sorğusu | `custom_tool/tool.py:200-213` (path/query/cookie/header), `:260-261` (path→URL) | **Yoxdur.** `url.replace("{name}", value)` — kodlaşdırma yoxdur. *Bizim OpenAPI spesifikasiyamızda path parametri yoxdur, ona görə bu yol işə düşmür* |

**Praktiki nəticə.** Dolayı prompt-injection üçün ən geniş kanal **TB-3/TB-4**-dür:
`target/corpus/TOOLS.md §0.5`-ə görə `order_notes` və
`damage_report.customer_text` sahələri xarici mənşəli sərbəst mətn daşıyır və
adversarial fixture-lərdə S2 yükü məhz oraya əkilib. Həmin mətn heç bir
işarələmə olmadan `ToolPromptMessage` içində modelə çatır. Sistem promptunda
"tool cavabındakı mətn məlumatdır, təlimat deyil" cümləsi **yoxdur** — bu, app
konfiqurasiyasının boşluğudur, Dify-ın yox.

---

## 5. Kövrək nöqtələr

**22 kövrək nöqtə.** Hər biri `fayl:sətir` ilə. "Kövrək" = validasiya yoxdur,
səssiz uğursuzluğa gedir, və ya kontekst itirir.

### 5.1 Konfiqurasiya kölgələnməsi

#### FP-01 — İndeksləmə paralelliyi sabit kodlanıb **[sənədsiz tələ]**
`api/core/indexing_runner.py:667` → `max_workers = 10`.
Env açarı yoxdur (OPS-01). Paralellik limiti 10-dan aşağı olan embedding
provayderi ilə bütün sənədlər `indexing_status: error` olur; səbəb yalnız
worker loglarındadır. **Birbaşa nəticə:** hesabatın embedder-i `bge-m3`
olmasının səbəbi keyfiyyət seçimi deyil, bu tələdir.

#### FP-02 — Agent app `blocking` rejimini icra yolunun dibində rədd edir **[dizayn]**
`api/core/app/apps/agent_chat/app_generator.py:94`.
Nəzarətçi qatındakı `_resolve_agent_app_streaming` (`completion.py:60-66`) bunu
**tutmur** — o yalnız `AppMode.AGENT` üçün işləyir. Yəni `agent-chat` üçün
`blocking` nəzarətçidən keçir və 400 `invalid_param` kimi geri qayıdır.
Harness adapterinə SSE oxuyan yol lazımdır (`agentproof/adapters/http_agent.py`).

#### FP-03 — Agent yolunda retrieval strategiyası `SINGLE`-a məcbur edilir, `top_k` dataset-dən oxunur **[dizayn + sənədsiz tələ]**
Üç yer bir-birini üst-üstə yazır (VALID-03):

1. `api/core/tools/utils/dataset_retriever_tool.py:53-55` —
   `# Agent only support SINGLE mode` → `retrieve_strategy = SINGLE`,
   app-in `dataset_configs.retrieval_model` dəyəri nə olursa olsun (canlı
   dəyər: `"multiple"`).
2. `api/core/rag/retrieval/dataset_retrieval.py:1327-1331` — `SINGLE` yolunda
   `retrieval_model_config = dataset.retrieval_model if dataset.retrieval_model
   else default_retrieval_model`; `top_k = retrieval_model_config["top_k"]`.
3. `dataset_retrieval.py:1315-1319` — lokal default `top_k: 2`, modul
   səviyyəsindəki `default_retrieval_model` (`:100-104`) isə `top_k: 4`.
   Lokal dəyər modul dəyərini kölgələyir.

`datasets.retrieval_model` NULL olsa agent **2 bənd** çəkər, halbuki UI/DSL `4`
göstərir. Xəbərdarlıq yoxdur. Bizim dataset-də sütun `top_k: 8` yazılıb —
buna görə canlı sistemdə 8 bənd gəlir. `reports/full-run-02` artefaktı bunu
147 case-in hamısında təsdiqləyir (retrieval edən hər case-də bir çağırış →
tam 8 bənd).

#### FP-04 — Rerank də dataset-dən oxunur; app-in seçdiyi reranker səssizcə işləmir **[sənədsiz tələ]** *(yeni)*
Eyni yol `reranking_enable` üçün də keçərlidir:
`dataset_retriever/dataset_retriever_tool.py:131` →
`retrieval_model = dataset.retrieval_model or default_retrieval_model`, sonra
`:154-157` → `reranking_model = retrieval_model.get("reranking_model") if
retrieval_model["reranking_enable"] else None`.

Canlı vəziyyət:

| Yer | `reranking_enable` | Model |
|---|---|---|
| `app_model_configs.dataset_configs` | **`true`** | `jina-reranker-v3` |
| `datasets.retrieval_model` (v2) | **`false`** | — |

Yəni app konfiqurasiyasında **aktiv görünən reranker faktiki olaraq işləmir**.
Bu, OPS-03-ün `top_k`-dan kənar, sənədləşdirilməmiş ikinci üzüdür.
Kod yolundan çıxarılıb; ayrıca A/B ölçməsi aparılmayıb — VALID-03-ün müşahidəsi
(8 bənd, xam bal sırası ilə) bununla uyğundur. `[rerank-in söndüyü ayrıca
eksperimentlə deyil, kod yolu + konfiqurasiya ilə təsdiqlənib]`

#### FP-05 — `PATCH`/`GET /v1/datasets/{id}` yazılan `retrieval_model`-i geri qaytarmır **[sənədsiz tələ]**
Yazma işləyir: `api/controllers/service_api/dataset/dataset.py:674-675` →
`update_data["retrieval_model"]`. Cavab modelində isə sahə yoxdur:
`api/fields/dataset_fields.py:143` yalnız `retrieval_model_dict` elan edir.
Nəticə: `PATCH` və ardınca `GET` hər ikisi `retrieval_model: null` qaytarır,
halbuki yazı baş tutub. Skriptlə setup quran adam əməliyyatı uğursuz sayır.
Yeganə etibarlı yoxlama nöqtəsi bazadır (OPS-05).

### 5.2 Səssiz uğursuzluqlar

#### FP-06 — Tool provayderi həll olunmasa tool **səssizcə** siyahıdan düşür **[sənədsiz tələ]**
`api/core/agent/base_agent_runner.py:196-200`:

```python
try:
    prompt_tool, tool_entity = self._convert_tool_to_prompt_message_tool(tool)
except Exception:
    # api tool may be deleted
    continue
```

Çılpaq `except Exception`. `provider_id` köhnəlibsə, credential silinibsə və ya
provayder tapılmasa, həmin tool modelə **ümumiyyətlə təklif olunmur**. Model
qalan alətlərlə cavab verir, HTTP cavabı 200 olur, heç bir yerdə xəta görünmür.
`target/app/IMPORT.md §3`-dəki "import `provider_id`-ni YOXLAMIR" xəbərdarlığının
kod qarşılığı budur. **Ən pis hal:** `escalate_to_human` düşür və eskalasiya
ölçüsü səssizcə sıfırlanır.

#### FP-07 — Sənədi olmayan dataset səssizcə buraxılır **[sənədsiz tələ]**
`api/core/rag/retrieval/dataset_retrieval.py:1300-1310` — dataset tapılmasa
(`:1300`) və ya `get_total_available_documents(session=session) == 0` (`:1307`)
olsa `continue`. Nəticədə `to_dataset_retriever_tool` boş siyahı qaytarır,
`_init_prompt_tools` (`base_agent_runner.py:210-216`) heç bir bilik tool-u
qeydə almır və **model bilik bazası olmadan işləyir**. Sistem promptu isə hələ
də "search the knowledge base" deyir. İndeksləmə FP-01-ə görə sınıbsa, bu iki
tələ ardıcıl işə düşür.

#### FP-08 — Retrieval boş sətir qaytara bilər, model bunu "nəticə yoxdur" kimi görmür **[dizayn]**
`dataset_retriever/dataset_retriever_tool.py:65` (dataset tapılmadı),
`:129` (metadata filtri heç nə buraxmadı), `:245` (kontekst siyahısı boş).
Üç halın hər üçü `return ""` verir. `fc_agent_runner.py:360` yalnız `is not None`
yoxlayır, ona görə **boş məzmunlu `ToolPromptMessage`** kontekstə düşür.
Model "axtardım, tapmadım" ilə "axtarış sındı" arasında fərq görmür.

#### FP-09 — Hər tool xətası normal müşahidəyə çevrilir; API cavabı 200 qalır **[dizayn, amma ölçmə riski]**
`api/core/tools/tool_engine.py:130-156` — `ToolProviderCredentialValidationError`,
`ToolNotFoundError`, `ToolParameterValidationError`, `ToolInvokeError` və
sonda çılpaq `except Exception` (`:152`) — hamısı `error_response` **sətrinə**
çevrilir və adi tool cavabı kimi qaytarılır (`:157`). `ToolSSRFError` də məhz
bu sonuncu bloka düşür.

**Nəticə:** infrastruktur nasazlığı (SSRF bloku, mock servis düşüb, timeout)
API sərhədində model keyfiyyəti problemindən **fərqlənmir**. Qaçış "uğurla"
başa çatır, `pass_rate` düşür, səbəb isə şəbəkədədir.

#### FP-10 — Upstream xəta gövdəsi modelin kontekstinə hopdurulur **[dizayn]**
`api/core/tools/custom_tool/tool.py:140-141`:
`raise ToolInvokeError(f"Request failed with status code {response.status_code} and {response.text}")`.

`target/corpus/TOOLS.md §0.4/§0.6` xətaları qəsdən **strukturlu obyekt + HTTP
4xx/5xx** kimi qaytarır (`target/tools/service.py:277-279`). Dify onları modelə
struktur kimi vermir — `tool invoke error: Request failed with status code 404
and {"error":{…}}` sətrinə çevirir. Yəni mock-un "errors are errors" dizaynı
Dify sərhədini keçəndə mətnə çevrilir.

#### FP-11 — `retriever_resources` sənəd səviyyəsində təkrarları atır **[ölçmə riski]** *(yeni)*
`api/core/app/task_pipeline/message_cycle_manager.py:195-206`:

```python
existing_ids = {(r.dataset_id, r.document_id) for r in merged_resources …}
for resource in event.retriever_resources or []:
    is_duplicate = (… (resource.dataset_id, resource.document_id) in existing_ids)
    if not is_duplicate:
        merged_resources.append(resource)
```

Təkrar meyarı **`segment_id` deyil, `document_id`**-dir. Yəni agent bilik
bazasını **ikinci dəfə** çağırıb eyni sənədin **başqa bəndlərini** gətirsə,
həmin bəndlər `retriever_resources`-dan tamamilə düşür. Model onları görüb,
metadata isə onları bildirmir.

**Empirik təsdiq** (`reports/full-run-02`, 147 case):

| KB çağırışı | Case sayı | Qeydə alınan bənd sayı |
|---:|---:|---|
| 0 | 33 | 0 |
| 1 | 96 | 8 |
| 2 | 17 | **8–14** (16 olmalı idi) |
| 3 | 1 | **10** (24 olmalı idi) |

4 case-də iki çağırışdan sonra cəmi **8** bənd qeydə alınıb — ikinci çağırışın
bütün nəticəsi görünməzdir. `retrieval_hit_at_k` və `precision_at_k`
grader-ləri məhz bu sahəni oxuyur, ona görə **18/147 (12.2%) case-də retrieval
ölçüsü aşağı göstərir**. Bu, hədəfin deyil, bizim ölçmənin problemidir və
hesabatda belə yazılmalıdır.

### 5.3 Kontekst və dövr

#### FP-12 — Yekun cavab hər iterasiyanın mətnini içinə alır **[dizayn, ölçmə riski]**
`api/core/agent/fc_agent_runner.py:307` → `final_answer += response + "\n"`.
Tool çağırışından əvvəlki ara mətn ("Let me look that up…") də yekun `answer`
sahəsinə düşür. Substring axtaran assertion-lar bu ara mətnə ilişə bilər —
`GRADER-AUDIT.md#A-11`-dəki çılpaq `lock` iynəsinin yanılma mexanizmi ilə eyni
sinifdəndir.

#### FP-13 — Sonuncu iterasiyada bütün alətlər çıxarılır **[dizayn]**
`fc_agent_runner.py:150-152`. `max_iteration: 5` → `max_iteration_steps = 6`;
6-cı çağırışda `prompt_messages_tools = []`. Model hələ də tool istəyirsə
`AgentMaxIterationError` (`:310-311`). Yəni 5 tool raundundan sonra model
**alətsiz cavab verməyə məcburdur** — bu, uzun ssenaridə uydurma ehtimalını
artıran struktur təzyiqdir.

#### FP-14 — Eyni alət bir iterasiyada iki dəfə çağırılsa, tarixçədə birləşir **[sənədsiz tələ]**
Saxlama sxemi tool **adı ilə açarlanır**:
`fc_agent_runner.py:213-215` → `json.dumps({tool_call[1]: tool_call[2] …})`;
`:392-398` → `observation={tool_response["tool_call_name"]: …}`;
`tool_name` isə `";".join(...)` (`:211`).

Yenidən qurma da ada görə gedir: `base_agent_runner.py:390-430` —
`tool_names = tool_names_raw.split(";")`, sonra `tool_inputs.get(tool, {})` və
`tool_responses.get(tool, …)`. `tool_call_id` **yeni UUID** kimi generasiya
olunur (`:413`), orijinal id saxlanmır.

Nəticə: bir iterasiyada `lookup_order` iki fərqli arqumentlə çağırılsa, dict
açarı toqquşur və **növbəti növbədə** hər iki çağırış eyni arqument/müşahidə
cütü ilə bərpa olunur. Çoxnövbəli case-lərdə kontekst səssizcə korlanır.

#### FP-15 — Tarixçə səssizcə kəsilir, cari növbənin tool cavabları isə heç vaxt kəsilmir **[dizayn]**
`api/core/prompt/agent_history_prompt_transform.py:60-76` — token büdcəsi
aşılanda köhnə mesajlar sondan-əvvələ doğru atılır, istifadəçiyə heç bir siqnal
getmir. Əksinə, cari növbənin `_current_thoughts` siyahısı
(`fc_agent_runner.py:573`) **budanmır** — yəni böyük tool cavabı büdcəni tək
başına doldura bilər.

#### FP-16 — `max_tokens` səssizcə 16-ya qədər endirilə bilər **[dizayn]**
`api/core/app/apps/base_app_runner.py:81-82`:
`max_tokens = max(model_context_tokens - prompt_tokens, 16)`.
Prompt kontekst hüduduna yaxınlaşanda cavab büdcəsi kəsilir; nəticə yarımçıq
cavabdır, xəta deyil. Bizim qaçışda p95 latency 78.6 s və uzun tool cavabları
var — bu yol nəzəri deyil. `[bizim qaçışda işə düşüb-düşmədiyi ölçülməyib]`

### 5.4 Şəbəkə və tool qatı

#### FP-17 — Custom tool çağırışları SSRF proxy-dən keçir; yoxlama metodu yanıldıcıdır **[sənədsiz tələ]**
`api/core/helper/ssrf_proxy.py:258` → `ToolSSRFError`.
squid tərəfində sıra vacibdir — konteynerdən oxundu:

```
/etc/squid/squid.conf:12   include /etc/squid/dify_allow_private.conf
/etc/squid/squid.conf:13   http_access deny to_private_networks
```

Allowlist deny-dən **bir sətir əvvəl**dir; həmin fayl entrypoint tərəfindən
generasiya olunur, ona görə `restart` yox, `recreate` lazımdır.

**Tələnin özü metodolojidir:** `docker exec docker-api-1 curl …` HTTP 200
qaytarır, çünki `curl` proxy-dən keçmir. Yalnız `ssrf_proxy.post(...)` həqiqi
yolu sınayır. **Ədalətli qeyd:** Dify-ın xəta mətni gözləniləndən yaxşıdır —
dəqiq env dəyişənini adlandırır, kopyalanabilən CIDR nümunəsi verir və issue
linki qoyur (`ssrf_proxy.py:258-263`). Problem sənədin keyfiyyəti deyil,
vaxtıdır: mesaj yalnız **birinci uğursuz çağırışdan sonra** görünür.

#### FP-18 — Custom tool başlıqları yalnız provider credential-larından yığılır **[dizayn]**
`api/core/tools/custom_tool/tool.py:86-116` — `headers = {}` sıfırdan qurulur və
yalnız `self.runtime.credentials`-dən doldurulur. Case-dən case-ə dəyişən
başlıq ötürmək mümkün deyil. Buna görə paralel eval lane-ləri üçün **hər
lane-in öz tool provayderi və öz app-i** lazımdır (`target/app/IMPORT.md §9`).
Tək app ilə qaçış seriallaşır.

#### FP-19 — Path parametrləri URL-ə kodlaşdırılmadan yapışdırılır **[dizayn]**
`custom_tool/tool.py:260-261` → `url = url.replace(f"{{{name}}}", f"{value}")`.
Dəyər LLM-in seçdiyi arqumentdir; kodlaşdırma və validasiya yoxdur.
**Bizim spesifikasiyamızda path parametri yoxdur** (5 tool-un hamısı POST +
JSON gövdə), ona görə bu yol qaçışda işə düşmür — amma path parametri olan
hədəfdə birinci baxılacaq yerdir.

### 5.5 Bilik bazasının tool kimi verilməsi

#### FP-20 — Agent app-da retrieval **məcburi deyil**; `chat` app-da məcburidir **[dizayn — və bu sənədin ən vacib bəndi]**

| App rejimi | Kod | Davranış |
|---|---|---|
| `chat` | `api/core/app/apps/chat/app_runner.py:161-196, 211` | **Hər mesajda** `DatasetRetrieval.retrieve` çağırılır və nəticə `context=` kimi prompt-a yığılır |
| `agent-chat` | `api/core/app/apps/agent_chat/app_runner.py:79-87, 152-160, 180-188` | `context` **heç vaxt ötürülmür** → `None`. Bilik bazası `_init_prompt_tools`-da adi tool kimi qeyd olunur (`base_agent_runner.py:210-216`) |

Yəni `agent-chat`-də **modelin bilik bazasına heç müraciət etməmək seçimi var**,
və bu seçim heç bir yerdə qeydə alınmır, xəbərdarlıq vermir, cavabı bloklamır.
Yeganə maneə sistem promptundakı bir cümlədir:
*«Policy questions are answered from the Aurora Goods knowledge base. Search it
before you state any rule, time limit, fee or amount.»*

**Ölçdüyümüz nəticə** (`reports/full-run-02`, 147 case):

> **33 case (22.4%) bilik bazasını bir dəfə də çağırmadı.**

#### FP-21 — Sistem mesajı hərfbəhərf `pre_prompt`-dur **[dizayn]**
`fc_agent_runner.py:490-502` (`_init_system_message`) və
`simple_prompt_transform.py:117-131, 214`. Dify nə tool istifadə qaydası, nə
sitat tələbi, nə də "tool mətni məlumatdır" xəbərdarlığı əlavə edir. Guardrail
qatı yoxdur — `sensitive_word_avoidance` DSL-də `false`, `annotation_reply`
`false`. **Bütün davranış nəzarəti bir mətn blokundadır.**

#### FP-22 — `INIT_PASSWORD` təyin olunsa konsol 401 verir **[sənədsiz tələ]**
`api/controllers/console/wraps.py:314-323`:

```python
if dify_config.DEPLOYMENT_EDITION != DeploymentEdition.CLOUD and not _is_setup_completed():
    if dify_config.INIT_PASSWORD:
        raise NotInitValidateError()   # 401 not_init_validated
    raise NotSetupError()
```

Setup bitməmişkən `INIT_PASSWORD` doludursa, hər qorunan konsol marşrutu
**401 `not_init_validated`** verir (`controllers/console/error.py:19-22`) və
web ön-uc istifadəçini `/install`-a qaytarır — səbəb göstərilmədən.
`setup.py:92-93` eyni xətanı `InitializationValidationRequiredError`-dan
törədir. **Ziddiyyət:** `target/SETUP.md:52,58` `INIT_PASSWORD` təyin etməyi
tövsiyə edir; `PLAN.md` "Quraşdırma qeydi" isə onu silməyi. Reproduksiya üçün
`PLAN.md` doğrudur.

---

## 6. Müşahidə olunmuş uğursuzluqlar → memarlıq

Bu bölmə AP-014-ün əsas sualına cavab verir. Hər tapıntı üçün `reports/full-run-02`
artefaktından **hansı alətlərin çağırıldığı və nəyin retrieval olunduğu**
çıxarılıb.

### F-1 (RF-01·02·03) — KB-də olmayan mövzuda siyasət uydurulur, eskalasiya edilmir

**Artefakt** (`g1-gap07-exchange-size`):

```
tool çağırışları: dataset_1623dd7e… ×2   ·   escalate_to_human: YOX
qeydə alınan bənd: 10   (2 çağırış → 16 olmalı idi — FP-11)
gətirilən sənədlər: returns-and-refunds ×3, promotions ×2, payments ×1,
                    international-shipping ×2, shipping-and-delivery ×2
ən yüksək bal: 0.4872   ·   ən aşağı: 0.4136
```

**Memarlıq mexanizmi — üç qat:**

1. **FP-20.** Model KB-ni çağırdı, amma mübadilə (exchange) mövzusu korpusda
   yoxdur. Retrieval **boş qaytarmır** — `semantic_search` həmişə `top_k` ədəd
   bənd verir, çünki `score_threshold_enabled: false` (dataset-in
   `retrieval_model` sütunundan oxundu). Yəni "bu mövzu KB-də yoxdur" siqnalı
   **texniki olaraq mövcud deyil**: model 10 bənd alır, hamısı mövzudan kənar,
   amma "nəticə tapılmadı" bayrağı yoxdur.
2. **FP-08 + §3.** Bəndlər `"\n"` ilə yapışdırılmış mətn kimi gəlir — bal yox,
   sənəd adı yox. Bu case-də bütün 10 bəndin balı **0.41–0.49** aralığındadır,
   halbuki F-2 kimi mövzusu örtülü case-də birinci bənd **0.78**-dir. Fərq
   ölçüləbiləndir — amma model onu **görmür**, çünki ballar prompt-a düşmür.
3. **FP-21.** Eskalasiya yalnız sistem promptundakı bir cümlədir. Heç bir kod
   yolu `escalate_to_human`-ı məcbur etmir. 9/9 cəhddə çağırılmadı.

**Bir cümlə ilə:** boşluq aşkarlanması üçün sistemdə heç bir mexanizm yoxdur —
nə həd, nə "tapılmadı" siqnalı, nə məcburi eskalasiya. Model boşluğu ancaq öz
mühakiməsi ilə tanıya bilər, və tanımadı.

### F-2 (RF-04) — Billing anomaliyasına uydurulmuş izah, birtərəfli rədd

**Artefakt** (`g1-anomaly-ord10049-plus-shipping`):

```
tool çağırışları: lookup_order · dataset_1623dd7e… · get_customer
qeydə alınan bənd: 8   (1 KB çağırışı — dedup problemi yoxdur)
pos=1  shipping-and-delivery §4.5 "Aurora Plus … free standard shipping"  0.7836
pos=2  account-and-membership  §2 "Aurora Plus is an annual paid membership" 0.6360
```

**Memarlıq mexanizmi.** Bu, retrieval problemi **deyil** — həm qayda, həm fakt
kontekstdə idi. `get_customer` cavabında `first_subscribed_at: 2024-03-05` və
`current_period_start: 2026-04-10` sahələrinin **hər ikisi** var idi.

Kövrək nöqtə **TB-3**-dür: tool cavabı `str(tool_response)` kimi düz JSON sətri
olaraq kontekstə düşür (`fc_agent_runner.py:361, 367-372`). Sahələrin
semantikası — hansının "üzvlük nə vaxt başladı", hansının "cari dövr nə vaxt
başladı" olduğu — heç bir yerdə modelə deyilmir. `TOOLS.md §2` bunu spesifikasiyada
yazır, amma spesifikasiya **prompt-a düşmür**: tool təsviri OpenAPI-dən gəlir
(`base_agent_runner.py:153-155` → `tool_entity.entity.description.llm`), sahə
səviyyəsində izah daşımır.

Yəni memarlıq **çoxsahəli tarix mühakiməsini bütövlükdə modelə ötürür** və
nəticəni yoxlayan heç nə yoxdur. FINDINGS-in "tool qatında `was_active_on(order_date)`
törəmə sahəsi" təklifi məhz bu boşluğu bağlayır.

### F-3 (RF-05) — Beynəlxalq sifarişə domestik son tarix tətbiq olunur

**Bu tapıntı üçün artefakt gözlənilən mənzərəni dəyişir.**

`pw-11-en-damage_complaint-international-current-t5`, 5 növbə:

| Növbə | Tool çağırışları | Qeydə alınan bənd |
|---|---|---:|
| 1–3 | — | 0 |
| 4 | `lookup_order` | 0 |
| 5 | `check_return_eligibility`, `dataset_1623dd7e…` | 8 |

5-ci növbədə gətirilən 8 bəndin **sənəd bölgüsü**:

```
1  returns-and-refunds.md   0.5928  "1.5 A return is a request to send goods back…"
2  returns-and-refunds.md   0.5716  "5. Items damaged … 5.1 Damage visible on arrival…"   ← 7 gün
3  returns-and-refunds.md   0.5633  "8. Precedence ladder 8.1 …"
4  promotions-and-price-match.md  0.5566
5  promotions-and-price-match.md  0.5498
6  promotions-and-price-match.md  0.5448
7  returns-and-refunds.md   0.5377
8  warranty-policy.md       0.5331
```

**`international-shipping.md`-dən bir dənə də bənd yoxdur.** Yəni §6.1
("14 calendar days … rather than the 7 days in returns-and-refunds.md §5.1")
**modelə heç vaxt çatmadı** — nə 5-ci növbədə, nə də əvvəlki dörd növbədə
(1–4-də retrieval ümumiyyətlə olmadı).

**Bu, FINDINGS.md-in F-3 üçün yazdığı mexanizmi dəqiqləşdirir.** Orada rejim
"eyni mövzuda iki qüvvədə olan bənd" (R6-nın konflikt istiqaməti) kimi təsvir
olunub. Artefakt göstərir ki, **iki bənd kontekstdə deyildi** — biri vardı,
digəri yox idi. Yəni bu, seçim uğursuzluğu deyil, **retrieval uğursuzluğudur**;
generasiya qatı əlindəki yeganə bənddən düzgün nəticə çıxardı. (FINDINGS.md
writer-in sahəsidir; bu qeyd AP-014-dən çıxan giriş məlumatıdır, düzəliş deyil.)

**Memarlıq mexanizmi — dörd həlqə:**

1. **Retrieval sorğusunu model yazır.** Bilik tool-unun yeganə parametri
   sərbəst mətn `query`-dir (`dataset_retriever/dataset_retriever_tool.py:29-31`).
2. **Kontekstdəki fakt retrieval-a keçmir.** Model 4-cü növbədə `lookup_order`
   çağırıb və öz mətnində *«destination country GE (Georgia)»* yazıb — yəni
   sifarişin beynəlxalq olduğunu **bilirdi**. Amma Dify-da tool nəticəsini
   retrieval sorğusuna qoşan avtomatik mexanizm yoxdur. `metadata_filtering_mode`
   var, canlı dəyəri **`disabled`**-dır (§1.1) — və aktiv olsaydı belə, filtri
   sənəd metadatasına görə qurur, tool cavabına görə yox.
3. **Rerank yoxdur (FP-04).** Xam vektor oxşarlığı "damage + 22 days" sorğusunu
   domestik zədə bəndinə yaxın sayır; beynəlxalq bənd 8-liyə girmir.
4. **Provenans yoxdur (§3, `:244`).** Model §8 precedence ladder bəndini
   **aldı** (mövqe 3), amma bu, kömək etmədi — və əslində **əks istiqamətə**
   işarə etdi.

   > **Düzəliş (2026-08-28).** Bu bənd əvvəl ladder-in "beynəlxalq domestikdən
   > üstündür" qaydasını kontekstə gətirdiyini yazırdı. Korpus bunu təsdiq
   > etmir. `returns-and-refunds.md` §8.1 açıq deyir ki, ladder **qaytarma
   > pəncərəsini** müəyyən edir — zədə bildirişi müddətini yox. Həmin cədvəldə
   > zədə **rank 2**, beynəlxalq təyinat **rank 3**-dür, yəni hərfi oxunuşda
   > domestik zədə bəndi üstündür. Beynəlxalq göndərişlər üçün 14 günlük
   > zədə-bildirişi istisnası **yalnız** `international-shipping.md` §6.1-dədir
   > və o bənd kontekstə düşməyib.
   >
   > Nəticə tapıntını **gücləndirir**: modelin kontekstinə düşən yeganə
   > meta-qayda onu domestik bəndə yönəldirdi. `FINDINGS.md` F-3 və
   > `docs/writeup.md` dəqiq versiya ilə yazılıb.

   Ladder-i düzgün tətbiq etmək üçün lazım olan beynəlxalq bənd yox idi, və
   hansı bəndin hansı sənəddən gəldiyini göstərən heç nə yox idi.

**Bir cümlə ilə:** agent app-ında retrieval **modelin yazdığı bir sətir mətnə**
söykənir və kontekstdəki strukturlu faktlarla (sifariş ölkəsi) heç bir əlaqəsi
yoxdur. Bu, seqment seçimli sorğular üçün sistematik zəiflikdir.

### F-4 (RF-06) — KB-də açıq yazılmış hesab-kilidi qaydasına haqsız imtina

**Artefakt** (`bva-b-21-lockout_failed_attempts-5`):

```
tool çağırışları: []          ← HEÇ BİRİ
qeydə alınan bənd: 0
```

**Model bilik bazasını ümumiyyətlə açmadı** və mövzunu öz səlahiyyətindən
kənar elan etdi. `account-and-membership.md §1.2` indekslənmiş korpusdadır
(9 seqmentdən biri) və sorğuya birbaşa cavab verir.

**Memarlıq mexanizmi — FP-20 saf halda.** Sual məhz task-da verilib: *"bilik
bazası tool kimi verilir və kontekst avtomatik prepend olunmur — bu, nəyə
imkan verir?"*

Cavab: **imtinanın sıfır qiymətə başa gəlməsinə.**

- `chat` app-da retrieval hər mesajda icra olunur (`chat/app_runner.py:161-196`);
  §1.2 bəndi prompt-da olardı və model onu görməmiş imtina edə bilməzdi.
- `agent-chat`-də retrieval bir tool çağırışıdır; model onu **atlaya bilər** və
  atlayanda heç bir qat müdaxilə etmir: `fc_agent_runner.py:147` dövrü tool
  çağırışı olmadan birinci iterasiyada bitir, `QueueMessageEndEvent` yayımlanır,
  cavab 200 ilə qayıdır.
- Cavabda `retriever_resources` **boş** olur — yəni siqnal metadatada **var**,
  amma onu oxuyan heç bir qat yoxdur. Bu bizim üçün ölçüləbiləndir; hədəf
  sistemin özü üçün heç bir nəticə vermir.

**Ölçü:** 33/147 case (22.4%) KB-siz cavab verdi. Bu, F-4-ün tək case
olmadığını göstərir — sistematik bir davranış səthidir.

**Əlavə qat (ölçmə tərəfi):** case tam qaçışda **keçmişdi** — `account_locked`
assertion-ı çılpaq `lock` sətrini axtarırdı, imtina mətnindəki "locked out"
onu təmin edirdi (`GRADER-AUDIT.md#A-11`). FP-12 (yekun cavabın bütün
iterasiya mətnlərini birləşdirməsi) eyni sinif riski gücləndirir.

### Xülasə cədvəli

| Tapıntı | Əsas memarlıq mexanizmi | Kövrək nöqtə | Artefakt sübutu |
|---|---|---|---|
| **F-1** | boşluq siqnalı yoxdur (threshold yox, "tapılmadı" yox), eskalasiya prompt-dadır | FP-08, FP-20, FP-21 | 2 KB çağırışı, 10 bənd, `escalate_to_human` yox |
| **F-2** | tool JSON-u semantikasız sətir kimi ötürülür | TB-3, FP-21 | qayda + fakt kontekstdə idi |
| **F-3** | retrieval sorğusunu model yazır, kontekstdəki fakta bağlanmır; rerank yox; provenans yox | FP-04, FP-20, §3 `:244` | 8 bənddə `international-shipping.md` **yox** |
| **F-4** | retrieval məcburi deyil — imtina sıfır qiymətlidir | **FP-20** | **0 tool, 0 bənd**; run-da 33/147 KB-siz |

---

## 7. Konfiqurasiya tələləri — növbəti adamı ilişdirəcək yerlər

| # | Tələ | Simptom | Doğru yol |
|---|---|---|---|
| **CT-01** | `INIT_PASSWORD` təyin olunub | `/install` səhifəsi dövrə vurur, səbəb göstərilmir; API 401 `not_init_validated` | Lokal test instansiyasında `.env`-də boş saxla (`wraps.py:321-323`) |
| **CT-02** | SSRF proxy private hədəfi bloklayır | Agent uydurulmuş sifariş məlumatı verir, tool izi yoxdur; `curl` isə 200 qaytarır | `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal` + `docker compose up -d ssrf_proxy` (**recreate**, restart yox). Yoxlama `ssrf_proxy.post(...)` ilə, `curl` ilə **yox** |
| **CT-03** | Marketplace əlçatanlığı | Model provider plugin-i `marketplace.dify.ai`-dən yüklənir (`docker-compose.yaml:411`); versiya zamanla dəyişir | Plugin-i `.difypkg` kimi çıxar, repo-da pin-lə (`target/plugins/`) |
| **CT-04** | `response_mode: blocking` | `400 invalid_param` — nəzarətçi qatı bunu tutmur | `agent-chat` yalnız `streaming`; adapter SSE oxumalıdır (`app_generator.py:94`) |
| **CT-05** | `top_k` mənbəyi | UI/DSL `4` göstərir, sistem `2` və ya `8` çəkir | Yeganə həqiqət `datasets.retrieval_model` sütunudur. `PATCH` cavabına baxma — o `null` qaytarır (FP-05). Postgres-dən oxu |
| **CT-06** | Rerank mənbəyi | App-də `jina-reranker-v3` aktiv görünür, faktiki rerank yoxdur | Eyni sütun. `datasets.retrieval_model.reranking_enable` hökm edir (FP-04) |
| **CT-07** | `DIFY_BASE_URL`-də `/v1` şəkilçisi | Adapter `f"{base_url}/chat-messages"` qurur (`agentproof/adapters/http_agent.py:214`) — şəkilçi olmasa 404 | `DIFY_BASE_URL=http://localhost:8088/v1` (default də budur, `:124`) |
| **CT-08** | `provider_id` placeholder qalıb | Tool səssizcə siyahıdan düşür, model uydurur (FP-06) | Import `provider_id`-ni yoxlamır. `grep -c REPLACE_WITH` → 0 olmalıdır (`IMPORT.md §3`) |
| **CT-09** | Case-lər arası vəziyyət sızması | `RMA_ALREADY_EXISTS`, orta qaçışda susqun korlanma | Hər case-dən sonra `POST /admin/reset` (PLAN.md) |
| **CT-10** | Paralel lane-lər | Tək app ilə qaçış seriallaşır; başlıqla lane ayırmaq mümkün deyil (FP-18) | Hər lane üçün ayrı tool provayderi + ayrı app (`IMPORT.md §9`) |

### 7.1 Sənəd borcu (reproduksiya riski)

Aşağıdakılar **kod tələsi deyil**, bizim öz sənədlərimizdəki uyğunsuzluqdur.
Sahibləri başqa rollardır, ona görə burada yalnız qeyd olunur.
**Vəziyyət 2026-08-28-ə aiddir** (AP-020 paralel işləyir).

| Yer | Yazır | Canlı vəziyyət | Status |
|---|---|---|---|
| `target/app/aurora-support-agent.yml` `dataset_configs.top_k` | `8` | dataset `top_k: 8` | ✅ AP-020 bağladı |
| Həmin fayl, `datasets[].dataset.id` | `1623dd7e-…` (bge-m3) | app `1623dd7e-…` bağlıdır | ✅ AP-020 bağladı |
| Həmin fayl, başlıq şərhi (sətir 8-9) | *«agent-chat … accepts response_mode: blocking»* | `blocking` → 400 (FP-02) | ⬜ **açıq** |
| `target/app/IMPORT.md §6` | `response_mode: "blocking"` ilə smoke `curl`; *«`blocking` işləyir, SSE parser lazım deyil»* | `blocking` → 400 (FP-02) | ⬜ **açıq** |
| `target/SETUP.md:52,58` | `INIT_PASSWORD` təyin et | təyin olunsa konsol 401 verir (FP-22) | ⬜ **açıq** (scout) |

---

## 8. Ölçmə üçün nəticələr

Bu bölmə hədəf sistem haqqında deyil — **bizim harness haqqındadır**.

1. **`retrieval_hit_at_k` / `precision_at_k` 18/147 case-də aşağı göstərir**
   (FP-11). Ya grader bu case-lərdə `skipped` sayılmalı, ya da chunk siyahısı
   `agent_thought.observation`-dan bərpa edilməlidir. Hazırda səssizcə
   natamamdır.
2. **`retriever_resources` boş olması ölçüləbilən siqnaldır.** 33 case-də KB
   çağırılmayıb. "Siyasət sualına KB-siz cavab verildi" ayrıca metrik ola
   bilər — hazırda heç bir grader ona baxmır.
3. **Infra xətası ilə model səhvi API sərhədində fərqlənmir** (FP-09). Adapter
   `agent_thought.observation`-da `"tool invoke error:"` / `"unknown error:"`
   prefikslərini axtarıb case-i `incomplete` səbətinə atmalıdır; əks halda
   şəbəkə problemi keyfiyyət düşüşü kimi hesabata düşür.
4. **Substring assertion-ları FP-12-yə görə risklidir** — yekun `answer`
   ara iterasiya mətnlərini də daşıyır. `GRADER-AUDIT.md`-də tətbiq edilən
   "verdiktə bax, söz kökünə yox" qaydası bu kökdən doğur.

---

## 9. Nə yoxlanmadı

- **FP-04 (rerank söndürülüb)** kod yolu və konfiqurasiya müqayisəsi ilə
  çıxarılıb; `reranking_enable: true/false` ilə A/B retrieval ölçməsi
  aparılmayıb. `[təsdiqlənməyib — ayrıca eksperiment lazımdır]`
- **FP-16 (`max_tokens` endirilməsi)** kodda var; bizim qaçışda işə düşüb-düşmədiyi
  ölçülməyib. `[təsdiqlənməyib]`
- **FP-14 (eyni alət iki dəfə → tarixçədə birləşmə)** kod oxunuşundan çıxarılıb;
  canlı çoxnövbəli reproduksiya ilə göstərilməyib. `[təsdiqlənməyib]`
- **TB-7 / FP-19 (path parametri)** bizim OpenAPI spesifikasiyamızda path
  parametri olmadığı üçün icra olunmur — nəzəri sərhəd kimi qeyd olunub.
- **Plugin qatı** (`docker-plugin_daemon-1`, `langgenius/anthropic 0.3.28`)
  yalnız qiymət cədvəli baxımından incələnib (OPS-04). Plugin-in prompt/parametr
  emalı (məsələn `thinking: false` → `{type: disabled}` çevrilməsi) DSL
  şərhindən götürülüb, kodda oxunmayıb. `[təsdiqlənməyib]`
- **`agent_backend` / `local_sandbox` konteynerləri** bizim axında iştirak
  etmir (yeni `agent` rejimi üçündür); yoxlanmayıb.
- **F-1/F-2/F-4 üçün retrieval sənəd bölgüsü** artefaktdan oxundu, amma hər
  case üçün *hansı bəndin doğru cavabı daşıdığı* əl ilə yoxlanmadı — o iş
  `docs/TRIAGE-RUN02.md`-dədir.

---

## 10. İstinadlar

- `docs/OPS-FINDINGS.md` — OPS-01…05, VALID-01…03
- `docs/FAILURE-TAXONOMY.md` — rejim ID-ləri (G1, G2, G7, R6, C4, S2, T1…)
- `docs/TRIAGE-RUN02.md` — 29 stabil uğursuzluğun əl ilə oxunuşu
- `docs/GRADER-AUDIT.md` — A-11, A-18 (yalançı yaşıllar)
- `target/corpus/TOOLS.md` — tool spesifikasiyası, §0.5 hücum səthi
- `target/app/IMPORT.md` — import proseduru, SSRF və `top_k` addımları
- `reports/full-run-02/VmH7QgPBAE7PwcMo6Xwz7Q.json` — bu sənəddəki bütün
  artefakt rəqəmlərinin mənbəyi
