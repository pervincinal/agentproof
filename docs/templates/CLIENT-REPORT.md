<!--
=======================================================================
  MÜŞTƏRİ HESABATI — ŞABLON
  Mənbə skeleti: bu skelet real bir auditdən (bax EXAMPLE-client-report.md)
  çıxarılıb. Hər bölmə bir səbəblə var; səbəbi bölmənin başında yazılıb.

  DOLDURMA QAYDASI
  ----------------
  {{ikiqat mötərizə}}   → doldurulacaq yer. Doldurulmamış qalmamalıdır.
  [ÖLÇÜLDÜ]             → rəqəm artefaktdan gəlir; artefakt yolu yazılır.
  [NAMƏLUM]             → ölçülməyib. Sıfır YOX, «təxminən» YOX — NAMƏLUM.
  <!-- İZAH: ... -->    → yazana təlimat. YEKUN SƏNƏDDƏ SİLİNİR.

  ÜÇ POZULMAZ QAYDA
  -----------------
  1. Reproduksiya qapısından keçməyən heç nə tapıntı deyil.
  2. Kalibrasiya olunmamış LLM-judge nəticəsi dərc olunmur.
  3. Ölçülməyən heç nə «təxminən» ilə doldurulmur.

  MƏCBURİ BÖLMƏLƏR: §4 və §8. Səbəbi hər ikisinin başında yazılıb.
  Məlumat yoxdursa bölmə SİLİNMİR — başlıq qalır, içi xəbərdarlığa çevrilir.
=======================================================================
-->

# {{Müştəri sistemi}} — etibarlılıq auditi

| | |
|---|---|
| **Sifarişçi** | {{şirkət}} |
| **Sınanan sistem** | {{sistem adı və versiyası}} |
| **Qaçış** | `{{qaçış qovluğu}}` · `run_id = {{run_id}}` · {{ISO tarix}} |
| **Oxucu** | {{applied-AI lead / CTO / platforma komandası}} |
| **Hesabat versiyası** | {{v1}} · {{tarix}} |
| **Düzəliş qeydi** | {{yoxdur / §12}} |

<!-- İZAH: `run_id` və qovluq adı hesabatın hər rəqəminin geri izlənə bilməsi
     üçündür. Onları çıxarmaq hesabatı yoxlanılmaz edir — çıxarılmır. -->

---

## 1. Xülasə

> **Bu bölmə niyə var.** Oxucu qərar üçün oxuyur, arxiv üçün yox: bir səhifədən
> sonra nə tapıldığını, nə qədər etibarlı olduğunu və növbəti addımın nə
> olduğunu bilməlidir.
> **Bura NƏ YAZILMIR:** metodologiya təfərrüatı (§2), tapıntıların izahı (§3),
> tövsiyə siyahısı (§10). Xülasə *nəticə* verir, *arqument* qurmur. Burada
> §2–§9-da müdafiə olunmayan heç bir cümlə görünə bilməz.

{{2–3 abzas. Birinci cümlə konkret olsun: neçə case, neçə təkrar, nə tapıldı.
Ümumi giriş cümləsi («AI sistemləri getdikcə daha çox…») yazılmır.}}

{{ƏN VACİB CÜMLƏ: xam keçid rəqəmi ilə auditdən keçmiş rəqəm arasındakı fərq.
Xam rəqəm tək başına heç nə demir və hesabat bunu birinci abzasda deməlidir.}}

| Ölçü | Dəyər | Mənbə |
|---|---:|---|
| Test case | **{{N}}** | `{{artefakt yolu}}` |
| Təkrar sayı (seed) | **{{N}}** | `{{yol}}` |
| Qiymətləndirilmiş cavab | **{{N × təkrar}}** | — |
| Xam keçid | **{{N}} / {{N}} = {{%}}** | `{{yol}}` |
| Stabil keçid ({{k}}/{{k}}) | **{{N}}** | `{{yol}}` |
| Stabil uğursuzluq ({{k}}/{{k}}, eyni səbəb) | **{{N}}** | `{{yol}}` |
| Flaky | **{{N}} → {{%}}** (hədd {{%}}, {{ALARM / normal}}) | `{{yol}}` |
| Əl ilə oxunan uğursuzluğun təsnifatı | **{{N}} real · {{N}} ölçmə boşluğu · {{N}} ikimənalı** | §4 |
| Auditin üzə çıxardığı yalançı yaşıl | **{{N}}** | §4 |
| **Dərc olunan tapıntı** | **{{N}}** | §3 |
| Judge kalibrasiyası | uyğunluq **{{%}}**, κ = **{{}}**, n = {{}} | §7 |
| Qaçış xərci | **${{}}** ({{qiymət rejimi və tarix}}) | `{{yol}}` |
| Gecikmə | p50 **{{}} s** · p95 **{{}} s** | `{{yol}}` |

{{1 abzas: tapıntılar arasındakı əlaqə — hansıları eyni kökdən çıxır. Bu abzas
müştəriyə neçə AYRI problemi olduğunu deyir, neçə simptomu olduğunu yox.}}

> **Nə DEYİLƏ BİLMƏZ.** {{Bu rəqəmlərin hansı konfiqurasiya / model / korpus
> üçün etibarlı olduğu; hansı ekstrapolyasiyanın qadağan olduğu. Səbəblər §8.}}

---

## 2. Metodologiya

> **Bu bölmə niyə var.** Hesabatın hər rəqəmi burada təsvir olunan qurğunun
> məhsuludur; qurğu dəyişəndə rəqəmlər də dəyişir. Müştərinin mühəndisi bu
> bölməni oxuyub qaçışı **özü təkrarlaya bilməlidir**.
> **Bura NƏ YAZILMIR:** nəticə və şərh. Metodologiya nəyin necə ölçüldüyünü
> yazır, nəyin tapıldığını yox.

### 2.1 Sınanan sistem (SUT)

| Komponent | Dəyər | Qeyd |
|---|---|---|
| Platforma | **{{ad və dəqiq versiya}}** | {{harada işləyir}} |
| Tətbiq tipi | {{app tipi / endpoint}} | {{}} |
| Model (SUT) | **{{model}}** · {{sampling / thinking parametrləri}} | {{model yoxlaması: match?}} |
| Embedder | **{{}}** | {{seçim səbəbi — aşağıda}} |
| Retrieval | {{metod}}, **`top_k = {{}}`**, rerank {{}}, threshold {{}} | {{sənəddən yox, CANLI sistemdən təsdiqləndi?}} |
| Tool / backend qatı | {{real / mock, neçə tool, saat pinlənib?}} | {{}} |
| Təkrar | **{{k}} seed** · izolyasiya: {{case-lər arası reset varmı}} | {{}} |
| Qiymət rejimi | **{{tarix}} · ${{giriş}} / ${{çıxış}} per 1M token** | {{cədvəl mənbəyi}} |

**Niyə {{embedder}}.** {{Seçimin səbəbi + seçimin nəticəyə təsiri. Əgər seçim
məcburiyyət idisə, bunu yazın: gizlətmək ən tez tutulan şeydir.}}

**Niyə `top_k = {{}}`.** {{Tədqiqat sualı nədir və bu dəyər onu necə xidmət edir.
Əgər dəyər sistemin defaultundan fərqlidirsə, bu, nəticəni ŞİŞİRDİR və §8-də
qeyd olunmalıdır.}}

### 2.2 Korpus və ground truth

{{Korpusun mənşəyi: müştərinin öz sənədləri / süni / qarışıq. Neçə sənəd, neçə
kanonik parametr, neçə tələ, neçə fixture. Ground truth-un NƏ OLDUĞU: cavab
nəyə qarşı yoxlanır?}}

- **Üstünlüyü:** {{obyektiv ground truth — cavab kanonik dəyərə qarşı yoxlanır,
  yalnız retrieved kontekstə qarşı yox}}
- **Zəifliyi:** {{korpus real istehsalat kataloqundan necə fərqlənir}}

<!-- İZAH: Bu iki bənd cüt yazılır. Yalnız üstünlüyü yazan hesabat satış
     materialıdır, audit deyil. -->

### 2.3 Reproduksiya qapısı

{{Qeyri-determinizmin nə üçün konfiqurasiya ilə söndürülə bilmədiyi (seed yoxdur
/ sampling rədd edilir / ...). Ona görə hər case {{k}} dəfə qaçırılır.}}

| Səbət | Meyar | Dərc oluna bilər? |
|---|---|---|
| `stable-pass` | {{k}}/{{k}} keçdi | — |
| **`stable-fail`** | **{{k}}/{{k}} sındı, eyni səbəblə** | **BƏLİ — yalnız bunlar** |
| `flaky` | 1–{{k-1}}/{{k}} keçdi | xeyr (§9) |
| `unstable-fail` | 0/{{k}}, lakin səbəblər fərqli | xeyr (§9) |

**Qayda:** {{reproduksiya qapısından keçməyən heç nə tapıntı deyil. Bu hesabatda
qapıdan keçən N case var; hər birinin bütün cavab mətnləri ƏL İLƏ oxunub və hər
təsnifat cavabdan BİRBAŞA SİTATLA müdafiə olunub.}}

{{İstisna varsa açıq yazılır: hansı tapıntı qapıdan SONRA tapılıb və onun
reproduksiya statusu necə ölçülüb.}}

---

## 3. Təsdiqlənmiş tapıntılar

> **Bu bölmə niyə var.** Auditin əsas məhsulu budur: reproduksiya olunan,
> sitatla müdafiə olunan uğursuzluqlar.
> **Bura NƏ YAZILMIR:** bir dəfə görünüb təkrarlanmayan hallar (§9), ölçmə
> alətinin öz səhvləri (§4), quraşdırma mərhələsindəki müşahidələr (§6),
> düzəliş planı (§10 — burada yalnız qısa «təklif olunan istiqamət» olur).

<!-- İZAH: Tapıntılar KÖK SƏBƏBƏ görə birləşdirilir, case sayına görə yox.
     Eyni mexanizmdən çıxan 3 case = 1 tapıntı, 3 müstəqil reproduksiya.
     Şişirdilmiş tapıntı sayı hesabatın etibarını ilk kəsən şeydir. -->

**Ümumi reproduksiya mühiti:** {{endpoint, app id, model, tool saatı}}

### F-{{n}} — {{tapıntının bir cümlə ilə ifadəsi (davranış, ittiham deyil)}}

| Sahə | Dəyər |
|---|---|
| **Uğursuzluq rejimi** | {{taksonomiya kodu və adı}} |
| **Ciddilik** | **{{HIGH / MEDIUM / LOW}}** |
| **Case-lər** | `{{case id}}` · `{{case id}}` |
| **Reproduksiya** | **{{k}}/{{k}}** {{× neçə müstəqil case, hansı dillərdə}} |

**Kanonik dəyər.** {{Ground truth nədir və harada yazılıb — fayl + bənd.}}

**Sistem promptu / qayda** (əgər aidiyyatı varsa): {{sitat}}

**Sorğu:**
```
{{istifadəçi sorğusunun tam mətni}}
```

**Agentin cavabından sitat** (`{{case id}}`, {{cəhd №}}):

> {{birbaşa sitat — parafraz YOX}}

**Gözlənilən davranış.** {{nə olmalı idi + hansı tool çağırılmalı idi}}

**Niyə bu, {{sadəcə ehtiyatlı cavab / kiçik dəqiqlik məsələsi}} deyil.**
{{Mexanizmin izahı. Oxucu bunu ÖZ sistemində tanımalıdır — bu abzas hesabatın
ən çox oxunan hissəsidir.}}

**Biznes təsiri.** {{Konkret zərər. Ümumi «keyfiyyət aşağı düşür» yazılmır.}}

**Təklif olunan istiqamət.** {{1–2 cümlə. Tam düzəliş planı §10-dadır — burada
təkrarlanmır, yalnız istinad edilir: «icra detalları §10, D-{{n}}».}}

---

<!-- İZAH: Hər tapıntı üçün eyni bloku təkrarlayın. Boş sahə buraxmayın:
     «Reproduksiya» sahəsi doldurulmayan tapıntı dərc olunmur. -->

---

## 4. Ölçmənin öz auditi  ⛔ **MƏCBURİ BÖLMƏ**

> **Bu bölmə niyə MƏCBURİDİR.** Auditin satdığı şey tapıntı siyahısı deyil —
> **tapıntıların doğru olmasıdır**. Bu bölmə oxucuya göstərir ki, biz öz
> alətimizin harada yanıldığını da ölçdük. Onsuz oxucunun əlində yoxlanılmamış
> bir siyahı qalır və o siyahının nə qədərinin real olduğu bilinmir. Praktikada
> bu bölmə hesabatın ən çox sitat gətirilən hissəsidir: müştərinin mühəndisi
> «bu adamlar özlərini də yoxlayıblar» qənaətinə məhz burada gəlir.
>
> **Kəsmək istəyi gələcək — kəsilmir.** Bu bölmə hesabatın öz zəifliyini
> göstərir və ona görə satış sənədində ilk hədəf olur. Amma zəiflik burada
> **etibar mənbəyidir**: yalançı müsbət tapıntı buraxılmış tapıntıdan pisdir və
> oxucu bunu bilir.
>
> **Məlumat yoxdursa bölmə SİLİNMİR.** Başlıq qalır, içi xəbərdarlığa çevrilir:
> *«Ölçmə aləti auditdən keçirilməyib — bu hesabatdakı tapıntıların hansı
> hissəsinin grader artefaktı olduğu NAMƏLUMDUR.»* Eyni qayda HTML hesabatda
> maşınla tətbiq olunur (baseline yoxdursa bölmə xəbərdarlıq qutusuna çevrilir,
> yox olmur).
>
> **Bura NƏ YAZILMIR:** hədəf sistemin qüsurları (§3, §6). Ölçmə alətinin
> səhvini hədəfin səhvi kimi göstərmək uydurma tapıntıdır; ikisinin qarışması
> bütün hesabatı etibarsızlaşdırır.

{{1 abzas: nə edildi. «N stabil uğursuzluğun hər cavab mətni əl ilə oxundu və
kanonik həqiqətlə tutuşduruldu.»}}

| Təsnifat | Say | Pay | Mənası |
|---|---:|---:|---|
| **REAL** | **{{N}}** | {{%}} | agent həqiqətən səhv etdi (§3) |
| **ÖLÇMƏ BOŞLUĞU** | **{{N}}** | {{%}} | cavab düzgün idi, **assertion səhv idi** |
| **İKİMƏNALI** | **{{N}}** | {{%}} | cavab qismən düzgün / sual natamam |
| **CƏMİ** | **{{N}}** | 100% | |

{{Yalançı yaşıl sayı: ölçmənin düzgün cavab kimi saydığı REAL uğursuzluqlar.
Bunlar auditsiz heç vaxt görünməzdi.}}

### 4.1 Nümunə 1 — `{{case id}}`: {{nə baş verdi}}

{{Bir tam açılış: assertion nə axtarırdı, cavab nə idi, niyə assertion yanıldı.
Ən azı BİR nümunə tam açılmalıdır — cədvəl inandırıcı deyil, nümunə inandırıcıdır.}}

### 4.2 Nümunə 2 — `{{case id}}`: {{nə baş verdi}}

{{İkinci nümunə — mümkünsə əks istiqamətdə: biri yalançı QIRMIZI, biri yalançı
YAŞIL. İkisi eyni istiqamətdəsə oxucu «bunlar yalnız bir tip səhv axtarıblar»
deyə bilər.}}

### 4.3 Düzəlişin ölçülmüş təsiri

{{Assertion düzəldildikdən sonra nə dəyişdi. Bu, yeni qaçış deyilsə açıq yazın:
«eyni cavab mətnləri, yeni assertion-lar — offline yenidən qiymətləndirmə».}}

| Nəticə | Say | Nümunə |
|---|---:|---|
| Saxta uğursuzluq aradan qalxdı | **{{N}}** | `{{case id}}` |
| **Yalançı yaşıl üzə çıxdı** | **{{N}}** | `{{case id}}` |
| Səbəb düzəldildi (nəticə eyni, izah düz) | **{{N}}** | `{{case id}}` |
| Offline etibarsız (yalnız canlı qaçış hökm verir) | **{{N}}** | `{{case id}}` |

### 4.4 Nəticə

{{Bir cümlə + rəqəm: auditsiz dərc olunsaydı dəqiqlik nə olardı.}}

{{Qalıq risklər: auditdə BAĞLANMAYAN bəndlər. Bunlar yazılmasa audit yarımçıqdır.}}

---

## 5. Qeyri-determinizm

> **Bu bölmə niyə var.** Eyni giriş eyni çıxışı vermirsə, tək qaçışlı hər
> ölçü — daxili dashboard-lar daxil — yanıldıcıdır. Müştərinin öz metrikləri
> bu bölmədən sonra fərqli oxunur.
> **Bura NƏ YAZILMIR:** flaky case-lərin siyahısı (§9). Burada yalnız ölçü və
> onun mənası var.

| Ölçü | Dəyər |
|---|---|
| Flaky | **{{N}} / {{N}} = {{%}}** — hədd {{%}}, {{alarm?}} |
| {{əlavə sabitlik ölçüləri}} | {{}} |

{{Nə demək olduğu: bu nisbət N-dən yuxarıdırsa, tək qaçışa əsaslanan hər
müqayisə (A/B, reqressiya, «düzəliş işlədi?») etibarsızdır.}}

---

## 6. Əməliyyat tapıntıları (quraşdırma və konfiqurasiya)

> **Bu bölmə niyə var.** Bu tapıntılar agentin cavab keyfiyyəti ilə bağlı deyil,
> amma müştərinin komandasına dərhal lazımdır: səssiz defaultlar, yanıldıcı
> diaqnostika, yanlış xərc hesabatı. Praktikada bunlar hesabatın ən tez tətbiq
> olunan hissəsidir, çünki düzəlişləri ucuzdur.
> **Bura NƏ YAZILMIR:** model davranışı (§3). Bura konfiqurasiya və platforma
> müşahidələri gedir.

### OPS-{{n}} — {{bir cümlə ilə}}

- **Sistem / yer.** {{versiya + fayl:sətir və ya konfiqurasiya yolu}}
- **Müşahidə.** {{nə göründü}}
- **Niyə əhəmiyyətlidir.** {{nəticəsi}}
- **Ədalətli qeyd.** {{platformanın bu məsələdə nəyi DÜZGÜN etdiyi — varsa}}
- **Tətbiq edilən / təklif olunan həll.** {{}}
- **Təsir.** {{yüksək / orta / aşağı}}

<!-- İZAH: «Ədalətli qeyd» sətri təsadüfi deyil. Yalnız qüsur sadalayan
     əməliyyat bölməsi hesabatı hücum sənədinə çevirir və ton etibarı yeyir. -->

---

## 7. Judge qatı və onun kalibrasiyası

> **Bu bölmə niyə var.** LLM-judge işlədilibsə, oxucu onun nə qədər etibarlı
> olduğunu bilmək hüququna malikdir. Kalibrasiya rəqəmi olmadan judge verdikti
> heç nədir.
> **Bura NƏ YAZILMIR:** judge-a ehtiyac olmayan case-lər. Determinist ölçü ilə
> həll olunan iş judge-a verilmir.
>
> **Şərti məcburiyyət:** judge İŞLƏDİLİBSƏ bu bölmə məcburidir və kalibrasiya
> rəqəmi olmadan judge nəticəsi **dərc olunmur**. Judge işlədilməyibsə bölmə
> bir sətrə yığılır: *«LLM-judge istifadə edilmədi; bütün qiymətləndirmə
> determinist assertion-larla aparıldı.»*

| Ölçü | Dəyər | Hədd | Nəticə |
|---|---:|---:|---|
| İnsan etiketi ilə uyğunluq | **{{%}}** | {{%}} | {{keçdi / keçmədi}} |
| Cohen κ | **{{}}** | {{}} | {{şərh}} |
| Etiket sayı (n) | {{}} | — | — |
| Rubrika | `{{ad}}@{{versiya}}` | — | — |
| Judge modeli | `{{model}}` | — | SUT-dan güclü olmalıdır |

{{Fikir ayrılıqları: hansı case-lərdə insan və judge razılaşmadı və niyə.
Sıfır fikir ayrılığı ŞÜBHƏLİDİR — etiketin judge-a uyğunlaşdırıldığını göstərir.}}

{{Bilinən yanlılıqlar: üslub, dil, uzunluq.}}

---

## 8. Nəyi ölçmədik  ⛔ **MƏCBURİ BÖLMƏ**

> **Bu bölmə niyə MƏCBURİDİR.** Məhdudiyyəti gizlətmək auditdə ən tez tutulan
> şeydir və bir dəfə tutulanda hesabatın qalan hissəsi də şübhə altına düşür.
> Daha praktiki səbəb: müştəri bu hesabatı daxili qərar üçün istifadə edəcək —
> hansı nəticənin çıxarıla BİLMƏDİYİNİ bilməsə, hesabat onu yanlış qərara
> aparar və məsuliyyət auditə qayıdar.
>
> **Kəsmək istəyi burada daha güclüdür — kəsilmir.** «Nəyi ölçmədik» bölməsi
> satış sənədini zəif göstərən yeganə bölmə kimi görünür; əslində alıcının
> «bunlar dürüstdür» qərarını verdiyi yerdir. Təcrübədə ikinci audit məhz bu
> bölməyə görə satılır.
>
> **Məlumat yoxdursa bölmə SİLİNMİR.** Başlıq qalır, içi xəbərdarlığa çevrilir:
> *«Məhdudiyyət reyestri qurulmayıb — bu hesabatdan hansı nəticələrin çıxarıla
> bilməyəcəyi sənədləşdirilməyib.»*
>
> **Bura NƏ YAZILMIR:** üzrxahlıq və özünütənqid. Hər bənd dörd suala cavab
> verir — nə ölçülmədi · niyə · İSTİQAMƏT · azaltmaq üçün nə lazımdır — və
> istiqamət olmadan bənd yarımçıqdır.

**İstiqamət notasiyası:**

| İşarə | Mənası |
|---|---|
| **↑ ŞİŞİRDİR** | Uğursuzluqları real istehsalatdan **ÇOX** göstərir; rəqəm pessimistdir |
| **↓ GİZLƏDİR** | Uğursuzluqları **AZ** göstərir; rəqəm **alt həddir** |
| **↔ İKİ TƏRƏFLİ** | Hər iki istiqamətdə səhv verə bilər; xalis təsir ölçülməyib |

### 8.{{n}} {{məhdudiyyət başlığı}} — **{{↑ ŞİŞİRDİR / ↓ GİZLƏDİR / ↔}}**

- **Nə ölçülmədi.** {{}}
- **Niyə.** {{}}
- **İstiqamət.** {{nəticəyə hansı tərəfə təsir edir}}
- **Azaltmaq üçün.** {{nə lazımdır — və bu, işin hüdudundadırmı}}

<!-- İZAH: Ən azı bu siniflər yoxlanmalıdır (aidiyyatı olanlar yazılır):
     konfiqurasiya seçimləri (top_k, embedder, model parametrləri) ·
     korpusun ölçüsü və təmizliyi · tələ sıxlığının realizmi ·
     təkrar sayı · örtülməyən uğursuzluq rejimləri · tək platforma /
     tək model → köçürülməzlik · xərc uçotunun tamlığı ·
     baseline olmadığı üçün reqressiya iddiasının mümkünsüzlüyü. -->

### 8.{{son}} Bu hesabatdan çıxarıla BİLMƏYƏN nəticələr

| # | Çıxarıla BİLMƏYƏN nəticə | Bloklayan məhdudiyyət | Niyə |
|---|---|---|---|
| 1 | «{{iddia}}» | {{§8.n}} | {{}} |

<!-- İZAH: Bu cədvəl oxucuya birbaşa ünvanlanır və hesabatın yanlış sitat
     gətirilməsinə qarşı yeganə qorumadır. Ən azı 5 sətir olmalıdır. -->

---

## 9. Kənarda qalan case-lər

> **Bu bölmə niyə var.** Reproduksiya qapısından keçməyən case-lər hesabatdan
> **çıxarılır, silinmir**. Oxucu nəyin nə üçün kənarda qaldığını görməlidir —
> əks halda «seçilmiş nəticə» şübhəsi qalır.
> **Bura NƏ YAZILMIR:** tapıntı. Bu bölmədəki heç bir sətir iddia deyil.

### 9.1 Flaky ({{1–k-1}}/{{k}} keçdi) — {{N}} case

| Case | Keçid | Ciddilik | Rejim |
|---|---|---|---|
| `{{id}}` | {{2/3}} | {{}} | {{}} |

### 9.2 `unstable-fail` (0/{{k}}, səbəblər fərqli) — {{N}} case

### 9.3 Ölçmə etibarsız olduğu üçün kənarda qalanlar

### 9.4 Növbəti qaçışdan əvvəl bağlanmalı olanlar

{{Bu alt-bölmə növbəti auditin iş siyahısıdır — müştəri üçün dəyərlidir.}}

---

## 10. İcraya hazır düzəliş siyahısı

> **Bu bölmə niyə var.** Hesabat oxunub rəfə qoyulursa auditin dəyəri sıfırdır.
> Bu bölmə müştərinin mühəndisinə **sabah səhər başlaya biləcəyi siyahı** verir:
> hansı qatda işləyəcəyini, nə qədər çəkəcəyini, düzəlişin işlədiyini hansı
> case ilə yoxlayacağını və nəyi sındıra biləcəyini bilir.
> **Bura NƏ YAZILMIR:** ölçülməmiş effekt vədi. «Bu, dəqiqliyi 20% artırır»
> tipli cümlə yazılmır — heç bir düzəliş bu auditdə ölçülməyib. Yazılan tək
> proqnoz **yoxlama case-ləridir**: düzəlişdən sonra hansı id-lərin yaşıla
> dönməli olduğu.

**Sxem** (hər bənd üçün eyni dörd sahə; tapıntı istinadı başlıqdadır):

| Sahə | Mənası |
|---|---|
| **QAT** | Düzəliş hansı qatda edilir: `prompt` · `retrieval konfiqurasiyası` · `tool sxemi` · `guardrail` · `bilik bazası mətni` · `arxitektura` · `infrastruktur` · `ölçmə qatı` · `proses`. **Qat ayrımının özü müştəri üçün dəyərdir:** eyni hesabatdakı düzəlişlərin fərqli qatlarda olması onları fərqli komandalara paylamağa imkan verir |
| **ƏMƏK** | Təxmini iş həcmi. **[TƏXMİN]** işarəsi ilə — ölçülməyib |
| **YOXLAMA** | Düzəlişdən sonra yaşıla dönməli case id-ləri (mövcud dataset id-ləri) |
| **RİSK** | Düzəliş nəyi sındıra bilər |

{{Bəndlərin sırası: əvvəlcə mexanizmi bağlayanlar, sonra möhkəmləndirənlər.}}

<!-- İZAH: Üç qayda:
     1. Bir tapıntının bir neçə düzəlişi ola bilər — hər biri AYRI bənddir,
        çünki qatları və riskləri fərqlidir.
     2. Yalnız DƏSTƏKLƏYİCİ olan bənd («ucuzdur, amma mexanizmi bağlamır»)
        açıq belə işarələnir. Əks halda müştəri ucuz bəndi görüb bahalını
        təxirə salır və problem qalır.
     3. Bəzi düzəlişin yoxlaması «yaşıl olacaq» deyil, «ÖLÇÜLƏ BİLƏN hala
        düşəcək» ola bilər (məsələn korpusun öz ziddiyyəti). Bu fərq yazılır —
        yaşıl vəd etmək ölçülməmiş effekt vədidir. -->

{{Əks istiqamətə çəkən bəndlər varsa (biri eskalasiyanı artırır, digəri yalançı
imtinanı azaldır) bu, siyahının sonunda açıq yazılır: onlar EYNİ qaçışda
ölçülməlidir, ayrı-ayrı qaçışlarda hər biri «işlədi» görünə bilər.}}

### D-{{n}} · {{düzəlişin adı}} → {{F-n / OPS-n}}

| | |
|---|---|
| **QAT** | `{{qat}}` |
| **ƏMƏK** | {{}} **[TƏXMİN]** |
| **YOXLAMA** | `{{case id}}` · `{{case id}}` → {{k}}/{{k}} keçməlidir |
| **RİSK** | {{düzəliş nəyi sındıra bilər — «risk yoxdur» qəbul edilmir}} |

{{1–3 cümlə: nə edilir və niyə məhz bu qatda.}}

### Xülasə cədvəli

| # | Düzəliş | Qat | Tapıntı | Yoxlama case sayı |
|---|---|---|---|---:|
| D-{{n}} | {{}} | {{}} | {{F-n / OPS-n}} | {{N}} |

---

## 11. Auditin əhatəsi və maya dəyəri

> **Bu bölmə niyə var.** Müştəri bu auditi təkrarlamaq və ya genişləndirmək
> istəyəcək; nəyin nə qədər başa gəldiyini bilməlidir.
> **Bura NƏ YAZILMIR:** ölçülməmiş xərc. Xərc uçotu natamamdırsa (bəzi
> cəhdlərin token istifadəsi gəlmirsə) rəqəm **alt hədd** kimi işarələnir və
> ölçülməyən cəhd sayı yanında yazılır.

| Maddə | Dəyər | İşarə |
|---|---:|---|
| Model xərci — ölçülən | ${{}} | [ÖLÇÜLDÜ] |
| Ölçülməyən cəhd | {{N}} cəhd | [NAMƏLUM] |
| Qaçış müddəti (divar saatı) | {{}} | [ÖLÇÜLDÜ] |
| Qiymət rejimi | {{tarix}} · ${{}}/${{}} | [ÖLÇÜLDÜ] |

{{Genişləndirmə variantları: case sayı, təkrar sayı, əlavə model / embedder.}}

---

## 12. Düzəliş qeydi

> **Bu bölmə niyə var.** Hesabat dərc olunduqdan sonra düzəldilirsə, nəyin
> dəyişdiyi və nəyin dəyişmədiyi açıq yazılır. Səssiz düzəliş auditin
> etibarını hesabatdakı hər hansı səhvdən daha çox zədələyir.
> **Bura NƏ YAZILMIR:** üslub düzəlişləri. Yalnız iddianı dəyişən düzəlişlər.
> Düzəliş yoxdursa bölmə bir sətrə yığılır: *«Bu hesabat dərcdən sonra
> düzəldilməyib.»*

### C-{{n}} · {{tarix}} — {{hansı bölmə}}

- **Nə yazılmışdı:** {{}}
- **Nə dəyişdi:** {{}}
- **Nə DƏYİŞMƏDİ:** {{tapıntının özü / ciddiliyi / reproduksiya statusu}}
- **Səbəb:** {{hansı artefakt ilk redaksiyanı təkzib etdi}}

---

## Əlavə A — reproduksiya təlimatı

> **Bu bölmə niyə var.** Müştərinin mühəndisi tapıntını öz gözü ilə görməlidir.
> Reproduksiya olunmayan iddia auditdə müdafiə olunmur.

```bash
{{dəqiq əmrlər: mühit dəyişənləri, qaçış əmri, filtr, artefakt yolu}}
```

| Artefakt | Yol | Nə saxlayır |
|---|---|---|
| Qaçış qeydi | `{{}}` | {{}} |
| Reproduksiya təsnifatı | `{{}}` | {{}} |
| Log | `{{}}` | {{}} |

---

<!--
=======================================================================
  YEKUN YOXLAMA SİYAHISI (sənədi göndərmədən əvvəl)
  -------------------------------------------------
  [ ] §4 var və doludur (və ya xəbərdarlığa çevrilib)
  [ ] §8 var və doludur (və ya xəbərdarlığa çevrilib); hər bəndin İSTİQAMƏTİ var
  [ ] §8-in son cədvəli («çıxarıla BİLMƏYƏN nəticələr») ən azı 5 sətirdir
  [ ] Hər tapıntının reproduksiya statusu var və qapıdan keçib
  [ ] Hər tapıntıda cavabdan BİRBAŞA SİTAT var (parafraz yox)
  [ ] §10-un heç bir sətrində ölçülməmiş effekt vədi yoxdur
  [ ] Bütün {{}} yerləri doldurulub
  [ ] Bütün <!-- İZAH --> blokları silinib
  [ ] Heç bir daxili tapşırıq nömrəsi, daxili rol adı və ya daxili
      müzakirə qeydi qalmayıb
      (HTML hesabatda eyni yoxlama maşınlıdır: `--audience client` daxili izi
       çıxarır, `report/html.py:find_internal_traces()` isə qalanı tutur;
       §4, §7 və §8 orada MANDATORY_SECTIONS ilə kəsilməz saxlanılır)
  [ ] Ton yoxlanılıb: «biz bu sistemi sınadıq və budur tapdığımız» —
      «bu sistem pisdir» YOX
  [ ] Hər rəqəmin yanında mənbə artefaktı var
=======================================================================
-->
