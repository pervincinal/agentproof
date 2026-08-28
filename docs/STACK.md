# STACK.md — Eval harness texnoloji qərarı

**Status:** Qərar verilib · **Tarix:** 2026-08-26 · **Müəllif:** Harness Engineer
**Əhatə:** Həm public tədqiqat qaçışı, həm də müştəri auditlərində təkrar istifadə olunan sistem.

---

## 1. Qərar (TL;DR)

**Hibrid: nüvə mühərriki kimi Inspect AI (UK AISI, MIT) + üstündə bizim öz `agentproof/` qatımız — adapter, grader registry, baseline/diff və hesabat.**

Yəni: qaçış mühərriki (paralellik, retry, log formatı, sandbox, debug UI) hazır və pulsuz gəlir; bizim yazdığımız yalnız **fərqləndirici hissə** — determinist grader-lər, kalibrasiya olunmuş judge, reqressiya müqayisəsi və hesabat.

Rədd edilənlər: promptfoo (OpenAI-a məxsusdur — müstəqillik problemi), Braintrust və LangSmith (self-host yalnız Enterprise müqavilə ilə), OpenAI Evals (2026-11-30 bağlanır), RAGAS (insan uyğunluğu çox aşağı), DeepEval (default telemetriya + ağır asılılıq), sıfırdan öz harness (2–3 həftə itki, nəticə daha pis).

---

## 2. Qərar meyarları və çəkiləri

Bu sıralama təsadüfi deyil — bizim biznes modelimizdən çıxır.

| # | Meyar | Çəki | Niyə |
|---|---|---|---|
| M1 | **Self-host / data egress = 0** | Bloklayıcı | Tənzimlənən sektor müştərisi (bank, sığorta, tibb) məlumatın bizim perimetrdən çıxmasına icazə vermir. Bu meyar keçilmirsə qalan heç nəyin əhəmiyyəti yoxdur. |
| M2 | **Xüsusi grader yazma asanlığı** | Çox yüksək | Bizim məhsulumuz məhz budur. Çərçivə grader-i çətinləşdirirsə, bizim marjamızı yeyir. |
| M3 | **Vendor müstəqilliyi** | Çox yüksək | Biz **müstəqil auditorik**. Audit alətinin sahibi audit olunan model provayderi olmamalıdır. |
| M4 | **Baseline müqayisəsi + CI** | Yüksək | "87%" faydasız; "91% → 87%, bu 4 case sındı" faydalıdır. |
| M5 | **Xərc/gecikmə telemetriyası** | Orta | Hesabatın ayrıca dəyərli bölməsi; olmasa özümüz yığmalıyıq. |
| M6 | **Müştəriyə təhvil xərci** | Yüksək | Auditin sonu "indi $X lisenziya alın" olmamalıdır. Bu deal öldürür. |
| M7 | **Başlama sürəti** | Orta | Tədqiqatı 2 ay gecikdirmək olmaz, amma 1 həftə fərq kritik deyil. |

---

## 3. Müqayisə cədvəli

| | **Inspect AI** | **promptfoo** | **DeepEval** | **RAGAS** | **Braintrust** | **LangSmith** | **OpenAI Evals** | **Sıfırdan öz** |
|---|---|---|---|---|---|---|---|---|
| **Lisenziya** | MIT | MIT | Apache-2.0 | Apache-2.0 | Qapalı (SaaS) | Qapalı (SaaS) | Platforma bağlanır | Bizim |
| **Sahibi** | UK AISI (dövlət) | **OpenAI** (03.2026-dan) | Confident AI (YC) | Exploding Gradients | Braintrust Data | LangChain Inc. | OpenAI | — |
| **M1 Self-host / egress** | ✅ Sadəcə Python kitabxanası. Şəbəkəyə yalnız hədəf model üçün çıxır. Log lokal fayl. | ✅ OSS lokal işləyir (SQLite). Amma prod self-host "tövsiyə olunmur"; ciddi variant = Enterprise On-Prem | ⚠️ İşləyir, **amma default telemetriya Posthog/Sentry/New Relic-ə gedir**; `DEEPEVAL_TELEMETRY_OPT_OUT=1` tələb olunur | ✅ Kitabxana | ❌ Self-host yalnız Enterprise planda | ❌ Self-host yalnız Enterprise ($100k+ səviyyə) | ❌ Yalnız OpenAI buludu | ✅ Tam nəzarət |
| **M2 Xüsusi grader** | ✅✅ `@scorer` dekoratoru → təmiz Python funksiya, `Score(value, answer, explanation, metadata)` qaytarır. Ayrıca paketə çıxarıla bilər | ⚠️ YAML mərkəzli; `python:`/`javascript:` assertion var, amma mürəkkəb grader YAML-ın içində yöndəmsizləşir | ✅ `BaseMetric` subclass — normal | ❌ Metrikləri hazırdır, öz determinist grader-in üçün deyil | ✅ TS/Python SDK, yaxşı | ⚠️ SDK var, amma platformaya bağlıdır | ❌ Məhdud grader tipləri | ✅ Nə istəsək |
| **M3 Lock-in** | **Ən aşağı.** Ödənişli tier ümumiyyətlə yoxdur, satmağa çalışan tərəf yoxdur | ⚠️ MIT qalır, amma yol xəritəsi OpenAI Frontier-ə xidmət edəcək. Provider-neytrallıq açıq sual | ⚠️ OSS → Confident AI buluduna yumşaq itələmə | Aşağı | ❌ Yüksək — data + iş axını platformada | ❌ Yüksək | ❌ Maksimum | Yoxdur |
| **M4 CI + baseline diff** | ⚠️ Qaçış və log var; **case-səviyyəli baseline diff-i özümüz yazmalıyıq** (~150–250 sətir) | ✅ Hazır müqayisə var, amma bizim istədiyimiz formatda deyil | ⚠️ pytest inteqrasiyası var, diff zəif | ❌ | ✅✅ Ən güclü tərəfi | ✅ Güclü | ⚠️ | Hamısını özümüz |
| **M5 Xərc/gecikmə** | ⚠️ Token istifadəsi (`EvalStats.model_usage`) və vaxt loga yazılır; **dollar üçün öz qiymət cədvəlimiz lazımdır** | ✅ Xərci nativ hesablayır | ⚠️ Zəif | ❌ | ✅ | ✅ | ⚠️ | Özümüz |
| **M6 Müştəriyə xərc** | **$0** — pip install, müştəri heç nə almır | $0 (OSS) / Team $50/ay / Enterprise custom | $0 / bulud üçün ödəniş | $0 | Pro $249/ay + Enterprise custom | Plus $39/istifadəçi + Enterprise custom | — | $0 |
| **M7 Başlama sürəti** | Orta — Task/Solver/Scorer abstraksiyasını öyrənmək 1–2 gün | **Ən sürətli** — YAML yaz, qaç | Orta | Sürətli | Sürətli | Sürətli | Sürətli | **Ən yavaş (2–3 həftə)** |
| **Əlavə hədiyyələr** | Paralellik + `max_connections` rate-limit idarəsi, retry, `eval-retry` ilə qismən nəticədən davam, `inspect view` debug UI, sandbox, 200+ hazır eval | Web UI, hazır red-team plagin dəsti (injection üçün faydalı) | 50+ hazır metrik | RAG metrikləri | Tam platforma | Tracing | — | — |
| **Elmi/brend etibarı** | ✅✅ UK AISI və frontier lab-ların frontier safety eval standartı | ✅ Geniş yayılıb | Orta | Orta | Sənaye | Sənaye | — | Sıfır (kənardan yoxlanıla bilməz) |

---

## 4. Rədd edilənlər və səbəbləri

### 4.1 promptfoo — ən yaxın rəqib, siyasi səbəbdən rədd

Texniki cəhətdən ən sürətli start. MIT, lokal qaçır, xərci nativ ölçür, red-team plaginləri Hunter-in prompt injection kateqoriyasını qismən hazır verir. OpenAI hətta öz Evals platformasından **rəsmi miqrasiya yolu** kimi promptfoo-nu göstərir.

Rədd səbəbləri, önəm sırası ilə:

1. **9 mart 2026-dan etibarən OpenAI-ın malıdır.** Biz müstəqil audit satırıq. Müştərilərin böyük hissəsinin agent-i OpenAI modelləri üzərində qurulub. "Sizin OpenAI agent-inizi OpenAI-ın alətiylə audit etdik" cümləsi auditin bütün mənasını zəiflədir. Bu texniki deyil, **məhsulun mövqeləndirmə problemidir** — və bizim satdığımız şey məhz müstəqillikdir.
2. **Yol xəritəsi riski.** MIT qalacağı bəyan edilib və bu doğrudur, amma növbəti 18 ayın red-team tədqiqatının OSS repoya, yoxsa OpenAI Frontier eksklüzivinə getməsi açıq sualdır. Biz alətin ən vacib hissəsində asılı qalmaq istəmirik.
3. **YAML tavanı.** Bizim grader-lərimiz sadə `contains` deyil: `tool_call_matches` parametr müqayisəsi, `no_leak` sistem prompt sızması, `consistency@k` semantik fərqlilik. Bunlar YAML konfiqinin içindəki `python:` qarmağına yazılanda oxunmaz və test edilməz olur. Grader-lərin özünün unit testi olmalıdır (bax `grader-eng.md`) — bu, normal Python paketi tələb edir.
4. **Self-host xəbərdarlığı.** Öz sənədləri OSS self-host-u prod üçün tövsiyə etmir (lokal SQLite, RBAC yox). Ciddi müştəri üçün Enterprise On-Prem lazım olur — yəni M6 pozulur.

> Qeyd: promptfoo-nun red-team plagin korpusunu **ilham mənbəyi** kimi istifadə etmək olar (hansı hücum sinifləri var), amma asılılıq kimi yox.

### 4.2 Braintrust — self-host divarına dəyir
Baseline/experiment müqayisəsi bazarın ən yaxşısıdır və bunu etiraf edirik. Amma self-hosted data plane yalnız Enterprise planındadır; Starter/Pro paylaşılan buludda işləyir. M1 bloklayıcıdır. Üstəlik audit sonunda müştəriyə "$249/ay + Enterprise danışığı" təklif etmək M6-nı pozur.

### 4.3 LangSmith — eyni problem, daha bahalı
Self-host yalnız Enterprise hibrid deployment-də, effektiv giriş həddi $100k+ səviyyəsində göstərilir. Həm M1, həm M6 pozulur. Əlavə olaraq LangChain ekosistemi ilə qravitasiya — hədəf sistem LangChain istifadə etmirsə, artıq yükdür.

### 4.4 OpenAI Evals — ölü variant
2026-06-03-də deprecation elan olunub: **2026-10-31-də read-only, 2026-11-30-da bağlanır.** Üstündə iki illik məhsul qurmaq mümkün deyil. Müzakirə bağlıdır.

### 4.5 RAGAS — metriklərinə güvənilmir
RAG metrikləri (faithfulness, context precision/recall) tanışdır və "RAG audit" satarkən cəlbedici görünür. Amma:
- RAGAS metriklərinin insan qiymətləndirməsi ilə korrelyasiyası ~0.55 səviyyəsində ölçülüb — pullu audit üçün qəbuledilməz.
- Sistem 0.95 faithfulness alıb yenə də səhv biznes cavabı verə bilər, çünki metrik retrieval-in **düzgünlüyünü** deyil, cavabın kontekstə **sadiqliyini** ölçür.
- Hamısı LLM-judge-dir → bahalı, qeyri-determinist, kalibrasiyasız.

**Əvəzi:** retrieval keyfiyyətini determinist ölçürük — etiketlənmiş gold chunk-lara qarşı `retrieval_hit@k` və `precision@k`. Bu ucuzdur, təkrarlanandır və müdafiə olunandır. RAGAS-ı ümumiyyətlə asılılıq kimi götürmürük.

### 4.6 DeepEval — yaxşı, amma bizə lazım deyil
Apache-2.0, `BaseMetric` ilə xüsusi metrik yazmaq normaldır, 50+ hazır metrik var. İki problem:
1. **Default telemetriya** Posthog, Sentry və New Relic-ə gedir. `DEEPEVAL_TELEMETRY_OPT_OUT=1` ilə söndürülür, amma opt-out mexanizmində keçmişdə səhvlər olub (`YES` dəyəri işləməyib və s.). Tənzimlənən müştəriyə "narahat olmayın, biz ENV dəyişəni qoymuşuq" deməli olmaq zəif mövqedir.
2. Hazır 50+ metrikin böyük hissəsi LLM-judge-dir və bizim fəlsəfəmizə (determinist üstünlük) ziddir. Yəni faydanın çoxunu istifadə etmirik, amma asılılığın hamısını daşıyırıq.

### 4.7 Sıfırdan öz harness — brend üçün lazımsız iş
Paralellik + rate-limit + retry + qismən nəticədən davam + strukturlaşdırılmış log + debug UI — bunların hamısı 2–3 həftəlik işdir və nəticə Inspect-dən yaxşı olmayacaq. **Müştəri qaçış mühərrikinin bizim yazdığımızı bilməyəcək və bilsə də ödəməyəcək.** Bu, düz mənada "brend üçün lazımsız iş"in tərifidir. Rədd.

---

## 5. Ticarət təhlili: "promptfoo konfiqi yazdım" vs "eval sistemi qurdum"

Bu suala düz cavab vermək lazımdır, çünki qərarın yarısı buradadır.

**Müştəri nəyə pul verir?** $3–6k-lıq auditdə dəyər zənciri belədir:

| Qat | Kim yazır | Müştəri üçün dəyər | Kopyalanma asanlığı |
|---|---|---|---|
| Qaçış mühərriki (paralellik, retry, log) | **Hazır alət** | Sıfır — görünmür | Kommodite |
| Hədəf adapteri | Biz (kiçik) | Aşağı | Asan |
| **Uğursuzluq taksonomiyası + dataset** | **Biz** | **Yüksək** | Çətin — domen bilgisi |
| **Determinist grader-lər** | **Biz** | **Ən yüksək** | Çətin — bizim IP-mizdir |
| **Judge kalibrasiyası** | **Biz** | Yüksək | Çətin |
| **Baseline/reqressiya qatı** | **Biz** | Yüksək — davamlı dəyər | Orta |
| **Hesabat və şərh** | **Biz** | Yüksək — satılan artefakt budur | Çətin |

Yəni: "sizin üçün promptfoo konfiqi yazdım" ucuz səslənir, çünki **doğrudan da ucuzdur** — cədvəlin yalnız 2-ci sətri. Bizim təklifimiz cədvəlin 3–7-ci sətirləridir və bu, mühərriki özümüzün yazıb-yazmamağımızdan asılı deyil.

Praktik nəticə üç maddədir:

1. **Mühərriki yazmaq marja yaratmır, marja yeyir.** Onu almırıq — pulsuz götürürük.
2. **Amma çərçivənin adı təhvildə görünməməlidir.** Müştəri `promptfooconfig.yaml` alırsa, dəyəri konfiqin ölçüsünə görə qiymətləndirir. Müştəri `agentproof/` paketi + hesabat alırsa, dəyəri tapıntılara görə qiymətləndirir. Ona görə **Inspect bizim daxili implementasiya detalımızdır**, təhvilin üzü deyil. Bu, gizlətmək demək deyil (metodologiya bölməsində açıq yazılır) — bu, təhvilin düzgün qatda paketlənməsidir.
3. **Inspect seçimi burada əlavə bonus verir.** Public tədqiqatda "UK AISI-nin frontier safety evalları üçün istifadə etdiyi çərçivə üzərində qurduq" cümləsi, "öz harness-imizi yazdıq" cümləsindən **daha güclü** satır. Öz harness "bəs sizin scorer-inizə niyə inanım?" sualını doğurur; tanınmış nüvə həmin sualı aradan qaldırır və diqqəti bizim grader-lərimizə yönəldir — yəni məhz göstərmək istədiyimiz yerə.

Bir cümlə ilə: **kommoditi al, fərqi qur.**

---

## 6. Tövsiyə olunan memarlıq

```
                  evals/run.py  (tək giriş nöqtəsi, CLI)
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
   agentproof/       agentproof/         agentproof/
    adapters/         runner/             report/
  (hədəf sistem)   (Inspect körpüsü)   (baseline, HTML, PR)
                          │
                    Inspect AI
              (paralellik, retry, log)
                          │
                  agentproof/graders/
            (TƏMİZ Python — Inspect import ETMİR)
```

**Ən vacib memarlıq qaydası:** `agentproof/graders/` paketi Inspect-i **import etmir**. Grader-lər `(Case, AgentResponse) -> GradeResult` imzalı təmiz funksiyalardır. Inspect ilə əlaqə yalnız `runner/scorer.py` içindəki nazik adapterdədir.

Bunun səbəbi birbaşa lock-in meyarıdır (M3): Inspect sabah dayanarsa, dəyişməli olduğumuz ~150 sətrlik bir fayldır, IP-mizin özü yox. Bu qayda pozularsa, qərarın yarısı itir.

---

## 7. Təklif olunan qovluq strukturu

```
agentproof/
├── docs/
│   ├── STACK.md                  ← bu sənəd
│   ├── ARCHITECTURE.md           ← Analyst
│   └── writeup.md                ← Writer
├── target/
│   └── SETUP.md                  ← Scout
│
├── agentproof/                   ← təkrar istifadə olunan paket (ƏSAS AKTİV)
│   ├── types.py                  ← Case, AgentRequest/Response, GradeResult, RunRecord
│   │
│   ├── adapters/                 ← hədəf sistemə qoşulma
│   │   ├── base.py               ← AgentAdapter protokolu
│   │   ├── http_agent.py         ← ümumi HTTP/REST agent (əksər müştəri üçün)
│   │   ├── openai_compat.py      ← /v1/chat/completions uyğun səth
│   │   └── local_python.py       ← in-process import (tədqiqat hədəfi üçün)
│   │
│   ├── graders/                  ← BİZİM FƏRQİMİZ · Inspect-dən asılı DEYİL
│   │   ├── base.py               ← Grader / AggregateGrader protokolları + registry
│   │   ├── deterministic/
│   │   │   ├── text.py           ← contains_all, contains_none, regex_match
│   │   │   ├── structure.py      ← json_schema
│   │   │   ├── tools.py          ← tool_call_matches
│   │   │   ├── leakage.py        ← no_leak
│   │   │   ├── retrieval.py      ← retrieval_hit_at_k, precision_at_k
│   │   │   └── budget.py         ← cost_under, latency_under
│   │   ├── aggregate/
│   │   │   └── consistency.py    ← consistency_at_k (k cavab tələb edir)
│   │   ├── judge/
│   │   │   ├── rubric.py         ← RubricJudge, struktur çıxış
│   │   │   ├── rubrics/*.md      ← rubrikalar versiyalanır
│   │   │   └── calibration.py    ← insan etiketi ilə uyğunluq hesabı
│   │   └── tests/                ← hər grader üçün pass+fail nümunəsi (məcburi)
│   │
│   ├── runner/                   ← Inspect körpüsü (NAZİK, dəyişdirilə bilən)
│   │   ├── provider.py           ← AgentAdapter → Inspect ModelAPI
│   │   ├── task.py               ← dataset.jsonl → Inspect Task
│   │   ├── scorer.py             ← tək @scorer, registry-yə dispatch edir
│   │   └── stages.py             ← cheap / judge mərhələ bölgüsü
│   │
│   ├── pricing/
│   │   └── models.yaml           ← token → USD cədvəli (Inspect dolları vermir)
│   │
│   └── report/
│       ├── normalize.py          ← Inspect .eval log → RunRecord (bizim sabit sxem)
│       ├── baseline.py           ← RunRecord × RunRecord → RunDelta
│       ├── merge.py              ← qaçış birləşməsi: ən son nəticə qalib, əvvəlki `superseded`
│       ├── html.py               ← statik hesabat
│       └── pr_comment.py         ← markdown xülasə
│
├── evals/
│   ├── run.py                    ← tək giriş nöqtəsi
│   ├── merge_runs.py             ← bir neçə qaçış → tək RunRecord (baseline istehsalı)
│   ├── datasets/*.jsonl          ← Dataset Engineer
│   ├── baselines/<target>@<dataset_hash>-<tarix>.json   ← docs/BASELINE.md
│   └── labels/judge_calibration.jsonl   ← əl ilə etiketlənmiş 20+ nümunə
│
├── reports/                      ← qaçış çıxışı (git-ignore, artefakt kimi yüklənir)
└── .github/workflows/evals.yml
```

Müştəri təhvili = `agentproof/` paketi + onların `evals/` qovluğu + `reports/`. Inspect sadəcə `requirements.txt`-də bir sətirdir.

---

## 8. Əsas modulların interfeysi (dizayn)

Aşağıdakılar **müqavilələrdir**, implementasiya deyil.

### 8.1 `types.py` — sistem boyu sabit tiplər

| Tip | Sahələr | Qeyd |
|---|---|---|
| `Case` | `id`, `input`, `tags[]`, `grader`, `expect{}`, `severity`, `source`, `repeat?` | Birbaşa dataset jsonl sətri (bax `dataset-eng.md`) |
| `AgentRequest` | `messages[]`, `session_id`, `seed?`, `metadata{}` | Çoxnövbəli case-lər üçün `messages` siyahıdır |
| `AgentResponse` | `text`, `tool_calls[]`, `retrieved[]`, `usage`, `latency_ms`, `raw` | `retrieved[]` = chunk id + mətn; retrieval grader-ləri üçün məcburi |
| `Usage` | `input_tokens`, `output_tokens`, `cached_tokens`, `model` | Dollar burada YOX — `pricing` qatında hesablanır |
| `GradeResult` | `passed: bool`, `score: float`, `grader: str`, `reason: str`, `evidence: dict` | `reason` insan üçün; `evidence` debug üçün (hansı ifadə tapılmadı və s.) |
| `CaseResult` | `case_id`, `response`, `grade`, `cost_usd`, `latency_ms`, `attempt` | Bir case-in bir qaçışı |
| `RunRecord` | `run_id`, `target`, `target_version`, `model`, `dataset_hash`, `started_at`, `results[]`, `totals` | **Bizim sabit sxemimiz** — Inspect log formatından asılı deyil |
| `RunDelta` | `fixed[]`, `broken[]`, `still_failing[]`, `flaky[]`, `pass_rate_before/after`, `cost_delta`, `p50/p95_delta` | Baseline müqayisəsinin nəticəsi |

### 8.2 `adapters/base.py` — hədəf sistem müqaviləsi

```
AgentAdapter (protokol)
  name        -> str
  version     -> str                      # hesabatda qeyd olunur
  invoke(req: AgentRequest) -> AgentResponse    # async
  health()    -> bool                     # qaçışdan əvvəl yoxlanır
```

**Müqavilə şərtləri:**
- Adapter **retry etmir** və **paralellik idarə etmir** — bunlar Inspect-in işidir. Adapter bir sorğu göndərir, bir cavab qaytarır.
  - **Yeganə istisna (AP-024): `rate_limit` sinfi.** Hədəf 429/529-u HTTP statusu ilə deyil, 200 statuslu SSE axınının içində `error` event-i kimi qaytarır — Inspect üçün bu, uğurlu cavabdır və onun retry maşını işə düşmür. Ona görə adapter yalnız bu sinfi eksponensial backoff-la (`Retry-After` varsa ona hörmətlə) təkrar edir. `credit_exhausted` və `auth` **təkrarlanmır**: gözləmək kömək etmir, hər cəhd pul və vaxt yandırır. `credit_exhausted` görünəndə qaçış **bütövlükdə dayanır** (`agentproof/failure.py:HALT`) və `evals/run.py` çıxış kodu **3** verir.
- Adapter xətanı iki sahə ilə qaytarır: `error` (hədəfin öz kodu — NƏ baş verdi) və `error_class` (səbəb sinfi — NƏ ETMƏLİ). Bir kodun altında iki fərqli hal qalmamalıdır.
- Adapter `latency_ms`-i özü ölçür (wall-clock, sorğudan cavaba).
- Hədəf token istifadəsini vermirsə, `usage` `None` olur və `cost_under` grader-i həmin case üçün `skipped` qaytarır — səssizcə keçmir.
- Yeni müştəriyə uyğunlaşma = bir adapter faylı. **Ölçü hədəfi: 150 sətirdən az.** Bundan çox olursa, hədəf sistem qara qutudur və Scout meyarları pozulub.

### 8.3 `graders/base.py` — fərqləndirici qat

```
Grader (protokol)
  name        -> str
  kind        -> "deterministic" | "judge"
  grade(case: Case, response: AgentResponse) -> GradeResult

AggregateGrader (protokol)      # consistency@k kimi çox cavab tələb edənlər
  grade_many(case: Case, responses: list[AgentResponse]) -> GradeResult

registry.get(name: str) -> Grader | AggregateGrader
```

**Müqavilə şərtləri:**
- **Bu paket `inspect_ai` import etmir.** Pozulmaz qayda.
- Determinist grader-lər **şəbəkəyə çıxmır**. Şəbəkə lazımdırsa, `kind = "judge"`-dur və ikinci mərhələyə düşür.
- Hər grader `evidence` doldurmalıdır. `passed=False` və boş `reason` qəbul olunmur — hesabatın dəyəri məhz buradadır.
- Hər grader-in `tests/` içində bilərəkdən keçən və bilərəkdən sınan nümunəsi olmalıdır (bax `grader-eng.md`).

```
RubricJudge (Grader)
  rubric_id, rubric_version, model
  grade(...) -> GradeResult   # daxili çıxış: {verdict, reason, confidence}
```
- Judge nəticəsi `GradeResult.evidence`-də `confidence` və `rubric_version` saxlayır.
- `calibration.py`: `calibrate(rubric, labels.jsonl) -> {agreement, n, confusion}`. **Uyğunluq < 85% olan judge CI-da bloklanır** və hesabatda faizi açıq yazılır.

### 8.4 `runner/` — Inspect körpüsü (dəyişdirilə bilən qat)

```
provider.py:  AgentAdapter -> inspect ModelAPI
              # Inspect-in paralellik/retry/rate-limit maşınından
              # istifadə etmək üçün hədəfi "model" kimi təqdim edir

task.py:      build_task(dataset_path, filter, stage, repeat) -> Task
              # jsonl -> inspect Sample; case metadata Sample.metadata-da qalır

scorer.py:    agentproof_scorer() -> Scorer
              # TƏK scorer. Sample.metadata["grader"] adını oxuyur,
              # registry-dən grader alır, GradeResult -> inspect Score çevirir.
              # Yeni grader əlavə etmək runner-a TOXUNMUR.

stages.py:    STAGE_CHEAP  = determinist grader-li case-lər
              STAGE_JUDGE  = judge grader-li case-lər
```

Bu dörd fayl Inspect-i bilən yeganə yerdir. Mühərrik dəyişsə, dəyişən budur.

### 8.5 `report/` — baseline və çıxış

```
normalize.py: inspect_log_path -> RunRecord
              # bizi Inspect-in log formatı dəyişikliklərindən qoruyur
              # burada token -> USD çevrilməsi pricing/models.yaml ilə edilir

baseline.py:  compare(current: RunRecord, baseline: RunRecord) -> RunDelta
              # kateqoriya: fixed / broken / still_failing / flaky
              # flaky = repeat>1-də qeyri-sabit nəticə; reqressiya sayılmır,
              #         amma ayrıca göstərilir
              gate(delta, policy) -> Pass | Fail(reasons)
              # policy: high severity case sınıqsa dərhal fail;
              #         ümumi pass rate düşməsi > həddi olarsa fail

html.py:      render(RunRecord, RunDelta) -> reports/index.html
              # kateqoriya üzrə keçmə, sınan case-lər TAM giriş/çıxış ilə,
              # xərc/gecikmə paylanması (p50/p95), zaman trendi

pr_comment.py: render(RunDelta) -> markdown
              # mütləq rəqəm deyil, DƏYİŞİKLİK:
              # "91% -> 87% · 4 sındı · 1 düzəldi · +$0.42 · p95 +1.3s"

merge.py:     merge_records([RunRecord, ...]) -> RunRecord + MergeOutcome
              # eyni case_id bir neçə qaçışda varsa ƏN SON götürülür
              # (meyar started_at; fayl adı və arqument sırası ROL OYNAMIR).
              # Əvəz olunan nəticə SİLİNMİR: `superseded` kimi sayılır.
              # Əvəzləmə eyni dataset_hash daxilindədir; sərhədi keçmək
              # üçün case tərifinin barmaq izi eyni olmalıdır (AP-042).
```

**Baseline snapshot-u** — `evals/baselines/<target>@<dataset_hash>-<tarix>.json`.
Cari snapshot iki qaçışın birləşməsidir (kredit kəsilməsi): hansı qaçışlardan,
hansı əmrlə, hansı grader versiyasından və nəyi ÖLÇMƏDİYİ **`docs/BASELINE.md`**-də
yazılıb. Snapshot əl ilə yamanmır — `python evals/merge_runs.py` ilə istehsal olunur.

### 8.6 `evals/run.py` — tək giriş nöqtəsi

```
python evals/run.py \
  --target        <adapter adı>        # məcburi
  --dataset       evals/datasets/*.jsonl
  --filter        tag=policy,severity=high
  --stage         cheap|judge|all      # default: all
  --repeat        N                    # qeyri-determinist case-lər üçün
  --seed          N
  --baseline      evals/baselines/<target>@<dataset_hash>-<tarix>.json
                                       # CI-da yolu `ci_gates.py baseline` verir
  --max-connections N                  # rate limit
  --out           reports/<run_id>/
  --fail-on-regression                 # CI üçün
  --skip-anchor-check                  # lövbər↔dataset yoxlamasını keç (hesabata düşür)
```

**`--filter` sintaksisi.** Vergül **şərt** ayırıcısıdır (VƏ), dəyər siyahısı deyil.
Eyni açarın təkrarı **VƏ YA** ilə birləşir, ona görə bir açara bir neçə dəyər
vermək üçün `|` var:

```
--filter 'tag=rag,severity=high'   # tag=rag VƏ severity=high
--filter 'id=a|b|c'                # id ∈ {a,b,c}  (= 'id=a,id=b,id=c')
--filter 'id=a,b,c'                # ✗ İŞLƏMİR — `b`, `c` şərt kimi oxunur
```

Açarlar: `tag` | `severity` | `grader` | `id`.

**Lövbər yoxlaması (AP-022).** Seçimdə retrieval (`gold_chunks`) case-i varsa,
qaçışdan əvvəl `target/corpus/anchor-map.json`-un dataset id-si hədəfin CARİ
dataset-i ilə tutuşdurulur. Uyğun deyilsə qaçış **açıq xəta ilə dayanır**
(`python target/corpus/anchors.py build`). Canlı dataset id oxunmursa (mock
hədəf, Dify-sız CI) qaçış davam edir, amma `anchor_check.status = "unverified"`
kimi hesabata düşür. Bax: A-19 — bayat xəritə 2 case-i `0/3` ilə sındırmışdı və
bu «retrieval işləmir» saxta tapıntısı kimi görünürdü.

Çıxış: `RunRecord` JSON + insan üçün konsol xülasə + `--baseline` verilibsə `RunDelta`.

**6 dəqiqə qaydası:** `--stage cheap` default olaraq CI-da hər PR-da qaçır (hədəf: < 4 dəq). `--stage judge` ayrıca job-dur və yalnız `evals/**` və ya hədəf konfiqi dəyişəndə, ya da nightly qaçır. Cheap mərhələ 6 dəqiqəni keçirsə, dataset böyükdür — problem harness-də deyil.

---

## 9. Risklər və azaldıcı tədbirlər

| # | Risk | Ehtimal | Təsir | Azaldıcı tədbir |
|---|---|---|---|---|
| R1 | ~~**Inspect model evalları üçün dizayn olunub, məhsul/agent evalları üçün yox.**~~ **✅ BAĞLANDI (2026-08-27)** — spike aparıldı, bax [`R1-SPIKE.md`](R1-SPIKE.md) | — | — | Yol (b) seçildi: Inspect **Custom Agent** (solver qatı) — hədəf `Model` kimi yox, agent kimi sarılır, `eval(model=None)` ilə API açarı olmadan qaçır. Yol (a) (ModelAPI provayderi) funksional işlədi, amma **5 case üçün hədəfə 25 sorğu** göndərdi (`generate()` hədəfin tool İZİNİ tool SORĞUSU kimi oxuyur → döngə) və `message_limit` olmadan terminasiya etmədi — rədd. Reqressiya testi: `test_run_issues_exactly_one_target_call_per_case` |
| R2 | Inspect log formatı major versiyada dəyişir | Aşağı | Orta | `report/normalize.py` yeganə toxunma nöqtəsidir; versiya `requirements.txt`-də pin olunur |
| R3 | Dollar xərci öz cədvəlimizdən gəlir → qiymətlər köhnəlir | Yüksək | Aşağı | `pricing/models.yaml` tarixli; hesabatda "qiymət cədvəli tarixi" göstərilir |
| R4 | UK AISI Inspect-i tərk edir | Çox aşağı | Orta | MIT + fork mümkün; həm də grader qatımız onsuz da müstəqildir |
| R5 | promptfoo-nu seçməməyimiz "sənaye standartı deyil" etirazı doğurur | Aşağı | Aşağı | Metodologiya bölməsində Inspect-in UK AISI mənşəyi yazılır — bu, zəiflik deyil, güc arqumentidir |
| R6 | Müştəri artıq LangSmith/Braintrust istifadə edir və oraya inteqrasiya istəyir | Orta | Aşağı | `RunRecord` sabit JSON sxemdir → export adapteri yazmaq kiçik işdir. Onların platformasına **yazırıq**, ondan asılı olmuruq |

---

## 10. İlk həftənin ardıcıllığı

1. ~~**R1 spike-ı** (1 gün)~~ — ✅ **bitdi**, `docs/R1-SPIKE.md`. Nəticə: ModelAPI yox, **Custom Agent** qatı. Sənədin qalanı qüvvədədir.
2. `types.py` + `graders/base.py` + registry (0.5 gün) — bütün komandanın bağlı olduğu müqavilə. Dataset Engineer və Grader Engineer bunu gözləyir, ona görə birinci çıxır.
3. `runner/` dörd faylı + `evals/run.py` skeleti (1 gün).
4. `report/normalize.py` + `baseline.py` + `pr_comment.py` (1.5 gün).
5. `.github/workflows/evals.yml` iki mərhələli (0.5 gün).
6. `report/html.py` (1 gün) — sonuncu, çünki JSON olmadan mənasızdır.

---

## 11. Mənbələr

- [Inspect (UK AISI) — rəsmi sayt](https://inspect.aisi.org.uk/) · [scorers](https://inspect.aisi.org.uk/scorers.html) · [eval logs](https://inspect.aisi.org.uk/eval-logs.html) · [extensions](https://inspect.aisi.org.uk/extensions.html) · [GitHub (MIT)](https://github.com/UKGovernmentBEIS/inspect_ai) · [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals)
- [OpenAI to acquire Promptfoo (09.03.2026)](https://openai.com/index/openai-to-acquire-promptfoo/) · [Promptfoo blog](https://www.promptfoo.dev/blog/promptfoo-joining-openai/) · [TechCrunch](https://techcrunch.com/2026/03/09/openai-acquires-promptfoo-to-secure-its-ai-agents/) · [CNBC](https://www.cnbc.com/2026/03/09/open-ai-cybersecurity-promptfoo-ai-agents.html) · [SecurityWeek](https://www.securityweek.com/openai-to-acquire-ai-security-startup-promptfoo/)
- [Promptfoo self-hosting sənədi](https://www.promptfoo.dev/docs/usage/self-hosting/) · [Enterprise](https://www.promptfoo.dev/docs/enterprise/) · [GitHub (MIT)](https://github.com/promptfoo/promptfoo)
- [Vendor-neutral alternativlər müzakirəsi (Repello)](https://repello.ai/blog/promptfoo-alternatives)
- [OpenAI deprecations — Evals bağlanması](https://developers.openai.com/api/docs/deprecations) · [Şərh](https://therouter.ai/news/openai-evals-agent-builder-prompts-deprecation-november-2026/)
- [DeepEval — data privacy / telemetriya](https://deepeval.com/docs/data-privacy) · [environment variables](https://deepeval.com/docs/environment-variables) · [telemetry.py](https://github.com/confident-ai/deepeval/blob/main/deepeval/telemetry.py) · [Enterprise](https://deepeval.com/enterprise)
- [RAGAS/TruLens/DeepEval müqayisəsi (Atlan)](https://atlan.com/know/llm-evaluation-frameworks-compared/) · [LLM-as-judge stress test (arXiv)](https://arxiv.org/pdf/2605.27789)
- [Braintrust pricing 2026](https://www.truefoundry.com/blog/braintrust-pricing) · [self-hosting changelog](https://www.braintrust.dev/docs/data-plane-changelog) · [Coverge analizi](https://coverge.ai/blog/braintrust-pricing)
- [LangSmith pricing 2026](https://coverge.ai/blog/langsmith-pricing) · [Langfuse vs LangSmith — lock-in](https://www.morphllm.com/comparisons/langfuse-vs-langsmith)
- [Langfuse (MIT, self-host)](https://github.com/langfuse/langfuse) — nüvə kimi seçilmədi, amma müştəri artıq observability istəyirsə export hədəfi kimi baxıla bilər

---

## 12. Paralel qaçış və izolyasiya (6 dəqiqə qaydası)

### 12.1 Problem

`POST /admin/reset` tool servisinin QLOBAL vəziyyətini sıfırlayırdı, ona görə
`reset + invoke` cütü atomik olmalı idi və qaçış FAKTİKİ OLARAQ SERİALLAŞIRDI.
`--max-connections` artırmaq heç nə vermirdi.

Ölçülən (10 case, `evals/datasets/full.jsonl`-dən, canlı Dify 1.17.0, `dify_http`):

| rejim | wall | s/case | p50 gecikmə |
|---|---|---|---|
| 1 lane (köhnə davranış) | 85 s | **8.5** | 9 172 ms |
| 5 lane | 22 s | **2.2** | 9 347 ms |

450 sorğuluq qaçış: 8.5 s/case → **~64 dəqiqə**.

### 12.2 Həll — tool vəziyyətinin ad sahəsi

`target/tools/service.py` mutasiya edən vəziyyəti `X-AG-Session` başlığına görə
bölür. Başlıq yoxdursa `default` ad sahəsi işlədilir — yəni köhnə davranışın
eynisi. `POST /admin/reset` YALNIZ öz ad sahəsini sıfırlayır (`?all=1` bütün
ad sahələrini silir, ancaq proses səviyyəsində təmizlik üçündür).

Runner tərəfdə (`agentproof/runner/isolation.py`) bu, **lane hovuzuna** çevrilir:
hər case bir lane icarəyə götürür, lane-in ad sahəsi case-dən sonra sıfırlanır,
lane geri qaytarılır. Paralellik lane sayı ilə məhdudlaşır və AÇIQ göstərilir
(`task.metadata.lanes`, `RunRecord.totals.lanes`).

Zəmanət pozulmur:

* lane daxilində `reset + invoke` hələ də atomikdir;
* iki lane eyni `(reset_url, ad sahəsi)` cütünü bölüşə bilməz — `build_lane_pool`
  bunu qaçış BAŞLAMAZDAN ƏVVƏL xəta ilə rədd edir;
* sıfırlama uğursuz olarsa lane ÖLÜ elan olunur və bir daha case-ə verilmir
  (`LaneExhausted`), qaçış səssizcə davam etmir.

Testlər `agentproof/tests/test_isolation.py`-dədir və HƏR İKİ istiqamətlidir:
3 case eyni sifarişə EYNİ ANDA (`threading.Barrier`) RMA açır və hamısı
uğurludur; ad sahəsi başlığı söndürüləndə həmin qaçış `RMA_ALREADY_EXISTS`
ilə sınır.

### 12.3 ⚠️ Dify məhdudiyyəti — bir lane = bir Dify app-i

Dify custom tool-a case-dən case-ə DƏYİŞƏN başlıq ötürə BİLMİR. Mənbədən
yoxlanılıb (Dify 1.17.0):

* `api/core/tools/custom_tool/tool.py::assembling_request` — başlıqları yalnız
  provider credential-larından (`api_key_header` / `api_key_value`) yığır;
* `…::do_http_request` — əlavə olaraq yalnız openapi-də elan edilmiş
  `in: header` parametrlərini qoyur, onların dəyəri isə LLM-in tool
  arqumentlərindən gəlir (yəni modelin nəzarətindədir — ölçməni çirkləndirər);
* nə `conversation_id`, nə `/v1/chat-messages`-in `user` sahəsi tool sorğusuna
  düşmür.

Deməli ad sahəsi **statik** olmalıdır: hər lane üçün ayrıca Dify app-i (eyni
DSL) + ayrıca tool provider, provider-in credential-ı `X-AG-Session: lane-N`
göndərir. Provizyon addımları: `target/app/IMPORT.md §9`.

Yalnız OXUYAN case-lərdən ibarət dataset istisnadır: mutasiya olmadığı üçün
tək app ilə də paralel qaçmaq etibarlıdır. Yuxarıdakı 5 lane-lik ölçmə məhz
belədir və `GET /admin/sessions` ilə təsdiqlənib (`created_rmas: 0`,
`escalations: 0`).

### 12.4 Nə qədər lane lazımdır — və tavan

Canlı Dify-ın buraxma qabiliyyəti (yalnız oxuyan sorğularla ölçülüb):

| eyni anda | wall | s/sorğu | median gecikmə | buraxma |
|---|---|---|---|---|
| 4  | 10.8 s | 2.71 | 9.4 s | 0.37 sorğu/s |
| 10 | 11.0 s | 1.10 | 9.2 s | **0.91 sorğu/s** |
| 16 | 19.7 s | 1.23 | 10.4 s | 0.81 sorğu/s |

Buraxma ~10-12 paralellikdə doyur (16-da maksimum gecikmə 19.7 s-ə qalxır —
növbə başlayır). Yəni **bir Dify instansiyasında tavan ≈ 0.9 sorğu/s**:

* 450 sorğu (150 case × `--repeat 3`) → ən yaxşı halda **≈ 8.3 dəqiqə**;
* 6 dəqiqəyə girmək üçün ya sorğu sayı azalmalıdır (`--repeat 3` yalnız
  qeyri-determinist alt dəstə tətbiq olunsun: 150 + 2×N), ya da Dify
  `api`/`worker` replikaları artırılmalıdır.

Bu, dürüst rəqəmdir: lane-lər harness-in seriallaşmasını aradan qaldırır,
amma hədəfin öz tavanını qaldırmır.

### 12.5 İstifadə

```bash
# tək lane — köhnə davranış (dəyişməyib)
python evals/run.py --target dify_http --tool-reset-url http://localhost:8099/admin/reset

# N lane
python evals/run.py --target dify_http --lanes evals/lanes.json
```

`evals/lanes.json`:

```json
[
  {"name": "lane-1",
   "tool_reset_url": "http://localhost:8099/admin/reset",
   "tool_session": "lane-1",
   "adapter": {"api_key": "app-…lane-1 app-inin açarı…"}},
  {"name": "lane-2", "tool_reset_url": "http://localhost:8099/admin/reset",
   "tool_session": "lane-2", "adapter": {"api_key": "app-…"}}
]
```

---

## 13. `usage.model` — əl etiketi deyil, yoxlanılan dəyər

Dify `message_end.metadata.usage`-da model ADINI vermir, ona görə etiket
`AGENTPROOF_SUT_MODEL`-dən gəlirdi. App-də model dəyişilib env unudulsa, xərc
SƏSSİZCƏ yanlış dərəcə ilə hesablanırdı — hesabat isə inandırıcı görünürdü.

`agentproof/runner/sut_model.py` qaçışın əvvəlində avtoritet mənbəni oxuyur:

```sql
select amc.model::text from apps a
join app_model_configs amc on amc.id = a.app_model_config_id
where a.id = '<APP_ID>';
```

⚠️ `where app_id = …` ilə oxumaq SƏHVDİR: hər redaktə `app_model_configs`-a yeni
sətir yazır və canlı bazada həmin app üçün artıq iki sətir var. Aktiv olan
yalnız `apps.app_model_config_id`-nin göstərdiyidir.

Davranış:

| hal | nəticə |
|---|---|
| etiket == app-in modeli | `match` — qaçış davam edir |
| etiket != app-in modeli | **`SutModelMismatch`, qaçış dayanır (exit 1)** |
| etiket boşdur | `adopted` — bazadakı ad götürülür |
| baza əlçatmazdır (CI) | `unavailable` — XƏBƏRDARLIQ, hesabata düşür |

Nəticə `RunRecord.totals.model_check`-ə yazılır, yəni "yoxlanmadı" halı
hesabatda gizlənə bilmir.

```bash
python evals/run.py --target dify_http \
  --dify-app-id 4daef326-beb5-4c36-88a4-167d20194729 \
  --model claude-sonnet-5
```

---

## 14. Çoxnövbəli söhbət (`conversation_id` zəncirlənməsi)

### 14.1 Problem

`dify_http` adapteri yalnız `req.query`-ni (sonuncu istifadəçi növbəsini)
göndərirdi və `conversation_id`-ni zəncirləmirdi. `full.jsonl`-dəki **15
çoxnövbəli case tək-növbəli kimi** ölçülərdi. C1 (kontekst itkisi) taksonomiyada
**P=20** prioritetlidir — yəni hesabatda rəqəm görünərdi, amma yalan olardı.
Yanlış ölçmək ölçməməkdən pisdir.

### 14.2 Həll

Adapter case-in bütün **istifadəçi** növbələrini bir söhbətdə ardıcıl göndərir:

1. növbə 0 → `conversation_id: ""` (yeni söhbət, SETUP.md §7.2);
2. cavabdan gələn `conversation_id` yadda saxlanır;
3. növbə 1..n → həmin id ilə. `user` sahəsi bütün növbələrdə **eynidir** —
   Dify söhbəti son istifadəçiyə bağlayır.

Susqun deqradasiya yoxdur:

| hal | davranış |
|---|---|
| bir növbə xəta verdi | qalan növbələr **göndərilmir**, `error` saxlanılır |
| ilk növbə `conversation_id` qaytarmadı, daha növbə var | **`conversation_not_returned`** xətası (yeni söhbətlə davam etmək case-i gizlicə tək-növbəliyə çevirərdi) |
| dataset-də skriptləşdirilmiş `assistant` növbəsi var | göndərilə bilmir (Dify tarixçəni özü qurur) → `raw.dropped_scripted_assistant_turns`-də **sayılır** |

### 14.3 Növbə-növbə qeyd

`AgentResponse.turns` hər növbənin öz `text` / `tool_calls` / `retrieved` /
`usage` / `latency_ms` dəyərini saxlayır (`raw.turn_index`, `raw.query`,
`raw.sent_conversation_id` ilə birlikdə). Yekun cavabın sahələri:

| sahə | çoxnövbəli semantika | niyə |
|---|---|---|
| `text` | **sonuncu** növbə | qiymətləndirilən yekun cavabdır |
| `tool_calls` | **bütün** növbələrin birləşməsi, sıra ilə | `forbidden_tools` başqa cür işləmir: 2-ci növbədəki icazəsiz `initiate_return` son növbəyə baxmaqla görünməz (T1, P=20) |
| `retrieved` | bütün növbələr, `chunk_id` üzrə təkrarsız | çoxnövbəli hit@k "hansısa növbədə tapıldı" deməkdir |
| `usage` | növbələrin **cəmi** | xərc bütöv söhbətə görədir |
| `latency_ms` | növbələrin cəmi | |

Tək növbəli case-də heç nə sarılmır — `turns` boş qalır və davranış əvvəlki
ilə **bit-bit eynidir**.

### 14.4 Lane və sıfırlama ilə uyğunluq

* Bir case = bir `invoke()` = **bir lane icarəsi**, ona görə çoxnövbəli case-in
  bütün növbələri eyni tool ad sahəsindədir (`test_all_turns_of_a_case_stay_in_one_lane`).
* `/admin/reset` case-in **əvvəlində** çağırılır, növbələr **arasında yox**.
  Növbələr arasında sıfırlansaydı, agent öz 1-ci növbədə yaratdığı RMA-nı 3-cü
  növbədə "yoxdur" görərdi — bu, hədəfin səhvi deyil, harness-in uydurduğu
  uğursuzluq olardı (`test_tool_state_is_not_reset_between_turns_of_one_case`).

### 14.5 Canlı sistemdə təsdiq

`mt-probe-01` — 2 növbə, 2-ci növbədə sifariş nömrəsi **qəsdən təkrarlanmır**:

```
növbə 0  sent_conversation_id=''   "Hi, my order is ORD-10015."
         -> "What would you like to know about ORD-10015 …"
növbə 1  sent_conversation_id='814c56aa-…'  "When was it delivered, and is it
         still inside the return window?"
         -> lookup_order çağırıldı; "Here's what I have for ORD-10015:
            Delivered: 2026-08-12 … 20 days since delivery"
conversation_chained: True   (hər iki növbə eyni id-də)
input_tokens: 2 994 -> 12 114   (artım = yığılan söhbət tarixçəsi)
```

`pw-02-en-policy_lookup-standard-current-t3` (3 növbə) da eyni id ilə keçdi.
