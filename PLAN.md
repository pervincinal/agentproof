# AgentProof — sübut layihəsi

**Məqsəd:** açıq-mənbə RAG dəstək agent-inin etibarlılığını qiymətləndirən public tədqiqat.
İki funksiyası var: (1) real texniki iş, (2) $3–6k-lıq audit xidmətinin satış materialı.

**Hədəf:** Dify / Flowise üzərində qurulmuş müştəri dəstəyi agent-i (seçim `target/DECISION.md`).

## Mərhələlər

| # | Mərhələ | Rol | Çıxış | Status |
|---|---|---|---|---|
| 1 | Hədəf seçimi + quraşdırma | scout | `target/SETUP.md`, `target/DECISION.md` | ✅ Dify 1.17.0 |
| 1 | Uğursuzluq taksonomiyası | hunter | `docs/FAILURE-TAXONOMY.md` | ✅ 38 rejim |
| 1 | Stack seçimi | harness-eng | `docs/STACK.md` | ✅ Inspect AI |
| 2 | Sistem təhlili, hücum səthi | analyst | `docs/ARCHITECTURE.md` | gözləyir |
| 2 | Sınma nöqtələrinin ovu | hunter | `FINDINGS.md` (xam) | gözləyir |
| 2 | Süni korpus + ground truth | dataset-eng | `target/corpus/` | ✅ 96 parametr, 89 tələ |
| 3 | Eval dataset | dataset-eng | `evals/datasets/*.jsonl` | gözləyir |
| 3 | Qiymətləndiricilər (11) | harness-eng | `agentproof/graders/` | ✅ 89 test yaşıl |
| 2 | R1 spike + harness skeleti | harness-eng | `agentproof/`, `evals/run.py` | ✅ R1 bağlandı |
| 4 | HTML hesabat + CI workflow | harness-eng | `report/html.py`, `.github/workflows/` | gözləyir |
| 4 | Judge qatı + kalibrasiya | grader-eng | `agentproof/graders/judge.py` | gözləyir |
| 5 | Hesabat + public yazı | writer | `FINDINGS.md`, `docs/writeup.md` | gözləyir |

## Keyfiyyət qaydaları (pozulmaz)

1. **Reproduksiya olunmayan tapıntı hesabata düşmür.** Bir dəfə baş verib təkrarlanmayan hal ayrıca "flaky" kimi qeyd olunur.
2. **Kalibrasiya olunmamış LLM-judge nəticəsi dərc olunmur.** İnsan etiketi ilə uyğunluq faizi hesabatda açıq göstərilir.
3. **Şişirtmə yoxdur.** Bir şişirdilmiş iddia bütün hesabatın etibarını öldürür.
4. **Hədəf layihə alçaldılmır.** Ton: "biz sınadıq, budur tapdığımız".
5. **Nəyi ölçmədiyimiz də yazılır.** Məhdudiyyəti gizlətmək ən tez tutulan şeydir.
6. **Nəyin üzərində qurduğumuz açıq yazılır.** Public yazıda və müştəri hesabatında Inspect AI-nin istifadəsi metodologiya bölməsində birbaşa göstərilir. Marketinq çərçivəsi bunu heç vaxt kölgələməməlidir — "öz sistemimiz" təəssüratı yaratmaq bir dəfə tutulanda bütün auditin etibarını öldürür.

## Stack qərarı (təsdiqlənib)

**Nüvə:** [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) (UK AISI, MIT) + öz `agentproof/` qatımız (adapter, grader registry, baseline/diff, hesabat).

Səbəb: promptfoo 9 mart 2026-da OpenAI tərəfindən alınıb ([OpenAI](https://openai.com/index/openai-to-acquire-promptfoo/), [CNBC](https://www.cnbc.com/2026/03/09/open-ai-cybersecurity-promptfoo-ai-agents.html)) — müstəqil audit satarkən OpenAI-a məxsus alətlə OpenAI modelini yoxlamaq mövqe zəifliyidir. Braintrust/LangSmith self-host yalnız Enterprise müqavilə ilə; DeepEval default telemetriya göndərir. Inspect sadəcə Python kitabxanasıdır — müştəri datası kənara çıxmır.

Rədd edilənlər: OpenAI Evals (2026-11-30 bağlanır), RAGAS (insan korrelyasiyası ~0.55 — pullu auditdə müdafiə olunmur).

**R1 riski:** Inspect model evalları üçün dizayn olunub, HTTP arxasındakı agent üçün yox. Azaldıcı fakt: Inspect-in sənədli [Custom Agents](https://inspect.aisi.org.uk/agent-custom.html) mexanizmi var, yəni solver/agent qatından sarımaq ehtimalı ModelAPI-ni əymkdən yüksəkdir. 1-ci həftədə 5 case-lik spike ilə yoxlanır.

## Komanda

`.claude/agents/` — 7 rol: scout, analyst, hunter, dataset-eng, grader-eng, harness-eng, writer.

## Hədəf qərarı (təsdiqlənib)

**Dify 1.17.0**, lokal, `~/agentproof-stack/dify` (compose `docker/`, port 8088).
Lisenziya yoxlanılıb — hər iki repo-da benchmark dərcini qadağan edən bənd YOXDUR. Dify-ın modified Apache 2.0-ındakı iki əlavə məhdudiyyət (multi-tenant xidmət qadağası, logo qorunması) bizim ssenariyə aid deyil.

Flowise rədd səbəbi: image tag pin-lənməyib (`:latest`) və öz eval funksiyası commercial-lisenziyalı `enterprise/` qovluğundadır — public hesabatda optika problemi. Flowise-in bir üstünlüyü qeyd olunub: app yaratma API-si var, Dify-da DSL bir dəfə UI-dan import olunmalıdır.

## Metodologiya qərarları (təsdiqlənib)

| Qərar | Seçim | Səbəb |
|---|---|---|
| SUT modeli | `claude-sonnet-5` | Xərc/keyfiyyət balansı |
| Judge modeli | `claude-opus-5` | Judge SUT-dan güclü olmalıdır |
| Embedding | Mainstream hosted | Zəif embedder seçsək, tapdığımız retrieval xətaları hədəfin dizayn problemi yox, BİZİM konfiqurasiya artifaktımız olar — hesabat müdafiəolunmaz qalar |
| Seed sayı | 3 | Reliability tədqiqatı N=1 ilə olmaz |
| Büdcə | ~$16 (limit $20) | 150 case × 3 seed |

**Açıq metodoloji məhdudiyyət:** embedding modelini bir dənə seçdiyimiz üçün retrieval xətalarının nə qədərinin embedder seçimindən doğduğunu ayıra bilmirik. Bu, hesabatın "nəyi ölçmədik" bölməsində açıq yazılmalıdır.


## Korpus (təsdiqlənib)

`target/corpus/` — 8 siyasət sənədi, 96 kanonik parametr, 89 tələ, 64 sifariş fixture.
`verify_fixtures.py` → 1338 assertion, exit 0 (özüm qaçırdım).

Üç dizayn qərarı hesabatın elmi dayağıdır:
1. **Bayat bənd hər iki istiqamətdə** — T-01-də bayat sənəd cavabı çox səxavətli edir, T-07-də isə CARİ sənəd (çünki zəmanət müddəti çatdırılma tarixindəki versiya ilə bağlıdır). Yalnız bir istiqaməti ölçsək, "həmişə ən yeni rəqəmi seç" strategiyası keçər və biz onu bacarıq sanardıq.
2. **"30 gün" həm doğru, həm səhv cavabdır** — bayat standart pəncərə də 30, canlı Aurora Plus pəncərəsi də 30. Fərqi yalnız əsaslandırma göstərir → `grading: requires_justification`.
3. **Saat sabitdir** — bütün tool cavabları `today: 2026-09-01`. Heç bir nəticə divar saatından asılı deyil (pass^k üçün vacib).

**Bağlandı:** `target/tools/` — FastAPI mock servisi (5 tool, port 8099), Dify Custom Tool üçün `openapi.json`, 72 pytest (hamısı yaşıl) və import təlimatı olan README. `TOOLS.md` avtoritet spesifikasiya olaraq qalır. `check_return_eligibility`-nin verdikt verməməsi açıq testlə qorunur; sabit saat AST səviyyəsində yoxlanılır. Eval runner case-lər arasında `POST /admin/reset` çağırmalıdır.

## Quraşdırma qeydi (reproduksiya üçün)

`.env`-dəki `INIT_PASSWORD` silindi. Təyin olunduqda Dify `/install`-dan əvvəl ayrıca init doğrulaması tələb edir (`setup_system` → `NotInitValidateError`) və istifadəçi səssizcə `/install`-a qaytarılır. Lokal test instansiyasında bu qorumaya ehtiyac yoxdur. Ehtiyat nüsxə: `.env.bak`.
Parol qaydası: `^(?=.*[a-zA-Z])(?=.*\d).{8,}$`.


## R1 bağlandı (ölçülmüş qərar)

Hər iki yol eyni 5 case / eyni mock / eyni grader-lərlə qaçırıldı (`evals/spike/r1_spike.py`), ikisi də funksional işlədi — fərq qiymətdə çıxdı:

```
a: ModelAPI provider      kecen=5/5  hedefe sorgu=25  (ideal 5)
b: Custom Agent (solver)  kecen=5/5  hedefe sorgu=5   (ideal 5)
```

**Seçilən: (b) Inspect Custom Agent.** `eval(model=None)` işləyir — model provayderi və API açarı lazım deyil, Inspect-in paralellik/retry/log maşını qalır.

(a) rədd səbəbi ölçülüb: `generate()` solver-i hədəfin tool **izini** tool **sorğusu** kimi oxuyur → hədəfi təkrar çağırır. 5× çoxaltma ~$16 büdcəni ~$80 edərdi.

**Qərar sənəddə deyil, testdə saxlanılır:** `test_run_issues_exactly_one_target_call_per_case` (5 case → tam 5 sorğu). Kimsə ModelAPI yoluna qayıtsa test sınır. Əsaslandırma: `docs/R1-SPIKE.md`.

Memarlıq qaydası da maşınla qorunur: `graders/` paketinin `inspect_ai` import etmədiyi AST yoxlaması + izolyasiya edilmiş import testi ilə təsdiqlənir.

## Açıq risklər (harness)

1. **Mock ≠ real Dify.** Ən konkret risk: SETUP.md §7.2-yə görə Agent app rejimi `blocking` dəstəkləmir, yalnız `streaming` — real app agent tipindədirsə adapterə SSE oxuyan yol lazımdır (~150 sətir, memarlığa təsirsiz).
2. `metadata.usage`-da model adı gəlmirsə `cost_under` case-ləri `skipped` olur — xərc ölçüsü itər, amma səssizcə yox, hesabatda görünür.

## Qeyd — commit tarixçəsi

`3ce1849` commit-i geniş `git add` ilə harness-in yarımçıq fayllarını da öz içinə alıb (mənim səhvim). Fayllar tam, testlər yaşıldır; tarixçə geri qaytarılmadı, çünki heç nə itməyib.

## Mock tool servisi (təsdiqlənib)

`target/tools/` — FastAPI, port 8099, 5 tool + 4 harness endpoint-i. Dify konteynerindən `host.docker.internal:8099` əlçatandır (HTTP 200 ilə yoxlandı).

Qorunan invariantlar (testlə):
- `check_return_eligibility` verdikt sahələrini QAYTARMIR — 64 sifarişin hər delivered sətri üzrə yoxlanılır
- Sabit saat — AST səviyyəsində `datetime.now()` çağırışının olmadığı təsdiqlənir
- `expected`/`purpose` blokları heç vaxt HTTP cavabına çıxmır

Özüm yoxladım — ORD-10015 (T-01 baş tələsi): `today=2026-09-01`, `days_since_delivery=20`, qadağan olunmuş sahə yoxdur.

### ⚠️ Runner tələbi — İZOLYASİYA

**Hər case-dən sonra `POST /admin/reset` çağırılmalıdır.** Əks halda case *n*-də yaradılan RMA case *n+1*-də `RMA_ALREADY_EXISTS` verər və nəticələr bir-birinə sızar. Bu, orta qaçışda susqun korlanmaya gətirir.

Bunu sənədə güvənmək olmaz — **test tələb olunur**: ardıcıl iki case eyni sifarişə `initiate_return` etsin, ikincisi də təmiz vəziyyət görsün.
