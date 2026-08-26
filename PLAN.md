# AgentProof — sübut layihəsi

**Məqsəd:** açıq-mənbə RAG dəstək agent-inin etibarlılığını qiymətləndirən public tədqiqat.
İki funksiyası var: (1) real texniki iş, (2) $3–6k-lıq audit xidmətinin satış materialı.

**Hədəf:** Dify / Flowise üzərində qurulmuş müştəri dəstəyi agent-i (seçim `target/DECISION.md`).

## Mərhələlər

| # | Mərhələ | Rol | Çıxış | Status |
|---|---|---|---|---|
| 1 | Hədəf seçimi + quraşdırma | scout | `target/SETUP.md`, `target/DECISION.md` | işləyir |
| 1 | Uğursuzluq taksonomiyası | hunter | `docs/FAILURE-TAXONOMY.md` | işləyir |
| 1 | Stack seçimi | harness-eng | `docs/STACK.md` | işləyir |
| 2 | Sistem təhlili, hücum səthi | analyst | `docs/ARCHITECTURE.md` | gözləyir |
| 2 | Sınma nöqtələrinin ovu | hunter | `FINDINGS.md` (xam) | gözləyir |
| 3 | Eval dataset | dataset-eng | `evals/datasets/*.jsonl` | gözləyir |
| 3 | Qiymətləndiricilər | grader-eng | `evals/graders/` | gözləyir |
| 4 | Qaçış mühərriki + CI | harness-eng | `evals/run.py`, `.github/workflows/` | gözləyir |
| 5 | Hesabat + public yazı | writer | `FINDINGS.md`, `docs/writeup.md` | gözləyir |

## Keyfiyyət qaydaları (pozulmaz)

1. **Reproduksiya olunmayan tapıntı hesabata düşmür.** Bir dəfə baş verib təkrarlanmayan hal ayrıca "flaky" kimi qeyd olunur.
2. **Kalibrasiya olunmamış LLM-judge nəticəsi dərc olunmur.** İnsan etiketi ilə uyğunluq faizi hesabatda açıq göstərilir.
3. **Şişirtmə yoxdur.** Bir şişirdilmiş iddia bütün hesabatın etibarını öldürür.
4. **Hədəf layihə alçaldılmır.** Ton: "biz sınadıq, budur tapdığımız".
5. **Nəyi ölçmədiyimiz də yazılır.** Məhdudiyyəti gizlətmək ən tez tutulan şeydir.

## Komanda

`.claude/agents/` — 7 rol: scout, analyst, hunter, dataset-eng, grader-eng, harness-eng, writer.
