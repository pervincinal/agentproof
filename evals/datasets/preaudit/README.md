# preaudit/ — hədəfə xas ön-audit datasetləri

**Tapşırıq:** AP-056 / AP-071 · **Runbook:** [`docs/PREAUDIT.md`](../../../docs/PREAUDIT.md)

Aurora dataseti metodu nümayiş etdirir. **Ön-audit üçün yaramır** — sualların
doğru cavabı hədəf şirkətin ÖZ dərc etdiyi qaydalarından gəlməlidir, bizim
süni korpusdan yox.

Ona görə hər hədəf üçün 12 case-lik ayrıca dataset qurulur.

---

## Sərhəd — əvvəlcə bunu oxu

**Ground truth burada şirkətin öz ictimai səhifəsidir**, bizim təyin etdiyimiz
dəyər deyil. Bu, ödənişli auditin tam ƏKSİDİR və hər ön-audit sənədində açıq
yazılır (`docs/templates/PREAUDIT-ONEPAGER.md` §«Nəyi ölçmədik»):

> «Doğru cavab» burada **bizim oxuduğumuz**dur, sizin təyin etdiyiniz deyil.

Yəni tapıntı belə oxunur: *«agentiniz sizin öz dərc etdiyiniz qaydadan fərqli
cavab verdi»* — hüquqi və ya sığorta rəyi deyil.

---

## Reseptin özü — 4 addım

### 1 · Şirkətin dərc etdiyi rəqəmləri çıxar

FAQ, yardım mərkəzi, ləğv səhifəsi, sənəd səhifəsi. **Rəqəmi, müddəti, haqqı,
uyğunluq şərtini** olduğu kimi köçür və mənbə URL-ni yaz.

Uydurma dəyər yoxdur. Səhifədə olmayan rəqəm datasetdə də olmur.

### 2 · Tələ ailələrini onların öz mətnindən qur

Aurora-nın ailələri hazır şablondur; onların qarşılığını hədəfin mətnində
axtar:

| Ailə | Nə axtarırsan | Acorn nümunəsi |
|---|---|---|
| **BVA** — kəsilmə nöqtəsi | rəqəmli hədd | 50 gün · 30,000 mil · 40 gün |
| **R6** — qayda toqquşması | eyni mövzuda iki fərqli qayda | claim: ümumi **24 saat**, fleet **72 saat** |
| **Eyni rəqəm, fərqli qayda** | təkrarlanan rəqəm | **48 saat** = cihaz quraşdırma **VƏ** breakdown gözləmə |
| **Əhatə** — ümumiləşdirmə | bir məhsula aid şərt | «no excess» yalnız impound · £25 yalnız ev sığortası |
| **S2** — uydurmaya müqavimət | dərc olunmamış rəqəm | «claim sonrası mükafatım nə qədər artacaq?» |

**Ən dəyərlisi üçüncü sətirdir.** Eyni rəqəmin iki mənası determinist
yoxlayıcını aldadır: cavabda rəqəm var, yəni «keçdi» görünür, halbuki səhv
qaydaya söykənib. Bu, `LIM-I02` və `F-3` ilə eyni sinifdir.

### 3 · Dataseti yaz

`acorn.jsonl` nümunədir. Hər sətir: `id`, `input`, `grader`, `tags`, `expect`,
`severity`, `note`.

`note` sahəsi **məcburidir** — doğru cavabın niyə doğru olduğunu və mənbəni
yazır. Onsuz sən bir ay sonra öz datasetini oxuya bilməyəcəksən.

Qraderlər: `contains_all` (rəqəm gəlməlidir), `contains_none` (səhv iddia
gəlməməlidir), `regex_match` (verdikt formaları).

### 4 · Şablon qur, əl ilə doldur

```bash
python3 evals/make_transcript.py evals/datasets/preaudit/<ad>.jsonl \
  --target <ad> --url <sayt> --repeat 1 \
  --out evals/datasets/preaudit/<ad>-transcript.yaml
```

Skript mesaj sayını **dərc olunmuş 30 həddi ilə** tutuşdurur.

Çatı aç, sualları yaz, cavabları yapışdır. Sonra:

```bash
python3 evals/import_manual.py evals/datasets/preaudit/<ad>-transcript.yaml \
  --dataset evals/datasets/preaudit/<ad>.jsonl --out preaudit/<ad>/phase1
python3 evals/reproduce.py preaudit/<ad>/phase1
```

**Mərhələ 2:** yalnız sınan case-ləri **2 dəfə də** soruş (`--repeat 2`
şablonu), birləşdirilmiş qovluqda `reproduce.py` qaçır. 12 + ≤18 = **≤30**.

---

## Qapı əl ilə yolda da işləyir

Uçdan-uca yoxlanılıb (06.09.2026, uydurma cavablarla):

- 3 cəhd, eyni səbəb → **`stable-fail`** — dərc oluna bilən namizəd
- 1 cəhd, sınsa belə → **`incomplete`** — namizəd DEYİL

Yəni əl ilə toplanmış cavab avtomatik qaçışdan **daha yumşaq qiymətləndirilmir**.

---

## Mühafizələr

`import_manual.py` bunları rədd edir:

| Nə | Niyə |
|---|---|
| `cost_usd`, `latency_ms`, `usage`, `retrieved`, `tool_calls` yazılıbsa | Əl ilə testdə ölçülmür. Sıfır yazmaq «ölçdük, sıfır çıxdı» demək olardı |
| Boş `text` | Doldurulmamış şablon bütün inkar assertion-larından keçər və **uydurma tapıntı** yaradardı |
| `<<PASTE AGENT ANSWER>>` yerində qalıbsa | Eyni səbəb |
| Datasetdə olmayan `case_id` | Sükutla düşən case ölçünü təhrif edir |

---

## Mövcud datasetlər

| Fayl | Hədəf | Case | Mənbə |
|---|---|---:|---|
| `acorn.jsonl` | Acorn Insurance (UK) | 12 | `acorninsure.co.uk/faqs/`, `/policy-cancellation/` — 06.09.2026 |

Növbəti namizədlər: `docs/outreach/targets.md` §3.
