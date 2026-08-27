# Əməliyyat tapıntıları (hədəf sistemin quraşdırılması zamanı)

Bunlar eval qaçışından deyil, sistemi qurarkən aşkarlandı. Hesabatın "operational reliability" bölməsinə aiddir.

## OPS-01 — İndeksləmə paralelliyi sabit kodlanıb, konfiqurasiya açarı yoxdur

**Sistem:** Dify 1.17.0
**Yer:** `api/core/indexing_runner.py:667` → `max_workers = 10`

Dify sənəd indeksləyərkən embedding sorğularını 10 paralel thread ilə göndərir. Bu dəyər sabit yazılıb — nə env dəyişəni, nə UI parametri var (`grep`-lə təsdiqləndi: `INDEXING_MAX_SEGMENTATION_TOKENS_LENGTH` və `TENANT_ISOLATED_TASK_CONCURRENCY` var, paralellik açarı yoxdur).

**Nəticə:** paralellik limiti 10-dan aşağı olan hər embedding provayderi ilə indeksləmə uğursuz olur. Jina pulsuz tier-i (2 paralel sorğu) ilə 8 sənədin hamısı `error` statusuna düşdü:

```
[models] Rate Limit Error, Concurrency limit exceeded: 2/2 concurrent requests.
```

**Niyə əhəmiyyətlidir:**
1. Xəta istifadəçiyə `indexing_status: error` kimi görünür; səbəbi yalnız worker loglarında oxunur. UI-da nə səbəb, nə də həll yolu göstərilir.
2. Avtomatik geri çəkilmə (backoff/retry) yoxdur — sorğu sadəcə sınır.
3. Provayder seçimi ilə indeksləmə arasındakı bu asılılıq heç bir yerdə sənədləşdirilməyib. İstifadəçi pulsuz tier ilə başlayıb səbəbini anlamadan ilişir.

**Təsir:** orta. Data itkisi yoxdur, amma quraşdırma mərhələsində susqun bloklayıcıdır və diaqnostikası konteyner loglarına giriş tələb edir.

## VALID-01 — Tələ dizaynı retrieval səviyyəsində təsdiqləndi

**Tarix:** 2026-08-27 · **Konfiqurasiya:** Gemini `gemini-embedding-001`, semantic_search, top_k=4, rerank yox

Korpus indeksləndikdən sonra iki tələ sorğusu ilə yoxlanıldı:

```
"What is the standard return window?"
  0.790  returns-and-refunds.md  [cari]          14
  0.752  returns-and-refunds.md  [BAYAT/App.A]   14, 30
  0.748  returns-and-refunds.md  [cari]          14
  0.740  international-shipping  [cari]          14, 30

"Aurora brand warranty period"
  0.798  warranty-policy.md      [cari]          18, 24, 30
  0.760  warranty-policy.md      [BAYAT/App.A]   18, 24
```

**Nəticə:** bayat bənd hər iki halda ilk 4-ə düşür və cari bənddən cəmi **0.038** bal geridədir. Yəni:

1. Agent kontekstdə həm cari, həm ləğv edilmiş qaydanı alır.
2. Embedding balında onları ayırd edən **heç bir siqnal yoxdur** — vektor oxşarlığının zaman ölçüsü yoxdur.
3. Bu, `docs/FAILURE-TAXONOMY.md` R6 rejimini və §"Boşluq 2"-ni (faithfulness kanonik həqiqətə qarşı deyil, retrieved kontekstə qarşı ölçülür) **canlı şəraitdə** təsdiqləyir: RAGAS bu halda `faithfulness = 1.0` verər, cavab isə yanlış olar.

**Metodoloji əhəmiyyəti:** tələ süni deyil, real retrieval davranışıdır. Hesabatda bu ölçmə tələ dizaynının etibarlılığını sübut edən dayaq kimi göstərilməlidir — "biz tələ qurduq və işlədi" yox, "tələ real sistemdə belə davranır".

## OPS-02 — Agent tətbiqində xüsusi (API) alətlər SSRF proxy tərəfindən bloklanır, quraşdırma anında isə heç bir siqnal yoxdur

**Sistem:** Dify 1.17.0 · **Tarix:** 2026-08-27
**Yer:** `api/core/helper/ssrf_proxy.py:258` → `ToolSSRFError`; `ssrf_proxy` konteynerində `/etc/squid/dify_common.conf.template:13-27` → `acl to_private_networks`

Dify xüsusi (custom / API) alət çağırışlarını `ssrf_proxy.py` vasitəsilə squid proxy-yə yönləndirir. Squid şablonu bütün RFC1918, loopback və link-local təyinatlarını rədd edir. Docker Desktop-da `host.docker.internal` → `192.168.65.254`, yəni `192.168.0.0/16` daxilindədir — nəticədə `http://host.docker.internal:8099` ünvanındakı mock servisə hər alət çağırışı `ToolSSRFError` ilə sınır.

**Tələ:** `docker-api-1` konteynerinin içindən sadə `curl` həmin URL-ə **HTTP 200** qaytarır, çünki curl proxy-dən keçmir. Yalnız real kod yolu sınır. Əlçatanlığı ən açıq üsulla yoxlayan komanda "yaşıl" görür, sonra işləməyən agenti debug etməyə başlayır.

**Ədalətli qeyd:** bu, quraşdırma mərhələsində bloklayıcıdır, amma Dify-ın xəta mətni gözləniləndən yaxşıdır — dəqiq env dəyişənini adlandırır, kopyalanabilən nümunə CIDR verir (`SSRF_PROXY_ALLOW_PRIVATE_IPS=172.21.0.0/16`) və əlaqəli issue-ya link qoyur. Problem sənədləşmənin keyfiyyəti deyil, vaxtıdır: bu mesaj yalnız birinci uğursuz alət çağırışından **sonra** görünür.

**Tətbiq edilən həll:** `~/agentproof-stack/dify/docker/.env`-ə `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal` (entrypoint həm `_IPS`, həm `_DOMAINS` açarını dəstəkləyir), sonra `docker compose up -d ssrf_proxy` — **restart yox, recreate**, çünki `/etc/squid/dify_allow_private.conf` faylını entrypoint yenidən generasiya edir. Təsdiq: `ssrf_proxy.post(...)` 200 qaytarır. Əvvəlki env-in ehtiyat nüsxəsi: `docker/.env.pre-ssrf-fix`.

Həllin işləməsi `include` sırasından asılıdır: `squid.conf.template`-də `dify_allow_private.conf` **12-ci sətirdə**, `http_access deny to_private_networks` isə **13-cü sətirdə**dir.

**Təsir:** orta. Data itkisi yoxdur; diaqnostikanın çətinliyi xəta mesajından yox, yoxlama metodunun yanıltıcılığından gəlir.

## OPS-03 — Agent tətbiqində tətbiq səviyyəsindəki `top_k` səssizcə iqnor edilir; faktiki default 2-dir

**Sistem:** Dify 1.17.0 · **Tarix:** 2026-08-27

Üç yer bir-birini üst-üstə yazır:

1. `api/core/tools/utils/dataset_retriever_tool.py:53-55` — `get_dataset_tools()` `retrieve_strategy`-ni `SINGLE`-a məcbur edir, şərh: *"Agent only support SINGLE mode"*. Tətbiqin `dataset_configs.retrieval_model` dəyəri nə olursa olsun.
2. `api/core/rag/retrieval/dataset_retrieval.py:1312-1331` — `to_dataset_retriever_tool()` `SINGLE` yolunda `top_k` / `search_method` / rerank dəyərlərini **datasetin öz** `retrieval_model` sütunundan götürür, tətbiq konfiqurasiyasından yox.
3. Həmin funksiyanın lokal defaultu (`:1319`) `top_k: 2`-dir; modul səviyyəsindəki `default_retrieval_model` (`:104`) isə `top_k: 4`. Lokal dəyər modul dəyərini kölgələyir.

**Nəticə:** Service API ilə açıq `retrieval_model` verilmədən yaradılan datasetin `datasets.retrieval_model` sütunu `NULL` qalır. Bu halda agent tətbiqi **2 bənd** çəkir, halbuki onun öz UI/DSL-i `4` göstərir. Heç bir xəbərdarlıq yoxdur.

**Niyə əhəmiyyətlidir:** bu, birbaşa VALID-01 ilə müqayisə edilə bilənliyi pozur — VALID-01 `top_k=4` ilə ölçülüb. Eyni korpus, eyni sorğu, amma agent yolunda iki dəfə az kontekst.

**Tətbiq edilən azaldıcı tədbir:** datasetin `retrieval_model`-i `PATCH /v1/datasets/{id}` ilə DSL-ə uyğun sabitləndi — `semantic_search`, `top_k: 4`, rerank yox, threshold yox; postgres-də təsdiqləndi. Bax: `target/app/IMPORT.md §1`.

**Təsir:** ölçmə etibarlılığı üçün yüksək, istismar üçün orta.

## OPS-04 (kiçik) — `PATCH`/`GET /v1/datasets/{id}` yazılan `retrieval_model`-i geri qaytarmır

**Sistem:** Dify 1.17.0 · **Tarix:** 2026-08-27

Yazma əməliyyatı işləyir və qalıcıdır (`api/controllers/service_api/dataset/dataset.py:675` → `update_data["retrieval_model"]`; postgres-də təsdiqləndi). Amma cavab modelində (`api/fields/dataset_fields.py`, `DatasetDetailResponse`) `retrieval_model` sahəsi deklarasiya olunmayıb — yalnız `retrieval_model_dict` var. Ona görə həm `PATCH` cavabı, həm də ardınca gələn `GET` `retrieval_model: null` qaytarır.

**Nəticə:** yazını API cavabı ilə yoxlayan çağırıcı əməliyyatın uğursuz olduğu qənaətinə gəlir. Yeganə etibarlı yoxlama nöqtəsi baza və ya UI-dır.

**Təsir:** aşağı. Funksional pozuntu yoxdur, amma skriptlə qurulan setup-ı məhz bu cür detallar "qeyri-sabit" göstərir.

## OPS-04 — Xərc hesabatı yanlışdır (keçid dövrü qiyməti)

**Sistem:** Dify 1.17.0 + `langgenius/anthropic` 0.3.28

Plugin `claude-sonnet-5` üçün `$3.00 / $15.00` sabit yazıb. Öz şərhi səbəbi izah edir:

```yaml
# *Introductory pricing of $2/$10 per million input/output tokens
#  through August 31, 2026; $3/$15 standard pricing thereafter.
pricing: {input: '3.00', output: '15.00'}
```

**2026-08-27 tarixinə qüvvədə olan rəsmi qiymət $2/$10-dur** (təsdiqlənib). Yəni Dify bu gün xərci **~50% şişirdilmiş** göstərir; 2026-09-01-dən etibarən onun rəqəmi düzgün olacaq.

**Ölçmə:** pilotda Dify $0.43 hesabladı; faktiki $0.25-ə yaxındır.

**Nəticə hesabat üçün:**
1. Xərc rəqəmlərimiz `pricing/models.yaml`-dan hesablanır (düzgün), Dify-ın `total_price` sahəsindən YOX.
2. Metodologiya bölməsində qaçışın tarixi və tətbiq olunan qiymət rejimi (`$2/$10 introductory` vs `$3/$15 standard`) AÇIQ yazılmalıdır — əks halda xərc rəqəmləri təkrarlana bilməz.
3. Proqnoz: 450 sorğu → **~$8.8** (31 avqusta qədər) / **~$13.2** (sonra).

**Ümumi dərs:** platformanın `total_price` sahəsinə güvənmək olmaz — qiymət cədvəlləri plugin içində sabit yazılır və model qiymətləri dəyişəndə gecikir. Bu, müştəri auditlərində də keçərlidir: xərc iddiası platformanın öz hesabından deyil, müstəqil cədvəldən gəlməlidir.

## VALID-02 — Bayat bənd tələsi EMBEDDER-DƏN ASILIDIR (ölçülmüş)

**Tarix:** 2026-08-27 · Eyni korpus, eyni sorğu, eyni `semantic_search`, rerank yox.

Sorğu: `"What is the standard return window?"` — bayat bəndin (Appendix A, ləğv edilmiş 30 günlük pəncərə) retrieval sıralamasındakı yeri:

| Embedder | Rank | Score |
|---|---:|---:|
| `gemini-embedding-001` | **2** | 0.752 |
| `bge-m3` (lokal, Ollama) | **8** | 0.533 |

**Nəticə.** `top_k=4` ilə Gemini tələni modelə çatdırır, `bge-m3` çatdırmır. Yəni sistemin bu testdən "keçməsi" agentin bacarığı haqqında deyil, **embedder seçimi** haqqında məlumat verir.

**Metodoloji qərar.** Əsas qaçış `top_k=8` ilə aparılır. Səbəb: tədqiqat sualı *"retrieval bayat bəndi üzə çıxarırmı?"* deyil (bu, embedder lotereyasıdır) — sual budur: **"hər iki bənd kontekstdə olanda agent onları ayırd edirmi?"** Testin şərti təmin olunmasa, 31 R6 case-i (datasetin 21%-i) səssizcə boş keçər və biz "agent bayat bəndləri yaxşı idarə edir" nəticəsi çıxararıq — halbuki heç nə sınanmayıb.

**Müstəqil tapıntı.** Dify-ın default `top_k` dəyəri **2**-dir. Bu dəyərdə bayat bənd tələsi əksər sorğularda modelə ümumiyyətlə çatmır. Yəni default konfiqurasiya ilə işləyən komanda bu uğursuzluq rejimini **heç vaxt müşahidə etməyəcək** — nə istehsalatda, nə də öz testlərində. Səhv cavab yalnız retrieval sıralaması dəyişəndə (yeni sənəd, yeni embedder versiyası, fərqli ifadəli sual) üzə çıxacaq.

**Hesabat üçün:** oxucuya deyiləsi cümlə — *"sizin sisteminizin bu testi keçməsi embedder-iniz haqqında agentinizdən çox şey deyir; embedder-i dəyişdiyiniz gün bu rejim özü üzə çıxa bilər."*
