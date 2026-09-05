# PREAUDIT.md — ön-audit runbook

**Tapşırıq:** AP-054 · **Qayda mənbəyi:** [`site/rules.html`](../site/rules.html) ·
**Kod:** `agentproof/preaudit.py` · `evals/run.py --profile preaudit`

Ön-audit odur ki, bir şirkətin **açıq demo** agentini heç kim bizi işə
götürməmişdən əvvəl test edirik və tapdığımızı onlara göndəririk. Satış
hərəkəti budur; qaydalar isə onu spam-dan ayıran yeganə şeydir.

---

## 0. Qayda sənəddə deyil, kodda

Saytda yeddi qayda dərc olunub. Üçüncüsü rəqəm verir — «bir sessiya, ≤ 30
sorğu, insan sürəti» — və məhz o, məşğul bir gündə pozulmağa ən açıq olanıdır.
Ona görə həmin hədd `send_with_retry` içində saxlanır: büdcə bitəndə sorğu
**göndərilmir**, `HALT` qalxır, qalan case-lər `skipped` olur və qaçış 3 kodu
ilə bitir.

**Təkrarlar da sayılır.** Bir case üçün 3 cəhd edilirsə, hədəfin serveri 3
sorğu görür. «30 sorğu» vədini alan adam bizim daxili təsnifatımızı deyil, öz
loglarını sayır.

Test: `agentproof/tests/test_preaudit_budget.py`. Hasar söndürüləndə 3 test
sınır — yəni testlər sayğacı yox, sorğunun getmədiyini ölçür.

---

## 1. Başlamazdan əvvəl — dayandırıcı yoxlamalar

| Yoxlama | Keçmirsə |
|---|---|
| Demo **açıqdır** (hesab, açar, dəvət tələb etmir) | **DAYAN** — qayda 1 |
| Sənədləşdirilmiş API və ya lokal qaçan açıq mənbə var | Əl ilə yol — [`PREAUDIT-ENTRYPOINT.md`](PREAUDIT-ENTRYPOINT.md) §B |
| İstifadə şərtləri avtomatlaşdırılmış girişi qadağan etmir | Əl ilə test et, ya da **DAYAN** — qayda 2 |
| Şərtlər qeyri-müəyyəndir | Qadağan sayılır — **DAYAN** |
| Şirkət opt-out siyahısındadır | **DAYAN** |

Opt-out siyahısı: `docs/optout.txt` (boşdursa, heç kim istəməyib).

---

## 2. İki mərhələ — niyə belədir

30 sorğu ilə 12 case-i 3 dəfə qaçırmaq mümkün deyil (36 > 30). Amma buna
ehtiyac da yoxdur: **hər case-i deyil, yalnız sınanları təkrarlamaq lazımdır.**

| Mərhələ | Nə edir | Sorğu |
|---|---|---:|
| **1 — namizəd axtarışı** | 12 case, bir cəhd | 12 |
| **2 — təkrarlanma** | yalnız sınanlar, 2 əlavə cəhd | ≤ 18 |
| | | **≤ 30** |

Yəni mərhələ 2-də **9-a qədər** namizədi tam təkrarlaya bilirsən. Daha çoxu
sınıbsa büdcə səni dayandırır — və bu, düzgün nəticədir: onsuz da göndərmək
üçün kifayət qədər tapıntın var.

---

## 3. İcra

Büdcə **fayla** yazılır ki, iki çağırış onu bölüşsün. **Hər hədəf üçün ayrıca
fayl** — yoxsa bir şirkətin büdcəsi digərinə keçər.

```bash
TARGET=acme
mkdir -p preaudit/$TARGET
```

**Mərhələ 1 — namizədlər:**

```bash
.venv/bin/python evals/run.py \
  --target json_http --dataset evals/datasets/full.jsonl \
  --filter 'severity=high' --stage cheap --repeat 1 \
  --profile preaudit --budget-file preaudit/$TARGET/budget.json \
  --out preaudit/$TARGET/phase1
```

Profil özü qoyur: büdcə **30**, bağlantı **1**, sorğular arası **1 s**. Açıq
yazılmış bayraq həmişə üstün gəlir — profil heç vaxt sənin qərarını səssizcə
dəyişmir.

**Mərhələ 2 — yalnız sınanlar:**

```bash
.venv/bin/python evals/run.py \
  --target json_http --dataset evals/datasets/full.jsonl \
  --filter 'id=<sınan-1>|<sınan-2>|<sınan-3>' --repeat 2 \
  --profile preaudit --budget-file preaudit/$TARGET/budget.json \
  --out preaudit/$TARGET/phase2
```

> `--filter` sintaksisi: vergül **şərt** ayırıcısıdır, `|` isə **dəyər**
> ayırıcısı. `id=a,b,c` səssizcə bir case seçir — `id=a|b|c` yaz (AP-027).

**Təkrarlanma:**

```bash
.venv/bin/python evals/reproduce.py preaudit/$TARGET/phase2
```

Yalnız `stable-fail` səbətindəkilər — və yalnız **eyni səbəbdən** 3/3 sınanlar
— bir sətirlik hesabata düşür.

---

## 4. Büdcə bitəndə nə görünür

```
QAÇIŞ DAYANDIRILDI — preaudit_budget_exhausted: dərc olunmuş sorğu həddi
qorundu (site/rules.html §3) — bu, qüsur deyil, hasarın işləməsidir
```

Çıxış kodu **3**. Qalan case-lər `skipped`-dir, **yaşıl deyil** — false-green
mühafizəsi onsuz da bunu təmin edir.

Büdcəni artırmaq üçün `--request-budget` var, amma onu istifadə etmək dərc
olunmuş qaydanı pozmaq deməkdir. Yeni büdcə lazımdırsa, əvvəlcə şirkətdən
icazə al — sonra qaydalar səhifəsini də yenilə. **Sənəd praktikadan geri
qalmamalıdır**; LIM-I03 üç ay məhz buna görə səhv göründü.

---

## 5. Göndərmə

Bir səhifəlik: `docs/templates/PREAUDIT-ONEPAGER.md` (AP-057).
Məktub şablonu və izləmə faylı: AP-058.

**Tapıntı tapılmayıbsa GÖNDƏRMƏ.** Tapıntısız məktub — sadəcə soyuq
məktubdur, və bu planın bütün fərqi ona tapıntı əlavə etməkdədir.

Göndərəndən sonra qayda 7 işləyir: artefaktı **pulsuz** ver, şərtsiz.
