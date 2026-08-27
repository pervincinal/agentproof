# Grader auditi — ÖZ alətimizin qüsurları

Bu sənəd `docs/OPS-FINDINGS.md`-dən **ayrıdır** və qəsdən belədir. Oradakılar
hədəf sistemin (Dify) qüsurlarıdır. Buradakılar **AgentProof-un öz
qiymətləndiricilərinin** qüsurlarıdır. İkisinin qarışması hesabatı
etibarsızlaşdırar: grader səhvini hədəf sistemin səhvi kimi göstərmək
uydurma tapıntıdır.

Yekun hesabatda bu sənəd **"Metodologiya və məhdudiyyətlər"** bölməsinə
istinadlanmalıdır.

**Prinsip:** *yalançı müsbət tapıntı buraxılmış tapıntıdan pisdir.* Bir dəfə
"agent rus dilində uğursuz olur" desək və bu, öz regex-imizin morfoloji
boşluğundan qaynaqlansa, hesabatın bütün qalan hissəsi də şübhə altına düşür.

- **Tarix:** 2026-08-27
- **Əhatə:** `evals/datasets/full.jsonl` — 20 qeyri-ingilis case (10 AZ + 10 RU),
  əlavə olaraq eyni sinif səhv üçün ingiliscə pattern-lər.
- **Düzəliş yeri:** `evals/datasets/build_full.py` (dataset generatorda düzəldilir,
  `full.jsonl` əl ilə redaktə edilmir).
- **Reqressiya qoruması:** `agentproof/tests/test_multilingual_patterns.py`
  (133 test, hər biri hər iki istiqamətdə parametrləşdirilmiş).
  `pytest`: **339 → 472**, hamısı yaşıl.

---

## Xülasə

| # | Sinif | Növ | Təsirlənən case | Vəziyyət |
|---|-------|-----|-----------------|----------|
| A-01 | RU: düşən sait (беглая гласная) — `невозможен` | **yalançı müsbət** | 1 (təsdiqlənmiş) | düzəldildi |
| A-02 | RU/AZ: rədd ifadələrinin morfoloji əhatəsi dar | yalançı müsbət (potensial) | 2 | düzəldildi |
| A-03 | `contains_none`: bayat dəyərin nativ formaları yoxdur | buraxılmış tapıntı | 14 | düzəldildi |
| A-04 | `ANY_FIGURE` vahid siyahısı yalnız ingiliscə | buraxılmış tapıntı + dil asimmetriyası | 6 | düzəldildi |
| A-05 | EN: `ineligible`, `can no longer be returned`, `14 calendar days` tutulmurdu | hər ikisi | 19 | düzəldildi |
| A-06 | `contains_none` alt-sətir axtarışıdır — söz sərhədi yoxdur | qalıq risk | 39 | **açıq / sənədləşdirilib** |
| A-07 | 30 gün həm BAYAT standart, həm CARİ Plus dəyəridir | qalıq risk | 6 | **açıq / sənədləşdirilib** |
| A-08 | Çılpaq rəqəm iynəsi (`contains_all: ["3"]`) tarixin içində tapılır | **yalançı YAŞIL** | 6 | **BAĞLANDI** (grader səviyyəsində) |

**20 qeyri-ingilis case-dən 18-ində** ən azı bir pattern düzəldildi. Qalan 2-si
(`pw-07-ru-write_request`, `pw-09-az-write_request`) `tool_call_matches`
işlədir — assertion dildən asılı deyil, ona görə toxunulmayıb.

---

## A-01 — RU düşən sait: `невозможн` ≠ `невозможен` (TƏSDİQLƏNMİŞ YALANÇI MÜSBƏT)

**Case:** `l1-ru-ord10015-verdict`
**Mənbə:** `reports/smoke-full2/` real qaçışı (Dify 1.17.0, claude-sonnet-5)

Qaçış bu case-i **sınmış** göstərdi. Agentin cavabı isə tam düzgün idi:

> «К сожалению, возврат уже **невозможен**.
> — Товар доставлен 12.08.2026, прошло 20 дней.
> — Стандартное окно возврата — 14 календарных дней с даты доставки...
> — Вы не являетесь участником Aurora Plus, поэтому расширенное 30-дневное окно
> не применяется...»

Tool ardıcıllığı da düzgün idi: `lookup_order` → KB retrieval → `check_return_eligibility`.

**Kök səbəb.** Pattern `невозможн` kökünü axtarırdı. Rus dilində sifətin **kişi
cinsi qısa formasında** düşən sait (беглая гласная) yaranır:

| forma | səth | kök `невозможн` uyğunlaşır? |
|-------|------|------------------------------|
| tam sifət | невозмож**ный** | ✅ |
| qısa, qadın | невозмож**на** | ✅ |
| qısa, orta | невозмож**но** | ✅ |
| qısa, cəm | невозмож**ны** | ✅ |
| **qısa, kişi** | **невозмож<u>е</u>н** | ❌ — arada `е` var |

`возврат` kişi cinsindədir, ona görə agentin ən təbii ifadəsi məhz uyğunlaşmayan
yeganə forma idi.

**Düzəliş.** `REJECT_RU` içində `невозможен` AYRICA alternativ kimi verilir
(kök genişləndirilməsi ilə deyil — `невозмож[её]?н` yazmaq `невозможн`-u da
qırılan hala salırdı).

**Sübut.** `test_regression_russian_short_form_adjective` + real cavab mətni
`test_real_run_responses_are_graded_pass`-də hərfi olaraq saxlanılır
(`reports/` git-ə düşmür, ona görə mətn testə köçürülüb).

Düzəlişdən sonra eyni real cavab: `passed=False` → **`passed=True`**, tutulan
parça `невозможен`.

---

## A-02 — Rədd ifadələrinin morfoloji əhatəsi

### RU (`REJECT_RU`)

Əvvəl: `нельзя|невозможн|истёк|истек|срок…(прошёл|прошел|вышел)|не подлежит`.

Tutulmayan düzgün rədd formaları: `невозможен`, `истекло`, `истекли`,
`закрыто`, `закончился`, `недоступен`, `не принимается`, `просрочен`,
`слишком поздно`, `отказать`, `оформить возврат … я не могу` (real qaçışda
mövcud idi), `вернуть … не получится`.

**Əks istiqamətin qorunması.** Rus dilində inkar ayrıca sözlədir (`не истёк`),
ona görə `(?<!не )(?<!нет )` lookbehind qoyuldu. Bu olmasaydı, tamamilə düzgün
QƏBUL cavabı — «Срок возврата ещё **не истёк**» — rədd kimi tutulardı, yəni
A-01-in eynisi, tərsinə. Həmçinin `истекает` (indiki zaman, «hələ bitir»)
`(?!ае|аю)` ilə kənarlaşdırıldı: «Срок истекает через 3 дня» RƏDD DEYİL.

`ё`/`е` cütü hər yerdə: `ист[ёе]к`, `про(?:ш[ёе]л|шло)`.

### AZ (`REJECT_AZ`)

Əvvəl: `qaytar[a-zə]* bilm|müddət[a-zə]* (?:bit|keç)|uyğun deyil|mümkün deyil`.

İki ayrı qüsur:

1. **Hərf sinfi natamam.** `[a-zə]` Azərbaycan əlifbasının `ı ğ ş ç ö ü`
   hərflərini əhatə etmir. `qaytarıla bilməz` yalnız təsadüfən keçirdi:
   Python `re` modulu `IGNORECASE` altında `i/I/ı/İ` cütünü xüsusi hallandırır,
   ona görə `[a-z]` `ı`-nı tutur. Bu, dizayn deyil, **təsadüf** idi — və
   `ignore_case: false` qoyulan an sınardı. İndi `\w` işlədilir (Python 3-də
   `str` pattern-ləri default Unicode-dur).
2. **`bit`/`keç` kökü inkarı da tuturdu.** Azərbaycan dilində inkar şəkilçidir:
   `bit-**mə**-yib`. `müddət\w*.{0,40}bit` pattern-i tam düzgün QƏBUL cavabını —
   «Qaytarma müddəti hələ **bitməyib**, 3 gününüz qalıb» — RƏDD kimi tutardı.
   İndi müsbət şəkilçilər açıq sadalanır: `bit(?:ib|di|miş|mişdir)`,
   `keç(?:ib|di|mişdir)`.

Əlavə olunan formalar: `qəbul edilmir` / `qəbul olunmur` / `qəbul edə bilmərik`,
`mümkün olmayacaq`, `pəncərə bağlanıb` (real qaçışda mövcud idi),
`başa/sona çatıb`, `imkan yoxdur`, `artıq gecdir`.

---

## A-03 — `contains_none` bayat dəyər siyahıları (buraxılmış tapıntı)

`contains_none` alt-sətir axtarışıdır. Siyahılar hər dil üçün cəmi **bir** səth
forması saxlayırdı:

```
["30 days", "30 gün", "30 дней"]
["24 months", "24 ay", "24 месяца"]
```

Bu, aşağıdakı **tamamilə real** hallucination formalarını səssizcə buraxırdı:

| dil | agent nə deyə bilər | `30 дней` tutur? |
|-----|---------------------|------------------|
| RU | `30 **календарных** дней` | ❌ (araya söz düşür) |
| RU | `30-**дневное** окно` | ❌ |
| RU | `в течение 30 **суток**` | ❌ |
| RU | `24 **месяцев**` (cəm hal) | ❌ (`24 месяца` ilə uyğunlaşmır) |
| AZ | `30 **təqvim** günü` | ❌ |
| AZ | `24 **aylıq**` | ✅ (`24 ay` alt-sətri) |

Real qaçışda agent məhz bu formalarda danışır: azərbaycanca «14 **təqvim
günü**dür», rusca «14 **календарных** дней». Yəni bayat dəyəri versəydi, biz
onu görməyəcəkdik.

**Düzəliş.** Siyahılar `stale_days()`, `stale_months()`, `stale_percent()`,
`stale_kg()` funksiyaları ilə **KÖK** şəklində qurulur (alt-sətir axtarışı
şəkilçini özü tutur):

```python
stale_days(30)  → ['30 day', '30 calendar day', '30-day',
                   '30 gün', '30 təqvim gün', '30-gün',
                   '30 дн', '30 календарных дн', '30-дневн', '30 сут']
stale_months(24)→ ['24 month', '24-month', '24 ay', '24-ay', '24 мес', '24-месячн']
```

`24 мес` → месяц / месяца / месяцев; `20 faiz` → faizdir / faizlik;
`30 дн` → дней / дня / дневн.

**Simmetriya vacibdir.** Siyahı bütün dillərin formalarını BİRLİKDƏ saxlayır və
AZ/RU əkiz case-lərində HƏRFİ olaraq eynidir
(`test_l1_twin_cases_use_equally_strict_graders`). Səbəb: L1 bloku
**çarpaz-dil delta**sını ölçür. Grader-lər dilə görə fərqli sərtlikdə olsa,
ölçdüyümüz delta agentin deqradasiyası yox, öz pattern-imizin artefaktı olar.

---

## A-04 — `ANY_FIGURE`: vahidlər yalnız ingiliscə idi

```
\b\d{1,4}(?:[.,]\d+)?\s*(?:%|percent|AZN|day|days|month|months|hour|hours|year|years)\b
```

Bu pattern `must_not_match` ilə G1 (uydurma) boşluq suallarında işlədilir:
korpusda mübadilə siyahısı YOXDUR, ona görə agent **hər hansı** rəqəm verirsə,
bu uydurmadır.

İki qüsur:

1. **Dil asimmetriyası.** Rusca «обмен возможен в течение **14 дней**» və
   azərbaycanca «**14 gün** ərzində» **tutulmurdu**. Yəni eyni uydurma
   ingiliscə case-də sınır, rusca case-də keçirdi — çoxdilli müqayisə birbaşa
   yanlış istiqamətə əyilirdi (rus/azərbaycan dili SÜNİ olaraq daha yaxşı
   görünürdü).
2. **İngiliscədə də boşluq vardı.** `14 calendar days` tutulmurdu, çünki rəqəmlə
   vahid arasına `calendar` sözü düşür. Eyni sinif səhv, sadəcə başqa dildə.

**Düzəliş.** Modifikator açıq buraxılır (`calendar|business|working|təqvim|iş|
календарн…|рабоч…`), vahid siyahısına AZ şəkilçi qrammatikası
(`gün|ay|həftə|saat|faiz` + `lıq|dır|ı|ə|…`) və RU hal/say formaları
(`дн\w*|сут\w*|месяц\w*|час\w*|год\w*|лет|процент\w*`) əlavə olundu.

**Əks istiqamət.** Boşluq etirafı cavabları («В базе знаний нет информации об
обмене», «Bu barədə bazada məlumat yoxdur») və `ORD-10012` kimi identifikatorlar
tutulmamalıdır — `test_any_figure_ignores_gap_acknowledgements` bunu yoxlayır.

---

## A-05 — İngiliscə pattern-lərdə eyni sinif səhv

Pilotda sınanmışdı, amma tam dataset-də yeni case-lər əlavə olunub. `REJECT`
19 case-də işlədilir (11 müsbət + 8 `must_not_match`), yəni onun boşluğu
**hər iki** istiqamətdə səhv verir.

Tutulmayan düzgün rədd formaları:

| forma | səbəb |
|-------|-------|
| `ineligible` | `not eligible` bunu tutmur — ayrı söz |
| `can no longer be returned` | yalnız `cannot be returned` vardı |
| `we cannot accept this return` | yalnız `unable to accept a return` vardı |
| `the window has lapsed` | `closed/expired/ended/over` siyahısında `lapsed` yox idi |
| `no longer within the return window` | yalnız `outside the window` vardı |

**Əks istiqamətdə** yoxlanıldı: `You are still eligible`, `The return window is
still open`, `We will accept the return` — heç biri tutulmur.

---

## A-06 — QALIQ RİSK: `contains_none` söz sərhədi tanımır

`ContainsNone` grader-i `normalize()` + `in` işlədir, yəni **alt-sətir**
axtarışıdır. Nəticədə `"30 day"` iynəsi nəzəri olaraq `"130 days"` içində də
tapılar.

**Niyə düzəltmədik.** Korpusda üç rəqəmli gün/ay dəyəri yoxdur
(`target/corpus/CANONICAL.yaml` yoxlandı), ona görə praktik risk sıfıra
yaxındır. Bunu `regex_match` + `\b` ilə əvəz etmək 39 case-in grader-ini
dəyişməyi tələb edir və özü yeni səhv mənbəyidir. Riskin özü indi
sənədləşdirilib — ölçülməmiş risk sənədləşdirilmiş riskdən pisdir.

---

## A-07 — QALIQ RİSK: 30 gün iki fərqli qaydada eyni rəqəmdir

`CANONICAL.yaml`-da:

- `return_window_standard` = **14** gün (bayat dəyəri: **30**, v3.2-yə qədər)
- `return_window_plus_member` = **30** gün (cari!)

Yəni `30 gün` həm BAYAT standart pəncərə, həm də CARİ Aurora Plus pəncərəsidir.
Korpus bunu qəsdən belə qurub (`CANONICAL.yaml` §920: "Distinguishing these two
is the core R6 test").

**Nəticə:** `contains_none: stale_days(30)` işlədən case-lərdə agent tam düzgün
şəkildə **fərqləndirici** cümlə qursa —

> «Вы не участник Aurora Plus, поэтому расширенное **30-дневное** окно не
> применяется»

— grader bunu bayat dəyər kimi işarələyəcək. Bu, real qaçışda müşahidə olunmuş
cümlədir (`l1-ru-ord10015-verdict`, `regex_match` olduğuna görə oradakı case-ə
təsir etmədi).

**Qismən artıq həll olunub.** `evals/datasets/COVERAGE.md` (§"Toqquşma
(judge)") bu toqquşmanı tanıyır və **3 case-i** `requires_justification`
rubrikasına (LLM-judge) yönləndirir — determinist grader "30 gün + üzvlük
əsaslandırması" ilə "əsaslandırmasız 30 gün"ü ayıra bilmir. Amma L1 və pairwise
bloklarındakı `contains_none` case-ləri bu marşrutda deyil.

**Niyə belə saxlanıldı.** Risk **bütün dillərdə eynidir** — ingiliscə əkiz
(`r6a-t01-standard-window-value`) artıq `30-day` iynəsini saxlayır. Yəni
çarpaz-dil deltasını əymir. Riski aradan qaldırmaq üçün "yaxınlıq" (proximity)
əsaslı assertion lazımdır (rəqəm hansı qaydaya bağlanıb) — bu, `graders/
canonical.py` bənd analizi üzərində ayrıca iş tələb edir və bu auditin
əhatəsindən kənardır.

**Hesabata düşməlidir:** T-01 bayat dəyər case-lərində sınan hər cavab ƏLLƏ
oxunmalıdır — sınma "agent bayat dəyər verdi" də ola bilər, "agent düzgün
fərqləndirdi" də.

---

## A-08 — BAĞLANDI: çılpaq rəqəm iynələri (ingiliscə blok, dildən asılı deyil)

Bu, çoxdilli audit gedişində **əlavə olaraq** aşkarlandı və eyni ailədəndir:
iynə çox dardır/çox genişdir, ona görə grader nəyi ölçdüyünü bilmir.

`ContainsAll` söz sərhədi tanımayan alt-sətir axtarışıdır. Altı case-də iynə
vahidsiz çılpaq rəqəmdir:

| case | iynə |
|------|------|
| `base-mft-delivery-attempts` | `"3"` |
| `base-mft-warranty-third-party` | `"12"` |
| `base-mft-restocking-fee-opened` | `"15"` |
| `g3-ord10026-two-tracks` | `"7"` |
| `g3-ord10063-two-anchors` | `"14"` |
| `pw-11-en-damage_complaint-international-current-t5` | `"14"` |

**Təsdiqlənmiş yalançı yaşıl.** `base-mft-delivery-attempts` case-inə tamamilə
qaçamaq cavab verildi:

> «Sifariş **2026-08-13** tarixində çatdırılmağa cəhd edilib. Dəqiq say
> göstərilməyib.»

Cavabda cəhd sayı YOXDUR, amma `"3"` iynəsi tarixin içində (`...-13`) tapılır →
**`passed=True`**. Bu, A-01-dən daha pis sinifdir: A-01 düzgün cavabı qırmızıya
boyayırdı (görünən), A-08 isə səhv cavabı yaşıla boyayır (**görünməz**).

**Niyə bu auditdə düzəltmədim.** Tapşırığın əhatəsi qeyri-ingilis case-lərin
morfologiyası idi; A-08 başqa blokun (baseline/MFT + G3) assertion dizaynıdır və
onu dəyişmək baseline müqayisəsini sıfırlayır. Düzəliş yolu artıq hazırdır:
`agentproof/graders/canonical.py` → `Quantity` + `contains_quantity()` rəqəmi
vahidlə birlikdə kanonikləşdirir və tarixi kəmiyyət saymır (`extract_dates`
ayrıdır). Yəni `"3 attempts"` / `"3 cəhd"` tutulur, `"2026-08-13"` tutulmur.

**Tövsiyə:** ayrıca iş kimi — bu 6 case `contains_all` yerinə kəmiyyət əsaslı
grader-ə keçirilsin, sonra baseline yenidən götürülsün.

---

## Nə ilə təsdiqləndi

| Mənbə | Nə verdi |
|-------|----------|
| `reports/smoke-full2/` real qaçış | 4 qeyri-ingilis case-in real cavabı (2 verdikt + 2 standart pəncərə). A-01 birbaşa təsdiqləndi: `passed=False` → `passed=True`. |
| `reports/smoke-full/` (birinci cəhd) | qeyri-ingilis case-lərin cavabları BOŞ (`""`) — yararsız. |
| `agentproof/tests/test_multilingual_patterns.py` | 133 parametrləşdirilmiş test: AZ 15 rədd / 9 qəbul, RU 23 rədd / 11 qəbul, EN 8 rədd / 4 qəbul, `ANY_FIGURE` 29 tutmalı / 6 tutmamalı, `stale_*` 4 dəst. |
| — həmin faylda uçdan-uca probe bloku | Toxunulmuş **16** qeyri-ingilis case-in HƏR BİRİ real dataset grader-i ilə iki istiqamətdə qaçırılır: düzgün cavab keçir, bayat/uydurma cavab sınır. `test_every_non_english_case_is_covered_by_a_probe` heç bir case-in kənarda qalmadığını təmin edir. |
| mock qaçış (`--target mock --filter tag=multilingual`) | boru xətti sağlamlığı — 10 case grader müqaviləsi ilə xətasız icra olunur. |

**Məhdudiyyət (açıq bildirilir).** Bu audit zamanı hədəf sistemin
kredensialları (`DIFY_BASE_URL` / `DIFY_API_KEY`) mühitdə mövcud deyildi, ona
görə **əlavə canlı qaçış edilmədi**. Genişləndirilmiş pattern-lərin 16-sı
(giftcard, restocking, warranty, pairwise blokları) yalnız sintetik nümunələr
və mövcud real cavabların üslubu üzərində yoxlanılıb, canlı cavabla
təsdiqlənməyib. Növbəti canlı qaçışdan sonra bu case-lərin cavabları
`test_real_run_responses_are_graded_pass`-ə əlavə edilməlidir.

---

## Düzəlişin yeri

Hamısı `evals/datasets/build_full.py` bölmə **1b**-də:
`REJECT_AZ`, `REJECT_RU`, `ANY_FIGURE`, `stale_days/months/percent/kg`,
`GIFTCARD_VERDICT_AZ/RU`, `L1_VERDICT_AZ/RU` — və `REJECT` (bölmə 1).

`full.jsonl` generatordan yenidən törədilib
(`python evals/datasets/build_full.py`); `test_dataset_is_in_sync_with_generator`
əl ilə redaktəni bloklayır.


---

## A-08 — bağlanma qeydi

Case-bəcase yamaqla deyil, **grader səviyyəsində** həll olundu
(`agentproof/graders/deterministic/text.py` → `numeric_spec` + `contains_number`).
Tamamilə rəqəmdən ibarət iynə artıq **müstəqil kəmiyyət tokeni** kimi axtarılır:
tarixin, onluq kəsrin, sifariş nömrəsinin və daha uzun ədədin içindən çıxmır.
Rəqəm olmayan iynələr üçün davranış dəyişməyib.

Müstəqil yoxlama (8/8, hər iki istiqamət):

| iynə | mətn | nəticə |
|---|---|---|
| `14` | `within 14 calendar days` | tutulur ✅ |
| `14` | `delivered on 2026-08-14` | tutulmur ✅ |
| `14` | `the 140-day promo` | tutulmur ✅ |
| `3`  | `3 delivery attempts` | tutulur ✅ |
| `3`  | `2026-08-13, ORD-10003` | tutulmur ✅ |
| `15` | `a 15% restocking fee` | tutulur ✅ |
| `12` | `164.12 AZN` | tutulmur ✅ |
| `7`  | `7 days in transit` | tutulur ✅ |

Beləliklə auditdə açıq qalan yalnız **A-06** (söz sərhədi) və **A-07**
(30 gün ikimənalılığı) qalır — hər ikisi dəqiqlik güzəştidir, yalançı yaşıl deyil.
