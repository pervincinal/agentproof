# CONFLICTS.md — ziddiyyət aşkarlamasının ÖLÇÜLMÜŞ nəticəsi

**Alət:** `target/corpus/conflicts.py` · **Tapşırıq:** AP-035 · **Rol:** dataset-eng
**Ölçmə:** Aurora Goods korpusu, 8 siyasət sənədi, 158 parametr namizədi
**Təkrarla:** `python target/corpus/conflicts.py score`
**Testlər:** `agentproof/tests/test_corpus_conflicts.py`
**Aidiyyat:** `TRAPS.md` (§2.3 reyestr, §5 toqquşmalar), `EXTRACTION.md` (namizəd qatı)

---

## 0. Bir cümlə ilə

Alət `TRAPS.md`-də sənədləşmiş **25 rəqəmli bayat cütün 20-sini** (80%) və
**5 rəqəm toqquşması qrupunun 5-ni** (100%) tapır; tapılmayan 5 cütün heç biri
aşkarlama boşluğu deyil — hər beşində dəyər `extract.py` namizədlərinə
ümumiyyətlə düşmür. **Çıxarıla bilən 20 cütün 20-si tapılır.**

Bayat tərəfin təxmini **20 doğru, 0 səhv**. Yalançı müsbət **8/105 = 7.6%**.

**Alət həqiqət təyin etmir. Ziddiyyət namizədi təklif edir.**

---

## 1. Nə üçün lazımdır

`extract.py` "sənəddə hansı parametrlər var" sualına cavab verir. Auditin
satılan dəyəri isə növbəti sualdadır: **hansı parametrlər bir-biri ilə
toqquşur?** Müştəri "sizin sənədləriniz bir-birini inkar edir" cümləsini
eşitmək üçün pul verir.

Aurora korpusunda ziddiyyətləri **biz əkmişik** — `TRAPS.md` reyestri məhz
bunun etirafıdır, harada olduqlarını əvvəlcədən bilirdik. Müştəri korpusunda
isə onlar **təsadüfən** mövcuddur və hazırda tapmağın yeganə yolu sənədləri
əl ilə oxumaqdır. 3 sənəddən böyük korpusda bu, günlərlə işdir.

---

## 2. Üç hesabat

| # | Hesabat | Sual | Aurora-da hədəf |
|---|---|---|---|
| 1 | `same_concept_different_value` | eyni anlayışın iki fərqli dəyəri varmı? | `TRAPS.md §2.3` — 27 bayat cüt |
| 2 | `same_number_different_concept` | eyni rəqəm neçə fərqli qaydada işlənir? | `TRAPS.md §5` — 5 toqquşma qrupu |
| 3 | `version_chain` | versiya/tarix damğaları bir-birini təsdiqləyirmi? | zəncir qırığı |

**1 və 2 qəsdən AYRIDIR.** Eyni rəqəmin fərqli kontekstdə təkrarlanması
ziddiyyət **deyil**: 30 gün həm bayat standart pəncərədir, həm **canlı**
Aurora Plus pəncərəsidir (`TRAPS.md §5`). Onları bir hesabatda birləşdirmək
məhz `docs/GRADER-AUDIT.md#A-07`-də və `docs/LIMITATIONS.md#LIM-I02`-də
qeydə alınan yanılmadır — ölçmənin özünü korlayır. Ona görə hesabat 1 **yalnız
dəyəri fərqli** cütləri, hesabat 2 **yalnız dəyəri eyni** qrupları verir.

---

## 3. Necə işləyir

### 3.1. Anlayış imzası

Namizədin özündə parametr adı yoxdur (`extract.py` yalnız rəqəm+vahid tapır),
ona görə anlayış **cümlənin özündən** çıxarılır: iqtibasın sözləri (çəki 1.0),
**bəndin öz başlanğıc cümləsi** (0.80) və bölmə başlığı (0.35). Sözlərin
əhəmiyyəti korpusun **öz IDF-indən** gəlir — sabit "vacib sözlər" siyahısı
yazsaydıq, alət Aurora leksikonuna bağlanardı.

İki qat ölçüldü və hər ikisi lazım çıxdı:

| Qat | Recall (25 cütdən) |
|---|---|
| yalnız iqtibas + başlıq, şəkilçi kəsimi yoxdur | 15 |
| \+ bəndin öz başlanğıc cümləsi (`**A.1 Membership fee …**`) | ↑ |
| \+ nazik şəkilçi kəsimi (`orders`→`order`, `delivery`→`deliver`) | **20** |

Bəndin başlanğıc cümləsi kritikdir: əlavə bəndlərində anlayışın **adı** məhz
oradadır (`A.1 Membership fee`), rəqəm isə ikinci cümlədədir — yəni iqtibasda
anlayış adı **görünmür**.

### 3.2. Müddət vahidləri bir ailədir

`30 calendar days` ↔ `72 hours` (T-19) real ziddiyyətdir. Vahidə görə
ayırsaq itir, ona görə müddətlər müqayisə üçün günə çevrilir. Çevirmə **yalnız
müqayisə açarıdır** — çıxışda dəyərlər olduğu kimi qalır.

### 3.3. Bir bəndin içi ziddiyyət deyil

Sərhəd cədvəli məhz bir bənddə yan-yana `500.00` və `500.01` yazır. Eyni bənd
daxilindəki cütlər susdurulur (`--same-clause` ilə açılır): ölçüldü, yalançı
müsbətlərin çoxu oradan gəlirdi (329 → 239 cüt, FP 24 → 12).

### 3.4. Bayatlıq təxmini — QƏRAR DEYİL

Hər cüt üçün iki tərəfin **bayatlıq balı** hesablanır: əlavədə olmaq (+3),
`superseded` / `no longer in force` işarəsi (+3), `under v3.2` versiya damğası
(+2), `until` / `through` son tarixi (+2), indiki zaman olmadan keçmiş zaman
(+1). Bal fərqi ≥3 → `stale_confidence: high`.

**Ölçülmüş nəticə: 20 doğru, 0 səhv, 0 qərarsız.** Ən təhlükəli səhv — canlı
dəyəri "bayat" işarələmək — Aurora-da **heç vaxt baş vermir** və bu, testdə
sabitlənib (`test_stale_side_guess_never_points_at_the_live_value`).

Təxminin **yanında dəlil** var (`stale_evidence`), yəni auditor onu yoxlaya
bilir. Qərar auditorundur: çıxışın açarı `conflict_candidates:`-dir və fayl
`CANONICAL.yaml` adına yazıla **bilmir** (yoxlanılır).

---

## 4. Ölçülmüş nəticə

```
=== HESABAT 1 — bayat cüt aşkarlanması ===
reyestrdə bayat cüt   : 25   (TRAPS.md §2.3)
tapıldı               : 20
RECALL                : 20/25 = 80.0%
bayat tərəfin təxmini : doğru 20 · səhv 0 · qərarsız 0
təklif edilən cüt     : 105 (yüksək prioritet: 50)
  sıralamada           : @20: 14/20 · @30: 18/20 · @50: 20/20
  bayat cütə düşən      : 29
  iki AYRI parametr     : 51   (auditor işi — real fərq)
  YALANÇI MÜSBƏT        : 8    (7.6%) — eyni parametrin iki üzü
  xəritələnmədi         : 17

=== HESABAT 2 — rəqəm toqquşması ===
reyestrdə qrup        : 5    (TRAPS.md §5)
RECALL                : 5/5 = 100.0%
təklif edilən qrup    : 20
  həqiqi toqquşma       : 15
  YALANÇI MÜSBƏT        : 5

=== HESABAT 3 — versiya/tarix zənciri ===
problem               : 2  (superseded_cue_outside_appendix)
```

### 4.1. Məxrəc niyə 25-dir, 27 yox

`TRAPS.md §2.3` 27 sətir sadalayır. Onlardan ikisi (`intl_ddp_threshold`
"no DDP, always DDU" və `free_return_label_threshold` "free at any order
value") **rəqəmlə ifadə olunmayan** bayat dəyərdir — `supersedes.value`
ədəd deyil, ona görə rəqəm cütü kimi ölçülə bilməz. Məxrəc rəqəmli 25 cütdür;
27-ni məxrəc kimi göstərmək alətin ölçülmədiyi işi ölçülmüş kimi verərdi.

### 4.2. Tapılmayan 5 cüt — tavan aşkarlamada deyil, ÇIXARIŞDA

| Parametr | Bayat dəyər | Niyə namizədlərə düşmür |
|---|---|---|
| `store_credit_bonus_percent` | 0 percent | sıfır sözlə ifadə olunub (`EXTRACTION.md`: `zero_expressed_in_words`) |
| `warranty_plus_extension_months` | 0 months | eyni |
| `erasure_grace_period_days` | qrace period yoxdur | eyni + `hyphenated_compound_modifier` |
| `lockout_failed_attempts` | 3 attempts | rəqəm sözlə yazılıb (`number_as_word`) |
| `instalment_terms_months` | [3, 6] | siyahı dəyər (`enumerated_list_value`) |

Beşinin heç birində **hər iki tərəf** namizədlərdə yoxdur — yəni ziddiyyət
məntiqi onları görə bilməzdi. Bu, testdə yoxlanılır
(`test_missed_pairs_are_extraction_gaps_not_detection_gaps`).

**Şərti recall: çıxarıla bilən 20 cütdən 20-si = 100%.** Recall-ı artırmağın
yolu `conflicts.py` deyil, `extract.py`-nin sıfır/söz-rəqəm/siyahı boşluqlarını
bağlamaqdır (`EXTRACTION.md §4` yol xəritəsi).

### 4.3. Yalançı müsbətlər — nə sayılır və nə sayılmır

Yalançı müsbət **dar** tərif edilib: cütün hər iki tərəfi **eyni kanonik
parametrə** düşürsə, alət bir parametrin iki üzünü ziddiyyət sanmışdır.

8 belə cüt var və hamısı eyni naxışdadır:

```
cod_max_order_value  : 499.99 AZN (§2.2 sərhəd cədvəli) ↔ 300 AZN (Appendix A.1)
dispatch_cutoff_time : 13:59 (§2.2 sərhəd cədvəli)      ↔ 16:00 (Appendix A.1)
```

**Dürüstlük qeydi:** bunların bir hissəsi auditor üçün əslində **faydalıdır** —
sağ tərəfdə həqiqətən bayat dəyər var, sadəcə sol tərəf kanonik dəyər deyil,
sərhəd zond nöqtəsidir. Onları "faydalı" saymaq rəqəmi yaxşılaşdırardı; ona
görə **saymırıq**. 7.6% rəqəmi alətin ən pis oxunuşudur.

Qalan iki kateqoriya zibil deyil:
* **51 cüt — iki AYRI parametr.** Bunlar `TRAPS.md §4`-dəki "görünüşdə
  ziddiyyət" sinfidir (14 gün ↔ 30 gün Plus; 7 gün promo ↔ 21 gün beynəlxalq).
  Auditor onları `applies_when` şərti ilə ayırmalıdır — bu, **işin özüdür**,
  səhv deyil.
* **17 cüt — xəritələnmədi.** Kanonik cədvəldə qarşılığı olmayan dəyərlər
  (nümunə rəqəmləri, cədvəl xanaları).

### 4.4. Sıralama — auditor 105 sətrin hamısını oxumur

Cütlər `priority` (bir tərəfdə aydın versiya/tarix işarəsi var, digərində yox)
və oxşarlıq üzrə sıralanır. Ölçüldü: **tapılan 20 cütün hamısı ilk 50
sətirdədir**, 18-i ilk 30-da. Sıralamasız (yalnız oxşarlıq) eyni nəticə üçün
100 sətir oxumaq lazım gəlirdi.

### 4.5. Eşiyin süpürülməsi

| Eşik | Recall | Təklif edilən cüt | Yalançı müsbət | Ən pis sıra |
|---|---|---|---|---|
| 0.18 | 20/25 | 338 | 12 (3.6%) | 42 |
| 0.22 | 20/25 | 239 | 12 (5.0%) | 42 |
| 0.30 | 20/25 | 148 | 9 (6.1%) | 42 |
| **0.35** ← seçilən | **20/25** | **105** | **8 (7.6%)** | **42** |
| 0.40 | 20/25 | 81 | 8 (9.9%) | 39 |
| 0.45 | 17/25 | 57 | 7 (12.3%) | 28 |
| 0.50 | 13/25 | 40 | 6 (15.0%) | 20 |

Recall 0.18–0.40 aralığında **dəyişmir**; dəyişən yalnız auditorun oxuyacağı
sətir sayıdır. Uçurum 0.45-dədir. İş nöqtəsi ondan **bir addım aşağı** (0.35)
seçilib ki, yeni korpusda paylanma bir az sürüşsə də cüt itməsin.

**Dürüstlük qeydi.** Bu eşik Aurora-ya baxaraq seçilib. Yeni korpusda
`--threshold` ilə yenidən süpürülməlidir; alət bunu dəstəkləyir, amma rəqəm
korpusdan-korpusa köçürülə bilməz.

---

## 5. Hesabat 2 — rəqəm toqquşmaları

5 sənədləşmiş qrupun **5-i də** tapılır. Alət 20 qrup təklif edir; 15-i
avtomatik "həqiqi" sayılır (üzvləri ən azı iki fərqli kanonik parametrə
düşür), 5-i yalançı müsbət sayılır.

**Əl ilə baxıldı — 5-in 3-ü əslində həqiqi toqquşmadır:**

| Qrup | Məzmun | Qiymət |
|---|---|---|
| `100 AZN` | pulsuz göndərmə həddi ↔ **bayat** price match cap | həqiqi — auditor görməlidir |
| `18 months` | üçüncü tərəf brend zəmanəti ↔ **bayat** Aurora zəmanəti | həqiqi |
| `21 days` | Zone C çatdırılma müddəti ↔ beynəlxalq qaytarma pəncərəsi | həqiqi (vahid fərqi: business_day ↔ day) |
| `6` | 6 aylıq zəmanət uzatması ↔ 6 aylıq taksit ↔ 6 saatlıq izləmə | zəif — çox ümumi rəqəm |
| `4` | Zone 2 çatdırılma ↔ 4 saatlıq skan | zəif |

Yəni **avtomatik ölçü alətin əleyhinə səhv edir**. Rəqəmi düzəltmirik:
avtomatik təsnifat nə deyirsə, o yazılır.

**Ən dəyərli çıxış — `cross_unit` bayrağı.** `30` qrupu `day / kg / minute /
month / percent` vahidlərini bir yerə yığır: `TRAPS.md §5`-dəki ən təhlükəli
qarışıqlıq (30 gün ↔ 30.0 kg) məhz belə görünür.

---

## 6. Hesabat 3 — versiya/tarix zənciri

Yoxlanan altı qırıq növü:

| Kod | Nə deyir |
|---|---|
| `appendix_version_mismatch` | əlavə `(v3.2)` deyir, sənəd `Supersedes: v3.1` deyir |
| `appendix_version_unstamped` | əlavədə versiya damğası yoxdur — hansı dövrü idarə etdiyi bilinmir |
| `supersedes_window_gap` | əvvəlki versiya 2025-11-30-da bitir, cari 2026-01-01-də başlayır → 31 günlük boşluq |
| `clause_superseded_date_mismatch` | bənd `superseded 2026-02-15` deyir, sənəd `Effective from 2026-01-01` |
| `clause_version_unknown` | bənd `under v2.9`-a istinad edir; sənəd yalnız v4.0 və v3.2-ni tanıyır |
| `superseded_cue_outside_appendix` | əsas mətndə bayatlıq işarəsi var — bənd hələ qüvvədədirmi? |
| `appendix_clause_undated` | əlavə bəndində nə tarix, nə versiya var |

**Aurora-da zəncir bütövdür** (yalnız 2 `superseded_cue_outside_appendix`
xəbərdarlığı — hər ikisi sənədin öz keçid bəndidir). Bu, alətin işlədiyini
sübut etmir, ona görə hər qırıq növü **süni mutasiya** ilə testdə yoxlanılır
(`test_chain_break_is_detected`): korpusun surətində bir sətir dəyişdirilir və
uyğun kodun çıxdığı təsdiqlənir. Təmiz surətdə isə **sıfır** problem çıxır.

---

## 7. Alətin sərhədləri (nə edə bilmir)

1. **Semantik ad çıxarmır.** İki cümlə eyni anlayışdan danışırsa amma **heç bir
   ortaq söz** işlətmirsə (`cut-off` ↔ `deadline for same-day dispatch`), alət
   onları bağlaya bilmir. IDF+şəkilçi qatı sinonimi əvəz etmir.
2. **Yalnız rəqəmli parametrlər.** Sözlə ifadə olunan qaydalar (`no grace
   period`, `always DDU`) `extract.py`-də namizəd olmadığı üçün buraya da
   çatmır — 25/27 məxrəcinin səbəbi budur.
3. **Yalnız Markdown.** PDF/DOCX üçün əvvəlcə mətnə çevirmə lazımdır; real
   müştəri sənədləri çox vaxt PDF-dir.
4. **Eşik korpusa köklənir.** §4.5-dəki 0.35 Aurora rəqəmidir.
5. **Ziddiyyəti HƏLL ETMİR.** `TRAPS.md §4`-dəki 9 "görünüşdə ziddiyyət"
   əslində şərti qaydadır və düzgün cavab üstünlük nərdivanındandır. Alət
   onları da namizəd kimi verir — çünki maşın hansının şərt, hansının səhv
   olduğunu ayıra bilmir. **Bu ayrımı auditor edir.**

---

## 8. İstifadə

```bash
python target/corpus/conflicts.py report                       # Aurora, konsola
python target/corpus/conflicts.py report target/corpus-library # başqa korpus
python target/corpus/conflicts.py report --out conflicts.draft.yaml
python target/corpus/conflicts.py report --threshold 0.30 --limit 20
python target/corpus/conflicts.py score                        # TRAPS-a qarşı ölçü
```

Çıxış YAML-ın açarı `conflict_candidates:`-dir və hər namizədin **hər iki
tərəfi üçün** sənəddəki tam cümlə `quote` sahəsindədir — auditor bir baxışda
təsdiqləyir və ya atır.
