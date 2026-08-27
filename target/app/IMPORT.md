# Aurora Goods Support Agent — import proseduru (Dify 1.17.0)

Dify-ın Service API-sində app yaratma endpoint-i yoxdur (`target/DECISION.md`),
ona görə DSL bir dəfə UI-dan import olunmalıdır. Aşağıdakı 6 addım o birdəfəlik
işdir. Hər addımda **nə görünməlidir** yazılıb — səhvi elə orada tut, sonuncu
`curl`-a qədər gözləmə.

**İnsanın etməli olduğu: 6 addım, ~10 dəqiqə.** Addım 0 və 1 artıq icra edilib
(bax aşağıdakı qeydlər) — onlar burada reproduksiya üçün qalır.

Artefakt: [`aurora-support-agent.yml`](aurora-support-agent.yml)

---

## 0. Ön şərtlər — SSRF allowlist (BLOKLAYICI)

> **Status: icra edilib (2026-08-27).** Sıfırdan quraşdırmada təkrarla.

Mock tool servisinin `http://host.docker.internal:8099`-də cavab verməsi
**kifayət deyil**. Dify custom tool sorğularını `ssrf_proxy` (squid) üzərindən
göndərir, squid isə default olaraq bütün private/RFC1918 hədəflərini bloklayır —
`host.docker.internal` da onlardan biridir (Docker Desktop-da `192.168.65.254`).
Konteynerdən düz `curl` işləyir, agent-in tool çağırışı isə işləmir. Fərq budur
və onu ancaq həqiqi yolu sınayanda görürsən.

```bash
cd ~/agentproof-stack/dify/docker

# .env-ə əlavə et (SSRF_PROXY_ALLOW_PRIVATE_IPS sətrinin yanına):
# SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal
docker compose up -d ssrf_proxy
```

**Görünməlidir** — squid konfiqi allowlist-i `deny to_private_networks`
qaydasından ƏVVƏL yazmalıdır:

```bash
docker exec docker-ssrf_proxy-1 cat /etc/squid/dify_allow_private.conf
# acl dify_allowed_private_domains dstdomain host.docker.internal
# http_access allow client_localnet dify_allowed_private_domains
```

**Həqiqi yolu yoxla** (düz `curl` yox, Dify-ın öz SSRF helper-i):

```bash
docker exec docker-api-1 sh -lc 'cd /app/api && .venv/bin/python -c "
from core.helper import ssrf_proxy
r = ssrf_proxy.post(\"http://host.docker.internal:8099/tools/lookup_order\",
                    json={\"order_id\":\"ORD-10015\"}, timeout=10)
print(r.status_code)"'
# 200
```

`ToolSSRFError ... blocked by SSRF protection` alırsansa allowlist tətbiq
olunmayıb — `ssrf_proxy` konteynerini `docker compose up -d ssrf_proxy` ilə
yenidən yarat (restart kifayət etmir, entrypoint konfiqi yenidən yazmalıdır).

Linux-da `host.docker.internal` avtomatik həll olunmur; compose-a
`extra_hosts: ["host.docker.internal:host-gateway"]` lazımdır. Domen əvəzinə IP
allowlist-i istəyirsənsə: `SSRF_PROXY_ALLOW_PRIVATE_IPS=192.168.65.254/32`
(IP mühitdən asılıdır, domen variantı daha köçürülənidir).

---

## 1. Bilik bazasının retrieval ayarını pin-lə (BLOKLAYICI)

> **Status: icra edilib (2026-08-27).** Sıfırdan quraşdırmada təkrarla.

### ⚠️ Əvvəlcə bunu oxu: `top_k`-nı DSL YOX, DATASET həll edir

Agent app-ında **dataset-in öz `retrieval_model`-u hökm edir.** App
konfiqurasiyası və DSL-dəki `dataset_configs.top_k` **oxunmur**. Səbəb:

1. Dify bilik bazasını tool kimi verir və
   `DatasetRetrieverTool.get_dataset_tools()` retrieval strategiyasını məcburi
   `SINGLE`-a çevirir (*"Agent only support SINGLE mode"*);
2. sonra `to_dataset_retriever_tool()` `top_k`, `search_method` və rerank
   ayarlarını **dataset sətrindən** oxuyur
   (`api/core/rag/retrieval/dataset_retrieval.py:1312-1331`);
3. `retrieval_model` NULL olan dataset üçün lokal default **`top_k: 2`**-dir.

**Heç bir addımda xəbərdarlıq yoxdur.** UI, DSL və API bir rəqəm göstərir,
sistem başqasını icra edir. Praktiki nəticələr:

- DSL-də `top_k`-nı dəyişmək **HEÇ NƏYƏ təsir etmir**. Retrieval-ı dəyişmək
  üçün aşağıdakı `PATCH`-i qaç.
- Bu addımı buraxmaq **səssiz** ölçmə xətası verir: dataset NULL qalır, agent
  2 bənd çəkir, sənədlər isə 8 yazır.
- `GET /v1/datasets/{id}` cavabındakı `retrieval_model_dict.top_k` da tam
  etibarlı deyil: sütun NULL olanda Dify orada **default** rəqəmi (`4`)
  göstərir. Sütunun HƏQİQƏTƏN sabitləndiyini yalnız baza deyir (aşağıda).

**Niyə 8, halbuki bu sənəd əvvəl 4 yazırdı** — `docs/OPS-FINDINGS.md →
VALID-03`: canlı app-a atılan sorğu **8** `retriever_resources` qaytardı (bayat
Appendix A bəndi 8-ci mövqedə). `4` rəqəmi VALID-01-dən gəlirdi, o isə
retrieval-ı `POST /v1/datasets/{id}/retrieve` ilə TƏK ölçmüşdü, agent yolu ilə
yox; VALID-02-dən sonra əsas qaçış `top_k=8`-ə keçdi (əks halda 31 R6 case-i
səssizcə boş keçərdi), amma bu sənəd yenilənmədi. Aşağıdakı `PATCH` faktiki
dəyəri yazır.

```bash
set -a; . ~/agentproof-stack/dify/docker/.env; set +a
curl -s -X PATCH \
  "http://localhost:8088/v1/datasets/1623dd7e-3e9e-4a8c-97c3-d66fdbac8e39" \
  -H "Authorization: Bearer $AGENTPROOF_DATASET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"retrieval_model":{"search_method":"semantic_search","reranking_enable":false,
       "reranking_mode":null,
       "reranking_model":{"reranking_provider_name":"","reranking_model_name":""},
       "top_k":8,"score_threshold_enabled":false,"score_threshold":null}}' > /dev/null
```

**Görünməlidir** — cavabın özünə baxma. `PATCH` və `GET /v1/datasets/{id}`
hər ikisi `retrieval_model: null` qaytarır (cavab modeli sahəni ümumiyyətlə
çıxarmır), halbuki yazı baş tutub. Yeganə etibarlı yoxlama bazadır:

```bash
docker exec docker-db_postgres-1 psql -U postgres -d dify -t -c \
  "select retrieval_model from datasets where id='1623dd7e-3e9e-4a8c-97c3-d66fdbac8e39';"
# {"top_k": 8, ..., "search_method": "semantic_search", ..., "reranking_enable": false, ...}
```

`top_k: 8`, `search_method: semantic_search`, `reranking_enable: false` —
əsas qaçışın konfiqurasiyası (`docs/OPS-FINDINGS.md → VALID-02`, canlı sistemdə
`VALID-03` ilə təsdiqləndi). Sorğu boş sətir qaytarırsa sütun **NULL**-dur:
`PATCH` tutmayıb, agent 2 bənd çəkəcək.

> Sənədə deyil, artefakta bax. Hər qaçış faktiki konfiqurasiyanı ÖZÜ ilə
> daşıyır: `RunRecord.effective_top_k`, `embedding_model`,
> `embedding_provider`, `reranking_enabled` — hamısı canlı dataset API-dən
> oxunur (`agentproof/runner/retrieval_config.py`), oxunmasa açıq `unknown`
> qalır. Bu fayl ilə artefakt fərqlənirsə, **artefakt doğrudur**.

---

## 2. Custom tool-u OpenAPI spesifikasiyasından yarat

Mock servis işləməlidir (`curl -s localhost:8099/openapi.json | head -c 40`).

1. Brauzerdə **`http://localhost:8088/integrations/tools/api`** aç.
   (Naviqasiya: yuxarı menyu **Integrations** → sol tərəfdə **Tools** →
   **Custom** tabı.)
2. **`Create a Swagger API as Tool`** kartına bas. Modalın başlığı
   **`Create Custom Tool`** olmalıdır.
3. **Name**: `aurora_goods_support_tools`
4. **Schema**: `target/tools/openapi.json` faylının BÜTÜN məzmununu yapışdır.
   (`Import from URL` ilə `http://host.docker.internal:8099/openapi.json` da
   olar — amma brauzer o hostu görməyə bilər, fayl yapışdırmaq daha etibarlıdır.)
5. **Authorization method** → **`None`**. Mock servis auth tələb etmir.
6. **`Save`**.

**Görünməlidir** — schema yapışdırılan kimi, saxlamazdan əvvəl, modalın altında
**`Available Tools`** cədvəli **5 sətir** göstərməlidir:

| Name | Method | Path |
|---|---|---|
| `lookup_order` | POST | `/tools/lookup_order` |
| `get_customer` | POST | `/tools/get_customer` |
| `check_return_eligibility` | POST | `/tools/check_return_eligibility` |
| `initiate_return` | POST | `/tools/initiate_return` |
| `escalate_to_human` | POST | `/tools/escalate_to_human` |

Adlar spesifikasiyadakı `operationId`-lərdən gəlir və DSL-dəki `tool_name`
dəyərləri ilə hərfbəhərf üst-üstə düşməlidir. 5-dən az sətir görürsənsə schema
tam yapışdırılmayıb — davam etmə.

**İstəyə bağlı, amma faydalı:** `lookup_order` sətrindəki **`Test`** düyməsi ilə
`order_id = ORD-10015` göndər. `"today": "2026-09-01"` qayıdırsa, həm spesifikasiya,
həm şəbəkə yolu (addım 0) canlıdır.

---

## 3. Tool provider id-ni DSL-ə yaz

`agent_mode.tools[].provider_id` **ApiToolProvider sətrinin UUID-idir** və o
ancaq addım 2-dən sonra mövcud olur. DSL-də hazırda placeholder var.

```bash
cd ~/agentproof

PROVIDER_ID=$(docker exec docker-db_postgres-1 psql -U postgres -d dify -t -A -c \
  "select id from tool_api_providers where name='aurora_goods_support_tools';")
echo "$PROVIDER_ID"   # UUID görünməlidir, boş sətir YOX

sed -i '' "s/REPLACE_WITH_API_TOOL_PROVIDER_ID/$PROVIDER_ID/g" \
  target/app/aurora-support-agent.yml    # Linux-da: sed -i "s/.../g" ...
```

**Görünməlidir** — 5 sətrin hamısı əvəzlənib, placeholder qalmayıb:

```bash
grep -c "$PROVIDER_ID" target/app/aurora-support-agent.yml   # 5
grep -c REPLACE_WITH target/app/aurora-support-agent.yml     # 0
```

> **Diqqət.** Import `provider_id`-ni YOXLAMIR. Placeholder qalarsa app
> problemsiz import olunur, tool-lar isə ilk çağırışda sınır. Bu sətri buraxma.

---

## 4. DSL-i import et

1. **`http://localhost:8088/apps`** aç (yuxarı menyu **Studio**).
2. **`Create App`** → **`Import DSL file`** → **`From DSL file`**, sonra
   `target/app/aurora-support-agent.yml`-i seç. (Faylı birbaşa səhifəyə
   sürükləmək də olar — **`Drop DSL file here to create app`** görünür.)
3. **`Create`**.

**Görünməlidir:**

- **`Version Incompatibility`** xəbərdarlığı **OLMAMALIDIR**. DSL `0.7.0`-dır,
  1.17.0-ın `CURRENT_APP_DSL_VERSION` dəyəri də `0.7.0`-dır. Xəbərdarlıq
  görürsənsə səhv Dify versiyasındasan — dayan.
- App yaranır və **Orchestrate** səhifəsi açılır
  (`http://localhost:8088/app/<APP_ID>/configuration`), app tipi **Agent**.
- Orchestrate səhifəsində:
  - **Model**: `claude-sonnet-5`
  - **Tools**: 5 tool, hamısı aktiv
  - **Context / Knowledge**: `Aurora Goods Policies`
  - **Instructions** qutusu boş deyil (system prompt)

Baza yoxlaması:

```bash
docker exec docker-db_postgres-1 psql -U postgres -d dify -t -c \
  "select id, name, mode, enable_api from apps;"
# <APP_ID> | Aurora Goods Support Agent | agent-chat | t
```

`mode` `agent-chat` olmalıdır — `agent` YOX. `agent` rejimi `blocking`
dəstəkləmir (bax §6 qeydi).

---

## 5. App API açarını al

1. App daxilində **`Access Point`** bölməsinə keç
   (`http://localhost:8088/app/<APP_ID>/access-point?accessPoint=serviceApi`).
   Səhifədəki bölmələr sırası: `webApp`, **`serviceApi`**, `mcp`, `trigger`.
2. **`Backend service api`** kartında **`API Key`** → yeni açar yarat.
3. Açar `app-` ilə başlayır. Onu **dərhal köçür** — bir daha tam görünmür.

Kart boş görünürsə: **Orchestrate** səhifəsində bir dəfə **`Publish`** bas,
sonra qayıt.

**Görünməlidir** — kartda `Service API Endpoint` `http://localhost:8088/v1`
olmalı və status **`Enabled`**. Baza yoxlaması:

```bash
docker exec docker-db_postgres-1 psql -U postgres -d dify -t -c \
  "select type, app_id, left(token, 8) from api_tokens order by created_at desc limit 3;"
# app | <APP_ID> | app-xxxx
```

Açarı repo-ya commit etmə. Harness üçün:

```bash
echo 'AGENTPROOF_APP_KEY=app-...' >> ~/agentproof-stack/dify/docker/.env
```

---

## 6. Doğrulama — API həqiqətən işləyirmi

Bu `curl` bütün zənciri bir dəfəyə yoxlayır: app açarı → agent → tool çağırışı →
bilik bazasından retrieval → `blocking` cavab.

```bash
set -a; . ~/agentproof-stack/dify/docker/.env; set +a

curl -s -X POST http://localhost:8088/v1/chat-messages \
  -H "Authorization: Bearer $AGENTPROOF_APP_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "inputs": {},
        "query": "Order ORD-10015 arrived and I want to return the item. Can I?",
        "response_mode": "blocking",
        "conversation_id": "",
        "user": "agentproof-smoke"
      }' | python3 -m json.tool
```

**Gözlənilən cavab** (qısaldılmış; dəyərlər qaçışdan qaçışa dəyişir):

```json
{
  "event": "message",
  "task_id": "…",
  "id": "…",
  "message_id": "…",
  "conversation_id": "…",
  "mode": "chat",
  "answer": "Your order ORD-10015 was delivered on 12 August 2026 …",
  "metadata": {
    "usage": {
      "prompt_tokens": 3412,
      "completion_tokens": 604,
      "total_tokens": 4016,
      "currency": "USD",
      "total_price": "0.0193…"
    },
    "retriever_resources": [
      {
        "position": 1,
        "dataset_id": "1623dd7e-3e9e-4a8c-97c3-d66fdbac8e39",
        "dataset_name": "Aurora Goods Policies",
        "document_name": "returns-and-refunds.md",
        "score": 0.79,
        "content": "…"
      }
    ]
  },
  "created_at": 1788…
}
```

Nəyə baxmalısan, önəm sırası ilə:

1. **`"event": "message"` və JSON gəlir** (SSE yox) → `blocking` işləyir,
   harness adapterinə SSE parser lazım deyil.
2. **`metadata.retriever_resources` boş deyil** → agent bilik bazasını çağırıb
   və sitatlar ölçülə bilir. Boşdursa `retriever_resource.enabled` sınıb və ya
   agent ümumiyyətlə retrieval etməyib.
3. **`metadata.usage`** doludur → xərc/token grader-ləri işləyəcək.
4. Tool çağırışının həqiqətən baş verdiyini təsdiqlə:

```bash
curl -s "http://localhost:8088/v1/messages?conversation_id=<CONVERSATION_ID>&user=agentproof-smoke" \
  -H "Authorization: Bearer $AGENTPROOF_APP_KEY" \
  | python3 -c "import json,sys; [print(t['tool'], '->', t['observation'][:120]) for m in json.load(sys.stdin)['data'] for t in m.get('agent_thoughts',[]) if t.get('tool')]"
# lookup_order -> {"today":"2026-09-01","order_id":"ORD-10015", …
```

`agent_thoughts` boşdursa və ya `tool` sahəsi yoxdursa — tool bağlantısı
sınıqdır, addım 3-ə qayıt.

---

## 7. Tez-tez rast gəlinən sınmalar

| Simptom | Səbəb | Həll |
|---|---|---|
| `400 {"code":"not_chat_app"}` | app `workflow`/`completion` rejimindədir | DSL-də `app.mode: agent-chat` olduğunu yoxla |
| `400 Agent App only supports streaming response mode.` | app **yeni** `agent` rejimində yaranıb | `app.mode`-u `agent-chat`-ə qaytar və yenidən import et |
| `400 provider_not_initialize` | Anthropic credential-ı yoxdur/etibarsızdır | `select provider_name, is_valid from providers;` → `t` olmalıdır |
| Cavab gəlir, `retriever_resources` boşdur | `retriever_resource.enabled` `false`-dur, VƏ YA agent retrieval etməyib | DSL-də `retriever_resource.enabled: true`; sonra Logs-da tool izinə bax |
| Cavabda uydurulmuş sifariş məlumatı, tool izi yoxdur | `provider_id` placeholder qalıb, VƏ YA SSRF bloku | addım 3, sonra addım 0 |
| Tool çağırışı `ToolSSRFError` verir | squid allowlist tətbiq olunmayıb | addım 0-ı təkrarla, `ssrf_proxy`-ni **recreate** et |
| Retrieval 8 yox, 2 chunk qaytarır | dataset-in `retrieval_model`-u NULL-dur (DSL-dəki `top_k` oxunmur) | addım 1 |
| DSL-də `top_k` dəyişdim, heç nə dəyişmədi | agent app-ında dataset hökm edir, DSL yox | addım 1 (`PATCH`) |
| `Version Incompatibility` modalı | Dify versiyası 1.17.0 deyil | `docker compose ps` → image tag-larını yoxla |

---

## 8. Nə YOXLANMAYIB

- Addım 2–6 (UI import, app API açarı, canlı `chat-messages` çağırışı) **icra
  edilməyib**: brauzerdə hesabla iş və açar yaratmaq scout-un icazə hüdudundan
  kənardır. Yuxarıdakı UI marşrutları və etiketləri 1.17.0 web build-indən
  oxunub, DSL sxemi isə `docker-api-1` içindəki mənbədən təsdiqlənib
  (`AgentChatAppConfigManager.config_validate` DSL-in `model_config` blokunu
  səhvsiz keçirdi), amma **importun özü icra olunmayıb**.
- §6-dakı cavab nümunəsi sxem baxımından doğrudur (sahə adları
  `service_api`-nin cavab modelindən), rəqəmlər isə illüstrativdir.
- Addım 0 və 1 **icra edilib və yoxlanılıb**.

---

## 9. Paralel lane-lərin provizyonu (opsional — sürət üçün)

Tək app ilə eval qaçışı seriallaşır (`docs/STACK.md §12`): ölçülən 8.5 s/case,
450 sorğu ≈ 64 dəqiqə. Paralel qaçmaq üçün hər lane-in ÖZ app-i olmalıdır,
çünki Dify custom tool-a case-dən case-ə dəyişən başlıq ötürə bilmir
(`core/tools/custom_tool/tool.py::assembling_request` — başlıqlar yalnız
provider credential-larından yığılır).

Hər lane üçün, `N = 1..K`:

**9.1 Tool provider yarat** — §2-dəki OpenAPI ilə eyni, YALNIZ auth fərqli:

| sahə | dəyər |
|---|---|
| Authorization type | API Key |
| Header name | `X-AG-Session` |
| Header prefix | Custom (prefiks YOXDUR) |
| API key value | `lane-N` |

Servis eyni qalır (`http://host.docker.internal:8099`) — ayrı port lazım deyil,
vəziyyəti ad sahəsi bölür.

**9.2 App-i import et** — §4-dəki DSL, yalnız `provider_id`-lər 9.1-dəki yeni
provider-in UUID-si ilə əvəz olunur, `app.name` isə `… (lane-N)` olur.

**9.3 App API açarını al** — §5.

**9.4 Yoxla ki, başlıq həqiqətən gedir:**

```bash
curl -s http://localhost:8099/admin/sessions | jq .
# lane-N ad sahəsi görünməlidir; `default`-da gözlənilməz trafik VARSA,
# həmin lane-in provider credential-ı düzgün qurulmayıb.
```

**9.5 Konfiqurasiyanı yaz** (`evals/lanes.json`) və qaçır:

```bash
python evals/run.py --target dify_http --lanes evals/lanes.json \
  --dify-app-id <lane-1 app id> --model claude-sonnet-5
```

⚠️ Bütün lane app-lərinin model konfiqurasiyası EYNİ olmalıdır — əks halda
nəticələr müqayisə edilə bilməz. Hər app id üçün:

```bash
docker exec docker-db_postgres-1 psql -U postgres -d dify -tAc \
  "select a.name, amc.model::text from apps a
   join app_model_configs amc on amc.id = a.app_model_config_id
   where a.name like 'Aurora Goods Support Agent%';"
```

⚠️ Bir lane = bir ad sahəsi. İki lane eyni `tool_session` dəyərini bölüşərsə,
`build_lane_pool` qaçışı BAŞLAMAZDAN ƏVVƏL rədd edir — bu, susqun sızmanın
qarşısını alır.
