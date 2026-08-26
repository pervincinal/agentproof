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
