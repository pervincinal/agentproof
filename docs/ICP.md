# ICP.md — alıcı kimdir

**Tapşırıq:** AP-073 · **Qərar tarixi:** 2026-09-06 · **Qərar verən:** Parvin
**Əvəz edir:** satış planı Faza 1-in ilkin ICP təyini

## Qərar

**Alıcı agenti SATAN şirkət deyil — agenti öz saytında İŞLƏDƏN şirkətdir.**

---

## Niyə dəyişdi

AP-056 yoxlaması ölçdü: Sıra A-nın **10 şirkətinin 10-unda** autentifikasiyasız
test edilə bilən səth yoxdur. Nə açıq API, nə sandbox, nə özünəxidmət demo —
hamısı «book a demo» / «request access».

Bu, meyarın sərtliyi deyil, **kateqoriyanın quruluşudur**: korporativ B2B AI
satıcıları API-ni açmır. Yəni «açıq demonu test et, tapıntı göndər» hərəkəti
həmin ICP-yə qarşı prinsipcə mümkün deyil — və onu mümkün etmək üçün
qaydalarımızı (hesab yaratmamaq, yalnız açıq səth) pozmaq lazım gələrdi.

**Bloklayıcı alət deyildi, alıcı idi.**

---

## Yeni alıcı

Agenti öz müştəriləri ilə **ictimai səhifədə** danışdıran, tənzimlənən sahədə
işləyən şirkət: bank, sığorta, telekom, enerji, pensiya, səhiyyə xidməti.

| | Köhnə ICP (satıcı) | Yeni ICP (istifadəçi) |
|---|---|---|
| Kimdir | Agent platforması satan Seriya A–B | Agenti öz saytında işlədən orta ölçülü şirkət |
| Agent açıqdırmı | **Xeyr** — demo satış zəngidir | **Bəli** — saytdadır, girişsiz danışır |
| Səhv cavabın zərəri | Müştərisinin problemi | **Birbaşa özünün** — pul, şikayət, tənzimləyici |
| Tənzimləyici öhdəlik | Zəif — təchizatçıdır | **Güclü** — sistemi işlədən odur |
| Qərar verən | CTO / təsisçi | Rəqəmsal / CX rəhbəri, risk, uyğunluq |
| Satış dövrü | qısa | **uzun** — qəbul edilən çatışmazlıq |

---

## Tənzimləmə arqumenti indi GÜCLÜDÜR

Bazar hesabatının R-5 riski deyirdi: *«EU AI Act-ı ön sıraya çıxarma — Annex III
sistemlərinin əksəriyyəti özünü qiymətləndirir»*.

Satıcı ICP-si üçün bu doğru idi. **İstifadəçi ICP-si üçün deyil.**

- AI Act **02.08.2026-dan tətbiq olunur**.
- Maliyyə xidmətləri, sığorta və məşğulluq üzrə **uyğunluq/hüquq qərarına təsir
  edən** çatbotlar **yüksək riskli** sayılır.
- Öhdəlik sistemi **bazara çıxaranın və işlədənindir** — yəni bizim yeni
  alıcının, təchizatçının yox.

Özünü qiymətləndirmə də **sənədləşdirilmiş sübut tələb edir**. Bizim hesabat
məhz odur: təkrarlanmış davranış sübutu, artefaktları ilə.

**Amma yenə birinci arqument olmasın.** Birinci arqument həmişə eynidir:
*agentiniz müştərinizə səhv qayda dedi və siz bunu müştəridən öyrəndiniz.*
Tənzimləmə büdcəni açır, ağrını yaratmır.

---

## Meyarlar

| # | Meyar | Necə yoxlanır |
|---|---|---|
| 1 | Saytda **girişsiz danışan** dəstək/satış agenti | Səhifəni aç, çatı işə sal, sual ver |
| 2 | Agent **qayda tətbiq edir** — tarif, şərt, uyğunluq, müddət | Bir siyasət sualı ver |
| 3 | Tənzimlənən sahə | bank · sığorta · telekom · enerji · pensiya · səhiyyə |
| 4 | EU / UK | vaxt zonası |
| 5 | **Orta ölçü** — tier-1 bank YOX | qərar verən adama çatmaq mümkün olsun |
| 6 | İstifadə şərtləri avtomatlaşdırmanı qadağan etmirsə | ToS oxu; qadağandırsa **əl ilə** (AP-071) |

**5-ci meyar vacibdir.** Tier-1 bank ən yaxşı hədəf kimi görünür və ən pisidir:
satınalma prosesi aylarla sürür və heç kim naməlum auditora cavab vermir.
Hədəf **challenger bank, insurtech, virtual operator, enerji təchizatçısı** —
agenti var, hüquq departamenti nəhəng deyil.

---

## Təsdiqlənmiş başlanğıc nöqtəsi

**Pockit** (UK neobank) — Gradient Labs-in agentini həm müştəri dəstəyində,
həm arxa ofisdə işlədir. **[Ö]** — mənbə: Gradient Labs bələdçisi, 2026.

Bu, yeni ICP-nin ilk təsdiqlənmiş nümunəsidir və eyni zamanda naxşı göstərir:
**satıcıların keys-stadiləri hədəf siyahısıdır.** Gradient Labs, PolyAI,
Parloa, Cognigy — hamısı müştərilərinin adını dərc edir. Onların referans
səhifəsi bizim namizəd mənbəyimizdir.

Bu, siyahı qurmağın ən sürətli yoludur və Dealroom-dan yaxşıdır: orada
şirkətin agenti **olduğu təsdiqlənmiş** olur.

Sahə statistikası da bunu dəstəkləyir: fintech əsaslı challenger banklarda
çatbot qəbulu **100%**, Avropa üzrə banklarda **85%** (2025). **[Ö]** — mənbə
sənaye hesabatı, müstəqil yoxlanmayıb.

---

## Nə dəyişir

| Sənəd | Dəyişiklik |
|---|---|
| `site/index.html` | Açılış və «Fit» bölməsi istifadəçiyə çevrilir |
| `docs/outreach/cold-email.md` | Ağrı «satınalma anketi» yox, «müştəri şikayət etdi» |
| `docs/outreach/target-list.md` | Meyarlar və mənbə dəyişir — satıcıların keys-stadiləri |
| `docs/PREAUDIT.md` | Dayandırıcı yoxlamalara «girişsiz danışırmı» əlavə olunur |
| AP-059 | Yeni siyahı qurulandan sonra açılır |

## Nə DƏYİŞMİR

Qaydalar. Yeddi qayda olduğu kimi qalır və indi **daha vacibdir**: hədəf artıq
demo deyil, **canlı müştəri sistemidir**. Sorğu büdcəsi, real şəxsi məlumat
qadağası və razılıqsız dərc qadağası burada daha ciddi işləyir.

Xüsusilə: **real sifariş nömrəsi, real müştəri adı, real hesab məlumatı heç
vaxt daxil edilmir.** Sual siyasət haqqında olur, konkret müştəri haqqında yox.
