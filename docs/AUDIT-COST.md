# AUDIT-COST.md — auditin maya dəyəri və müddət modeli

**Tarix:** 2026-09-01 · **Rol:** writer · **Tapşırıq:** AP-040
**Mənbə:** `reports/` (22 qaçış qovluğu) · `agentproof/report/cost.py` ·
`agentproof/pricing/models.yaml` · `docs/LIMITATIONS.md` LIM-E08 / LIM-E11 ·
`board/tasks.json` · `PLAN.md` · `target/corpus/verify_fixtures.py`

---

## 0. Bu sənəd nə edir və nə etmir

**Edir:** Aurora Goods auditinin **geriyə dönük** hesabını çıxarır — artefaktda
yazılmış model xərci, qaçış müddətləri, əl işinin ölçülə bilən həcmi, və bunların
150 → 300 case, `--repeat 3` → `1`, qiymət rejimi dəyişikliyi üzrə miqyaslanması.

**Etmir:** qiymət təyin etmir. Auditin **əmək saatı ölçülməyib** (§5) — repo-da
timesheet yoxdur, board isə yalnız işin son üçdə birini əhatə edir. Ona görə bu
sənəd bir rəqəmlik "audit $X-ə başa gəlir" cavabı VERMİR; onun yerinə döşəmə
düsturu və həssaslıq cədvəli verir (§10).

### İşarələmə qaydası (bütün sənəd boyu)

| İşarə | Mənası |
|---|---|
| **[Ö]** | **Ölçülmüş** — rəqəm birbaşa artefaktdan oxunub, yolu göstərilib |
| **[H]** | **Hesablanmış** — ölçülmüş rəqəmlərdən arifmetika ilə çıxarılıb, fərziyyə açıq yazılıb |
| **[N]** | **NAMƏLUM** — ölçülməyib. Sıfır deyil, "təxminən" deyil, **naməlum** |

Heç bir **[H]** və **[N]** sətri **[Ö]** kimi göstərilmir. LIM-E11-in qaydası budur:
*«audit sizə nə qədər başa gəlir?» sualına «təxminən» cavabı qəbuledilməzdir;
«$X ölçüldü, N cəhdin xərci ölçülmədi» isə dürüst cavabdır.*

---

## 1. Ölçülən model xərci — mərhələ üzrə

Bütün rəqəmlər `reports/*/<run_id>.json` → `totals.cost_usd`.
Qiymət cədvəli: `pricing/models.yaml`, `as_of: 2026-08-27`, SUT = `claude-sonnet-5`
@ **$2 / $10** (introductory rejim, 2026-08-31 daxil olmaqla).

| Mərhələ | Qaçış | Case | Təkrar | Xərc (USD) | Divar saatı | Status |
|---|---|---:|---:|---:|---:|---|
| **Pilot** | `pilot` | 10 | 1 | **0.1967** | 1m 13s | ✅ |
| **Harness qurulması** | `smoke-full` | 6 | 1 | 0.0000 | 0m 03s | hamısı `skipped` |
| | `smoke-full2` | 6 | 1 | 0.1357 | 1m 37s | ✅ |
| | `smoke-bge` | 6 | 1 | 0.1596 | 1m 12s | ✅ |
| | `anchor-fix` | 2 | 1 | 0.1135 | 0m 30s | ✅ |
| | `full-run-03-retry` | 25 | 3 | 0.0000 | 0m 35s | hamısı `skipped` |
| | `full-run-03-retry2` | 1 | 3 | 0.0390 | 0m 24s | ✅ `complete` |
| | `gate-check-mock` / `gate-green` / `gate-red` | 5+5+5 | 1 | 0.0000 | ~0s | mock hədəf |
| | `gate-live` | 4 | 1 | 0.0792 | 0m 34s | ✅ `complete` |
| | **Alt-cəm** | | | **0.5270** | ~4m 55s | |
| **Tam qaçış** | `full-run-01` | 147 | 3 | **[N] NAMƏLUM** | 1h 05m 00s | `cancelled`, **RunRecord yoxdur** |
| | `full-run-02` | 147 | 3 | **11.3364** | 1h 10m 55s | ✅ |
| | `full-run-03` | 162 | 3 | **9.3215** | 0h 46m 22s | 25 case `skipped` (rate limit) |
| | `full-run-03b` | 25 | 3 | **2.3921** | 0h 14m 18s | ⚠️ `partial` — 45 cəhd ölçülmədi |
| | **Alt-cəm (ölçülən)** | | | **23.0499** | 2h 11m 35s | + `full-run-01` naməlum |
| **Triage / yenidən yoxlama** | `ap021-recheck` | 22 | 3 | 0.0903 | 0h 24m 12s | 21 `skipped` |
| | `ap021-recheck2` | 22 | 3 | 1.9091 | 0h 11m 15s | ✅ |
| | `ap021-recheck3` | 5 | 3 | 0.1539 | 0h 04m 55s | 4 `skipped` |
| | `ap006-consistency-verdict` | 1 | 3 | 0.0620 | 0m 20s | ✅ |
| | `ap006-consistency-verdict-2` | 1 | 3 | 0.0630 | 0m 18s | ✅ |
| | **Alt-cəm** | | | **2.2784** | 0h 41m 00s | |
| **Judge + kalibrasiya** | `judge-01` (SUT hissəsi) | 3 | 3 | 0.1760 | 1m 26s | ✅ |
| | `judge-01` judge çağırışları (`claude-opus-5`) | 3 | — | **0.0387** | — | keşdən hesablandı |
| | Kalibrasiya, 30 etiket (`claude-opus-5`) | 30 | — | **0.3342** | — | keşdən hesablandı |
| | **Alt-cəm** | | | **0.5489** | | |
| **Digər** | `audit-live` | [N] | — | **[N] NAMƏLUM** | [N] | log `started`, **RunRecord yoxdur** |

### Yekun ölçülən model xərci

| | USD | İşarə |
|---|---:|---|
| SUT (`claude-sonnet-5`) — bütün `RunRecord.totals.cost_usd` cəmi | **26.2280** | **[Ö]** |
| Judge (`claude-opus-5`) — `reports/judge-cache/` + `reports/judge-01/judge-cache/` | **0.3729** | **[Ö]** |
| **CƏMİ ÖLÇÜLƏN** | **26.6009** | **[Ö]** |
| **Ölçülməyən** | **[N] NAMƏLUM** | §2 |

> **Judge xərci `totals.cost_usd`-a DAXİL DEYİL.** `report/normalize.py` xərci yalnız
> `AgentResponse` obyektlərindən yığır — grader qatının model çağırışları oraya
> düşmür. Yuxarıdakı $0.3729 keş fayllarının `meta.input_tokens` /
> `meta.output_tokens` sahələrindən ayrıca hesablanıb (49,374 giriş + 3,493 çıxış
> token kalibrasiya, 5,001 + 549 `judge-01` üçün; `claude-opus-5` @ $5/$25).
> Bu, LIM-E11-də sadalanmayan **ikinci** uçot boşluğudur və burada ilk dəfə yazılır.

---

## 2. Ölçülməyən hissə — LIM-E11 və onun genişlənməsi

Üç ayrı kor nöqtə var. Heç biri sıfır deyil; hamısı **naməlumdur** və hamısı
xərci **AŞAĞI** göstərir.

### 2.1 `usage` qaytarmayan uğursuz cəhdlər — **[N]**

`full-run-03b`-nin `cost_coverage` bloku (ölçülmüş, artefaktdan):

```
attempts            120
measured_attempts    75      → xərci ölçüldü ($2.3921)
unmeasured_attempts  45      → xərci NAMƏLUM
status              "partial"
direction           "understates"
```

Yəni bu qaçışın **cəhdlərinin 37.5%-i** üçün token sayı ümumiyyətlə gəlmədi.
Səbəb LIM-E11-də yazılıb: Dify `message_end`-i yalnız uğurlu axında göndərir;
xəta axını `error` event-i ilə bitir və token sayı orada yoxdur. Sorğu modelə
çatıb — giriş tokenləri ödənilib — amma neçəsi olduğu bilinmir.

`cost_coverage` sahəsi yalnız AP-026-dan sonrakı 6 qaçışda var. Ondan əvvəlki
**14 qaçışda** eyni boşluq mövcud idi, sadəcə **görünmürdü** — orada
`unmeasured_attempts` `—` yazılıb, çünki sahə hələ yox idi. Bu, §1 cədvəlindəki
$26.23-ün nə qədər aşağı olduğunu daha da bilinməz edir.

### 2.2 RunRecord yaratmayan qaçışlar — **[N]**

İki qovluqda `.eval` logu var, RunRecord yoxdur:

| Qovluq | Log statusu | Nümunə | Divar saatı | Xərc |
|---|---|---:|---:|---|
| `full-run-01` | `cancelled` | 147 | 1h 05m 00s | **[N]** |
| `audit-live` | `started` | — | — | **[N]** |

`full-run-01` **147 case-lik tam qaçışdır** və 65 dəqiqə işləyib. Xərci $0 deyil —
sadəcə heç bir artefaktda yazılmayıb. Inspect-in öz `model_usage` sahəsi də boşdur
(`{}`), çünki R1 qərarına görə hədəf Custom Agent yolu ilə çağırılır və Inspect-in
model API-si ümumiyyətlə işə düşmür (`docs/R1-SPIKE.md`).

### 2.3 Qaçışın hissəsi olmayan çağırışlar — **[N]**

Diaqnostika, kəşfiyyat, DSL sazlaması, grader debug — bunlar `RunRecord`
yaratmır. LIM-E11 bunu qismən qaçılmaz sayır və sənədləşdirir.

### 2.4 Yeganə hesab uzlaşdırması — **[Ö], amma n = 1**

LIM-E11-də bir dəfə hesab ilə uzlaşdırma aparılıb:

> qeydlər həmin dövr üçün **$23.72** göstərdi, hesabdan **~$40** getdi.

Yəni həmin pəncərədə qeydlər faktiki xərcin **~59%-ni** tutmuşdu.

**Bu rəqəm çarpan kimi İSTİFADƏ EDİLMİR.** Bir müşahidədir, fərqin iki mənbəyi
qarışıqdır (sınan sorğular + qaçışdan kənar çağırışlar), və başqa pəncərədə
uzlaşdırma aparılmayıb. §1-dəki $26.60 **alt həddir** — nə qədər aşağı olduğu
naməlumdur. Müştəriyə deyiləcək cümlə budur, "təxminən $45" deyil.

---

## 3. Qaçış müddəti (divar saatı) — **[Ö]**

`reports/*/logs/*.eval` başlıqlarından (`stats.started_at` → `stats.completed_at`).

| Qaçış | Case | Müddət | Case başına | p50 gecikmə | p95 gecikmə |
|---|---:|---:|---:|---:|---:|
| `full-run-02` | 147 | 1h 10m 55s | 28.9 s | 19,980 ms | 78,577 ms |
| `full-run-03` | 162 | 0h 46m 22s | 17.2 s | 13,059 ms | 52,615 ms |
| `full-run-01` | 147 | 1h 05m 00s (kəsildi) | — | — | — |
| `full-run-03b` | 25 | 0h 14m 18s | 34.3 s | 29,588 ms | 69,054 ms |
| `ap021-recheck` | 22 | 0h 24m 12s | 66.0 s | 1,749 ms | 37,064 ms |

**Diapazon: 150 case-lik tam qaçış üçün 17–29 s/case → 43–72 dəqiqə** (§7).
`ap021-recheck`-in 66 s/case dəyəri rate limit backoff-una görə kənar dəyərdir və
diapazona daxil edilmir; `full-run-03b` isə ən çətin 25 case-dir.

---

## 4. Xərcin harada olduğu — bir cümlə

**Ölçülən model xərcinin 86.6%-i (23.05 / 26.60) üç tam qaçışdan gəlir.**
Pilot, smoke, gate, judge və kalibrasiya birlikdə $1.27-dir — yəni **hazırlıq və
qapı işi model büdcəsinin ~5%-idir**. Büdcə planlaşdırılarkən yalnız tam
qaçışların sayı əhəmiyyət daşıyır.

---

## 5. Əmək — auditin ƏSL maya dəyəri

### 5.1 Saat: **[N] NAMƏLUM**

Repo-da timesheet yoxdur. `board/tasks.json` yalnız **status keçidlərinin
vaxtını** saxlayır — bu, **elapsed**-dır, **əmək deyil**: gecə fasiləsi, gözləmə
və qaçışın özünün divar saatı bu spanların içindədir.

Üstəlik board **işin sonuna doğru qurulub**: ilk board hadisəsi
`2026-08-27T19:02:20`, halbuki ilk qaçış artefaktı `2026-08-26T21:54:57`-dir.
Yəni **korpus qurulması, uğursuzluq taksonomiyası, harness skeleti və grader
qatının yazılması board-a heç düşməyib.**

| Ölçü | Dəyər | İşarə |
|---|---:|---|
| Board-dakı tapşırıq sayı | 43 | **[Ö]** |
| `in_progress` spanı olan tapşırıq | 21 | **[Ö]** |
| Bu 21 tapşırığın `in_progress → review` cəmi | **23.05 saat** | **[Ö] elapsed, əmək DEYİL** |
| AP-013-ün gecə fasiləsi çıxılmaqla | 9.58 saat | **[H]** |
| Board-dan əvvəlki fazaların əməyi | **[N] NAMƏLUM** | — |

**Ona görə bu sənəd əmək saatını rəqəmlə vermir.** Onun əvəzinə əl işinin
**həcmini** verir — həcm ölçülüb və müştəri korpusunda birbaşa təkrarlanır.

### 5.2 Əl işinin ölçülən həcmi — **[Ö]**

#### Korpus qurulması — 100% əl ilə (AP-034)

`target/corpus/verify_fixtures.py` canlı qaçırıldı (exit 0):

```
documents            : 8
canonical parameters : 96      (aktiv 96, supersedes-li 27)
boundary thresholds  : 36      (108 probe nöqtəsi)
superseded pairs     : 27
colliding values     : 5
known gaps           : 7
resolved combos      : 14 return + 7 warranty
fixture orders       : 64
fixture customers    : 10
injection payloads   : 3
assertions run       : 1338
```

Fayl həcmi: `CANONICAL.yaml` 1,657 sətir · `FIXTURES.yaml` 925 · `TRAPS.md` 289 ·
`TOOLS.md` 312 · 8 siyasət sənədi 938 sətir — **cəmi 4,121 sətir**.
Hər dəyər əl ilə yazılıb və hər biri üçün `status`, `doc_version`, `applies_when`
insan tərəfindən verilib. AP-034 bunun **namizəd çıxarışını** avtomatlaşdırmağı
hədəfləyir — təsdiqi yox.

#### Triage — 29 case əl ilə oxundu (AP-021)

`docs/TRIAGE-RUN02.md`-dən:
- **29 stable-fail case**, hər birinin **hər üç cəhdinin cavab mətni** `.eval`
  logundan çıxarıldı və əl ilə oxundu → **87 cavab mətni**.
- Hər cavab `CANONICAL.yaml` və korpus sənədləri ilə tutuşduruldu. Sitatsız
  təsnifat qəbul edilmədi.
- Nəticə: **5 REAL-FAILURE · 14 GRADER-GAP · 10 AMBIGUOUS** + əlavə olaraq
  yalançı yaşıllar arasından **1 yeni real tapıntı (RF-06)**.
- Board spanı (AP-021): **1.74 saat elapsed** — bu, board-da tam əhatə olunmuş
  yeganə əl-triage tapşırığıdır.

**Bu mərhələ hesabatın etibarını təyin edir.** Triage olmasaydı 29 "stabil
tapıntı"nın 24-ü dərc olunardı və onların içində ən azı iki dağıdıcı saxta iddia
var idi («agent prompt injection-a uğradı», «retrieval işləmir») — ikisi də
yanlış. **Bu iş hər müştəridə tam təkrarlanır və avtomatlaşdırıla bilmir.**

#### Grader auditi (`docs/GRADER-AUDIT.md`)

- Əhatə: 20 qeyri-ingilis case (10 AZ + 10 RU) + eyni sinif üçün ingiliscə pattern-lər.
- **8 qüsur sinfi** (A-01 … A-08) tapıldı: 3 yalançı müsbət, 3 buraxılmış tapıntı,
  2 yalançı yaşıl.
- **20 case-dən 18-ində** ən azı bir pattern düzəldildi.
- Reqressiya qoruması: **133 yeni test** (`test_multilingual_patterns.py`);
  pytest sayı 339 → 472.

#### Judge kalibrasiyası

- `evals/calibration/labeled.yaml` — **30 əl ilə etiketlənmiş nümunə**, 436 sətir;
  hər etiketin `note` sahəsində niyə belə etiketləndiyi yazılır (`load_labels()`
  izahsız etiketi qəbul etmir).
- Nəticə **[Ö]**: uyğunluq **96.7%**, κ = **0.9497**, n = 30, `claude-opus-5`.
- Model xərci: **$0.3342** — yəni kalibrasiyanın maya dəyəri modeldə deyil,
  **30 etiketin əl ilə yazılmasındadır**.

#### Hesabatın yazılması

`FINDINGS.md` 74,094 bayt. Board spanları: AP-009 (FINDINGS) 1.32 saat elapsed,
AP-010 (writeup) 0.32 saat elapsed — **[Ö] elapsed, əmək deyil**.

---

## 6. Təqvim müddəti — **[Ö]**

| Ölçü | Dəyər |
|---|---|
| İlk qaçış artefaktı (`pilot`) | 2026-08-26 T21:54:57 UTC |
| Son qaçış artefaktı (`gate-live`) | 2026-08-28 T10:27:29 UTC |
| **Artefaktdan-artefakta təqvim müddəti** | **36 saat 33 dəqiqə** |
| Commit olan təqvim günü | **3** (08-26, 08-27, 08-28) |
| Commit sayı | 25 |
| Son board hadisəsi | 2026-09-01 T21:47 (hesabat/şablon işi davam edir) |

⚠️ **Bu müddət agent komandası ilə əldə olunub və insan komandasının təqvimi
kimi oxuna BİLMƏZ.** Müştəri auditinin təqvimi üçün ondan çıxarıla bilən yeganə
şey **maşın hissəsinin** müddətidir: tam qaçış 43–72 dəqiqə (§3), yəni bir günün
içində 3–4 tam qaçış mümkündür. Aralarındakı əl işinin təqvimi **[N] naməlumdur**.

---

## 7. Miqyaslama

**Baza (ölçülmüş) — case başına, 3 təkrar daxil:**

| Qaçış | Case | Xərc | Case başına | İşarə |
|---|---:|---:|---:|---|
| `full-run-02` | 147 (qiymətləndirilən) | $11.3364 | **$0.0771** | **[Ö]** |
| `full-run-03` | 137 (qiymətləndirilən) | $9.3215 | **$0.0680** | **[Ö]** |
| `full-run-03b` | 25 | $2.3921 | **$0.0957** | **[Ö]**, alt hədd (45 cəhd ölçülməyib) |

**Qəbul edilən diapazon: $0.068 – $0.096 / case (3 təkrar).**
Bir cəhd üçün: **$0.0227 – $0.0319** **[H]** (case xərci 3-ə bölünür; `cost_usd`
cəhdlərin cəmidir, ona görə bölmə düzgündür — LAKİN backoff təkrarları xətti
deyil, bu isə diapazonun **yuxarı** ucunu daha da yuxarı apara bilər).

### 7.1 Case sayı və təkrar sayı üzrə — **[H]**

Fərziyyə açıq yazılır: **xərc case sayına və təkrar sayına xəttidir.**
Bu fərziyyə backoff təkrarlarını nəzərə almır (§2.1) — yəni rəqəmlər **alt həddir**.

| Ssenari | $2/$10 rejimi (≤2026-08-31) | $3/$15 rejimi (≥2026-09-01) | Divar saatı |
|---|---:|---:|---:|
| 150 case × 3 təkrar | **$10.20 – $14.36** | **$15.30 – $21.53** | 43 – 72 dəq |
| 150 case × 1 təkrar | $3.40 – $4.79 | $5.10 – $7.18 | 14 – 24 dəq |
| 300 case × 3 təkrar | **$20.40 – $28.71** | **$30.61 – $43.07** | 86 – 145 dəq |
| 300 case × 1 təkrar | $6.80 – $9.57 | $10.20 – $14.36 | 29 – 48 dəq |

> **`--repeat 1` variantı bir seçim deyil.** `PLAN.md` keyfiyyət qaydası №1:
> *reproduksiya olunmayan tapıntı hesabata düşmür.* Reproduksiya səbətləri
> (`stable-fail` / `flaky` / `unstable-fail`) yalnız N ≥ 3 ilə hesablanır.
> `full-run-02`-də **flaky nisbəti 17.0%** çıxdı (`reproduction.json`:
> `flaky_rate: 0.170`, `flaky_alarm: true`) — N = 1 ilə bu 25 case səssizcə
> tapıntı kimi dərc olunardı. Cədvəldəki `--repeat 1` sətri **yalnız qənaətin
> nəyə başa gəldiyini göstərmək üçündür**: $7–14 qənaət müqabilində hesabatın
> etibarı gedir.

### 7.2 Judge qatının payı — **[Ö] + [H]**

| Ölçü | Dəyər | İşarə |
|---|---:|---|
| `full.jsonl`-də judge işlədən case | **3 / 165 = 1.8%** (`requires_justification`) | **[Ö]** |
| 3 judge çağırışının model xərci | **$0.0387** (5,001 giriş + 549 çıxış token) | **[Ö]** |
| Judge çağırışı başına | $0.0129 | **[H]** |
| Tam qaçışdakı payı ($9.32 – $11.34 bazasında) | **0.34% – 0.42%** | **[H]** |
| Kalibrasiya (30 etiket, bir dəfəlik / rubrika versiyası) | **$0.3342** | **[Ö]** |
| Etiket başına kalibrasiya xərci | $0.0111 | **[H]** |
| **Fərz: 165 case-in HAMISI judge-a getsəydi** | +$2.13 → qaçış xərcinə **~+20%** | **[H]** |

**Nəticə:** judge qatı model büdcəsində praktiki olaraq görünmür (<0.5%). Onun
maya dəyəri **modeldə deyil, 30 etiketin əl ilə yazılmasındadır** və o iş
rubrika hər dəyişəndə **yenidən** lazımdır (`REQUIRES_JUSTIFICATION_V1`
versiyalanır; köhnə kalibrasiya yeni rubrikanı müdafiə etmir).

---

## 8. Qiymət rejiminə həssaslıq — **[Ö]**

`pricing/models.yaml` tarixə həssas dərəcə saxlayır:

```yaml
claude-sonnet-5:
  input: 2.0            # introductory, 2026-08-31 daxil olmaqla
  output: 10.0
  cached_input: 0.2
  effective_until: "2026-08-31"
  after: {input: 3.0, output: 15.0, cached_input: 0.3}
```

Giriş, çıxış və keşlənmiş giriş — **üçü də dəqiq 1.5× artır**. Yəni token
qarışığından asılı olmayaraq **hər sonnet-5 rəqəmi dəqiq ×1.5 olur**. Bu, təxmin
deyil, arifmetikadır:

| | $2/$10 | $3/$15 (2026-09-01-dən) |
|---|---:|---:|
| `full-run-02` | $11.3364 | **$17.0046** |
| `full-run-03` | $9.3215 | **$13.9822** |
| `full-run-03b` | $2.3921 | **$3.5882** |
| Bütün SUT qaçışları | $26.2280 | **$39.3420** |
| Judge (`claude-opus-5`, dərəcə dəyişmir) | $0.3729 | $0.3729 |
| **CƏMİ ÖLÇÜLƏN** | **$26.6009** | **$39.7149** |

**Praktiki nəticə (bu gün, 2026-09-01):** artefaktlardakı bütün xərc rəqəmləri
artıq **köhnə rejimə aiddir**. Müştəri zəngində Aurora auditinin xərci
**$26.60 deyil, bugünkü qiymətlə ~$39.71** kimi deyilməlidir — və hər ikisinin
yanında "bu, alt həddir" (§2) qeydi getməlidir.

> **Ayrıca tələ (OPS-04 / LIM-E08):** Dify-ın öz `anthropic` plugin-i
> `claude-sonnet-5`-i həmişə $3/$15 kimi hesablayır. 2026-08-31-ə qədər onun
> rəqəmi ~50% şişik idi; **2026-09-01-dən etibarən düzgün olur**. Yəni müştəri
> platformanın öz xərc panelinə baxıb bizim köhnə rəqəmlərimizlə uyğunsuzluq
> görürsə, səbəb budur.

---

## 9. Bir dəfəlik iş və hər müştəridə TƏKRARLANAN iş

Bu ayrım qiymət modelinin özəyidir: bir dəfəlik iş amortizasiya olunur,
təkrarlanan iş hər auditin döşəməsinə birbaşa girir.

| İş | Artefakt | Təkrarlanma | Qeyd |
|---|---|---|---|
| Harness (`agentproof/`, adapter, runner) | `agentproof/` | **bir dəfəlik** | R1 qərarı testlə qorunur |
| 11 determinist grader | `agentproof/graders/` | **bir dəfəlik** + korpus üçün pattern düzəlişi | 251 grader testi |
| Hesabat / HTML / CI / baseline qapısı | `report/`, `.github/workflows/` | **bir dəfəlik** | |
| Xərc uçotu, reproduksiya qapısı, board | `report/cost.py`, `evals/reproduce.py` | **bir dəfəlik** | |
| **Korpus + ground truth** | `target/corpus/` (4,121 sətir, 96 parametr) | **HƏR MÜŞTƏRİDƏ** | 100% əl ilə — AP-034 hədəfi |
| **Dataset generasiyası** | `evals/datasets/build_full.py` → 165 case | **HƏR MÜŞTƏRİDƏ** | generator Aurora-ya sabit bağlıdır — AP-036 hədəfi |
| **Tam qaçış (×3 təkrar)** | `reports/full-run-*` | **HƏR MÜŞTƏRİDƏ** | $15–22 (bugünkü rejim, 150 case) |
| **Triage (əl ilə cavab oxuma)** | `docs/TRIAGE-RUN02.md` | **HƏR MÜŞTƏRİDƏ** | avtomatlaşdırıla bilmir |
| **Grader auditi** | `docs/GRADER-AUDIT.md` | **HƏR MÜŞTƏRİDƏ** | müştərinin dili/terminologiyası dəyişir |
| Judge kalibrasiyası (30 etiket) | `evals/calibration/labeled.yaml` | **rubrika dəyişəndə** | rubrika versiyalıdır |
| Hesabatın yazılması | `FINDINGS.md`, müştəri hesabatı | **HƏR MÜŞTƏRİDƏ** | |

### 9.1 AP-034 / AP-036-nın vəd etdiyi gün qənaəti — bu modelə qarşı yoxlanır

AP-034-ün təsvirində yazılıb: korpusun əl ilə qurulması *«14 günlük auditi ~25
günə çıxarır»*.

**Yoxlama nəticəsi: bu iki rəqəmin repo-da artefakt mənbəyi YOXDUR.** **[N]**

- Nə `14 gün`, nə `25 gün` heç bir `reports/`, `docs/` və ya `board/` artefaktında
  ölçülməyib. Ölçülən təqvim müddəti **36 saat 33 dəqiqədir** (§6) və o da agent
  komandasının müddətidir.
- Ölçülən yeganə şey **həcmdir**: 96 parametr, 8 sənəd, 1,338 assertion, 4,121
  sətir — hamısı əl ilə (§5.2). Bu həcmin neçə günə çevrildiyi ölçülməyib.

**Buna görə də AP-034 və AP-036 "N gün qənaət edir" iddiası ilə satıla bilməz.**
Onların düzgün ifadəsi ölçülə bilən formadadır və AP-034-ün öz DoD-u da məhz bunu
tələb edir: *«recall və false-positive rəqəmi ÖLÇÜLÜR … "avtomatik çıxarır"
iddiası ölçülmüş rəqəm olmadan yazılmır»*.

Bu sənədin tövsiyəsi: AP-034 bitəndə **recall × 96 parametr** ölçüsü bu sənədə
əlavə olunsun, gün qənaəti isə **yalnız ikinci audit üçün əvvəl/sonra ölçüsü
alındıqdan sonra** yazılsın.

---

## 10. Qiymət döşəməsi

**Bir cümlə:**

> **Model xərci auditin qiymət döşəməsini təyin etmir** — ölçülən bütün Aurora
> audit dövrü bugünkü qiymət rejimində **$39.71**-dir (alt hədd), yəni $3–6k-lıq
> qiymətin **0.7–1.3%-i**; döşəməni **təkrarlanan əl işi** təyin edir və o iş
> **saatla ölçülməyib**, ona görə döşəmə burada rəqəmlə deyil, **düsturla**
> verilir: `döşəmə = $40 (model, alt hədd) + H × R`, burada `H` = §9-dakı
> təkrarlanan mərhələlərin saatı **[N]**, `R` = saatlıq dərəcə **[N]**.

### 10.1 Həssaslıq cədvəli — arifmetika, təxmin deyil

$3,000-lıq audit üçün model xərci ($40) çıxıldıqdan sonra əməyə $2,960 qalır.
Marjanın sıfır olduğu saat sayı:

| Saatlıq dərəcə `R` | $3,000-da break-even `H` | $6,000-da break-even `H` |
|---:|---:|---:|
| $50 | 59.2 saat | 119.2 saat |
| $75 | 39.5 saat | 79.5 saat |
| $100 | 29.6 saat | 59.6 saat |
| $150 | 19.7 saat | 39.7 saat |
| $200 | 14.8 saat | 29.8 saat |

**Bu cədvəl qiymət təklif etmir.** O, bir sualı ölçülə bilən hala gətirir:
*təkrarlanan mərhələlər (korpus + dataset + qaçış + triage + grader auditi +
hesabat) neçə saat çəkir?* Cavab bilinən kimi döşəmə birbaşa oxunur.

**İlk müştəri auditində ölçülməli olan yeganə şey budur.** Tövsiyə: ilk audit
zamanı §9-dakı hər təkrarlanan sətir üçün faktiki saat qeyd olunsun — bu, ikinci
zəngdən başlayaraq qiyməti təxmin olmaqdan çıxarır.

---

## 11. YEKUN CƏDVƏL — tipik audit

**Tipik audit tərifi:** 150 case, `--repeat 3`, tək SUT modeli (`claude-sonnet-5`),
judge qatı case-lərin ~2%-ində, bir tam qaçış + bir yenidən qaçış, əl ilə triage,
grader auditi, bir hesabat. Aurora auditi məhz bu formadadır.

| Maddə | Dəyər | İşarə |
|---|---:|---|
| **MODEL XƏRCİ** | | |
| Pilot + smoke + qapı yoxlamaları | $0.72 → **$1.08** | **[Ö]** → ×1.5 |
| Tam qaçış (150 case × 3) | **$15.30 – $21.53** | **[H]** ($0.068–0.096/case bazasında) |
| Yenidən qaçış / triage yoxlamaları | $2.28 → **$3.42** | **[Ö]** → ×1.5 |
| Judge çağırışları (~3 case) | **$0.04** | **[Ö]** |
| Judge kalibrasiyası (30 etiket, rubrika başına) | **$0.33** | **[Ö]** |
| **Model xərci CƏMİ (bugünkü $3/$15 rejimi)** | **$20.17 – $26.40** | **[H]**, **ALT HƏDD** |
| Ölçülməyən model xərci | **NAMƏLUM** | **[N]** — §2 |
| **ƏMƏK** | | |
| Korpus qurulması (≈8 sənəd, ≈96 parametr, ≈1,300 assertion) | **NAMƏLUM saat** | **[N]** — həcm ölçülüb, saat yox |
| Dataset generasiyası + örtük yoxlaması | **NAMƏLUM saat** | **[N]** |
| Triage (≈29 case × 3 cəhd = ≈87 cavab mətni əl ilə) | **NAMƏLUM saat** (board elapsed: 1.74 s) | **[N]** / **[Ö] elapsed** |
| Grader auditi (≈8 qüsur sinfi, ≈133 reqressiya testi) | **NAMƏLUM saat** | **[N]** |
| Judge kalibrasiyası (30 etiket + izah) | **NAMƏLUM saat** | **[N]** |
| Hesabatın yazılması | **NAMƏLUM saat** (board elapsed: 1.64 s) | **[N]** / **[Ö] elapsed** |
| **Əmək CƏMİ** | **NAMƏLUM** | **[N]** — §5.1, §10 |
| **TƏQVİM** | | |
| Maşın hissəsi (tam qaçış) | **43 – 72 dəqiqə** | **[Ö]** |
| Bir günə sığan tam qaçış sayı | **3 – 4** | **[H]** |
| Aurora auditinin artefaktdan-artefakta müddəti | **36 saat 33 dəqiqə** | **[Ö]**, agent komandası |
| Müştəri auditinin təqvim müddəti | **NAMƏLUM** | **[N]** — insan komandası ölçülməyib |

**Cədvəldən çıxan iki cümlə (müştəri zəngi üçün):**

1. «Auditin model xərci **$20–26-dır** və bu, ölçülmüş alt həddir — qiymətin
   ~1%-i. Qiymət model xərcindən gəlmir.»
2. «Qiymət **əl işindən** gəlir: 150 test halının siyasət sənədlərinizdən
   törədilməsi, 3 təkrarlı qaçış, sonra hər stabil uğursuzluğun **əl ilə**
   oxunub təsnif edilməsi. Aurora-da bu triage 29 tapıntıdan **yalnız 5-inin**
   real olduğunu göstərdi — qalan 24-ü dərc olunsaydı hesabat yanlış olardı.»

---

## 12. Bu sənədin öz məhdudiyyətləri

1. **Bir hədəf, bir korpus, bir model.** Bütün rəqəmlər Dify 1.17.0 + Aurora
   korpusu + `claude-sonnet-5` üzərindədir. Başqa platforma / daha uzun cavablar
   case başına xərci dəyişir.
2. **Case başına xərc korpusdan asılıdır.** Aurora cavabları qısadır (mock tool
   qatı, kiçik korpus — LIM-C09/C10). Böyük bilik bazasında giriş tokeni artır.
3. **`--repeat 3` diapazonu 3 qaçışdan çıxarılıb** (147, 137, 25 case). N = 3
   qaçış üzrə diapazondur, paylanma deyil.
4. **Əmək saatı ölçülməyib** — bu sənədin ən böyük boşluğu və §10-un tək
   dəyişəni. İlk müştəri auditində ölçülməlidir.
5. **Xərc rəqəmləri alt həddir** (LIM-E11). Nə qədər aşağı olduğu bilinmir.

---

## 13. İstinadlar

| Rəqəm | Mənbə |
|---|---|
| Bütün `cost_usd`, `wasted_cost_usd`, `cost_coverage` | `reports/*/<run_id>.json` → `totals` |
| Divar saatı, qaçış statusu | `reports/*/logs/*.eval` → `stats.started_at` / `completed_at` |
| Judge / kalibrasiya tokenləri | `reports/judge-cache/*.json`, `reports/judge-01/judge-cache/*.json` → `meta` |
| Qiymət cədvəli və tarix keçidi | `agentproof/pricing/models.yaml`, `agentproof/pricing/table.py` |
| Uçot bölgüsü və qaydası | `agentproof/report/cost.py` (AP-026) |
| Xərc kor nöqtəsi | `docs/LIMITATIONS.md` LIM-E11 (+ LIM-E08 qiymət rejimi) |
| Platformanın xərc səhvi | `docs/OPS-FINDINGS.md` OPS-04 |
| Triage həcmi və nəticəsi | `docs/TRIAGE-RUN02.md` |
| Grader auditi | `docs/GRADER-AUDIT.md` |
| Kalibrasiya nəticəsi | `docs/JUDGE-CALIBRATION.md`, `evals/calibration/labeled.yaml` |
| Korpus həcmi | `target/corpus/verify_fixtures.py` (canlı qaçırıldı, exit 0) |
| Reproduksiya / flaky nisbəti | `reports/full-run-02/reproduction.json` |
| Board elapsed | `board/tasks.json` → `history` |
| Faza statusu, keyfiyyət qaydaları | `PLAN.md` |
