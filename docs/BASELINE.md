# Baseline — reqressiya qapısının istinad nöqtəsi (AP-013)

> "87%" faydasız; **"91% → 87%, bu 4 case sındı"** faydalıdır (STACK.md M4).
> Bu sənəd cari baseline snapshot-unun **necə götürüldüyünü** yazır. Baseline
> təkrar istehsal oluna bilmirsə, audit sənədi deyil.

---

## 1. Cari snapshot

| | |
|---|---|
| **Fayl** | `evals/baselines/dify_http@e60c825c84bbda8a-2026-08-28.json` |
| **Hədəf** | `dify_http` · model etiketi `claude-sonnet-5` (`model_check: match`) |
| **Retrieval** | `bge-m3` (ollama) · `top_k=8` · reranking yoxdur · `retrieval_check: live` |
| **`dataset_hash`** | `e60c825c84bbda8a` |
| **Ölçmə tarixi** | 2026-08-27 → 2026-08-28 |
| **Case** | **162** (hər biri üçün verdikt var, `skipped` yoxdur) |
| **Keçdi / sındı** | 124 / 38 → keçmə dərəcəsi **76.5%** |
| **`baseline` teqli 39 case** | 36 keçdi / 3 sındı (92.3%) |
| **Təkrar** | `--repeat 3` (RunRecord-da verdikt tək, cəhdlər `.eval` logundadır) |
| **Xərc** | $11.71 (`cost_coverage: partial` — 45 cəhdin xərci ölçülməyib) |

Əvəz olunan 25 nəticə `skipped` idi (hədəfə sorğu getmədi), ona görə onların
xərci sıfırdır: `spent_including_superseded_usd` da $11.71-dir. Əvəzləmə
ölçülmüş nəticəni əvəz etsəydi, iki rəqəm fərqlənərdi.

`baseline` teqli dəstin vəziyyəti artefaktda ayrıca saxlanılır
(`totals["baseline_tagged"]`): ümumi keçmə dərəcəsi sabit qalıb məhz həmin
dəstdə case sınsa, ümumi rəqəmdə itərdi. Hazırda sınan üç case:

```
bva-b-13-warranty_aurora_brand_mo-24
bva-b-21-lockout_failed_attempts-4
bva-b-21-lockout_failed_attempts-5
```

---

## 2. Hansı qaçışlardan və NİYƏ İKİ QAÇIŞDAN

| qaçış | run_id | başlama | dataset_hash | nəticə |
|---|---|---|---|---|
| `reports/full-run-03` | `3eeCxPbaqUBrdcxcSaxXUL` | 2026-08-27T20:57:16Z | `e60c825c84bbda8a` | 162 case · 25-i **`skipped`** |
| `reports/full-run-03b` | `o6zhCse2Dm4UV4r3njg4JB` | 2026-08-28T09:33:31Z | `916f1c90bd3c3249` | həmin **25 case** · hamısı ölçüldü |

**Səbəb: kredit kəsilməsi.** `full-run-03` ortasında Anthropic kreditləri
tükəndi (`credit_exhausted`) və 25 case hədəfə ümumiyyətlə göndərilmədi.
Kredit bərpa olunandan sonra həmin 25 case `--filter id=…` ilə yenidən qaçdı
(`full-run-03b`). Yəni **tam qaçış artefaktı tək faylda yoxdur** — o, iki
qaçışın birləşməsidir.

Birləşmə **əl ilə edilmir**. Qayda koddadır (`agentproof/report/merge.py`),
əmr aşağıdadır, provenans isə artefaktın öz içindədir
(`totals["merge"]`): hansı mənbələr, nə əvəz olundu, hansı xəbərdarlıq var.

### Grader versiyası

Snapshot **A-08-dən SONRAKI** qaçışdan götürülüb (`docs/GRADER-AUDIT.md`
"A-08 — bağlanma qeydi"): çılpaq rəqəm iynələri artıq tarixin, onluq kəsrin və
sifariş nömrəsinin içindən tutulmur. A-08-dən əvvəlki qaçışlar (`full-run-02`
və öncəsi) baseline üçün YARARSIZDIR — onlardakı yaşıl case-lərin bir hissəsi
yalançı yaşıldır və reqressiya ölçüsünü sürüşdürərdi.

---

## 3. Təkrar istehsal (bir əmr)

```bash
python evals/merge_runs.py reports/full-run-03 reports/full-run-03b \
    --merge-across-datasets \
    --out evals/baselines/dify_http@e60c825c84bbda8a-2026-08-28.json
```

Alət:

1. hər case üçün **ən son** qaçışın nəticəsini götürür (meyar `started_at`,
   fayl adı yox — AP-042);
2. əvəz olunan 25 nəticəni **silmir**: `totals["merge"]["superseded"]`-də
   saxlayır və sayır;
3. rəqəmləri (keçmə dərəcəsi, xərc, gecikmə) **yalnız qalib nəticələrə** görə
   yenidən hesablayır; faktiki ödənilən məbləğ
   `totals["merge"]["spent_including_superseded_usd"]`-də qalır;
4. birləşmədən sonra **ölçülməmiş case qalarsa yazmır** (`--allow-skipped`
   olmadan) — baseline "bu case ölçülmədi" saxlaya bilməz.

### `--merge-across-datasets` niyə lazımdır

`runner/task.py`-də `dataset_hash(cases)` **filtrdən SONRAKI** case dəstinə
görə hesablanır, yəni dataset-in versiyasını yox, **seçilmiş alt dəsti**
imzalayır. Ona görə `--filter` ilə qaçırılan `full-run-03b`-nin hash-i
(`916f1c90…`) ana qaçışdan (`e60c825c…`) həmişə fərqlidir və ciddi qayda
birləşməni bloklayır.

Bayraq sərhədi keçir, **amma kor-koranə yox**: birləşmə yalnız case
**tərifinin barmaq izi** (case dict-in sha256-sı, `.eval` logundan oxunur) hər
iki qaçışda eyni olduqda baş verir. Üst-üstə düşən 25 case üçün barmaq izləri
bayt-bayt eynidir; artefaktda
`totals["merge"]["case_fingerprints_verified"] = true` yazılıb. Barmaq izi
fərqli olan case **heç vaxt** birləşdirilmir.

Birləşmiş qeydin `dataset_hash`-i **case dəstini tam əhatə edən** mənbədən
götürülür (burada `full-run-03` → `e60c825c84bbda8a`), "ən son qaçış"dan yox:
25-lik qaçış dəstin yalnız altıda birini imzalayır.

---

## 4. Ad sxemi

```
evals/baselines/<target>@<dataset_hash>-<YYYY-MM-DD>.json
```

* `<target>` — adapter adı (`dify_http`). Fərqli hədəflərin baseline-ları
  qarışmır.
* `<dataset_hash>` — snapshot-un əhatə etdiyi case dəstinin imzası. Dataset
  dəyişəndə hash dəyişir, yəni köhnə baseline yeni dataset-in adı altında
  görünmür.
* `<YYYY-MM-DD>` — ölçmənin **bitdiyi** gün (ən son mənbə qaçışın tarixi).

Qovluqda bir neçə snapshot ola bilər. `evals/ci_gates.py baseline` **ən
sonuncunu** seçir; meyar `started_at`, **fayl adı deyil** — ad sxemi
dəyişəndə leksikoqrafik sıralama səssizcə yanlış faylı seçərdi.

> **Ölçü qeydi.** Snapshot tam RunRecord-dur (cavab mətnləri, tool çağırışları,
> retrieval çıxışı daxil) — ~2.6 MB. Debug dəyəri buradadır: `reports/`
> qovluğu `.gitignore`-dadır, yəni repoda saxlanan yeganə tam artefakt budur.
> Snapshot sayı artanda köhnələri silmək lazım gələcək.

---

## 5. CI-da nə dəyişdi

```yaml
# hər PR-da (açarsız job)
- run: python evals/ci_gates.py baseline evals/baselines --require
```

`--require` AP-013-dən sonra açıldı: snapshot təsadüfən silinsə CI **qırmızı**
olur. Əvvəllər qapı yalnız xəbərdarlıq yazırdı, çünki snapshot yox idi və
yoxluğun özü susmamalı idi.

Canlı job-da (`workflow_dispatch`) baseline yolu eyni qapıdan gəlir və qaçışa
`--baseline <yol> --fail-on-regression` kimi ötürülür. Qapı siyasəti
(`report/baseline.py::GatePolicy`): keçmə dərəcəsinin **2 punktdan** çox
düşməsi və ya **high severity** case-in sınması bloklayır; flaky case
reqressiya sayılmır, amma ayrıca göstərilir.

---

## 6. Bu baseline-ın ÖLÇMƏDİYİ şeylər

1. **Dataset-in 3 case-i snapshot-da yoxdur.** `evals/datasets/full.jsonl`
   hazırda **165** case-dir; `full-run-03` qaçanda 162 idi. Sonradan əlavə
   olunan üç case heç bir qaçışda ölçülməyib:

   ```
   r6j-collision-14-days-price-match
   r6j-collision-30-days-plus-member
   r6j-collision-30kg-domestic-vs-intl
   ```

   Bunlar gələcək müqayisədə `RunDelta.new_cases` kimi görünəcək və sınsalar
   `still_failing`-ə düşəcək — yəni **reqressiya kimi bloklamayacaqlar**.
   Növbəti tam qaçışda baseline yenilənməlidir.

2. **Flaky nisbəti 19.8%** (`--repeat 3`, 32/162 case). Bu, `FLAKY_ALARM`
   həddindən (10%) yuxarıdır: ölçmənin özü qeyri-sabitdir. Baseline hər case
   üçün TƏK verdikt saxlayır (`normalize_log()` cəhdləri birləşdirir), ona görə
   qeyri-sabit case-lər baseline-da "keçdi" və ya "sındı" kimi donub qalır və
   növbəti qaçışda səbəbsiz `fixed`/`broken` verə bilər. `compare()` bunu
   qismən yumşaldır (cari qaçışda flaky olan case reqressiya sayılmır), amma
   həll deyil.

3. **Xərcin bir hissəsi ölçülməyib**: 45 cəhd `usage` qaytarmadı
   (`cost_coverage.status = partial`) — həmin cəhdlərin xərci **naməlumdur,
   sıfır deyil**.

4. **`judge` mərhələsi daxil deyil**: qaçış `--stage cheap` ilə edilib, yəni
   snapshot yalnız determinist grader-lərin verdiktlərini saxlayır.
