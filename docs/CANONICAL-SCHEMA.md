# CANONICAL-SCHEMA.md — həqiqət cədvəlinin sxemi

**Status:** qüvvədə · **Tapşırıq:** AP-033 · **Rol:** dataset-eng
**Kod:** `target/corpus/schema.py` · **JSON Schema:** `target/corpus/canonical.schema.json`
**Nümunə:** `target/corpus/CANONICAL.yaml` (Aurora Goods)
**Testlər:** `agentproof/tests/test_corpus_schema.py`

---

## 0. Bu sənəd nə üçündür

`CANONICAL.yaml` auditin **həqiqət cədvəlidir**: qiymətləndirici agentin cavabını
bu cədvəllə tutuşdurur, agentin tapdığı mətnlə YOX. Fərq bütün korpusun mövcudluq
səbəbidir — RAGAS tipli "faithfulness" ölçüsü cavabı **tapılan konteksdlə**
tutuşdurduğu üçün *bayat, amma sədaqətlə sitat gətirilmiş* cavab 1.0 alır və
yanlış olur (`docs/FAILURE-TAXONOMY.md` §10).

Bu sənədə qədər sxemin özü heç yerdə yazılmamışdı — o, `verify_fixtures.py`-nin
içindən oxunurdu. Müştəri korpusu qurmağa başlayan an "hansı sahələr məcburidir"
sualının cavabı Python oxumaqdan keçirdi, üstəlik həmin skript Aurora parametr
adlarını sabit kodladığı üçün başqa korpusda ümumiyyətlə qaçmırdı.

**İndi sxem üç formada, hamısı bir mənbədən:**

| Forma | Yer | Nə üçün |
|---|---|---|
| Sənədləşdirilmiş `FieldSpec` cədvəlləri | `target/corpus/schema.py` | Vahid həqiqət mənbəyi; sənəd və JSON Schema buradan doğur |
| JSON Schema 2020-12 | `target/corpus/canonical.schema.json` | Müştəri istənilən alətlə (CI, IDE, `jsonschema`) qaçırır |
| `validate()` | `target/corpus/schema.py` | JSON Schema-nın ifadə edə bilmədiyi **çarpaz istinad** qaydaları |

> **Vacib sərhəd.** JSON Schema yalnız **formanı** ifadə edir. "`superseded_index`
> mövcud parametrə baxırmı", "`precedence_rank` nərdivanda varmı", "`doc` reyestrdədirmi"
> kimi qaydalar JSON Schema-da yazıla bilmir. İkisi bir yerdə tam sxemdir —
> yalnız JSON Schema qaçırmaq yarım yoxlamadır.

### Qaçırmaq

```
python target/corpus/schema.py validate target/corpus/CANONICAL.yaml
python target/corpus/schema.py validate /yol/musteri/CANONICAL.yaml
python target/corpus/schema.py emit-json-schema        # JSON Schema-nı yenidən yaz
python target/corpus/schema.py fields                  # sahə cədvəlini çap et
```

`validate` çıxışı: qaçırılan assertion sayı, `WARN` sətirləri (exit 0-a mane olmur),
`error` sətirləri (exit 1). Hər tapıntının **kodu** var (`parameter.doc_registered`) —
CI-də konkret qaydaya görə süzmək üçün.

---

## 1. Sənəd nə DEYİL

* **Bu sxem müştəri sənədlərini təsvir etmir.** O, sənədlərdən **çıxarılmış**
  parametr cədvəlini təsvir edir. Çıxarış özü ayrı alətdir:
  `target/corpus/extract.py` (AP-034) — və o, yalnız **namizəd** təklif edir.
  Ölçülmüş recall və tapılmayanların səbəb bölgüsü: `target/corpus/EXTRACTION.md`.
* **Sxem doğruluğu yoxlamır.** `value: 14` sənəddə həqiqətən 14-dürmü — bunu
  maşın bilə bilməz; insan təsdiqləyir. Sxem yalnız cədvəlin **daxili
  ardıcıllığını** və **tamlığını** qoruyur.
* **Sxem Aurora bilmir.** `validate()` heç bir parametr adını sabit kodlamır.
  Aurora ilə heç bir ortaq adı olmayan korpus da təmiz keçir — bu, testlə
  qorunur (`test_validator_accepts_a_completely_different_corpus`).

---

## 2. Sənədin üst quruluşu

```yaml
meta:                     # məcburi — şirkət, valyuta, pinlənmiş tarix, sənəd reyestri
precedence_ladder:        # məcburi — ziddiyyətləri determinist həll edən pillələr
counting_rules:           # məcburi — "N gün" hardan sayılır
parameters:               # məcburi — həqiqət cədvəlinin özü
superseded_index:         # opsional — bayat dəyər tələləri
colliding_values:         # opsional — eyni rəqəmin fərqli mənaları
resolved_<kombinasiya>:   # opsional, təkrarlana bilər — öncədən həll olunmuş çox şərtli hallar
gaps:                     # opsional — CAVABI OLMAYAN suallar (uydurma ölçüsü)
temporal_applicability:   # opsional — hansı tarixdəki versiya hökm sürür
value_measurement:        # opsional — pul astanaları nəyin üzərindən ölçülür
```

`resolved_` prefiksi ilə başlayan istənilən ad qəbul edilir
(`resolved_return_windows`, `resolved_warranty_periods`, `resolved_loan_periods` …) —
domenə görə dəyişir, ona görə sxem onu prefikslə tanıyır, adla yox.

---

## 3. Sahə-sahə tərif

Cədvəllər `target/corpus/schema.py`-dəki `FieldSpec` tərifləridir.
**"Niyə lazımdır" sütunu bəzək deyil:** sahəni buraxmaq qərarı orada verilir.

#### `meta`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `company` | `string` | **məcburi** | Hesabatın kimə aid olduğunu göstərir; birdən çox müştəri korpusu eyni maşında qarışmasın deyə. |
| `corpus_version` | `string` | **məcburi** | Korpus dəyişdikdə baseline diff-in nəyə qarşı müqayisə etdiyi bilinsin — versiyasız korpusda reqressiya izah oluna bilmir. |
| `currency` | `string` | **məcburi** | Pul vahidli parametrlərin vahidi bununla tutuşdurulur; səhv valyuta astanası səssiz yanlış cavab verir. |
| `evaluation_reference_date` | `string` | **məcburi** | PİNLƏNMİŞ qiymətləndirmə saatı. Bu olmasa 'neçə gün keçib' sualının cavabı divar saatından asılı olur və eyni case sabah başqa nəticə verir — reproduksiya itir. |
| `timezone` | `string` | opsional | Gün sərhədi (`23:59`) hansı zonada bağlanır. Cut-off tipli parametrlərdə sərhəd testi bundan asılıdır. |
| `language` | `string` | opsional | Sənədlərin əsas dili — çoxdilli çıxarışda vahid seçimi. |
| `generated` | `string` | opsional | Cədvəlin yığıldığı tarix — auditin izi. |
| `documents` | `array<any>` | **məcburi** | Korpusun sənəd reyestri. Hər parametrin `doc` sahəsi bura baxır; reyestrsiz 'hansı versiya qüvvədədir' sualı cavabsızdır. |

#### `meta.documents[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `file` | `string` | **məcburi** | Sənəd faylının adı — parametrlərin `doc` sahəsi bununla eyni yazılır. |
| `id` | `string` | **məcburi** | Sabit sənəd kodu; fayl adı dəyişsə də istinad qırılmır. |
| `version` | `string` | **məcburi** | Qüvvədə olan versiya. Parametrin `doc_version` sahəsi bununla tutuşdurulur — uyğunsuzluq korpusun yarısının bayat olduğunu göstərir. |
| `effective_from` | `string` | **məcburi** | Bu versiyanın qüvvəyə mindiyi tarix. Temporal sual ('sifariş keçən il verilib') yalnız bununla cavablandırıla bilər. |
| `supersedes_version` | `string` | opsional | Əvəz olunan versiya — sənəd əlavəsindəki bayat bəndlərin hansı versiyaya aid olduğunu bağlayır. |

#### `parameters[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `id` | `string` | **məcburi** | Sabit maşın açarı. Bütün çarpaz istinadlar (`superseded_index`, `colliding_values`, `resolved_*`) buna baxır. |
| `name` | `string` | opsional | İnsan üçün ad — hesabatda göstərilir. |
| `value` | `string | number | integer | boolean | null | array` | **məcburi** | DOĞRU cavab. Qiymətləndirici agentin cavabını bununla tutuşdurur, agentin tapdığı mətnlə YOX — bütün korpusun mövcudluq səbəbi budur. İnterval dəyər siyahı kimi yazılır: `[4, 7]` = 4-7 vahid. |
| `unit` | `string` | **məcburi** | Vahid ailəsi. Vahidsiz `14` cavabı `14 gün`, `14 %` və `14 AZN` ilə eyni sayılardı — ölçmə mənasını itirərdi. |
| `status` | `any` | **məcburi** | `active` HƏQİQƏTİ, `superseded` TƏLƏNİ təyin edir. Bu sahə olmadan 'sədaqətlə sitat gətirilmiş bayat cavab' düzgün sayılır. |
| `doc` | `string` | **məcburi** | Dəyərin yaşadığı sənəd — `meta.documents[].file` ilə eyni. Retrieval lövbəri və auditorun yoxlaması bundan asılıdır. |
| `section` | `string` | **məcburi** | Bənd nömrəsi (`§2.1`). Auditorun bir dəqiqədə yoxlaya bilməsi üçün; həm də `doc#clause` lövbərinə çevrilir. |
| `doc_version` | `string` | **məcburi** | Dəyərin götürüldüyü sənəd versiyası. Sənəd yenilənəndə hansı parametrlərin yenidən oxunmalı olduğu yalnız bununla bilinir. |
| `applies_when` | `string` | **məcburi** | Dəyərin QÜVVƏDƏ OLDUĞU şərtlər — nəsr dilində, tam. Eyni rəqəm korpusda bir neçə yerdə olur; şərt yazılmasa 'hansı 14 gün' sualı cavabsız qalır və case şərt seçməsini deyil, sətir uyğunluğunu ölçür. |
| `effective_from` | `string` | opsional | Bu dəyərin qüvvəyə mindiyi tarix — versiyalar arası keçiddə hansı dəyərin tətbiq olunduğunu təyin edir. |
| `supersedes` | `object` | opsional | ƏVƏZ OLUNMUŞ dəyər. Bu blok olmadan bayat-bənd tələsi (korpusun ən dəyərli hissəsi) ümumiyyətlə qurula bilmir: agentin sənəd əlavəsindən tapdığı köhnə rəqəmin yanlış olduğunu maşın bilməz. |
| `boundary` | `object` | opsional | Sərhəd zondu. Astana parametrində səhvlərin böyük hissəsi off-by-one-dır; N-1/N/N+1 nöqtələri olmadan bu sinif ölçülmür. |
| `precedence_rank` | `integer` | opsional | `precedence_ladder`-dəki pillə. Bir neçə qayda eyni anda tətbiq olunanda hansının qazandığını determinist edir. |
| `basis` | `string` | opsional | Faiz/pul dəyərinin nəyin üzərindən hesablandığı. |
| `timezone` | `string` | opsional | Yalnız vaxt tipli dəyərlər üçün zona. |
| `note` | `string` | opsional | Auditor üçün qeyd — qiymətləndirməyə təsir etmir. |
| `anchor` | `string` | opsional | Retrieval gold lövbəri (`doc.md#2.1`), varsa. |
| `cross_reference` | `string | number | integer | boolean | null` | opsional | Digər sənədə istinad. |
| `derived_from` | `string | array` | opsional | Dəyər başqa parametrlərdən çıxırsa, mənbə `id`-ləri. Mənbə dəyişəndə hansı törəmə dəyərin yenidən hesablanacağını göstərir. |
| `derived_totals` | `object | array` | opsional | Hesablanmış cəmlər. |
| `version_governed_by` | `string` | opsional | Hansı tarixdəki versiyanın hökm sürdüyü (`temporal_applicability` qarşılığı). |

#### `parameters[].supersedes`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `value` | `string | number | integer | boolean | null | array` | **məcburi** | KÖHNƏ dəyər — sənəd əlavəsində hələ də yazılı olan rəqəm. Tələnin özü budur. |
| `doc_version` | `string` | **məcburi** | Köhnə dəyərin aid olduğu versiya — tələnin hansı mətn parçasından gəldiyini auditor yoxlaya bilsin. |
| `effective_until` | `string` | opsional | Köhnə dəyərin son qüvvədə olduğu gün. Temporal case-lər ('2025-də verilən sifariş') yalnız bununla qurulur. |
| `unit` | `string` | opsional | Köhnə dəyərin vahidi, aktivdən fərqlidirsə. |
| `note` | `string` | opsional | Köhnə dəyər rəqəm deyilsə (`əvvəllər limit yox idi`) izah burada. |

#### `parameters[].boundary`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `dimension` | `string` | **məcburi** | Sərhədin ölçüldüyü kəmiyyət — hansı girişi dəyişdiyimizi adlandırır, yoxsa nöqtələr şərhsiz rəqəmdir. |
| `points` | `array<any>` | **məcburi** | Ən azı 3 zond nöqtəsi (N-1, N, N+1) və ən azı 2 fərqli nəticə. Hamısı eyni nəticə verirsə bu sərhəd deyil — sınmayan testdir. |

#### `parameters[].boundary.points[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `value` | `string | number | integer | boolean | null | array` | **məcburi** | Zond nöqtəsinin girişi. |
| `expected` | `string | number | integer | boolean | null` | **məcburi** | Həmin girişdə gözlənilən nəticə. |

#### `precedence_ladder[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `rank` | `integer` | **məcburi** | Pillə nömrəsi; 1-dən başlayır və boşluqsuz artır. İlk uyğun pillə qazanır, aşağıdakılar heç qiymətləndirilmir. |
| `rule` | `string` | **məcburi** | Pillənin maşın adı — parametrlər buna istinad edir. |
| `source` | `string` | **məcburi** | Pillənin sənəddəki mənbəyi. Mənbəsiz nərdivan auditorun deyil, korpus müəllifinin fikridir. |

#### `counting_rules.<ad>`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `anchor` | `string` | **məcburi** | Saymanın başladığı hadisə (çatdırılma/sifariş/göndəriş tarixi). Eyni 14 gün fərqli lövbərdən sayılanda fərqli cavab verir — korpusun ən çox yayılan gizli ziddiyyəti budur. |
| `anchor_is_day` | `integer` | opsional | Lövbər günü 0-dırmı, 1-dirmi. |
| `inclusive_final_day` | `boolean` | opsional | Son gün daxildirmi. |
| `calendar_or_business` | `any` | opsional | Təqvim, yoxsa iş günü. Bu seçim 5 günlük pəncərəni 7 günə çevirir. |
| `closes_at` | `string` | opsional | Pəncərənin bağlandığı yerli vaxt. |
| `unit` | `string` | opsional | Saymanın vahidi (gün/ay). |
| `note` | `string` | opsional | İnsan üçün izah. |

#### `superseded_index[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `parameter` | `string` | **məcburi** | Tələnin bağlandığı aktiv parametrin `id`-si. Mövcud olmayan parametrə baxan tələ heç vaxt qiymətləndirilmir. |
| `stale_value` | `string | number | integer | boolean | null | array` | **məcburi** | Sənəddə hələ də yazılı olan köhnə dəyər. |
| `doc` | `string` | **məcburi** | Köhnə dəyərin oxunduğu sənəd. |
| `appendix` | `string` | opsional | Sənəd əlavəsindəki dəqiq yer. |
| `not_true_from` | `string` | opsional | Köhnə dəyərin yanlış olduğu ilk gün. |
| `unit` | `string` | opsional | Köhnə dəyərin vahidi. |
| `trap` | `string` | opsional | Tələ kodu — hesabatda case ilə bağlanır. |

#### `colliding_values[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `value` | `string | number | integer | boolean | null | array` | **məcburi** | Korpusda bir neçə mənası olan rəqəm. |
| `unit` | `string` | opsional | Ortaq vahid; mənalar fərqli vahiddədirsə `mixed`. |
| `meanings` | `array<any>` | **məcburi** | Həmin rəqəmin ən azı 2 fərqli mənası. Bir mənası olan rəqəm toqquşma deyil — case sətir uyğunluğu ilə keçərdi. |

#### `colliding_values[].meanings[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `parameter` | `string` | **məcburi** | Mənanın aid olduğu parametr `id`-si. |
| `status` | `string` | opsional | Bu mənanın aktiv, yoxsa bayat olduğu. |
| `correct_for` | `string` | opsional | Bu mənanın doğru olduğu şərt. |
| `unit` | `string` | opsional | Mənaya xas vahid (`unit: mixed` halında). |

#### `resolved_<kombinasiya>[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `id` | `string` | **məcburi** | Kombinasiyanın sabit kodu — fixture-lar buna istinad edir. |
| `deciding_parameter` | `string` | opsional | Kombinasiyanı həll edən parametr. İnsan mühakiməsi olmadan çox şərtli sualı qiymətləndirməyə imkan verən sahə budur. |
| `deciding_rank` | `integer` | opsional | Qazanan nərdivan pilləsi. |
| `note` | `string` | opsional | Nə üçün məhz bu pillənin qazandığı. |

#### `gaps[]`

| sahə | tip | | niyə lazımdır |
|---|---|---|---|
| `id` | `string` | **məcburi** | Boşluğun sabit kodu. |
| `topic` | `string` | **məcburi** | Korpusda CAVABI OLMAYAN mövzu. |
| `question_examples` | `array<string>` | **məcburi** | Boşluğu tetikləyən real suallar — uydurma (hallüsinasiya) yalnız konkret sual verildikdə ölçülə bilir. |
| `correct_behaviour` | `array<string>` | **məcburi** | Yeganə doğru davranışlar (məlumat yoxdur / insana ötür). Yazılmasa qiymətləndirici 'boş cavab'la 'düzgün imtina'nı ayıra bilmir. |
| `forbidden_in_answer` | `array<string>` | opsional | Cavabda görünsə uydurma sayılan şeylər. |
| `why_it_retrieves_something` | `string` | opsional | Boşluğun QONŞU məzmunu olduğunu göstərir — boş retrieval verən boşluq çox asandır və heç nə ölçmür. |
| `nearest_distractor` | `string` | opsional | Agentin yanlış ümumiləşdirə biləcəyi ən yaxın fakt. |

---

## 4. Tam nümunə — bir parametr

```yaml
- id: return_window_standard          # sabit maşın açarı; bütün istinadlar buna baxır
  name: Standard return window        # insan üçün ad
  value: 14                           # DOĞRU cavab
  unit: days                          # vahidsiz 14 mənasızdır
  status: active                      # `active` həqiqətdir, `superseded` tələdir
  effective_from: 2026-01-01
  supersedes:                         # TƏLƏ: sənəd əlavəsində hələ də yazılı olan rəqəm
    value: 30
    unit: days
    doc_version: "3.2"
    effective_until: 2025-12-31
  doc: returns-and-refunds.md         # meta.documents reyestrində olmalıdır
  section: "§2.1"                     # auditor bir dəqiqədə yoxlaya bilsin
  doc_version: "4.0"                  # reyestrdəki cari versiya ilə eyni olmalıdır
  applies_when: "domestic delivery; item not promotional, not clearance,
                 not non-returnable, not damaged-on-arrival; customer not
                 an Aurora Plus member"
  precedence_rank: 6                  # nərdivandakı pillə
  boundary:                           # off-by-one sinfini ölçən zond
    dimension: days_since_delivery
    points:
      - {value: 13, expected: eligible}
      - {value: 14, expected: eligible}      # son gün DAXİLDİR
      - {value: 15, expected: not_eligible}
```

### 4.1 `supersedes` — onsuz tələ yoxdur

Korpusun ən dəyərli hissəsi **bayat bənd tələsidir**: sənədin əlavəsində köhnə
rəqəm (`30 gün`) hələ də yazılıdır, retrieval onu tapır, agent onu sədaqətlə
sitat gətirir və **yanlış** cavab verir. `supersedes` bloku olmadan qiymətləndirici
bu cavabın yanlış olduğunu bilə bilməz — çünki agentin sitatı tapdığı mətnə uyğundur.

`supersedes` yazılmadıqda itən şey: `superseded_index`-dəki tələ ölçülməz olur.
Sxem bunu ayrıca kod ilə tutur — `superseded_index.parameter_has_supersedes`.

Köhnə dəyər rəqəm olmaya da bilər (`əvvəllər limit yox idi`). O halda
`value: null` + məcburi `note` yazılır (`supersedes.null_value_needs_note`).

### 4.2 `applies_when` — onsuz case şərt seçməsini ölçmür

Eyni rəqəm korpusda bir neçə yerdə olur. Aurora-da `14` ən azı **8** fərqli
şey deməkdir (standart qaytarma pəncərəsi, qiymət uyğunluğu pəncərəsi, üzvlük
haqqının tam qaytarılması, silinmə üçün güzəşt müddəti …). `applies_when`
yazılmasa "hansı 14 gün" sualı cavabsız qalır və case şərt seçməsini deyil,
**sətir uyğunluğunu** ölçər — yəni heç nə ölçməz.

Nəsr dilində, tam yazılır: `"domestic return; order total below 150.00 AZN;
customer-initiated"`. Qısaltma yox — auditor bunu sənədə qarşı oxuyur.

### 4.3 `boundary` — off-by-one sinfi başqa cür ölçülmür

Astana parametrlərində səhvlərin böyük hissəsi sərhəddədir: 14-cü gün daxildir,
15-ci yox. Üç nöqtə (N-1, N, N+1) və **ən azı iki fərqli nəticə** tələb olunur.
Hamısı eyni nəticə verirsə bu sərhəd deyil, sınmayan testdir —
`boundary.distinct_expected`.

`dimension` sahəsi nöqtələri adlandırır; onsuz `{value: 14}` şərhsiz rəqəmdir.

### 4.4 `effective_from` və `doc_version` — temporal suallar

"Keçən il verilmiş sifariş hansı pəncərəyə tabedir" sualı yalnız bu iki sahə
ilə cavablandırıla bilər. `doc_version` reyestrdəki cari versiyadan fərqlidirsə
sxem bunu xəta sayır (`parameter.doc_version_matches`) — parametr bayat sənəddən
oxunub deməkdir.

### 4.5 Sərhəd (astana) parametrlərinin forması

Astana parametri üç sahəni birlikdə tələb edir:

| Sahə | Rolu |
|---|---|
| `value` + `unit` | astananın özü (`150.00 AZN`) |
| `applies_when` | astananın **hansı ölçüyə** tətbiq olunduğu (`merchandise value`, `order total` deyil) |
| `boundary` | `149.99 / 150.00 / 150.01` zondları — "or more" mi, "above" mı |

`applies_when` içində ölçünün adı yazılmasa eyni astana iki fərqli cavab verir:
`150.00 AZN` çatdırılma haqqı daxil ölçülərsə sifariş keçir, mal dəyəri üzrə
ölçülərsə keçmir. Aurora korpusunda bu, ayrıca `value_measurement` bölməsi ilə
də bağlanıb.

---

## 5. Çarpaz istinad qaydaları (JSON Schema-da ifadə oluna bilməyənlər)

| Kod | Qayda | Səviyyə |
|---|---|---|
| `root.required_section` | `meta`, `parameters`, `precedence_ladder`, `counting_rules` var | xəta |
| `parameter.doc_registered` | `doc` → `meta.documents[].file` | xəta |
| `parameter.doc_version_matches` | `doc_version` = reyestrdəki cari versiya | xəta |
| `parameter.duplicate_id` | `id` təkrarlanmır | xəta |
| `parameter.precedence_rank_known` | `precedence_rank` → nərdivan pilləsi | xəta |
| `parameter.currency_matches_meta` | 3 hərfli valyuta vahidi = `meta.currency` | xəta |
| `parameter.value_type` | `value` skalyar və ya interval (`[4, 7]`) | xəta |
| `ladder.duplicate_rank`, `ladder.rank_gap` | pillələr `1..N`, boşluqsuz, təkrarsız | xəta |
| `superseded_index.parameter_known` | tələ mövcud parametrə baxır | xəta |
| `superseded_index.parameter_has_supersedes` | tələnin parametrində `supersedes` bloku var | xəta |
| `supersedes.value_differs` | köhnə dəyər aktivdən fərqlidir | xəta |
| `supersedes.null_value_needs_note` | `value: null` → `note` məcburi | xəta |
| `colliding.parameter_known`, `colliding.min_meanings` | toqquşmanın ən azı 2 tanınan mənası var | xəta |
| `resolved.deciding_parameter_known` | `deciding_parameter` → parametr cədvəli | **xəbərdarlıq** |
| `parameter.unknown_field`, `root.unknown_section` | sxemdə olmayan sahə | **xəbərdarlıq** |
| `parameter.section_format` | `§2.1` / `2.1` / `Appendix A.3` formasında | **xəbərdarlıq** |

Xəbərdarlıq exit kodunu dəyişmir — məqsədi işi bloklamaq deyil, gözdən qaçmasına
mane olmaqdır.

---

## 6. Bilinən sapmalar (referans korpusda)

Referans korpus **bir** xəbərdarlıq verir və bu gizlədilmir:

```
WARN resolved_return_windows[11]: `deciding_parameter` parametr cədvəlində
     yoxdur: non_returnable_category   [resolved.deciding_parameter_known]
```

`RC-12` kombinasiyasını parametr yox, nərdivan qaydası (`non_returnable_or_clearance`)
həll edir. Bu, real (kiçik) asılı istinaddır: fixture həmin case-i parametrə bağlaya
bilmir. Xəta səviyyəsinə qaldırılmadı, çünki bəzi kombinasiyanı doğrudan da qayda
həll edir; amma xəbərdarlıq qaldı ki, sayı artanda görünsün. Test bunu bir ədədə
sabitləyir (`test_aurora_has_exactly_one_known_warning`) — ikinci xəbərdarlıq
yaransa CI onu göstərir.

---

## 7. Yeni korpusa başlayanda — minimum

Sıra bilərəkdən bu cürdür: parametrlər tələlərdən əvvəl, tələlər fixture-lardan əvvəl.

1. **`meta`** — şirkət, valyuta, **pinlənmiş** `evaluation_reference_date`,
   bütün sənədlərin reyestri (fayl, id, versiya, `effective_from`).
   Pinlənmiş tarix olmadan "neçə gün keçib" sualının cavabı divar saatından
   asılı olur və eyni case sabah başqa nəticə verir.
2. **`counting_rules`** — hər pəncərə ailəsi üçün lövbər (`delivery_date`,
   `order_date`, `dispatch_date`), təqvim/iş günü, son gün daxildirmi.
   Eyni "14 gün" fərqli lövbərdən sayılanda fərqli cavab verir; bu, korpusların
   ən çox yayılan gizli ziddiyyətidir.
3. **`precedence_ladder`** — bir neçə qayda eyni anda tətbiq olunanda hansının
   qazandığı. Boşluqsuz `1..N`.
4. **`parameters`** — 7 məcburi sahə ilə. Namizədləri `extract.py` çıxarır,
   **insan təsdiqləyir**.
5. **`boundary`** — hər astana parametrinə. Bu, korpusun ölçmə gücünün
   böyük hissəsidir.
6. **`supersedes` + `superseded_index`** — sənəd əlavələrindəki köhnə rəqəmlər.
   Tələ qatı budur.
7. **`gaps`** — cavabı OLMAYAN suallar. Onsuz uydurma ölçülmür. Boşluq
   **qonşu məzmunlu** olmalıdır (retrieval boş qayıtmasın) — yoxsa case çox asandır.
8. **`resolved_*`** — çox şərtli halların öncədən həll olunmuş cavabı; insan
   mühakiməsi olmadan qiymətləndirməyə imkan verən sahə budur.

Hər addımdan sonra:

```
python target/corpus/schema.py validate <fayl>
```

---

## 8. İş bölgüsü — sxem qatı vs korpus qatı

| Fayl | Nə bilir | Yeni müştəridə |
|---|---|---|
| `target/corpus/schema.py` | heç bir domen adı bilmir | **dəyişmir** |
| `target/corpus/canonical.schema.json` | schema.py-dən generasiya olunur | **dəyişmir** |
| `target/corpus/CANONICAL.yaml` | Aurora həqiqəti | tam əvəz olunur |
| `target/corpus/verify_fixtures.py` | Aurora hesablamaları (`WINDOW_PARAM`, sifariş/zəmanət arifmetikası, `FIXTURES.yaml` cütü) | tam əvəz olunur |

`verify_fixtures.py` artıq sxem yoxlamasını **təkrarlamır** — onu `schema.py`-dən
alır və çıxışında iki qatın töhfəsini ayrıca göstərir:

```
schema assertions    : 2399  (schema.py, corpus-independent; legacy subset 807)
fixture assertions   : 531   (Aurora-specific, this file)
legacy assertions    : 1338  (the historical 1338 — must not shrink)
assertions run       : 2930
```

`legacy assertions` sətri qəsdən var: köçürmə zamanı assertion sayının azalması
korpusun səssizcə daha az yoxlanması deməkdir. Test bunu 1338-də sabitləyir
(`test_verify_fixtures_still_reports_the_full_legacy_count`).
