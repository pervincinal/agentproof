# COMMERCIAL-TERMS.md — qiymət və müqavilə şərtləri

**Tapşırıq:** AP-063 · **Tarix:** 2026-09-06 ·
**Dərc olunmuş qiymət:** [`site/index.html`](../site/index.html#pricing)

Bu sənəd daxilidir və **qiyməti təyin etmir** — dərc olunmuş qiymət saytdadır.
Burada qiymətin arxasındakı mexanika, sərhədlər və nədən güzəşt edilmədiyi
yazılır ki, danışıq zamanı hər dəfə yenidən qərar verilməsin.

---

## 1. Qiymət pilləsi

| Xidmət | Qiymət | Müddət | Nə daxildir |
|---|---:|---|---|
| Dizayn tərəfdaşı (ilk 2) | **$2,000** | 14 gün | Giriş auditi + referans müqabilində — [AP-065](outreach/design-partner-offer.md) |
| Təkrarlanma auditi | **$4,500** | 14 gün | Bir sistem, bir versiya, təkrarlanmış tapıntılar + düzəliş siyahısı |
| Tam audit | **$14,000-dan** | 4–6 həftə | Sahəyə uyğun korpus, düzəlişdən sonra təkrar test, attestasiya |
| Reqressiya nəzarəti | **$2,500 / ay** | davamlı | Hər buraxılışda eyni dataset, dəyişiklik hesabatı |

**«Giriş qiyməti» olduğu saytda yazılıb** və bu, dürüstlükdür, taktika deyil:
`AUDIT-COST.md` §10 döşəməni hələ də düsturla verir, çünki `H` (əmək saatı)
ölçülməyib. İlk ödənişli audit `agentproof.timesheet` ilə qeyd olunandan sonra
bu cədvəl yenidən baxılır.

---

## 2. Üç mexanika — hər üçü müzakirə mövzusu deyil

### 2.1 50% imzada

Tək operator, tanınmayan qarşı tərəf, əvvəlcədən görülən iş. Bu, güvənsizlik
deyil, **simmetriyadır**: alıcı da məndən əvvəlcədən nəticə istəmir.

Rədd edilirsə: qiyməti aşağı salma, **əhatəni** kiçilt.

### 2.2 Əhatə hasarı

Bir sətirdə: **bir sistem, bir versiya, N case, 14 gün.**

- «Bir versiya» — audit başlayandan sonra hədəf dəyişirsə, qaçış yenidən
  başlayır və bu, ayrıca sətirdir. Dəyişən hədəf üzərində tapıntı
  təkrarlanmır; təkrarlanmayan tapıntı isə hesabata düşmür.
- «Bir sistem» — ikinci agent ikinci auditdir. Eyni korpus işlədilsə belə,
  triage və grader auditi hər sistem üçün təkrardır (`AUDIT-COST.md` §9).
- **Düzəlişdən sonrakı təkrar test AYRICA sətirdir** — birinci qiymətə
  bağlanmır. Bağlansa, düzəlişin nə vaxt gələcəyi mənim riskim olardı.

### 2.3 Sıfır tapıntı zəmanəti

> Heç bir təkrarlanmış uğursuzluq tapılmasa, **yarısını ödəyirsiniz və korpusu
> saxlayırsınız.**

Təmiz nəticə real nəticədir və alıcının riskini silir. Amma bu şərt mənə
uğursuzluq tapmaq marağı yaradır, ona görə onu **satarkən özüm adlandırıram**
(§3).

Korpus alıcıda qalır — yəni pul tam qaytarılmasa da, əlində təkrar işlədə
biləcəyi bir artefakt olur.

---

## 3. Maraq toqquşması — gizlətmirik, hasarını göstəririk

Satış zamanı deyiləcək mətn:

> «Bu zəmanət mənə uğursuzluq tapmaq üçün maraq yaradır — bunu bilirəm və
> gizlətmirəm. Məni saxlayan **3/3 təkrarlanma qapısıdır**, və o qapının kodu
> açıqdır. İstəyirsinizsə mənim öz filtrimi özünüz auditə çəkə bilərsiniz.»

Bu, hesabat şablonuna da girib (AP-064), yəni iddia yalnız satışda deyil,
təhvildə də yazılıdır.

**İkinci hasar:** tapıntı sayı heç vaxt qiymətə bağlanmır. Nə bonus, nə
success fee. Tapıntı başına ödəniş auditoru tapıntı istehsalçısına çevirir.

---

## 4. Nədən güzəşt edilmir

| Xahiş | Cavab |
|---|---|
| «Agentimizi də düzəldə bilərsən?» | **Xeyr.** Siz düzəldirsiniz, mən təkrar test edirəm. Müstəqillik məhsulun özüdür və iki dəfə satıla bilməz |
| «Tapıntı başına ödəyək» | **Xeyr** — §3 |
| «Hesabatdan bu tapıntını çıxar» | **Xeyr.** Kontekst əlavə edə bilərəm, dərci gecikdirə bilərəm (qayda 6 onsuz da bunu verir), amma sizə bildirilmiş tapıntı geri alınmır |
| «NDA imzala» | **Bəli** — adi haldır və qayda 6 ilə ziddiyyət təşkil etmir |
| «Nəticəni bizim brendimizlə dərc et» | **Bəli**, sizin razılığınızla — hesabat onsuz da brendsizdir |
| «Daha ucuz olsun» | Qiymət yox, **əhatə** kiçilir — §2.1 |

---

## 5. Nə vaxt işi qəbul ETMİRİK

- Alıcı hesabatı **daxili qərar üçün deyil, kiminsə üstünə atmaq üçün**
  istəyirsə. Audit sübutdur, silah deyil.
- Hədəf sistemi **biz qurmuşuqsa** — heç vaxt olmayacaq, çünki qurmuruq.
- Alıcı nəticəni **əvvəlcədən bilmək** istəyirsə («təmiz çıxacağına
  əminsənmi?»). Cavab: bilmirəm, ölçəcəyəm.
- Hədəf **canlı istifadəçi trafikindədirsə** və test onlara toxunacaqsa.
  Sandbox və ya kopya tələb olunur.

Bu siyahının olması gəlirdən qiymətlidir: rədd edilə bilməyən auditorun
hesabatı da rədd edilə bilməz — yəni dəyəri yoxdur.

---

## 6. Ölçüləcək — ilk auditdə

`agentproof.timesheet` ilə hər təkrarlanan mərhələ. Nəticə `AUDIT-COST.md`
§10.2-yə yazılır və **bu cədvəl həmin ölçüdən sonra yenilənir.** İkinci
qiymət təxmin olmamalıdır.
