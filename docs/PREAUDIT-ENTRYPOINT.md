# PREAUDIT-ENTRYPOINT.md — açıq demoya necə qoşuluruq

**Tapşırıq:** AP-055 · **Qərar tarixi:** 2026-09-05 ·
**Bağlı:** [`PREAUDIT.md`](PREAUDIT.md) · [`ADAPTERS.md`](ADAPTERS.md) ·
[`site/rules.html`](../site/rules.html)

## Qərar

**Brauzer avtomatlaşdırma adapteri YAZILMIR.**

Hədəf meyarına yeni şərt əlavə olunur: *sənədləşdirilmiş API və ya lokal
qaçırıla bilən açıq mənbə demosu*. Yalnız veb-vidceti olan şirkətlər siyahıdan
çıxarılmır — onlar **əl ilə** test olunur (şərtlər icazə verirsə), və əl ilə
yazılmış transkript eyni qrader zəncirindən keçirilir.

---

## Problem

Ön-audit planı hədəf şirkətin agentini bizi işə götürməmişdən əvvəl test
etməyi tələb edir. Amma bizim dörd kanalımız (`dify_http`, `json_http`,
`callable`, `mock`) HTTP API və ya proses daxili çağırış gözləyir, halbuki
şirkətlərin çoxunda açıq olan şey **marketinq saytındakı çat vidcetidir**.

Yəni Faza 1-in bloklayıcısı texniki görünür: «vidcet üçün adapter yazaq».

## Niyə brauzer adapteri yazmırıq

**1. Öz qaydamızı pozardı.** Qayda 2 deyir: şərtlər avtomatlaşdırılmış girişi
qadağan edirsə, əl ilə test edirik və ya ümumiyyətlə etmirik; qeyri-müəyyən
şərti qadağan sayırıq. Marketinq saytlarının şərtlərində «no automated
access», «no scraping», «no bots» bəndləri **adi haldır**. Belə adapter
yazmaq — istifadə etməyəcəyimiz alət qurmaq, ya da qaydanı pozmaq deməkdir.

Auditor üçün bu, texniki qərar deyil: **qaydanı pozmaq üçün alət qurmaq,
qaydanı artıq pozmaqdır.**

**2. Sorğu büdcəsi ölçülməz olardı.** Bir vidcet açılışı onlarla şəbəkə
sorğusu (analitika, telemetriya, sessiya) yaradır. «≤ 30 sorğu» vədini
brauzerdə saymaq mümkün deyil — hansı sorğunun bizim, hansının səhifənin
olduğunu ayıra bilmirik. Ölçülməyən vəd, vəd deyil.

**3. Sübut zəiflərdi.** Vidcetdən alınan cavabda `usage` yoxdur, `retrieved`
yoxdur, `conversation_id` yoxdur. `AGENTPROOF` qaydası budur ki, tapılmayan
sahə **sıfır deyil, `None`-dur** — yəni belə qaçışın hesabatının yarısı
«ölçülmədi» olardı. Müştəriyə göndərilən bir səhifəlik sənədin dəyəri məhz
artefaktdadır.

**4. Kövrəklik.** Vidcetin DOM-u xəbərdarlıqsız dəyişir. Sınan selektor
səssizcə boş cavab verər, boş cavab isə «agent cavab vermədi» kimi oxunar —
yəni **uydurma tapıntı**. Bu, layihənin bütövlükdə qarşısını almağa çalışdığı
səhv sinfidir.

---

## Nə edirik əvəzinə

### A · Sənədləşdirilmiş API (əsas yol)

Hədəf siyahısının meyarı dəyişir: **açıq demo** kifayət deyil, **açıq demo +
sənədləşdirilmiş giriş nöqtəsi** lazımdır. Praktikada bu üç formadan biridir:

| Forma | Kanal | Əlavə iş |
|---|---|---|
| Sənədli REST/JSON API, açıq açar və ya açarsız sandbox | `json_http` | sahə xəritəsi (`--query-field`, `--text-path`) |
| Açıq mənbə repo, lokal qaçır | `callable` və ya `json_http` | quraşdırma |
| Dify / oxşar platforma üzərində qurulub | `dify_http` | yoxdur |

Bu, siyahını daraldır — və bu, **fayda**dır: API-si sənədləşdirilmiş şirkət
onsuz da korporativ satışa hazırlaşan şirkətdir, yəni bizim ICP-mizə daha
yaxındır. Meyar filtri həm texniki, həm kommersiya filtridir.

### B · Yalnız vidceti olanlar (əl ilə)

Şirkət ICP-yə tam uyğundursa, amma API-si yoxdursa:

1. Şərtləri oxu. Avtomatlaşdırma qadağandırsa — **əl ilə** yaz, brauzeri
   avtomatlaşdırma.
2. ≤ 12 sual, bir sessiya, öz əlinlə.
3. Cavabları transkript faylına köçür.
4. Transkripti eyni qrader zəncirindən keçir — **hökmü yenə kod verir, mən
   yox.**

Dördüncü addım hələ qurulmayıb; onun üçün ayrıca tapşırıq açılıb (AP-071).
O olmadan əl ilə ön-audit **etmirik**, çünki qradersiz «tapıntı» sadəcə
mənim fikrimdir.

### C · Nə vaxt tamamilə imtina edirik

- Demo hesab, dəvət və ya kart tələb edirsə → **qayda 1**, dayan.
- Şərtlər qeyri-müəyyəndirsə → qadağan say, dayan.
- Şirkət opt-out siyahısındadırsa → dayan.

---

## Açıq risklər — gizlətmirik

**R-1 · Meyar siyahını yarıya endirir.** Sənədli API tələbi 40 namizədin
təxminən yarısını kəsə bilər. Ölçülməyib — AP-056 siyahısı qurulanda faktiki
nisbət yazılacaq. Bu sənəd rəqəm uydurmur.

**R-2 · Əl ilə yol miqyaslanmır.** 12 sual əl ilə ~40 dəqiqədir. 15 ön-audit
üçün bu, təkbaşına idarə oluna bilər; 50 üçün yox. Miqyas lazım olanda qərar
yenidən baxılmalıdır — **avtomatlaşdırma ilə yox, hədəf seçimi ilə.**

**R-3 · Rəqib bu qərarı vermir.** Vidceti avtomatlaşdıran rəqib daha çox
şirkəti test edə bilər. Bu, real kommersiya itkisidir və qəbul edilir:
auditorun məhsulu sürət deyil, qaydaya sadiqlikdir.

**R-4 · Şərtləri mən oxuyuram.** Hüquqi rəy deyil. Qeyri-müəyyənlikdə dar
oxunuş seçilir və şübhə varsa test edilmir.

---

## Nəticə

Bloklayıcı texniki deyildi. Adapter yazmaq problemi həll etmirdi — **qaydanı
pozmaq şərti ilə** həll edirdi. Qərar: hədəf meyarını dəyişmək, aləti yox.
