# PREFLIGHT.md — hədəfin ölçüləbilirliyi (auditdən ƏVVƏL)

**Rol:** harness-eng · **Tarix:** 2026-09-01 · **Tapşırıq:** AP-032
**Aidiyyat:** `agentproof/preflight.py` · `docs/ADAPTERS.md` ·
`docs/LIMITATIONS.md` (LIM-I09, LIM-E06)

---

## 0. Nə üçündür

Satış zəngindən sonrakı ilk texniki sual "sizin sisteminizi ölçə bilərikmi?"
olur. `health()` yalnız "canlıdır" deyir. Əsl sual isə **nəyi ölçə bilərik**:

* hədəf `retrieved[]` vermirsə -> `retrieval_hit_at_k`, `precision_at_k` YOX;
* `tool_calls` vermirsə -> `tool_call_matches` YOX;
* `usage` vermirsə (və ya model etiketi yoxdursa) -> `cost_under` YOX;
* söhbəti zəncirləyə bilmirsə -> kontekst itkisi (C1) ölçülmür.

Preflight bunu **3 sorğu** ilə deyir və çıxışı birbaşa müştəri sənədinə
köçürülə bilər.

## 1. İstifadə

```bash
export DIFY_API_KEY=... DIFY_BASE_URL=http://localhost:8088/v1
python -m agentproof.preflight --target dify_http --model claude-sonnet-5

# öz JSON servisinizə qarşı
export AGENTPROOF_JSON_URL=https://api.acme.internal/agent/invoke
export AGENTPROOF_JSON_API_KEY=...
export AGENTPROOF_JSON_MAP=./acme-map.json      # sahə xəritəsi (docs/ADAPTERS.md)
python -m agentproof.preflight --target json_http --model claude-sonnet-5 \
    --out-md reports/preflight.md --out-json reports/preflight.json
```

Faydalı açarlar: `--probe "<sual>"` (bilik bazasına və tool-a toxunan sual
verin), `--follow-up` (çoxnövbəli zondun növbələri), `--memo ORD-10001`
(xatırlanmalı nişan), `--no-multi-turn` (2 sorğuya qənaət), `--json`.

`callable` hədəfi CLI-dan qurula bilmir (`fn` bir Python obyektidir):

```python
report = asyncio.run(run_preflight(adapter, target="callable"))
print(render_markdown(report))
```

Çıxış kodu: cavab alınmayıbsa `1` — CI-da qapı kimi işlədilə bilər.

## 2. Zondlar

| # | Zond | Nə deyir |
|---|------|----------|
| 1 | health | adapter hədəfə çatır |
| 2 | answer | tək növbəli sorğuya mətn qayıdır |
| 3 | tool_calls | icra olunan tool-lar cavabda görünür |
| 4 | retrieved | bilik bazası parçaları cavabda görünür |
| 5 | usage | token hesabı cavabda görünür |
| 6 | cost | `cost_under` HƏQİQƏTƏN qərar verə bilir |
| 7 | multi_turn | söhbət zəncirlənir və kontekst qalır |

2–6 **bir** sorğudan oxunur (hər ölçü üçün ayrıca sorğu göndərmək eyni məlumatı
iki qat pula alardı), 7 isə iki növbə göndərir.

## 3. Oxumağın üç qaydası

**(a) `XEYR` ≠ `XƏTA`.** `XEYR` hədəfin məhdudiyyətidir və hesabata düşür.
`XƏTA`/`keçildi` isə **bizim** ölçə bilmədiyimizdir — bundan məhdudiyyət
nəticəsi çıxarmaq müştəriyə olmayan bir problem danışmaqdır. Ona görə hesabatda
"Ölçülməmiş qalan zondlar" ayrıca bölmədir və o grader-lər "işləyir" siyahısına
DÜŞMÜR, "təsdiqlənmədi" kimi göstərilir.

**(b) 5-ci və 6-cı sətir eyni şey deyil.** Canlı Dify 1.17 `usage` verir, amma
model adını vermir; `cost_under` isə qiymət cədvəlində model tapmasa `skipped`
qaytarır. Ona görə xərc zondu sahəyə deyil, **grader-in öz qərarına** baxır.
`--model` verilmədən canlı qaçışın çıxışı belədir:

```
| 5 | Token hesabı görünür               | bəli | in=8935 out=364; model etiketi YOXDUR |
| 6 | Xərc hesablana bilir (`cost_under`)| XEYR | qiymət cədvəlində model yoxdur: ''    |
```

**(c) Gecikmə profili paylanma deyil.** 3 ölçmədən median çıxarmaq olar, amma
p95 çıxarmaq olmaz. Real profil tam qaçışdan gəlir.

## 4. Canlı nümunə (Dify 1.17, `claude-sonnet-5`, 2026-09-01)

```
| 1 | Hədəf əlçatandır                    | bəli | health() True
| 2 | Tək növbəli sorğuya mətn qaytarır   | bəli | 615 simvol cavab
| 3 | İcra olunan tool-lar görünür        | bəli | 2 çağırış: dataset_1623dd7e_…, lookup_order
| 4 | Retrieval parçaları görünür         | bəli | 8 parça, id nümunəsi: '7ddbd583-63fa-…'
| 5 | Token hesabı görünür                | bəli | in=8935 out=392; model: claude-sonnet-5
| 6 | Xərc hesablana bilir (`cost_under`) | bəli | bu zondun xərci $0.032685
| 7 | Çoxnövbəli söhbət zəncirlənir       | bəli | 2 növbə bir söhbətdə, nişan xatırlandı

Gecikmə: 3 ölçmə — min 1953 ms · median 5306 ms · maks 9293 ms
```

Bu hədəfdə 12 grader-in hamısı işləyir. Diqqət: 4-cü sətirdəki id **Dify
segment UUID-sidir**, korpusdakı `sənəd#bənd` lövbəri deyil — `retrieval_*`
grader-ləri üçün lövbər xəritəsi lazımdır (`target/corpus/anchors.py`,
`docs/LIMITATIONS.md`).

## 5. Müştəri hesabatına nə köçürülür

`--out-md` çıxışının "Nəyi ÖLÇƏ BİLMİRİK" bölməsi birbaşa auditin
"nəyi ölçmədik" hissəsinin xammalıdır. Zəngdə deyiləcək cümlə budur:

> Sizin sistemdə bu ölçülər mümkün deyil — `<grader adları>` — çünki API
> `<sahə>` qaytarmır. Qalan `<N>` grader işləyir.
