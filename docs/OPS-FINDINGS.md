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
