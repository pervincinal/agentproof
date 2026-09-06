<!--
  ÖN-AUDİT BİR SƏHİFƏLİYİ — şablon (AP-057).

  Bu, `CLIENT-REPORT.md`-in kiçildilmiş versiyasıdır, sadələşdirilmiş yox.
  Fərq həcmdədir: 2 tapıntı, 12 case, bir qaçış. Fərq İNTİZAMDA DEYİL —
  təkrarlanma qapısı, «nəyi ölçmədik» bölməsi və artefakt yolları qalır,
  çünki onlar olmadan sənəd sübut olmaqdan çıxıb marketinq olur.

  Alıcı bunu heç nə ödəmədən alır (qayda 7). Ona görə burada nə şərt var,
  nə də saxlanmış hissə.

  DOLDURULMAYAN SAHƏ SİLİNMİR — «ölçülmədi» yazılır.

  GÖNDƏRİŞDƏN ƏVVƏL MƏCBURİ:
      python3 evals/verify_quotes.py <bu fayl> <merged.json>
  Sənəddəki hər agent sitatı artefaktda hərfbəhərf olmalıdır. Sitatı
  «səliqələşdirmək» — bir söz əlavə etmək, tire dəyişmək — hesabatın
  qalanının da etibarını itirir. Skript bunu tutur.
-->

# {{Şirkət}} — {{məhsul}} üzərində ön-audit

| | |
|---|---|
| **Kim etdi** | AgentProof — müstəqil audit · agentproof-site.onrender.com |
| **Nə vaxt** | {{tarix}} |
| **Nə test olundu** | {{açıq demo URL}} |
| **Neçə sual** | {{n}} · hər namizəd {{k}} dəfə təkrarlandı |
| **Neçə sorğu getdi** | {{spent}}/{{limit}} — `{{budget.json}}` |
| **Sifariş edilibmi** | **Xeyr.** Sizdən icazə və ya ödəniş istənməyib |

---

## Bunu niyə aldınız

Sizin agentinizi korporativ alıcının təhlükəsizlik yoxlaması kimi sınadıq və
{{n}} uğursuzluq **eyni səbəbdən {{k}}/{{k}} təkrarlandı**. Aşağıda hər
birinin sualı, cavabı və təkrarlanma jurnalı var.

**Bunlar sizindir.** Bizimlə danışmasanız da saxlayırsınız — heç bir hissə
saxlanılmayıb.

---

## Necə test etdik — və nəyə toxunmadıq

Yalnız açıq demonuza {{spent}} sorğu getdi, bir sessiyada, ardıcıl, sorğular
arası fasilə ilə. Autentifikasiyanın arxasına keçmədik, hesab yaratmadıq,
real şəxsi məlumat daxil etmədik və başqa istifadəçinin datasına çıxmağa
cəhd etmədik.

Bütün qaydalar dərc olunub: **agentproof-site.onrender.com/rules**
Sorğu həddi sənəddə deyil, kodda saxlanılır — büdcə bitəndə qaçış dayanır.

**Test etmədiyimiz istəyirsinizsə**, domeninizi yazın; dayanırıq, topladığımızı
silirik və iki iş günündə təsdiq göndəririk.

---

## Tapıntılar

> Yalnız **{{k}}/{{k}} eyni səbəbdən** sınayanlar buraya düşür. Bir və ya iki
> dəfə sınayanlar §«Kənarda qalanlar»dadır — onlar tapıntı deyil.

### P-1 — {{davranışın bir cümlə ilə ifadəsi}}

**Soruşduq**

> {{sualın tam mətni}}

**Agent cavab verdi**

> {{cavabın müvafiq hissəsi — kəsirsənsə "…" ilə göstər}}

**Niyə səhvdir.** {{İdarəedici qayda / gözlənilən dəyər və onun mənbəyi.
Nəticə düzgün, əsaslandırma səhvdirsə — bunu AÇIQ yaz, çünki determinist
yoxlayıcı belə halı yaşıl boyayır.}}

**Təkrarlanma**

| Cəhd | Nəticə | Səbəb eynidirmi |
|---|---|---|
| 1 | uğursuz | — |
| 2 | uğursuz | bəli |
| 3 | uğursuz | bəli |

**Artefakt.** `{{run_id}}` · `{{fayl yolu}}` · dataset `{{hash}}`

**Nə qədər ciddidir.** {{Pul / uyğunluq / etimad baxımından. Şişirtmə —
şişirdilmiş ciddilik hesabatın qalanını da şübhə altına salır.}}

---

### P-2 — {{...}}

{{eyni struktur}}

---

## Kənarda qalanlar — ölçdük, saymadıq

| Nə | Say | Niyə hesabatda yoxdur |
|---|---:|---|
| Bir-iki dəfə sınadı (flaky) | {{n}} | Təkrarlanma qapısını keçmədi |
| Qiymətləndirilə bilmədi | {{n}} | {{səbəb}} — uğursuzluq DEYİL |
| Qeyri-müəyyən | {{n}} | Qaydanın özü iki cür oxunur |

{{Bu cədvəl boş olsa belə qalır: kənarda qalanı göstərməyən hesabat,
tapıntı sayını şişirdir.}}

---

## Nəyi ölçmədik ⛔

{{Bu bölmə MƏCBURİDİR və hər zaman doludur.}}

- **{{n}} sual, {{sizin sahə}} üzrə tam əhatə deyil.** Tam audit {{N}}+ case
  işlədir; bu, bir zondlamadır.
- **Sizin real korpusunuzu görmədik.** Suallar ictimai demonuzun cavablarından
  çıxarılıb, sizin daxili siyasətlərinizdən yox — yəni «doğru cavab» burada
  **bizim oxuduğumuz**dur, sizin təyin etdiyiniz deyil. Tam auditdə bu tərsinə
  olur.
- **{{usage / retrieval / conversation_id}} ölçülmədi** — demo onu qaytarmır.
  Bu, sıfır demək deyil, **naməlum** deməkdir.
- **Bu sənəddən çıxarıla bilməyən nəticə:** «agent {{x}}%-də səhv edir».
  {{n}} sual belə bir nisbət vermir.

---

## Bundan sonra nə olur

**Heç nə** — istəməsəniz. Yuxarıdakılar sizindir.

İstəyirsinizsə, 20 dəqiqə: tapıntıları addım-addım göstərim və sizin
şəraitinizdə əhəmiyyətli olub-olmadığını birlikdə qərar verək. Audit uyğun
deyilsə bunu deyəcəyəm — quraşdırma işi görmürük, ona görə sizi ona
inandırmaqda marağımız yoxdur.

Tam audit: sabit qiymət, 14 gün, sizin korpusunuz üzərində.
**agentproof-site.onrender.com**

---

*{{ad}} · {{email}} · metod və kod: github.com/pervincinal/agentproof*
