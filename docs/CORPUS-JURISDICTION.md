# CORPUS-JURISDICTION.md — EU/UK üçün korpus variantı lazımdırmı

**Tapşırıq:** AP-068 · **Qərar tarixi:** 2026-09-06 · **Rol:** dataset-eng

## Qərar

**Ayrıca EU/UK korpus variantı YARADILMIR.**

Bunun əvəzinə bir konkret boşluq bağlanır: korpusda **qanuni hüququn şirkət
siyasətini üstələməsi** tələsi yoxdur. Bu, EU/UK-a xas ən dəyərli tələ
ailəsidir və tam variantdan qat-qat ucuzdur.

---

## Tapşırığın fərziyyəsi səhv idi

AP-068-i yazanda belə yazmışdım: *«Aurora Goods siyasətləri neytral/ABŞ
yönümlüdür»*. Korpusu ölçəndə bu doğru çıxmadı.

| Ölçdüm | Nəticə |
|---|---|
| Valyuta | **AZN — 104 dəfə.** USD, EUR, GBP: **sıfır** |
| Vergi anlayışı | **VAT** — ABŞ-ın `sales tax`-ı deyil |
| Şəxsi məlumatın silinməsi | Var: sorğu → **14 günlük geri götürmə müddəti** → 30 gün icra |
| Silinmədən sonra saxlanan | Mühasibat qeydi: sifariş nömrəsi, tarix, məbləğ, **VAT** |
| Köhnəlmiş bəndin saxlanma səbəbi | *«statutory record-keeping period»* |

Yəni korpus struktur baxımından **ABŞ deyil, Avropaya yaxındır**: VAT,
silinmə hüququ, geri götürmə pəncərəsi və qanuni saxlama müddəti — hamısı
GDPR-ə bənzər rejimin formasıdır (adı çəkilmədən).

Valyutanın AZN olması qüsur deyil, **üstünlükdür**: korpusun süni olduğu ilk
baxışdan görünür. EUR-a çevirmək onu real şirkətə daha çox oxşadardı — bu,
istinad korpusu üçün pisdir.

---

## Daha vacib səbəb: korpus müştəri auditində təkrar istifadə OLUNMUR

`AUDIT-COST.md` §9 «HƏR MÜŞTƏRİDƏ» sətri budur: **korpus + ground truth hər
müştəri üçün yenidən qurulur.** Ödənişli auditdə doğru cavabı müştərinin öz
siyasətləri təyin edir; Aurora korpusu isə **metodu nümayiş etdirən
artefaktdır**, şablon deyil.

Ona görə Aurora-nın yurisdiksiyası kommersiya baxımından demək olar
əhəmiyyətsizdir. EU variantı qurmaq eyni nümayişi ikinci dəfə etmək olardı —
xərc real, fayda simvolik.

---

## Bağlanan boşluq: qanuni üstələmə tələsi

27 tələdən **heç biri** «qanun siyasəti üstələyir» halını ölçmür
(`grep -ci 'statutory|consumer right|law overrides|legal minimum'` → **0**).

Halbuki tənzimlənən EU/UK alıcısı üçün ən bahalı səhv məhz budur:

> Siyasət deyir «14 gün». Qanun deyir «14 gün, **çatdırılmadan** sayılır».
> Agent siyasəti düzgün sitat gətirir və **yenə də səhv edir**.

Bu, mövcud tələ ailələrinə oxşamır:

| Mövcud | Yeni |
|---|---|
| T-01 / T-07 — bayat bənd, hər iki istiqamətdə | Bənd **qüvvədədir**, amma qanuni minimumdan aşağıdır |
| R6 — iki bənd toqquşur | Toqquşma korpusun **içində deyil**, korpus ilə **xarici norma** arasındadır |

Və bu, F-3 ilə eyni sinifdir: **cavab düzgün mənbədən gəlir, nəticə səhvdir.**
Determinist yoxlayıcı onu yaşıl boyayardı.

---

## Nə edilir

Yeni tapşırıq: **AP-072** — `T-28…T-30` qanuni üstələmə tələ ailəsi.

- Korpusa qısa bir «Statutory minimums» bölməsi əlavə olunur; kanonik fayl
  hansı bəndin qanuni minimumdan aşağı olduğunu **açıq** yazır.
- 3–4 case: agent siyasəti sitat gətirir, qanuni minimumu tətbiq etmir.
- **Sərhəd:** bu, hüquqi məsləhət deyil və olmayacaq. Korpus süni bir
  yurisdiksiya təyin edir və doğru cavabı `CANONICAL.yaml` verir — real
  qanunvericiliyə istinad edilmir. Real audit üçün qanuni minimumu
  **müştəri** təyin edir, biz yox.

Sonuncu bənd vacibdir: hüquqi rəy verməyə başlasaq, sata bilməyəcəyimiz və
məsuliyyətini daşıya bilməyəcəyimiz bir şeyə keçmiş olarıq.

---

## Nə etmirik və niyə

| Fikir | Qərar | Səbəb |
|---|---|---|
| Bütün korpusu EUR-a çevir | **Yox** | Süniliyi gizlədir; kommersiya faydası yoxdur |
| GDPR-i adı ilə korpusa sal | **Yox** | Real hüquqi mətnə istinad hüquqi rəy təəssüratı yaradır |
| Ayrıca EU korpus variantı | **Yox** | Korpus onsuz da hər müştəridə yenidən qurulur |
| Qanuni üstələmə tələsi | **Bəli** — AP-072 | Ölçülmüş boşluq, dar, ucuz, EU/UK alıcısına birbaşa aid |

---

## Yenidən baxılır

İlk EU/UK müştərisi auditdən sonra. Real korpus qurulanda burada yazılanların
hansının doğru çıxdığı ölçüləcək — xüsusən «yurisdiksiya əhəmiyyətsizdir»
iddiası.
