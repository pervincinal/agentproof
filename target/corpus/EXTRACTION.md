# EXTRACTION.md — parametr çıxarışının ÖLÇÜLMÜŞ nəticəsi

**Alət:** `target/corpus/extract.py` · **Tapşırıq:** AP-034 · **Rol:** dataset-eng
**Ölçmə:** Aurora Goods korpusu, 8 siyasət sənədi, 96 kanonik parametr
**Təkrarla:** `python target/corpus/extract.py score`
**Testlər:** `agentproof/tests/test_corpus_extract.py`

---

## 0. Bir cümlə ilə

Alət 96 kanonik parametrin **85-ni** (88.5%) düzgün sənəd və düzgün bənddə tapır;
158 namizədin **137-si** (86.7%) korpusun real məzmununa düşür. Qalan işi —
dəyərin doğruluğu, şərtləri və aktiv/bayat statusu — **insan** görür.

**Alət ground truth qurmur. Namizəd təklif edir.**

---

## 1. Nə üçün lazımdır

Auditin ən bahalı hissəsi müştərinin siyasət sənədlərindən parametr cədvəli
çıxarmaqdır. Aurora korpusundakı 96 parametr **tam əl ilə** yazıldı. Müştəri
üçün bu iş sıfırdan təkrarlanır və 14 günlük auditi ~25 günə çıxarır — yəni
birbaşa marjanı yeyir.

Tam avtomatlaşdırma **mümkün deyil**: `value: 14` sənəddə həqiqətən 14-dürmü,
hansı şərtlərdə qüvvədədir, aktivdirmi yoxsa bayatdır — bunları maşın təsdiq
edə bilməz. Ona görə alət nə iddia edir, onu edir: rəqəm+vahid cütlərini tapır,
hər birinin yanına **sənəddəki tam cümləni** qoyur və insanın qarşısına
təsdiq üçün çıxarır.

---

## 2. Ölçülmüş nəticə

```
sənəd                 : 8
namizəd               : 158
kanonik parametr      : 96
RECALL @doc           : 85/96 = 88.5%
RECALL @clause        : 85/96 = 88.5%
  aktiv parametrə düşən : 84  (53.2%)
  bayat (tələ) dəyərə   : 24
  sərhəd zond nöqtəsinə : 29
  FAYDALI PAY           : 137/158 = 86.7%   (qalan 21 namizədi auditor atır)
tapılmadı             : 11
```

**Rəqəmlərin oxunuşu.**

| Ölçü | Nə deməkdir |
|---|---|
| `RECALL @doc` | Kanonik parametrin dəyər+vahidi düzgün sənəddə tapıldı |
| `RECALL @clause` | Üstəlik düzgün **bənddə** tapıldı. Burada ikisi eynidir — yəni tapılan hər dəyər dərhal doğru bəndə düşüb, auditor axtarmır |
| `aktiv parametrə düşən` | Namizəd `parameters[]`-dəki bir dəyərə uyğun gəldi |
| `bayat (tələ) dəyərə` | Namizəd sənəd əlavəsindəki köhnə dəyərə düşdü — bu, korpusun **tələ qatıdır**, zibil deyil |
| `sərhəd zond nöqtəsinə` | Namizəd `boundary.points`-dəki zonda düşdü (`149.99`, `14:01`) — bunlar da korpusun real məzmunudur |
| `FAYDALI PAY` | Yuxarıdakı üçünün cəmi. Auditorun **atacağı** namizəd sayı: 21 |

`aktiv parametrə düşən` payını (53.2%) tək başına "dəqiqlik" kimi göstərmək
alətin faydasını olduğundan **az** göstərir: sərhəd nöqtələri və bayat dəyərlər
korpusun ən dəyərli hissəsidir və onları da əl ilə yazmaq lazım gəlirdi.

---

## 3. Nə qədəri hazır moduldan, nə qədəri yeni qatdan gəlir

Ablasiya — hər qatı söndürüb yenidən ölçdük:

| Konfiqurasiya | Recall | Namizəd |
|---|---|---|
| **Yalnız `agentproof/graders/canonical.py`** (mövcud motor, dəyişməz) | 71/96 = **74.0%** | 137 |
| \+ interval naxışı (`4-7 business days` → `[4, 7]`) | 79/96 = **82.3%** | 145 |
| \+ `kg` və saat (`14:00`) vahidləri | 83/96 = **86.5%** | 156 |
| \+ sayılan isimlər (`attempts`, `codes`, `characters`) | **85/96 = 88.5%** | 158 |

**Dürüstlük qeydi.** Son sətir (**+2 parametr**) Aurora korpusuna baxaraq
yazılıb — həmin üç vahid məhz bu korpusda olduğu üçün əlavə edildi. Yəni
88.5%-in **2 faiz bəndi bu korpusa uyğunlaşdırılmışdır**; yeni müştəridə
gözlənilən başlanğıc **~86%**, əsas hissəsi isə (74% → 86%) domendən asılı
olmayan qatlardan gəlir. Rəqəmi olduğu kimi yazırıq ki, ilk müştəridə
"84%-ə düşdü" sualı sürpriz olmasın.

Mövcud modullar **dəyişdirilmədi**: `graders/canonical.py`-nin vahid lüğəti
agent CAVABLARINI qiymətləndirmək üçün qurulub, onu genişləndirmək
qiymətləndirmə semantikasını dəyişərdi. Siyasət mətninə xas vahidlər
`extract.py`-də, ayrıca qatdadır.

---

## 4. Tapılmayan 11 parametr — səbəb bölgüsü

Bu cədvəl növbəti versiyanın **yol xəritəsidir**. Hər sətir əl ilə sənəddən
yoxlanıldı; təsnifat kanonik parametrin göstərdiyi **bəndin mətninə** baxır,
bütün sənədə yox (kiçik rəqəmlərdə — `0`, `1`, `3` — sənəd səviyyəli axtarış
təsadüfi sətir tapıb yanlış diaqnoz qoyurdu).

| Səbəb | Say | Parametrlər | Sənəddəki forma | Düzəlişin qiyməti |
|---|---|---|---|---|
| `zero_expressed_in_words` | 3 | `restocking_fee_sealed`, `plus_free_shipping_minimum`, `return_window_clearance` | "**No** restocking fee is charged", "with **no minimum order value**", "There is **no** return window" | Orta — inkarın hansı kəmiyyətə aid olduğunu tapmaq lazımdır; səhv bağlama yalan namizəd yaradır |
| `non_numeric` | 3 | `plus_prorated_refund_unit`, `intl_free_shipping_available`, `intl_cod_available` | "is **never free**", "is **not available**", `enum` dəyər | **Dizayn seçimi** — bunlar rəqəm deyil; bəli/xeyr və kateqoriya çıxarışı ayrı alətdir |
| `qualifier_between_number_and_unit` | 1 | `delivery_attempts` | "**3 delivery attempts**" | Ucuz — rəqəmlə vahid arasında bir sözə icazə |
| `unit_synonym_missing` | 1 | `recurring_retry_attempts` | "retried up to **3 times**" (cədvəldə vahid `attempts`) | Ucuz — sinonim lüğəti (`times` ↔ `attempts`) |
| `hyphenated_compound_modifier` | 1 | `erasure_grace_period_days` | "a **14-calendar-day** grace period" | Ucuz — defislə birləşmiş modifikator naxışı |
| `enumerated_list_value` | 1 | `instalment_terms_months` | "in **3, 6, or 12** monthly instalments" → `[3, 6, 12]` | Orta — vergüllü siyahını bir dəyər kimi yığmaq |
| `number_as_word` | 1 | `promo_codes_per_order` | "**One** promotional code per order" | Ucuz — söz-rəqəm artıq `graders`-də var, sayılan isimlə birləşdirmək qalıb |

**Yekun:** 11 tapılmayanın **4-ü ucuz** düzəlişlə tutulur (→ ~92%), **3-ü orta**
(→ ~95%), **3-ü isə prinsipial olaraq bu alətin işi deyil** (rəqəm deyil).
Praktiki tavan: **~95%**, qalan 5% həmişə insanın işidir.

---

## 5. Sərhəd — alət nə etmir

* **`parameters:` yazmır.** Çıxış açarı `parameter_candidates:`-dir. Fayl
  birbaşa CANONICAL.yaml kimi istifadə edilə bilməz — sxem validatoru onu
  rədd edir (testlə qorunur).
* **`CANONICAL.yaml` adlı fayla yazmaqdan imtina edir** (`write_draft` xəta atır).
* **`status`, `doc_version`, `applies_when` sahələrini BOŞ buraxır.** Bunlar
  insanın qərarıdır:
  * `status` — dəyər aktiv həqiqətdir, yoxsa əlavədəki tələ?
  * `applies_when` — hansı şərtlərdə qüvvədədir? Onsuz case şərt seçməsini
    deyil, sətir uyğunluğunu ölçür.
* **Namizədin doğruluğunu iddia etmir.** Hər namizədin `source.quote`
  sahəsində sənəddəki **tam cümlə** var; auditor bir baxışda təsdiqləyir və
  ya atır. İqtibası olmayan namizəd yoxdur (testlə qorunur).

Alət **məsləhətçi bayraqlar** qoyur, qərar vermir:

```yaml
source:
  quote: "Under v3.2 the standard return window was 30 calendar days from the delivery date."
  heading: "Appendix A — Superseded provisions (v3.2)"
  in_table: false
  in_appendix: true
  likely_superseded: true      # ← təklif, qərar deyil; insan `status`-u seçir
```

---

## 6. İstifadə

```bash
# qaralama çıxar (səkkiz sənəd)
python target/corpus/extract.py draft target/corpus/*.md --out candidates.draft.yaml

# recall-ı yenidən ölç
python target/corpus/extract.py score
python target/corpus/extract.py score --json extraction-report.json
```

Sonrakı iş ardıcıllığı `docs/CANONICAL-SCHEMA.md` §7-dədir: namizədlər →
insan təsdiqi → `applies_when` → `boundary` → `supersedes` → sxem validasiyası.

---

## 7. Əhatə dairəsindən kənar

**Giriş formatı yalnız Markdown-dır.** Confluence, PDF və HTML dəstəyi
BİLƏRƏKDƏN qurulmayıb: giriş formatı ilk müştəridən sonra dəqiqləşir və indi
üç parser saxlamaq üçüncüsü lazım olmadan borc yaradır. Bənd bölgüsü
`anchors.py`-dən gəldiyi üçün yeni format üçün yalnız "mətn + bənd nömrəsi"
qatını yazmaq lazım gələcək.
