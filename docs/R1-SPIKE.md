# R1 spike — Inspect-i HTTP arxasındakı RAG agent-inə bağlamaq

**Status:** BAĞLANDI · **Tarix:** 2026-08-27 · **Müəllif:** Harness Engineer
**Risk mənbəyi:** `docs/STACK.md` §9, R1

> R1: *Inspect model evalları üçün dizayn olunub, məhsul/agent evalları üçün yox.
> Onun `Model` abstraksiyası provayder modelini gözləyir; bizim hədəfimiz HTTP
> arxasında RAG agent-idir.*

**Nəticə: yol (b) — Custom Agent (solver qatı) seçildi. Yol (a) — ModelAPI provayderi rədd edildi.**

---

## 1. Spike necə aparıldı

Real API açarı olmadan: hədəf `agentproof/testing/mock_dify.py` — Dify Service
API-nin `target/SETUP.md §7`-dəki wire formatını təqlid edən stub
(`POST /v1/chat-messages` blocking zərfi, `metadata.usage`,
`metadata.retriever_resources`, `GET /v1/messages` → `agent_thoughts`,
`GET /v1/info` Bearer yoxlaması, Dify xəta zərfləri).

Hər iki yol **eyni 5 case**, **eyni mock server** və **eyni grader-lərlə** qaçdı:

| case | grader | nəyi yoxlayır |
|---|---|---|
| `spike-01-restocking-fee` | `contains_all` | dəqiq siyasət rəqəmləri (30 gün, 15%) |
| `spike-02-giftcard-gap` | `contains_none` | boşluq halında siyasət uydurmur |
| `spike-03-giftcard-escalates` | `tool_call_matches` | `escalate_to_human` çağırılıb, `initiate_return` yox |
| `spike-04-order-retrieval` | `retrieval_hit_at_k` | gold chunk top-3-dədir |
| `spike-05-latency-budget` | `latency_under` | gecikmə büdcəsi |

Təkrar üçün:

```bash
.venv/bin/python evals/spike/r1_spike.py
```

---

## 2. Nəticə

```
--- R1 xulase (5 case) ---
  a: ModelAPI provider         status=success  kecen=5/5  hedefe sorgu=25 (ideal 5)
  b: Custom Agent (solver)     status=success  kecen=5/5  hedefe sorgu=5 (ideal 5)
tam kecen yol sayi: 2/2
```

**Hər iki yol funksional olaraq işləyir.** Fərq düzgünlükdə deyil, qiymətdədir:
yol (a) 5 case üçün hədəfə **25 sorğu** göndərdi — **5× çoxaltma**.

---

## 3. Yol (a) — ModelAPI provayderi · RƏDD

Kod silinmədi: `agentproof/runner/provider.py` qərarın təkrar yoxlanması üçün
qalır və spike-da hər dəfə qaçır. Rədd səbəbləri ölçülmüş faktlardır:

### 3.1 Tool izi tool sorğusu kimi oxunur → sonsuz döngə (bloklayıcı)

Inspect-in `generate()` solver-i modelin qaytardığı `tool_calls`-u **icra
ediləsi sorğu** sayır: tool-u çağırır, nəticəni söhbətə əlavə edir və modeli
yenidən çağırır. Bizim hədəfimizdə isə tool döngəsi **hədəfin öz içindədir** —
`agent_thoughts` artıq baş vermiş işin **izidir**, sorğu deyil.

Nəticə: Inspect izi sorğu kimi oxuyur, tool-u tapmır, xəta mesajını söhbətə
yazır və hədəfi TƏKRAR çağırır. Hədəf eyni cavabı verir. Döngə bağlanır.

Ölçülmüş: bir tool izi olan **tək** case üçün hədəfə **6 sorğu** getdi.
Spike ilk dəfə `message_limit` olmadan qaçırılanda **ümumiyyətlə bitmədi** —
süni `message_limit=12` qoyulandan sonra terminasiya etdi.

Bu, təkcə sürət problemi deyil: `SETUP.md §9`-dakı ~$16-lıq büdcə 5× çoxaltma
ilə ~$80 olur, üstəlik hədəfə lazımsız yük gedir və transkript saxta
"tool tapılmadı" mesajları ilə çirklənir.

### 3.2 `retrieved[]` üçün yer yoxdur

`ModelOutput`-da retrieval chunk-ları üçün sahə yoxdur. Yeganə çıxış —
`metadata` içinə soxmaq. Yəni `retrieval_hit_at_k` və `precision_at_k`
(bizim ən müdafiəolunan RAG ölçülərimiz, `STACK.md` §4.5) çərçivənin
sənədli sahəsində deyil, sərbəst lüğətdə yaşayır.

### 3.3 `base_url` / `api_key` semantikası toqquşur

`ModelAPI.__init__` `base_url` və `api_key`-i **model provayderi** üçün
mənimsəyir; bizdə bunlar **hədəf məhsulun** ünvanı və açarıdır. `**model_args`-a
düşmürlər — spike-ın ilk qaçışı məhz buna görə
`LocalProtocolError("Illegal header value b'Bearer '")` ilə sındı. Əl ilə geri
ötürmək lazım gəldi.

### 3.4 Hesabatda `target` və `model` bir-birinə qarışır

Inspect adapteri "model" sayır: log-un `model` sahəsinə `agentproof/dify_http`
yazılır. Halbuki bizim `RunRecord` sxemində `target` (Dify app@1.17.0) və
`model` (hədəfin İÇİNDƏKİ SUT modeli, `claude-sonnet-5`) **ayrı sahələrdir** —
müştəri hesabatında bu ikisi qarışmamalıdır.

### 3.5 Token usage yanlış qata yazılır

Inspect `EvalStats.model_usage`-u model provayderi üzrə aqreqasiya edir. Bizim
usage isə hədəfin daxili modelinə aiddir və hədəf onu **verməyə də bilər**
(o zaman `cost_under` `skipped` qaytarmalıdır). ModelAPI qatında "usage yoxdur"
ilə "usage sıfırdır" fərqi itir.

---

## 4. Yol (b) — Custom Agent · SEÇİLDİ

`agentproof/runner/agent.py`, [Inspect Custom Agents](https://inspect.aisi.org.uk/agent-custom.html)
mexanizmi ilə. `@agent` funksiyası `AgentState`-i alır, adapteri çağırır,
tam `AgentResponse`-u sample store-a yazır (`runner/bridge.py`), `state.output`-u
doldurur.

Qazandıqlarımız:

| | yol (a) | yol (b) |
|---|---|---|
| Hədəfə sorğu (5 case) | 25 | **5** |
| `message_limit` olmadan terminasiya edir? | **xeyr** | bəli |
| `retrieved[]` daşınır? | yalnız `metadata` hack-i ilə | bəli (store) |
| API açarı / model provayderi lazımdır? | `--model` mütləqdir | **`model=None`** |
| `target` və `model` ayrı qalır? | xeyr | bəli |
| Inspect-in paralellik / retry / limit / log maşını? | var | **var** |

Ən vacibi: `eval(model=None)` işləyir. Yəni harness **API açarı olmadan**
qaçır — bütün bu iş və 89 test məhz belə yoxlanıldı. Inspect-in paralellik,
retry, `--max-connections` rate-limit idarəsi, `.eval` log formatı və
`inspect view` debug UI-ı olduğu kimi qalır. Yalnız `Model` abstraksiyası
atlanır — çünki **hədəf model deyil, məhsuldur**.

STACK.md §9-dakı geri çəkilmə planı ("Inspect-in solver qatında birbaşa
`AgentAdapter` çağırmaq") məhz bu idi. Praktikada geri çəkilmə yox, **düzgün
seçim** olduğu ortaya çıxdı.

---

## 5. Reqressiya mühafizəsi

Qərar sənəddə deyil, testdə saxlanılır:

- `agentproof/tests/test_end_to_end.py::test_run_issues_exactly_one_target_call_per_case`
  — 5 case üçün mock serverə tam **5** sorğu getməlidir. Kimsə ModelAPI yoluna
  qayıtsa, bu test sınır.
- `agentproof/tests/test_architecture_rule.py::test_only_runner_and_normalize_touch_inspect`
  — Inspect körpüsü nazik qalır (icazəli fayl siyahısı).

---

## 6. R1-dən sonra qalan risk

Spike hədəfin **wire formatı** üzərində aparıldı, hədəfin **özü** üzərində yox.
Mock Dify-ın cavab zərfi `SETUP.md §7`-dən götürülüb, amma real Dify 1.17.0-a
qarşı `POST /v1/chat-messages` **hələ qaçırılmayıb** (admin hesabı və model
provayderi qurulmayıb — `SETUP.md §11` "YOXLANMADI" bölməsi).

Konkret olaraq mock ilə real arasında yoxlanmamış üç nöqtə:

1. **Agent app rejimi `blocking` dəstəkləmir** (`SETUP.md §7.2`) — yalnız
   `streaming`. Real app agent tipindədirsə, adapterə SSE oxuyan yol lazımdır.
2. `agent_thoughts`-dakı `tool_input` formatının real çıxışda dəqiq forması.
3. `metadata.usage`-da model adının gəlib-gəlmədiyi — gəlmirsə `cost_under`
   bütün case-lərdə `skipped` verəcək (səssiz keçmə deyil, amma xərc ölçüsü
   itir).

Bunlar adapter səviyyəsindədir (`agentproof/adapters/http_agent.py`, < 150 sətir)
və **memarlıq qərarına təsir etmir** — R1 bağlıdır.
