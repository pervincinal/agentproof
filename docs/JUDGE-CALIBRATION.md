# JUDGE-CALIBRATION.md — LLM-as-judge qatı və onun kalibrasiyası

**Status:** Qurulub · **Tarix:** 2026-08-27 · **Rol:** grader-eng
**Aidiyyat:** `agentproof/graders/judge.py`, `agentproof/graders/calibration.py`,
`evals/calibration/`, `docs/FAILURE-TAXONOMY.md` §10 Boşluq 7, `target/corpus/TRAPS.md` §5

---

## 1. Judge nə vaxt işlədilir (və nə vaxt YOX)

**Qayda: determinist grader ilə ölçülə bilən heç nə judge-a getmir.**

Judge bahalıdır, qeyri-deterministdir və kalibrasiya tələb edir. `contains_all`
ilə həll olunan işi judge-a vermək məhsulun keyfiyyətini aşağı salır, yuxarı yox.
Bizim 11 determinist grader-imiz datasetin böyük hissəsini örtür; judge yalnız
determinist ölçünün **prinsipcə** işləmədiyi yerdə açılır.

Hazırda bir belə hal var: `grading: requires_justification` (TRAPS.md §5).

**Problem.** Korpusda "30 gün" həm doğru, həm səhv cavabdır:

| Mənbə | Dəyər | Status |
|---|---|---|
| `return_window_standard` (Appendix A.1, tələ T-01) | 30 gün | **BAYAT** — 2026-01-01-dən qüvvədən düşüb |
| `return_window_plus_member` | 30 gün | **AKTİV** — domestik Plus üzvü, promosyon olmayan mal |
| `plus_trial_days` · `erasure_completion_days` · `intl_rma_arrival_days` … | 30 gün | aktiv, amma **başqa parametr** |

Rəqəm eynidir. `contains_all: ["30"]` hər üçünü keçirir — yəni bayat bənddən
gələn cavabı da yaşıl boyayır. Fərqi **yalnız əsaslandırma** göstərir, ona görə
bu case-lər judge-a düşür. Judge cavabın **hansı yolla gəldiyini** qiymətləndirir,
rəqəmi yox.

---

## 2. Rubrika (`requires_justification` / v1)

Rubrika `agentproof/graders/judge.py` içində `REQUIRES_JUSTIFICATION_V1`
sabitindədir və **versiyalanır**. Mətn dəyişirsə versiya qalxır; köhnə
kalibrasiya rəqəmi yeni rubrikanı müdafiə etmir.

Verdikt dəsti üç sinifdir və `passed` **yalnız** `justified` üçün doğrudur:

| Verdikt | Mənası | Auditdəki hekayəsi |
|---|---|---|
| `justified` | Cavab idarəedici qaydanı göstərir və rəqəmi ondan çıxarır | keçdi |
| `unjustified` | Rəqəm düzdür, idarəedici şərt göstərilmir | "təsadüfən düz ola bilər" |
| `wrong` | Tələ qaydasına / bayat bəndə əsaslanır, ya rəqəm səhvdir | **nümayiş oluna bilən qüsur** |

`unjustified` və `wrong` qəsdən ayrı saxlanılır: hesabatda ikisi fərqli iddiadır.

Çıxış **struktur**dur — `{verdict, reason, confidence}` — və `output_config.format`
JSON schema ilə məcbur edilir. Sxemə uyğun gəlməyən cavab `skipped` olur, heç
vaxt səssiz `passed` yox.

---

## 3. Determinizm — dürüst versiya

Messages API-də **`seed` parametri yoxdur**. Uydurmuruq. Determinizm üç yolla
təmin olunur və hər üçü `GradeResult.evidence`-də açıq yazılır:

1. **`temperature = 0`** — yalnız onu qəbul edən modellərdə. Opus 5 / Sonnet 5 /
   Fable 5 / Opus 4.7–4.8 sampling parametrlərini API səviyyəsində rədd edir
   (HTTP 400), ona görə həmin modellərdə sahə **göndərilmir** və
   `temperature_applied = False` qeyd olunur. Sükut yerinə yazırıq: kalibrasiya
   rəqəmi bu fərqi gizlətməməlidir. `JudgeConfig.validate()` sıfırdan fərqli
   temperature-i ümumiyyətlə qəbul etmir.
2. **Sabit prompt baytları** — rubrika versiyalanır, şablon dəyişməzdir.
3. **`JudgeCache`** — `sha256(model + system + user)` barmaq izi ilə cavab keşi.
   Eyni giriş + eyni rubrika versiyası → bayt-bayt eyni verdikt. "Seed idarəsi"nin
   real qarşılığı budur; keş faylları hesabat artefaktına daxil edilir ki, audit
   kənardan yenidən yoxlana bilsin.

**Judge modeli SUT-dan güclü olmalıdır.** `JudgeConfig(sut_model=...)` verilibsə,
model tier müqayisə olunur və zəif judge konfiqurasiyası `ValueError` ilə
dayandırılır. Default judge modeli `claude-opus-5`.

---

## 4. Kalibrasiya

### 4.1 Dəst

`evals/calibration/labeled.yaml` — **30 əl ilə etiketlənmiş nümunə**
(minimum tələb 25). Sinif balansı: `justified` 11 · `unjustified` 9 · `wrong` 10.

Nümunələr korpusdan törəyib: beş ssenari (`S-PLUS`, `S-STD`, `S-PROMO`,
`S-INTL`, `S-WARR`) `CANONICAL.yaml` və `TRAPS.md` tələlərinə (T-01, T-07, T-23,
C-03, C-04) birbaşa bağlıdır. Hər nümunənin **`note`** sahəsi niyə belə
etiketləndiyini izah edir — izahsız etiket auditdə müdafiə olunmur və
`load_labels()` onu qəbul etmir.

### 4.2 Ölçülər

- **Uyğunluq faizi** (`agreement`) — insan etiketi ilə üst-üstə düşmə.
- **Cohen's kappa** — `(po − pe) / (1 − pe)`. Xam faiz təsadüfi uyğunluğu
  gizlədir: üç sinifli dəstdə həmişə eyni verdikti verən "null model" 30%
  alır, balans pozulubsa 60%-ə də qalxa bilər — kappa-sı isə ~0 olur.
- **Confusion matrix + sinif üzrə recall** — ümumi faiz hansı sinifdə zəif
  olduğunu gizlədir.
- **Yanlılıq probu** — aşağıda.

**Qapı:** uyğunluq ≥ **85%** VƏ kappa ≥ **0.70**.

### 4.3 POZULMAZ QAYDA

> **Uyğunluq 85%-dən aşağıdırsa RUBRİKA düzəldilir, DATASET DEYİL.**

Etiketi judge-a uyğunlaşdırmaq kalibrasiyanı özünü təsdiqləyən mərasimə çevirir:
sonda 100% uyğunluq alırsan və heç nə ölçmüş olmursan. Etiket yalnız o halda
dəyişir ki, etiketin özündə səhv **sübut olunsun** (`CANONICAL.yaml` ilə
ziddiyyət) — və dəyişikliyin səbəbi `labeled.yaml`-ın `note` sahəsində yazılır.

Bu qayda üç yerdə saxlanılır ki, unudulmasın:
1. `agentproof/graders/calibration.py` modul sənədi + `CALIBRATION_RULE` sabiti;
2. bloklama mesajının **mətnində** (`"RUBRİKA düzəlməlidir (dataset yox)"`);
3. `labeled.yaml` faylının başlığında.

Dəstin **sha256**-sı hər hesabata yazılır — səssiz redaktə hesabatda görünür.

### 4.4 Yanlılıq yoxlaması

Dəstdə eyni məzmun qəsdən fərqli üslublarda təkrarlanır: `neutral`, `terse`,
`verbose`, `confident`, `hedged`, `formatted`. Məzmun və doğru qərar eynidir,
yəni **verdikt dəyişməməlidir**. Dəyişirsə, bu judge-un verbosity / əminlik /
format yanlılığıdır (FAILURE-TAXONOMY §10 Boşluq 7). Hesabat qrup üzrə
`style_flip_rate` və üslub üzrə sapma nisbətini göstərir.

Rubrika özü də bu yanlılığı açıq qadağan edir (qayda 1) və bunun mətndə
qalması test ilə qorunur (`test_rubric_forbids_style_criteria_explicitly`).

**Ölçülmədi (dürüstlük üçün):**
- **Mövqe (position) yanlılığı** — bizim rubrika cüt müqayisə etmir, tək cavab
  qiymətləndirir, ona görə swap testi tətbiq olunmur.
- **Dil yanlılığı** — AZ/RU üçün ayrıca etiketli dəst tələb edir; L1 ölçüsü
  açılanda əlavə olunmalıdır.

---

## 5. İstifadə

```bash
# şəbəkəsiz: boru xəttini yoxlayır, "null model" bazasını göstərir
python evals/calibration/run_calibration.py --dry-run

# real qaçış (ANTHROPIC_API_KEY və ya `ant auth login` profili)
python evals/calibration/run_calibration.py \
    --model claude-opus-5 --sut-model claude-sonnet-5 \
    --cache-dir reports/judge-cache --fail-under-threshold
```

`--dry-run` sabit verdiktli **null model**-lə qaçır: nəticə həmişə bloklanır
(`dry_run: true`) və eyni zamanda kappa-nın niyə lazım olduğunu nümayiş etdirir —
uyğunluq 30%, κ = 0.00.

Çıxış: `evals/calibration/report.json`.

---

## 6. Hesabata avtomatik düşmə

Uyğunluq faizi və kappa **gizlədilə bilməz**:

- `report/normalize.py` hər `RunRecord`-un `totals["judge"]` sahəsini
  `calibration.judge_status()` ilə doldurur — ayrıca addım yoxdur;
- `report/pr_comment.py` qaçışda judge grader-i varsa **məcburi** «Judge
  kalibrasiyası» bölməsi çıxarır (PR şərhi və konsol xülasəsi);
- kalibrasiya faylı yoxdursa, bölmə susmur — böyük hərflərlə
  «JUDGE KALİBRASİYA EDİLMƏYİB» xəbərdarlığı yazılır.

Səbəb sadədir: **kalibrasiya edilməmiş judge nəticəsi elmi zibildir** və pullu
auditdə müdafiə olunmur. Rəqəmi hesabatdan çıxarmaq mümkün olmamalıdır.

---

## 7. Memarlıq qeydi

`agentproof/graders/` paketi **`inspect_ai` import etmir** (STACK.md §6) — judge
və kalibrasiya modulları da daxil. Şəbəkəyə çıxış `JudgeClient` protokolu ilə
**kənardan** verilir (`RubricJudge.bind(client)`), `anthropic` SDK isə yalnız
`AnthropicJudgeClient` içində və yalnız ilk çağırışda import olunur.

Nəticə: bütün test dəsti (60 judge/kalibrasiya testi daxil) **real API açarı
olmadan, şəbəkəsiz** qaçır və `graders/` paketi SDK quraşdırılmadan da qalxır.

`kind = "judge"` olduğuna görə bu grader `--stage judge` mərhələsinə düşür və
hər PR-da qaçmır (STACK.md §8.6, 6 dəqiqə qaydası).
