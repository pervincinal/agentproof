# LIMITATIONS.md — nəyi ölçmədik

**Rol:** writer · **Tarix:** 2026-08-27 · **Tapşırıq:** AP-008
**Aidiyyat:** `PLAN.md` Keyfiyyət qaydası №5 · `evals/datasets/COVERAGE.md` §9 ·
`docs/GRADER-AUDIT.md` A-06/A-07 · `docs/JUDGE-CALIBRATION.md` §4.4 ·
`docs/OPS-FINDINGS.md` VALID-02 · `docs/FAILURE-TAXONOMY.md` §14 ·
`target/corpus/TRAPS.md` §11 · `target/DECISION.md` §5 · `target/app/IMPORT.md` §8

---

## 0. Bu sənəd nə üçündür

Biz **audit** satırıq. Auditorun etibarı nəyi tapdığından çox, **nəyi tapmadığını
dürüst deməsindən** gəlir. Məhdudiyyəti gizlədən hesabat bir dəfə tutulanda
bütün iş dəyərsizləşir — o cümlədən düzgün olan hissəsi.

Bu sənəd repo-da AÇIQ elan olunmuş hər məhdudiyyəti bir yerə yığır. Hər bənd
dörd sualı cavablandırır:

1. **Nə ölçülmədi** — konkret, ölçüsü ilə.
2. **Niyə** — qərar idi, yoxsa maneə.
3. **İstiqamət** — bu məhdudiyyət tapıntıları **şişirdir**, yoxsa **gizlədir**?
4. **Azaltmaq üçün nə lazımdır** — konkret iş, mümkünsə tapşırıq ID-si ilə.

**İstiqamət notasiyası** — sənədin ən vacib hissəsi:

| İşarə | Mənası |
|---|---|
| **↑ ŞİŞİRDİR** | Uğursuzluqları real istehsalat şəraitindən **ÇOX** göstərir. Rəqəmimiz pessimistdir. |
| **↓ GİZLƏDİR** | Uğursuzluqları **AZ** göstərir. Real sistem daha pis ola bilər; rəqəmimiz alt həddir. |
| **↔ İKİ TƏRƏFLİ** | Hər iki istiqamətdə səhv verə bilir; xalis təsir ölçülməyib. |
| **⊘ TƏTBİQ OLUNMUR** | Ölçmə ssenarisi bu riski ehtiva etmir; nə şişirdir, nə gizlədir. |

**Doğrulama qaydası:** mənbəsi olmayan bənd bu sənədə düşmür. Mənbə repo-dakı
sənəd, kod sətri və ya qaçış artefaktıdır. Sübutu olmayan, amma qeyd edilməli
olan hallar açıq şəkildə **[təsdiqlənməyib]** işarələnir.

---

## 1. Ölçmə aləti — grader və judge

Bu bölmə **bizim öz alətimizin** qüsurlarıdır, hədəf sistemin yox. İkisini
qarışdırmaq — grader səhvini hədəfin səhvi kimi göstərmək — uydurma tapıntıdır
(`GRADER-AUDIT.md` girişi).

### LIM-I01 · `contains_none` söz sərhədi tanımır — **↑ ŞİŞİRDİR** (nominal)

- **Nə ölçülmədi.** `ContainsNone` grader-i `normalize()` + `in`, yəni **alt-sətir**
  axtarışıdır. `"30 day"` iynəsi nəzəri olaraq `"130 days"` içində də tapılır.
  Datasetdə **39 case** bu grader-i işlədir.
- **Niyə.** Korpusda üç rəqəmli gün/ay dəyəri yoxdur (`CANONICAL.yaml` yoxlanıldı),
  ona görə praktik risk sıfıra yaxındır. `regex_match` + `\b`-ə keçmək 39 case-in
  grader-ini dəyişməyi tələb edir və özü yeni səhv mənbəyidir.
- **İstiqamət.** Nominal olaraq uğursuzluqları şişirdir (düzgün cavabda təsadüfi
  alt-sətir → yalançı sınma). Cari korpusda **praktikada neytral**, çünki
  tetikləyici dəyər yoxdur. Korpus genişlənən gün risk aktivləşir.
- **Azaltma.** AP-016 — `contains_none`-a söz sərhədi gətirmək.
- **Mənbə.** `docs/GRADER-AUDIT.md` A-06 (AÇIQ).

### LIM-I02 · "30 gün" iki fərqli qaydada eyni rəqəmdir — **↑ ŞİŞİRDİR** (təsdiqlənmiş)

- **Nə ölçülmədi.** Grader `return_window_standard`-ın **BAYAT** 30 gününü
  `return_window_plus_member`-in **CARİ** 30 günündən ayıra bilmir.
  Nəticədə agentin tam **düzgün fərqləndirici** cümləsi — «Вы не участник
  Aurora Plus, поэтому расширенное **30-дневное** окно не применяется» — bayat
  dəyər kimi işarələnir.
- **Niyə.** Riski aradan qaldırmaq üçün "yaxınlıq" (proximity) əsaslı assertion
  lazımdır — rəqəm hansı qaydaya bağlanıb. Bu, `graders/canonical.py` bənd
  analizi üzərində ayrıca işdir və multilingual auditin əhatəsindən kənarda idi.
- **İstiqamət.** **Stale-answer rate-i birbaşa şişirdir.** Bu, nəzəri risk deyil:
  həmin cümlə real qaçışda müşahidə olunub (`l1-ru-ord10015-verdict`).
- **Azaltma.** AP-005 — `contains_none` + `stale_days(30)` işlədən HƏR sınmış
  case əl ilə oxunmalı və iki səbətə bölünməlidir: (a) həqiqi bayat dəyər,
  (b) düzgün fərqləndirmə = grader artefaktı. Hesabatda **yalnız (a)** üzərindən
  hesablanmış düzəldilmiş rate işlədilə bilər.
- **Mənbə.** `docs/GRADER-AUDIT.md` A-07 (AÇIQ) · `evals/datasets/COVERAGE.md` §3.

### LIM-I03 · Judge kalibrasiyası REAL qaçırılmayıb — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** `evals/calibration/report.json` hazırda **dry-run null
  modelin** nəticəsidir: `judge_model: "dry-run/constant"`, `agreement: 0.30`,
  `kappa: 0.00`. Qapı (uyğunluq ≥ 85% VƏ κ ≥ 0.70) **heç ölçülməyib**.
- **Niyə.** `ANTHROPIC_API_KEY` mühitdə yoxdur (AP-003 `blocked`).
- **Nəticəsi.** `requires_justification` rubrikasına yönləndirilmiş **3 case**
  (30 gün toqquşması) indiyə qədər ölçülməyib — tam qaçış `--stage cheap` ilə
  gedir. Yəni R6 bloku natamamdır və "147/150 determinist" rəqəmi izahsız qalır.
- **İstiqamət.** Uğursuzluqları gizlədir: determinist grader-in **prinsipcə**
  ayıra bilmədiyi 3 hal ümumiyyətlə qiymətləndirilməyib. PLAN.md qaydası №2-yə
  görə kalibrasiya olunmamış judge nəticəsi **dərc oluna bilməz** — yəni bu
  bölmədən hesabata heç bir rəqəm düşmür.
- **Azaltma.** AP-003 (API açarı mühitə verilməlidir) → sonra AP-004.
- **Mənbə.** `docs/JUDGE-CALIBRATION.md` §4 · `evals/calibration/report.json`.

### LIM-I04 · Judge-in mövqe (position) yanlılığı ölçülmədi — **⊘ TƏTBİQ OLUNMUR**

- **Nə ölçülmədi.** Cüt müqayisədə cavabların yerini dəyişib verdikt sabitliyini
  yoxlayan swap testi.
- **Niyə.** Rubrikamız cüt müqayisə etmir — **tək cavabı** üç sinifə
  (`justified` / `unjustified` / `wrong`) ayırır. Mövqe yanlılığının tətbiq
  sahəsi yoxdur.
- **İstiqamət.** Nə şişirdir, nə gizlədir. Cüt müqayisəli rubrika əlavə olunarsa
  bu bənd yenidən açılmalıdır.
- **Mənbə.** `docs/JUDGE-CALIBRATION.md` §4.4.

### LIM-I05 · Judge-in dil yanlılığı ölçülmədi — **↔ İKİ TƏRƏFLİ** (hazırda hərəkətsiz)

- **Nə ölçülmədi.** AZ/RU cavablar üzərində judge-in insan etiketi ilə uyğunluğu.
  Kalibrasiya dəsti (30 nümunə) yalnız ingiliscədir.
- **Niyə.** Ayrıca etiketli çoxdilli dəst tələb edir; L1 ölçüsü judge-a
  açılmayıb.
- **İstiqamət.** **Hazırda hərəkətsizdir**, çünki judge yalnız 3 ingiliscə
  case-də işlədilir. Çoxdilli case-lər judge-a keçirilən gün istiqamət
  qeyri-müəyyəndir və o vaxta qədər ölçülməlidir — əks halda ölçdüyümüz
  cross-language delta agentin deqradasiyası yox, judge-un artefaktı ola bilər.
- **Mənbə.** `docs/JUDGE-CALIBRATION.md` §4.4.

### LIM-I06 · Genişləndirilmiş 16 pattern canlı cavabla təsdiqlənməyib — **↔ İKİ TƏRƏFLİ**

- **Nə ölçülmədi.** Multilingual auditdə toxunulmuş **16 qeyri-ingilis case**-in
  (giftcard, restocking, warranty, pairwise blokları) yeni pattern-ləri yalnız
  **sintetik nümunələr** və mövcud real cavabların üslubu üzərində yoxlanılıb.
  Audit zamanı `DIFY_BASE_URL` / `DIFY_API_KEY` mühitdə yox idi.
- **Niyə.** Kredensial yoxluğu — maneə, qərar deyil.
- **İstiqamət.** Pattern həm dar (buraxılmış tapıntı = ↓), həm geniş (yalançı
  sınma = ↑) ola bilər. A-01 bu ailənin təsdiqlənmiş nümunəsidir: bir morfoloji
  boşluq tam düzgün cavabı qırmızıya boyamışdı.
- **Azaltma.** Növbəti canlı qaçışdan sonra bu case-lərin cavabları
  `test_real_run_responses_are_graded_pass`-ə əlavə edilməlidir.
- **Mənbə.** `docs/GRADER-AUDIT.md` §"Məhdudiyyət (açıq bildirilir)".

### LIM-I07 · Determinist grader-lər səthi ölçür, semantikanı yox — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Cavabın **mənası**. 150 case-dən 147-si (98%) səth
  uyğunluğu ilə qiymətləndirilir: `regex_match` 85, `contains_none` 39,
  `tool_call_matches` 11, `contains_all` 8, `no_leak` 2, retrieval 2.
- **Niyə.** Şüurlu qərar: judge bahalıdır, qeyri-deterministdir və özü də səhv
  edir. Determinist ölçmə auditdə müdafiə olunandır.
- **İstiqamət.** Uğursuzluqları gizlədir. Ən aydın sinif: **qaçamaq (evasive)
  cavab**. Müsbət verdiktlər `must_not_match` ("rədd nişanəsi YOXDUR") ilə
  ölçülür — mövzunu tamamilə yayındıran, amma rədd sözü işlətməyən cavab bu
  assertion-dan keçir. Boş cavab qorunub (infra xətasında `scorer.py` case-i
  **skip** edir, keçmiş saymır), amma **boş olmayan qaçamaq cavab** qorunmayıb.
  A-08 bunun təsdiqlənmiş nümunəsi idi: «Dəqiq say göstərilməyib» cavabı
  `passed=True` almışdı (grader səviyyəsində bağlandı).
- **Azaltma.** Qaçamaqlıq (evasiveness) üçün ayrıca ölçü — hazırda yoxdur.
- **Mənbə.** `evals/datasets/COVERAGE.md` §8 · `docs/GRADER-AUDIT.md` A-08.

### LIM-I08 · Sabitlik (`consistency_at_k`) ölçüsü köhnədir — **↔ İKİ TƏRƏFLİ**

- **Nə ölçülmədi.** `mode=verdict` rejimində sabitlik. Yeganə mövcud rəqəm
  `reports/pilot/consistency`-dədir və **köhnə** `mode=key_facts` rejimindəndir:
  `agreement 0.67` — 3 cavab eyni qərarı verdi, grader ifadə fərqini
  qeyri-sabitlik saydı. Case sonradan `mode=verdict`-ə keçirilib, amma
  yenidən qaçırılmayıb.
- **İstiqamət.** Köhnə rəqəm qeyri-sabitliyi **şişirdir** (ifadə fərqi qərar
  fərqi sayılıb); yeni rejimdə səth metrikləri (`numbers_agreement`,
  `normalized_agreement`) 1.0 vermir və onların necə təqdim olunacağı qərar
  tələb edir. Xalis istiqamət ölçülməyib.
- **Struktur qeydi.** `pass^k` / qeyri-determinizm ölçüsü **datasetdə deyil,
  qaçış rejimindədir** (`--repeat N`), və aqreqat `consistency_at_k` case-ləri
  ayrıca faylda (`evals/datasets/pilot-consistency.jsonl`) saxlanılır, çünki
  `--repeat` qlobaldır. Yəni əsas 150 case-lik qaçış **öz-özünə sabitlik rəqəmi
  vermir** — o, ayrıca qaçış tələb edir.
- **Azaltma.** AP-006.
- **Mənbə.** AP-006 · `evals/datasets/COVERAGE.md` §9.5 ·
  `agentproof/graders/aggregate/consistency.py` ·
  `evals/datasets/pilot-consistency.jsonl`.

### Bağlanmış məhdudiyyətlər (silinmir — auditdə görünməlidir)

| ID | Nə idi | Necə bağlandı | Təsdiq |
|---|---|---|---|
| **A-08** | Çılpaq rəqəm iynəsi (`contains_all: ["3"]`) tarixin, sifariş nömrəsinin, onluq kəsrin içində tapılırdı → **yalançı YAŞIL** (6 case) | Case yamaqla yox, **grader səviyyəsində**: `graders/deterministic/text.py` → `numeric_spec` + `contains_number`; rəqəm yalnız **müstəqil kəmiyyət tokeni** kimi axtarılır | 8/8 müstəqil yoxlama, hər iki istiqamət (`14` → `within 14 calendar days` tutulur, `2026-08-14` tutulmur) |
| **A-01 – A-05** | AZ/RU morfoloji boşluqları: düşən sait (`невозможен`), inkar şəkilçisi (`bitməyib`), natamam hərf sinfi, `ANY_FIGURE` yalnız ingiliscə vahidlər | `build_full.py` §1b-də pattern-lər genişləndirildi; 20 qeyri-ingilis case-in 18-ində ən azı bir pattern düzəldildi | 133 parametrləşdirilmiş test (`test_multilingual_patterns.py`); `pytest` 339 → 472 |
| **Adapter — çoxnövbəli** | `dify_http` yalnız sonuncu istifadəçi növbəsini göndərirdi və `conversation_id`-ni zəncirləmirdi → 15 çoxnövbəli case tək-növbəli kimi ölçülərdi | Adapter bütün növbələri BİR söhbətdə ardıcıl göndərir; hər növbənin mətni/tool/`usage`/retrieval-ı ayrıca qalır | Canlı Dify-da təsdiqləndi (`pw-02-…-t3` — üç növbə eyni `conversation_id`-də); `test_multi_turn.py`, `test_isolation.py` |

---

## 2. Əhatə — dataset və korpus

### LIM-C01 · 21 həddin kəsilmə nöqtəsi ölçülmür — **↓ GİZLƏDİR** (dəqiqlik itkisi)

- **Nə ölçülmədi.** 36 kanonik həddin hər üç probe nöqtəsi (`n−1` · `n` · `n+1`)
  **108 case** edərdi. Datasetdə **66** var: 15 hədd tam üçlüklə (45 case),
  qalan **21 hədd tək nöqtə** ilə (21 case).
- **Niyə.** 108 case datasetin **72%-ini** tək bir rejimə (G2) verərdi və R6,
  G1, S2, T1, L1, C1 üçün yer qalmazdı — risk əsaslı paylama qaydası pozulardı.
- **İstiqamət.** Tapıntı sayını deyil, **dəqiqliyini** azaldır: tək nöqtəli 21
  hədd üçün yalnız *pozuntu faktı* alınır, *kəsilmə nöqtəsi* yox. «Sistem
  200.01 AZN-də price match qapağını tətbiq etmir» bilinir, «199.99-da düzgün
  idimi» bilinmir. Tək nöqtə qəsdən **məhdudlaşdırıcı** tərəfdən seçilib
  (21 hədin 18-ində `n+1`), çünki uydurma agent həmişə həddən artıq səxavətli
  olur — yəni seçim uğursuzluq tapmağa meyllidir.
- **Mənbə.** `evals/datasets/COVERAGE.md` §2, §9.2.

### LIM-C02 · 27 bayat tələdən 13-ü örtülməyib — **↔ İKİ TƏRƏFLİ**

- **Nə ölçülmədi.** T-04, T-10, T-11, T-12, T-16…T-19, T-21, T-23, T-24, T-26,
  T-27 — **13 tələ** ayrıca case almadı. `stale-answer rate` **14 tələ**
  üzərində hesablanır, 27 üzərində yox.
- **Niyə.** Büdcə: hər tələ üçün ayrıca case datasetin paylamasını pozardı.
  Örtülməyənlərin bir hissəsi sərhəd və pairwise blokları vasitəsilə **dolayı**
  toxunulur, amma ayrıca ölçülmür.
- **İstiqamət.** **Qeyri-müəyyən.** 14 tələ təsadüfi seçilməyib — ən yüksək
  dəyərli və ölçülə bilən tələlərdir, yəni seçim yuxarı meyllidir; digər
  tərəfdən 13 tələnin sınması ümumiyyətlə görünmür. Xalis təsir ölçülməyib.
  Hesabatda məxrəc **açıq yazılmalıdır** ("14 tələ üzərində").
- **Azaltma.** AP-015.
- **Mənbə.** `evals/datasets/COVERAGE.md` §3, §9.1.

### LIM-C03 · 3-yollu kombinator əhatə yoxdur — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Pairwise dəst **100 faktor cütünün 100%-ini** 15 case ilə
  örtür, amma **üçlükləri** yox. `lang=ru × turns=5 × qtype=write_request` kimi
  konkret üçlü qarşılıqlı təsir bu dəstdə **ola bilməz**.
- **Niyə.** 3-yollu əhatə ~45 case tələb edərdi; nəzəri gəlir azdır (nasazlıqların
  əksəriyyəti ən çoxu iki faktorun təsirindən yaranır).
- **İstiqamət.** Yalnız üç faktorun birləşməsində üzə çıxan uğursuzluqlar
  görünmür. "Pairwise 100%" iddiası **cüt** əhatəsidir və hesabatda məhz bu
  formada yazılmalıdır — "bütün kombinasiyalar örtüldü" yox.
- **Mənbə.** `evals/datasets/COVERAGE.md` §6, §9.3.

### LIM-C04 · Çoxnövbəli deqradasiya əyrisi yoxdur — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** *Hansı növbədə sınır* (failure-onset turn). 5 C1 case-i
  yalnız **sınma faktını** verir.
- **Niyə.** Əyri üçün eyni sualın 1/3/5/8 növbəli variantları lazımdır (~20 case).
- **İstiqamət.** Sınma sayını dəyişmir, amma "kontekst uzandıqca pisləşir"
  iddiasını mümkünsüz edir. Uzun söhbətlərdə deqradasiya varsa və 5 növbədən
  sonra başlayırsa, biz onu **görmürük**.
- **Azaltma.** AP-017.
- **Mənbə.** `evals/datasets/COVERAGE.md` §9.4 · `FAILURE-TAXONOMY.md` §10 Boşluq 5.

### LIM-C05 · R4 invariantlıq çevrilmələri ölçülmür — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Typo, parafraz, registr dəyişikliyi və digər sorğu
  formulyasiyası çevrilmələri. Örtülən yeganə çevrilmə **dil**dir (L1).
- **Niyə.** Hər sərhəd case-inin 6 variantı 400+ case edərdi.
- **Diqqət — daxili ziddiyyət.** `FAILURE-TAXONOMY.md` §11 qeydi R4-ün "metod
  olaraq bütün digər testlərin içinə hopdurulduğunu" yazır. Bu, **icra
  olunmayıb**: dataset invariantlıq variantları saxlamır. Taksonomiyanın
  prioritet arqumenti ilə faktiki dataset arasındakı bu fərq hesabatda
  gizlədilməməlidir.
- **İstiqamət.** R4 (P=15, sıra 11) ümumiyyətlə ölçülmür. Sorğu formulyasiyasına
  həssaslıq real sistemlərdə tez-tez rast gəlinən rejimdir — hesabatımız bu
  barədə **heç nə deyə bilmir**.
- **Mənbə.** `evals/datasets/COVERAGE.md` §9.6 · `FAILURE-TAXONOMY.md` §11.

### LIM-C06 · R7 multi-tenant sızması ölçülə bilməz — **⊘ TƏTBİQ OLUNMUR**

- **Nə ölçülmədi.** Kirayəçilər arası kontekst sızması.
- **Niyə.** Quraşdırma tək kirayəçidir; korpus səviyyəsində ssenari mümkün deyil.
- **İstiqamət.** P=10 rejim ölçülməmiş qalır. Çoxkirayəçili müştəri sistemində
  bu ayrıca iş tələb edir və hesabatın nəticələri ora **köçürülə bilməz**.
- **Mənbə.** `evals/datasets/COVERAGE.md` §9.7.

### LIM-C07 · G4 istinad uyğunsuzluğu ölçülmür — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Cavabdakı istinadın həqiqətən gətirilən bəndə uyğun gəlməsi.
- **Niyə.** Hədəf sistem strukturlaşdırılmış istinad qaytarmır — ölçmə obyekti
  yoxdur.
- **İstiqamət.** P=12 rejim görünmür. Agent düzgün rəqəmi səhv bəndə istinadla
  versə, biz bunu **tuta bilmirik**.
- **Mənbə.** `evals/datasets/COVERAGE.md` §9.8.

### LIM-C08 · 38 uğursuzluq rejimindən 12-si birbaşa ölçülür — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Taksonomiya **38 rejim** təyin edir. Datasetdə birbaşa
  büdcə alan rejimlər: **G2, R6, G1, T1, L1, C1, S2, S1, G7, G3, R3, R2** — 12.
  Qalan **26** rejim ayrıca ölçülmür. Onların arasında yüksək prioritetlilər:
  **C4** eskalasiya uğursuzluğu (P=16), **O4** səssiz reqressiya (P=16),
  **R4** (P=15), **S5** PII ifşası (P=15), **L2** çoxdilli təhlükəsizlik boşluğu
  (P=15), **G6** sikofansiya, **C2** kontekst rot, **C3** entity qarışması,
  **T2/T4/T5**, **S3**, **S6**, **O2/O3**, **S4**, **L3**.
- **Qeyd (dəqiqlik üçün).** G6 və C3 5 C1 case-inin **içində** dolayı toxunulur
  (sikofansiya təzyiq pilləsi + entity qarışması), amma ayrıca ölçülmür və
  ayrıca hesablanmır. S5-in bir hissəsi 2 `no_leak` case-i ilə örtülür.
- **İstiqamət.** Hesabat "38 rejimi yoxladıq" **deyə bilməz**. Ölçülməyən 26
  rejimin heç birində uğursuzluq iddiası — nə müsbət, nə mənfi — mümkün deyil.
- **Mənbə.** `docs/FAILURE-TAXONOMY.md` §11 · `evals/datasets/COVERAGE.md` §1.

### LIM-C09 · Korpus kiçikdir — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Böyük kataloqda retrieval deqradasiyası (R2, T6). Korpus
  **8 sənəd, ~40 min simvol**. Real bilik bazaları yüzlərlə sənəddir.
- **İstiqamət.** Tapdığımız retrieval xətaları **alt həddir** — real sistemdə
  daha pis olması gözlənilir.
- **Mənbə.** `target/corpus/TRAPS.md` §11.1.

### LIM-C10 · Korpus struktur baxımından təmizdir (süni korpus) — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Real siyasət sənədlərinin səliqəsizliyi: PDF artefaktları,
  cədvəl pozuntuları, təkrarlanan bölmələr, uyğunsuz başlıq iyerarxiyası.
- **Niyə (üstünlüyü).** Süni korpus **obyektiv ground truth** verir: 96 kanonik
  parametr, 89 tələ, 64 fixture, `verify_fixtures.py` → 1338 assertion. Real
  sənədlərlə "düzgün cavab" özü mübahisəlidir və audit müdafiə olunmur.
- **Zəifliyi.** Korpus chunking üçün "asan"dır.
- **İstiqamət.** Retrieval xətalarını gizlədir (alt hədd). Eyni zamanda
  **ground truth-un dəqiqliyini artırır** — yəni tapdığımız hər tapıntı daha
  etibarlıdır, sadəcə tapıntıların sayı az tərəfə əyilib.
- **Mənbə.** `target/corpus/TRAPS.md` §11.2 · `PLAN.md` §Korpus.

### LIM-C11 · Korpus tək dillidir — **↓ GİZLƏDİR** (L1 üçün)

- **Nə ölçülmədi.** Çoxdilli **korpus** ssenarisi (sənədlərin bir hissəsi AZ,
  bir hissəsi EN). L1 testi yalnız **sorğu dilini** dəyişir; sənəd dili həmişə
  ingiliscədir.
- **İstiqamət.** Ölçdüyümüz cross-language delta **yalnız generasiya qatına**
  aiddir. Çoxdilli korpusda retrieval qatındakı dil uyğunsuzluğu əlavə
  deqradasiya verir və biz onu görmürük. Yəni real çoxdilli sistemdə delta
  daha böyük ola bilər.
- **Mənbə.** `target/corpus/TRAPS.md` §11.3.

### LIM-C12 · Zaman ölçüsü sabitdir — **⊘ TƏTBİQ OLUNMUR** (şüurlu izolyasiya)

- **Nə ölçülmədi.** Eval zamanı siyasətin dəyişməsi. Bütün tool cavabları
  `today: 2026-09-01`-ə pin-lənib; `datetime.now()` çağırışının olmadığı AST
  səviyyəsində yoxlanılır.
- **Niyə.** Heç bir nəticə divar saatından asılı olmamalıdır — `pass^k` üçün
  vacibdir.
- **İstiqamət.** Ölçmənin təkrarlanabilirliyini artırır. Real sistemdəki
  "siyasət eval ortasında dəyişdi" ssenarisi simulyasiya olunmur.
- **Mənbə.** `target/corpus/TRAPS.md` §11.4 · `PLAN.md` §Korpus 3.

### LIM-C13 · `initiate_return` real yazma etmir — **↔ İKİ TƏRƏFLİ**

- **Nə ölçülmədi.** İcazəsiz write-ın **zərəri**. Mock servisdə audit logu var,
  geri qaytarılmayan yan təsir yoxdur.
- **İstiqamət.** T1 ölçüsü **davranışı** ölçür, **zərəri** yox. «Agent icazəsiz
  write etdi» iddiası edilə bilər; «bu, X AZN itki deməkdir» edilə bilməz.
- **Mənbə.** `target/corpus/TRAPS.md` §11.6.

### LIM-C14 · Tələlərin sıxlığı real deyil — **↑ ŞİŞİRDİR** (ən böyük şişirtmə mənbəyi)

- **Nə ölçülmədi.** Real bilik bazasında bayat bəndlərin faktiki nisbəti.
  Bizim korpusda **96 parametrdə 27 bayat cüt** var — real bazadan qat-qat çox.
- **Niyə.** Tələ sıxlığı qəsdən yüksəkdir: az case ilə çox rejim ölçmək üçün.
- **İstiqamət.** **Stale-answer rate mütləq mənada şişirdilmişdir.** Rəqəmimiz
  **nisbi** göstəricidir — sistemlər arası müqayisə üçün etibarlıdır.
  «Production-da hər 4 cavabdan biri bayatdır» kimi ekstrapolyasiya
  **yanlışdır** və hesabatda qadağandır.
- **Mənbə.** `target/corpus/TRAPS.md` §11.5 · `evals/datasets/COVERAGE.md` §9.9.

### LIM-C15 · Injection əhatəsi hücum səthi ilə məhduddur — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Geniş injection payload dəsti. Korpusda **3 dolayı
  injection payload-u** + **1 birbaşa probe** var — cəmi 5 case (S2 + S1).
- **Niyə.** Bu rejim korpusdakı hücum səthi ilə məhdudlaşır, case sayı ilə yox.
- **İstiqamət.** «Sistem prompt injection-a davamlıdır» nəticəsi **çıxarıla
  bilməz**. 4 payload keçilməsi bir red-team nəticəsi deyil.
- **Mənbə.** `evals/datasets/COVERAGE.md` §1 (S2/S1 sətri) · `TRAPS.md` §7.

### LIM-C16 · Taksonomiyanın öz boşluqları — **⊘ / ↓**

- **Nə ölçülmədi** (taksonomiyanın özü də əhatə etmir):
  **səs/telefon kanalı** (ASR səhvləri, kəsilmə) · **multimodal giriş**
  (ekran şəkli, PDF) · **uzunmüddətli yaddaş zəhərlənməsi** (hədəf sistemdə
  persistent memory yoxdur) · **ədalətlilik / demoqrafik yanlılıq** ·
  **supply chain** (LLM04 — model/embedding provayder riski; test deyil, audit
  mövzusudur).
- **İstiqamət.** Bu siniflər hesabatda ümumiyyətlə yoxdur. Xüsusilə
  **ədalətlilik** — dəstək keyfiyyətində demoqrafik yanlılıq ölçülməlidir və
  bu versiyada yoxdur; bunu "problem tapılmadı" kimi oxumaq səhvdir.
- **Mənbə.** `docs/FAILURE-TAXONOMY.md` §14.

---

## 3. Mühit və konfiqurasiya

### LIM-E01 · `top_k=8` seçimi — **↑ ŞİŞİRDİR** (ən aydın şişirtmə)

- **Nə edildi.** Əsas qaçış `top_k=8` ilə aparılır. **Dify-ın agent yolundakı
  faktiki default `top_k` dəyəri 2-dir** (`dataset_retrieval.py:1319` lokal
  defaultu modul səviyyəsindəki `4`-ü kölgələyir; dataset `retrieval_model`-u
  NULL olduqda bu dəyər tətbiq olunur).
- **Niyə.** Tədqiqat sualı *"retrieval bayat bəndi üzə çıxarırmı?"* deyil — bu,
  embedder lotereyasıdır. Sual budur: **"hər iki bənd kontekstdə olanda agent
  onları ayırd edirmi?"** Testin şərti təmin olunmasa, **31 R6 case-i
  (datasetin 21%-i)** səssizcə boş keçər və biz "agent bayat bəndləri yaxşı
  idarə edir" nəticəsi çıxararıq — halbuki heç nə sınanmayıb.
- **İstiqamət — açıq yazılır.** `top_k=8` bayat-bənd uğursuzluqlarını **real
  istehsalat şəraitindən ÇOX göstərir**, çünki default 2-dir. Default
  konfiqurasiya ilə işləyən komanda bu rejimi əksər sorğularda **heç vaxt
  müşahidə etməyəcək**.
- **Amma bu, rejimin olmadığı demək deyil.** Default 2 ilə tələ modelə
  çatmır — yəni uğursuzluq **gizlənir**, aradan qalxmır. Səhv cavab retrieval
  sıralaması dəyişən gün (yeni sənəd, yeni embedder versiyası, fərqli ifadəli
  sual) üzə çıxacaq. Hesabat hər iki cümləni birlikdə deməlidir.
- **[təsdiqlənməyib]** Konfiqurasiya sənədləri **ziddiyyətlidir**: DSL
  (`target/app/aurora-support-agent.yml:149`) və `IMPORT.md §1` datasetin
  `retrieval_model`-unu **`top_k: 4`**-ə pin-ləyir, `OPS-FINDINGS.md` VALID-02
  isə əsas qaçışın **`top_k=8`** ilə aparıldığını yazır. `full-run-02`-nin
  faktiki dəyəri təsdiqlənməlidir (AP-002 DoD §3). Bu təsdiq olmadan R6 bloku
  haqqında heç bir rəqəm dərc edilə bilməz.
- **Mənbə.** `docs/OPS-FINDINGS.md` VALID-02, OPS-03 · AP-002.

### LIM-E02 · Embedder asılılığı — **↔ İKİ TƏRƏFLİ** (nəticə şərtlidir)

- **Ölçülən fakt.** Eyni korpus, eyni sorğu (`"What is the standard return
  window?"`), eyni `semantic_search`, rerank yox. Bayat bəndin (Appendix A,
  ləğv edilmiş 30 günlük pəncərə) retrieval sıralamasındakı yeri:

  | Embedder | Rank | Score |
  |---|---:|---:|
  | `gemini-embedding-001` | **2** | 0.752 |
  | `bge-m3` (lokal, Ollama) | **8** | 0.533 |

- **Nə ölçülmədi.** Retrieval xətalarının nə qədərinin **embedder seçimindən**,
  nə qədərinin agentin özündən doğduğu. Embedding modeli **bir dənə** seçildiyi
  üçün bu ayrım mümkün deyil.
- **İstiqamət.** `top_k=4` ilə Gemini tələni modelə **çatdırır**, `bge-m3`
  **çatdırmır**. Yəni sistemin bu testdən "keçməsi" agentin bacarığı haqqında
  deyil, **embedder seçimi** haqqında məlumat verir. Nəticələr yalnız
  konfiqurasiya ilə birlikdə oxunmalıdır; embedder dəyişəndə istiqamət də
  dəyişir.
- **Oxucuya deyiləsi cümlə.** *"Sizin sisteminizin bu testi keçməsi
  embedder-iniz haqqında agentinizdən çox şey deyir; embedder-i dəyişdiyiniz
  gün bu rejim özü üzə çıxa bilər."*
- **Azaltma.** Ən azı iki embedder ilə paralel qaçış — hazırda büdcədə yoxdur.
- **Mənbə.** `docs/OPS-FINDINGS.md` VALID-02, VALID-01 · `PLAN.md`
  §"Açıq metodoloji məhdudiyyət".

### LIM-E03 · `temperature` bağlana bilmir — **↔ İKİ TƏRƏFLİ**

- **Nə ölçülmədi.** Qeyri-determinizmin konfiqurasiya ilə söndürüldüyü hal.
  **`claude-sonnet-5` sampling parametrlərini rədd edir** — `temperature`,
  `top_p`, `top_k` API-dən çıxarılıb; göndərilsə HTTP 400. Dify tərəfində
  `langgenius/anthropic` 0.3.28 plugin-i onları adaptive-thinking modelləri
  üçün **şərtsiz atır**. Judge tərəfində eyni məhdudiyyət `claude-opus-5`-ə də
  aiddir (`judge.py::_SAMPLING_REJECTED`); Messages API-də **`seed` parametri
  ümumiyyətlə yoxdur**.
- **Nəticəsi.** Qaçışlar arası dəyişkənlik **konfiqurasiya ilə söndürülə
  bilməz**. Yeganə azaldıcı vasitə təkrardır — PLAN.md büdcəsi məhz buna görə
  3 seed nəzərdə tutur. Judge tərəfində determinizm `JudgeCache`
  (`sha256(model + system + user)` barmaq izi) ilə təmin olunur, model
  parametri ilə yox.
- **İstiqamət.** Səs-küy hər iki istiqamətdə işləyir: tək qaçışda görünən
  tapıntı təsadüfi ola bilər (↑), təkrarlanmayan real uğursuzluq itə bilər (↓).
- **Azaltma.** AP-007 — hər case üçün 3 təkrarı üç səbətə bölən alət: hər 3-də
  sındı (stabil) · 1–2-də sındı (flaky) · heç birində sınmadı. **Hesabata
  yalnız stabil səbətdən tapıntı düşür** (PLAN.md qaydası №1).
- **Mənbə.** `target/app/aurora-support-agent.yml:41-45` ·
  `agentproof/graders/judge.py:147-158` · `docs/JUDGE-CALIBRATION.md` §3.

### LIM-E04 · Tək embedder, tək model, tək platforma — **⊘ / köçürülməzlik**

- **Nə ölçülmədi.** Nəticələrin başqa yığıma köçürülməsi. Ölçmə **yalnız** bu
  üçlük üçün etibarlıdır:
  **Dify 1.17.0** (lokal Docker, 16 servis) · SUT **`claude-sonnet-5`**
  (`thinking: false`, `effort: high`, `max_tokens: 4096`) · embedder
  **`bge-m3`** (lokal, Ollama) **[təsdiqlənməyib — `reports/smoke-bge`
  vaxtından çıxarılıb; `RunRecord` embedder sahəsi saxlamır, aşağıda LIM-E06]**.
- **İstiqamət.** Başqa platformaya (Flowise, LangGraph, öz yığım), başqa modelə
  və ya başqa embedder-ə **köçürülməsi sübut edilməyib**. Hesabatın hər
  tapıntısı bu konfiqurasiya ilə birlikdə sitat gətirilməlidir.
- **Mənbə.** `PLAN.md` §Metodologiya qərarları · `target/DECISION.md` §1.

### LIM-E05 · N=3 təkrar — **↓ GİZLƏDİR** (nadir uğursuzluqlar)

- **Nə ölçülmədi.** Nadir, aralıq (intermittent) uğursuzluqlar. Büdcə 150 case
  × **3 seed** ≈ $16 ($20 limiti altında). `FAILURE-TAXONOMY.md` §11 O1
  (qeyri-determinizm, P=15) üçün **"hər test 10 qaçışla"** nəzərdə tuturdu —
  bu, icra olunmayıb.
- **İstiqamət.** 3 təkrarda görünməyən, amma 10-da görünəcək uğursuzluqlar
  **itir**. `pass^3` statistik gücü zəifdir: 3 qaçışda 3 dəfə keçən case-in
  həqiqi keçmə ehtimalı 50%-dən yuxarı olduğunu deyə bilərik, "sabitdir"
  deyə bilmərik.
- **Mənbə.** `PLAN.md` §Metodologiya qərarları · `docs/FAILURE-TAXONOMY.md` §11.

### LIM-E06 · `RunRecord` retrieval konfiqurasiyasını qeyd etmir — **↔ reproduksiya riski**

- **Nə ölçülmədi.** Qaçış artefaktı **embedder adını və `top_k` dəyərini
  saxlamır**. `RunRecord` sahələri: `run_id`, `target`, `target_version`,
  `model`, `dataset_hash`, `started_at`, `results`, `totals`. Retrieval
  konfiqurasiyası yoxdur.
- **Niyə əhəmiyyətlidir.** LIM-E01 və LIM-E02-nin hər ikisi məhz bu iki
  parametrdən asılıdır. Reproduksiya xarici sənədə güvənir — və o sənədlər
  hazırda **bir-biri ilə ziddiyyətlidir** (DSL `top_k: 4` ↔ VALID-02 `top_k=8`).
- **İstiqamət.** Nəticəni əyməz, amma **yenidən yoxlanmasını** çətinləşdirir.
  Auditdə bu, tapıntının özü qədər vacibdir.
- **Azaltma.** `RunRecord`-a retrieval konfiqurasiya bloku əlavə etmək
  (`embedder`, `top_k`, `search_method`, `rerank`).
- **Mənbə.** `agentproof/types.py:329-353` · `reports/smoke-bge/*.json`.

### LIM-E07 · `thinking: false` — **↑ ŞİŞİRDİR** (agent zəiflədilib)

- **Nə edildi.** SUT konfiqurasiyasında adaptive thinking **açıq şəkildə
  söndürülüb** (`thinking: false` → plugin `thinking: {type: disabled}` göndərir).
- **Niyə.** Büdcə qərarıdır, default deyil: açarı buraxsaq API-nin adaptive-on
  defaultu qalır və reasoning tokenləri output hesabına düşür —
  `PLAN.md` təxmini (~1k output token/case) bunu örtmür.
- **İstiqamət.** Bayat bənd ayırd etmə, sərhəd hesablaması və çoxşərtli
  eliqibility məhz reasoning-dən faydalanan tapşırıqlardır. `thinking: false`
  ilə ölçülən uğursuzluq nisbəti eyni modelin thinking açıq konfiqurasiyasından
  **çox olması gözlənilir** — yəni tapıntıları şişirdir. Fərqin ölçüsü
  **ölçülməyib**.
- **Azaltma.** Eyni datasetin `thinking: true` ilə bir qaçışı — büdcədə yoxdur.
- **Mənbə.** `target/app/aurora-support-agent.yml:46-52`.

### LIM-E08 · Xərc rəqəmləri qiymət rejiminə bağlıdır — **↔ tarixdən asılı**

- **Nə ölçülmədi.** Platformanın öz xərc hesabatının doğruluğu — biz ona
  güvənmirik. Dify plugin-i `claude-sonnet-5` üçün `$3.00 / $15.00` sabit
  yazıb; **2026-08-27 tarixinə qüvvədə olan rəsmi qiymət $2/$10-dur**. Yəni
  Dify bu gün xərci **~50% şişirdilmiş** göstərir (pilotda $0.43 hesabladı,
  faktiki ~$0.25).
- **Bizim tərəf.** Xərc `pricing/models.yaml`-dan hesablanır, Dify-ın
  `total_price` sahəsindən yox; `price_table_as_of` hər `RunRecord`-a yazılır.
- **İstiqamət.** Xərc iddiası **tarixə bağlıdır**: eyni qaçış 2026-09-01-dən
  sonra ~50% baha görünəcək ($2/$10 introductory → $3/$15 standard).
  Metodologiya bölməsində qaçış tarixi və tətbiq olunan qiymət rejimi **açıq
  yazılmalıdır** — əks halda xərc rəqəmləri təkrarlana bilməz.
- **Mənbə.** `docs/OPS-FINDINGS.md` OPS-04 (xərc) · `docs/STACK.md` §9 R3.

### LIM-E09 · Tool qatı mockdur, hədəf lokal instansiyadır — **↓ GİZLƏDİR**

- **Nə ölçülmədi.** Real backend davranışı: gecikmə quyruğu (O3), tool
  timeout-ları, qismən uğursuzluqlar, yük altında davranış, şəbəkə
  dəyişkənliyi, xərc sürüşməsi (O2). Tool qatı FastAPI mock servisidir
  (5 tool, port 8099, 64 fixture, sabit saat); hədəf lokal Docker
  instansiyasıdır, production deployment deyil.
- **Niyə.** Mock ground truth-u və izolyasiyanı təmin edir — hər case-dən sonra
  `POST /admin/reset` çağırılır ki, case *n*-də yaradılan RMA case *n+1*-ə
  sızmasın.
- **İstiqamət.** Tool qatındakı real uğursuzluq rejimləri (O2, O3, T3 döngə,
  T6 kataloq deqradasiyası) **görünmür**. Ölçdüyümüz gecikmə (p50 ≈ 11.5 s,
  p95 ≈ 16.4 s — `reports/smoke-bge`) tək kirayəçili boş sistemin gecikməsidir.
- **Mənbə.** `PLAN.md` §Mock tool servisi · `target/corpus/TRAPS.md` §11.6.

### LIM-E10 · `IMPORT.md` marşrutunun bir hissəsi sənəd yazılarkən icra olunmamışdı — **qismən aradan qalxıb**

- **Nə ölçülmədi (yazıldığı anda).** `IMPORT.md` addım 2–6 (UI import, app API
  açarı, canlı `chat-messages` çağırışı) **icra edilməmişdi** — brauzerdə
  hesabla iş scout-un icazə hüdudundan kənardadır. UI marşrutları 1.17.0 web
  build-indən oxunub, DSL sxemi konteyner içindəki mənbədən təsdiqlənib.
- **Cari vəziyyət.** Sonrakı canlı qaçışlar (`reports/smoke-full2`,
  `reports/smoke-bge`, `reports/full-run-*`) app-in işlədiyini göstərir — yəni
  import faktiki olaraq baş verib.
- **Qalıq.** `IMPORT.md` §6-dakı cavab nümunəsinin **rəqəmləri illüstrativdir**
  (sahə adları `service_api` cavab modelindən doğrudur). Bu nümunəyə istinadən
  heç bir ölçmə iddiası qurulmamalıdır.
- **Mənbə.** `target/app/IMPORT.md` §8.

---

## 4. Metodologiya və status

### LIM-M01 · Rəqəmlər nisbidir, mütləq deyil — **↑ ŞİŞİRDİR** (ekstrapolyasiya edilərsə)

- **Qayda.** Bütün rate göstəriciləri (stale-answer rate, pass rate, boundary
  violation rate) **sistemlər və konfiqurasiyalar arası müqayisə** üçün
  etibarlıdır. Production tezliyinə **ekstrapolyasiya edilə bilməz**.
- **Səbəb yığını.** LIM-C14 (tələ sıxlığı) + LIM-E01 (`top_k=8`) + LIM-C02
  (14 tələ məxrəci) + LIM-I02 (A-07 artefaktları) — dördü də eyni istiqamətə,
  yuxarı işləyir.
- **Mənbə.** `target/corpus/TRAPS.md` §11.5 · `evals/datasets/COVERAGE.md` §9.9.

### LIM-M02 · Baseline snapshot yoxdur — **⊘ O4 ölçülə bilmir**

- **Nə ölçülmədi.** Səssiz reqressiya (O4, P=16). Datasetdə `baseline` teqli
  **39 case** var (33 sərhəd `inside`/`edge` + 3 MFT + 3 G7 əks dəsti), amma
  **ilk baseline snapshot-u hələ götürülməyib** (AP-013 `backlog`).
- **İstiqamət.** «Sistemdə reqressiya var / yoxdur» iddiası **mümkün deyil**.
  Baseline olmadan yalnız cari vəziyyət ölçülür.
- **Mənbə.** `evals/datasets/COVERAGE.md` §4 · AP-013.

### LIM-M03 · Stabil/flaky ayrımı aləti hələ yoxdur — **↔ hazırda tətbiq olunmur**

- **Nə ölçülmədi.** PLAN.md qaydası №1 («reproduksiya olunmayan tapıntı
  hesabata düşmür») hazırda **maşınla tətbiq olunmur**. Tam qaçış `--repeat 3`
  ilə gedir, yəni məlumat var, amma qaydanı tətbiq edən alət AP-007-də hələ
  `in_progress`-dir.
- **İstiqamət.** Alət hazır olmadan yazılan hər tapıntı əl ilə yoxlanmalıdır.
  Bu bənd bağlanmadan `FINDINGS.md` (AP-009) yazıla bilməz.
- **Mənbə.** AP-007 · `PLAN.md` Keyfiyyət qaydası №1.

### LIM-M04 · Determinist verdiktlərin insan yoxlaması qismidir — **↔ İKİ TƏRƏFLİ**

- **Nə ölçülmədi.** 150 case-in nəticələrinin sistematik insan doğrulaması.
  Mövcud insan yoxlaması: **30 etiketli nümunə** (yalnız judge rubrikası üçün,
  özü də hələ real qaçırılmayıb — LIM-I03) + multilingual audit probu
  (16 case, hər iki istiqamət) + A-07 triage (AP-005, **hələ edilməyib**).
- **İstiqamət.** Grader artefaktlarının qalan hissəsi ölçülməmişdir. A-01 və
  A-08 göstərdi ki, bu ailə hər iki istiqamətdə səhv verir: A-01 düzgün cavabı
  qırmızıya boyayırdı (görünən), A-08 səhv cavabı yaşıla (görünməz).
- **Mənbə.** `docs/GRADER-AUDIT.md` §"Nə ilə təsdiqləndi" · AP-005.

### LIM-M05 · Hesabatın rəqəmləri hələ mövcud deyil — **STATUS**

- **Vəziyyət (2026-08-27).** Tam qaçış (`full-run-02`, 150 case × 3 təkrar)
  **hələ bitməyib** (AP-002 `in_progress`); `full-run-01` yarımçıq qaldı.
  `RunRecord` yazılana qədər **heç bir tapıntı iddiası edilə bilməz**.
- **Bu sənəd üçün nəticə.** Yuxarıdakı bəndlər dizayn və konfiqurasiya
  məhdudiyyətləridir və qaçışın nəticəsindən asılı deyil. Qaçış bitəndən sonra
  **yenidən yoxlanmalı** olanlar: LIM-E01 (faktiki `top_k`), LIM-E04 (faktiki
  embedder), LIM-I02 (A-07 artefakt sayı), LIM-E03/M03 (flaky səbəti),
  və skip edilmiş case-lərin səbəb kateqoriyaları (AP-002 DoD §2).
- **Mənbə.** AP-002.

---

## 5. İddia → məhdudiyyət xəritəsi

Hesabatın hər iddiası hansı məhdudiyyətlərlə birlikdə oxunmalıdır:

| Hesabatdakı iddia | Bağlı məhdudiyyətlər |
|---|---|
| «Stale-answer rate = X%» | LIM-C14 (sıxlıq ↑) · LIM-E01 (`top_k=8` ↑) · LIM-I02 (A-07 artefaktı ↑) · LIM-C02 (məxrəc 14/27) · LIM-E02 (embedder) |
| «Sərhəd kəsilmə nöqtəsi Y-dədir» | LIM-C01 — yalnız **15 hədd** üçün kəsilmə nöqtəsi var; qalan 21-i üçün yalnız pozuntu faktı |
| «Cross-language delta = Z» | LIM-I06 (patternlər canlı təsdiqlənməyib) · LIM-C11 (korpus tək dilli) · LIM-I05 (judge dil yanlılığı, judge açılarsa) |
| «Pairwise əhatə 100%» | LIM-C03 — **cüt** əhatəsidir, üçlük yox |
| «Agent icazəsiz write etdi» | LIM-C13 — davranış ölçülür, zərər yox |
| «Sistem injection-a davamlıdır/deyil» | LIM-C15 — 4 payload; red-team nəticəsi deyil |
| «Cavablar sabitdir / qeyri-determinizm X%» | LIM-E03 (temperature bağlana bilmir) · LIM-E05 (N=3) · LIM-I08 (consistency ölçüsü köhnə) · LIM-M03 |
| «Xərc $W/case» | LIM-E08 (qiymət rejimi + tarix) · LIM-E09 (mock, yüksüz sistem) |
| «Retrieval hit@k = V» | LIM-E02 (embedder) · LIM-C09 + LIM-C10 (korpus kiçik və təmiz → alt hədd) |
| «Judge verdikti: justified/unjustified/wrong» | LIM-I03 — kalibrasiya qapısı keçilməyib; **dərc edilə bilməz** |
| «Reqressiya yoxdur» | LIM-M02 — baseline yoxdur |
| «Çoxnövbəli söhbətdə N-ci növbədə sınır» | LIM-C04 — deqradasiya əyrisi ölçülmür |
| «38 uğursuzluq rejimi yoxlandı» | LIM-C08 — birbaşa ölçülən **12**-dir |
| «Bu 30 günlük cavab bayatdır» | LIM-I02 — əl ilə oxunmadan bu iddia edilə bilməz (AP-005) |

---

## 6. Bu hesabatdan çıxarıla BİLMƏYƏN nəticələr

Qısa cədvəl — auditin oxucusuna birbaşa ünvanlanır.

| # | Çıxarıla BİLMƏYƏN nəticə | Bloklayan məhdudiyyət | Niyə |
|---|---|---|---|
| 1 | «Production-da hər N cavabdan biri bayatdır» | LIM-C14 · LIM-E01 · LIM-M01 | Tələ sıxlığı süni yüksəkdir, `top_k` defaultdan 4× böyükdür |
| 2 | «Dify bayat bəndləri pis idarə edir» | LIM-E02 · LIM-E04 | Nəticə **embedder şərtlidir**; tək platforma, tək embedder |
| 3 | «`claude-sonnet-5` bu tapşırıqda zəifdir» | LIM-E07 · LIM-E03 · LIM-E04 | Model `thinking: false` ilə qaçırılıb; sampling pin-lənə bilmir |
| 4 | «Sistem prompt injection-a davamlıdır» | LIM-C15 | 3 dolayı + 1 birbaşa payload — red-team deyil |
| 5 | «Agent 38 uğursuzluq rejimindən keçdi» | LIM-C08 | Birbaşa ölçülən 12 rejimdir; 26-sı ölçülməyib |
| 6 | «Retrieval keyfiyyəti yaxşıdır» | LIM-C09 · LIM-C10 · LIM-E02 | Korpus kiçik və təmizdir — nəticə **alt həddir** |
| 7 | «Cavablar sabitdir / qeyri-determinizm yoxdur» | LIM-E05 · LIM-E03 · LIM-I08 | N=3; `temperature` söndürülə bilmir; sabitlik ölçüsü köhnədir |
| 8 | «Sistemdə reqressiya yoxdur» | LIM-M02 | Baseline snapshot götürülməyib |
| 9 | «Uzun söhbətlərdə N-ci növbədən sonra pisləşir» | LIM-C04 | Deqradasiya əyrisi ölçülmür |
| 10 | «Judge X% dəqiqliklə işləyir» | LIM-I03 | Kalibrasiya real modellə qaçırılmayıb (dry-run: 0.30 / κ=0.00) |
| 11 | «Agent AZ/RU-da mütləq X% pisdir» | LIM-I06 · LIM-C11 | Ölçülən **delta**dır; mütləq bal grader əhatəsindən asılıdır |
| 12 | «İcazəsiz write X AZN zərər verir» | LIM-C13 | Mock geri qaytarılmayan yan təsir yaratmır |
| 13 | «Production xərci $W olacaq» | LIM-E08 · LIM-E09 · LIM-M01 | Qiymət rejimi tarixdən asılıdır; sistem yüksüzdür |
| 14 | «Sorğu formulyasiyası nəticəyə təsir etmir» | LIM-C05 | R4 çevrilmələri ümumiyyətlə ölçülmür |
| 15 | «Sistemdə demoqrafik yanlılıq yoxdur» | LIM-C16 | Ədalətlilik bu versiyada ölçülmür |
| 16 | «Sistem çoxkirayəçili mühitdə təhlükəsizdir» | LIM-C06 | Quraşdırma tək kirayəçidir |
| 17 | «Agent istinadları düzgün verir» | LIM-C07 | Hədəf strukturlaşdırılmış istinad qaytarmır |

---

## 7. Yeniləmə qaydası

Bu sənəd `FINDINGS.md` (AP-009) və `docs/writeup.md` (AP-010)-un
**"nəyi ölçmədik"** bölməsinin mənbəyidir. Qaydalar:

1. Yeni məhdudiyyət aşkarlananda **əvvəlcə burada** qeydə alınır, sonra
   hesabata köçürülür.
2. Bağlanan məhdudiyyət silinmir — **"bağlandı" qeydi ilə** saxlanılır
   (A-08 nümunəsi kimi). Silinmiş məhdudiyyət auditdə görünməz olur.
3. Hər bənd mənbə istinadı ilə gəlir. Mənbəsiz bənd ya çıxarılır, ya
   **[təsdiqlənməyib]** işarələnir.
4. **İstiqamət sahəsi məcburidir.** İstiqaməti yazılmamış məhdudiyyət oxucuya
   heç nə vermir — o, bilməlidir ki, rəqəm hansı tərəfə əyilib.
