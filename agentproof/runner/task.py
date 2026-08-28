"""dataset.jsonl -> Inspect Task (STACK.md §8.4)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from inspect_ai import Task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser

from agentproof.runner.agent import target_agent
from agentproof.runner.bridge import case_context
from agentproof.runner.isolation import LanePool, build_lane_pool
from agentproof.runner.scorer import agentproof_scorer
from agentproof.runner.stages import Stage, filter_stage
from agentproof.types import Case


def _resolve_gold_anchors(cases: list[Case]) -> list[Case]:
    """`doc#clause` gold lövbərlərini hədəfin segment id-lərinə çevirir.

    Dataset-də retrieval gold-ları SABİT lövbərlərdir (`returns-and-refunds.md#2.1`),
    Dify segment UUID-ləri deyil — yenidən indeksləmə bütün UUID-ləri dəyişir və
    xam UUID saxlayan dataset həmin an səssizcə sınır.

    Çevirmə qatı hədəfə aiddir, harness-ə yox: modul yalnız case-də HƏQİQƏTƏN
    lövbər olduqda import olunur, ona görə harness lövbərsiz başqa hədəflərdə
    dəyişmədən işləyir. Modul və ya xəritə yoxdursa — AÇIQ XƏTA, səssiz keçmə yox.
    """
    if not any("#" in str(g) for c in cases for g in c.expect.get("gold_chunks", [])):
        return cases
    try:
        from target.corpus.anchors import resolve_cases  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover — konfiqurasiya xətası
        raise ValueError(
            "dataset `doc#clause` gold lövbərləri işlədir, lakin çevirmə qatı "
            f"(target/corpus/anchors.py) import olunmadı: {exc}"
        ) from exc
    return resolve_cases(cases)


def load_cases(dataset_path: str | Path) -> list[Case]:
    cases: list[Case] = []
    for line_no, line in enumerate(Path(dataset_path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            cases.append(Case.from_dict(json.loads(line)))
        except (ValueError, KeyError) as e:
            raise ValueError(f"{dataset_path}:{line_no} — dataset sətri oxunmadı: {e}") from e
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"{dataset_path}: təkrarlanan case id-ləri: {sorted(dupes)}")
    return _resolve_gold_anchors(cases)


def dataset_hash(cases: Iterable[Case]) -> str:
    payload = json.dumps([c.to_dict() for c in cases], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


FILTER_KEYS = ("tag", "severity", "grader", "id")

#: Xəta mesajı sintaksisi GÖSTƏRMƏLİDİR. `id=a,b,c` yazmaq təbii görünür, amma
#: vergül AYRI şərtləri ayırır — səbəbini deməyən mesaj qaçış itirir (AP-025).
FILTER_SYNTAX_HELP = (
    "  bir açar, bir neçə dəyər (VƏ YA): --filter 'id=a|b|c'\n"
    "  və ya açarı təkrarla            : --filter 'id=a,id=b,id=c'\n"
    "  fərqli açarlar VƏ ilə birləşir  : --filter 'tag=rag,severity=high'\n"
    "  vergül DƏYƏR siyahısı deyil, ŞƏRT ayırıcısıdır — `id=a,b,c` işləmir\n"
    f"  açarlar: {'|'.join(FILTER_KEYS)}"
)


def parse_filter(expr: str | None) -> list[tuple[str, str]]:
    """`tag=policy,severity=high` -> [("tag","policy"), ("severity","high")]

    Bir açarın bir neçə dəyəri `|` ilə də yazıla bilər: `id=a|b|c` tam olaraq
    `id=a,id=b,id=c` ilə eynidir (`apply_filter` təkrar açarları VƏ YA ilə
    birləşdirir). `id=a,b,c` isə İŞLƏMİR — vergül şərt ayırıcısıdır — ona görə
    xəta mesajı düzgün formatı göstərir.
    """
    if not expr:
        return []
    out: list[tuple[str, str]] = []
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(
                f"--filter sintaksisi: key=value; alındı: {part!r}\n" + FILTER_SYNTAX_HELP
            )
        key, raw_value = part.split("=", 1)
        key = key.strip()
        values = [v.strip() for v in raw_value.split("|")]
        if not any(values) or any(not v for v in values):
            raise ValueError(
                f"--filter: {key!r} açarının dəyəri boşdur ({part!r})\n" + FILTER_SYNTAX_HELP
            )
        out.extend((key, value) for value in values)
    return out


def apply_filter(cases: list[Case], expr: str | None) -> list[Case]:
    """Eyni açarın təkrarı VƏ YA, fərqli açarlar VƏ məntiqi ilə birləşir."""
    clauses = parse_filter(expr)
    if not clauses:
        return cases
    by_key: dict[str, list[str]] = {}
    for key, value in clauses:
        by_key.setdefault(key, []).append(value)

    def matches(case: Case, key: str, values: list[str]) -> bool:
        if key == "tag":
            return any(v in case.tags for v in values)
        if key == "severity":
            return case.severity in values
        if key == "grader":
            return case.grader in values
        if key == "id":
            return case.id in values
        raise ValueError(
            f"naməlum filter açarı: {key!r}\n" + FILTER_SYNTAX_HELP
        )

    return [c for c in cases if all(matches(c, k, v) for k, v in by_key.items())]


def select_cases(
    dataset_path: str | Path,
    filter_expr: str | None = None,
    stage: Stage = "all",
) -> list[Case]:
    """Qaçırılacaq case dəsti — Task qurmadan əvvəl yoxlanır (boş ola bilər)."""
    return filter_stage(apply_filter(load_cases(dataset_path), filter_expr), stage)


def _sample_input(case: Case) -> str | list[Any]:
    """Çoxnövbəli case-in BÜTÜN növbələri Sample-a keçir.

    Əvvəllər burada `case.query` (yalnız sonuncu user mesajı) verilirdi — yəni
    çoxnövbəli (C1 sharded) case sükutla tək-növbəli case-ə çevrilirdi. İndi
    tam söhbət `state.messages`-a düşür və adapter onu bütöv görür.

    QEYD (`evals/datasets/COVERAGE.md` §7): `dify_http` adapteri hazırda yalnız
    `req.query`-ni göndərir və `conversation_id`-ni zəncirləmir — yəni C1
    case-ləri bu adapterlə hələ tam ölçülmür. Bu, adapter boşluğudur, dataset
    boşluğu deyil; dataset düzgün kodlaşdırılıb.
    """
    if isinstance(case.input, str):
        return case.input
    return [ChatMessageUser(content=m.get("content", "")) if m.get("role") == "user"
            else ChatMessageAssistant(content=m.get("content", ""))
            for m in case.input]


def build_task(
    dataset_path: str | Path,
    adapter: str,
    adapter_config: dict[str, Any] | None = None,
    filter_expr: str | None = None,
    stage: Stage = "all",
    repeat: int = 1,
    seed: int | None = None,
    reset_url: str | None = None,
    lanes: LanePool | list[dict[str, Any]] | None = None,
) -> tuple[Task, list[Case]]:
    cases = select_cases(dataset_path, filter_expr, stage)
    if not cases:
        raise ValueError(
            f"{dataset_path}: filter={filter_expr!r} stage={stage!r} heç bir case seçmədi. "
            "Boş qaçış yaşıl nəticə kimi görünməməlidir — `select_cases()` ilə əvvəlcədən yoxla."
        )
    pool = lanes if isinstance(lanes, LanePool) else build_lane_pool(lanes, reset_url)
    samples = [
        Sample(input=_sample_input(c), id=c.id, target="", metadata=c.to_dict()) for c in cases
    ]
    task = Task(
        dataset=MemoryDataset(samples, name=Path(dataset_path).stem),
        # `setup` hər sample-dan ƏVVƏL qaçır: case id-sini store-a yazır, çünki
        # Inspect agent-ə yalnız `messages` ötürür (AP-024 — dayandırma səbəbi
        # hansı case-də göründüyü ilə yazılmalıdır).
        setup=case_context(),
        solver=target_agent(
            adapter=adapter,
            adapter_config=adapter_config or {},
            repeat=repeat,
            seed=seed,
            lanes=pool,
        ),
        scorer=agentproof_scorer(),
        name="agentproof",
        metadata={
            "dataset_hash": dataset_hash(cases),
            "stage": stage,
            "adapter": adapter,
            # Hesabatda GÖRÜNMƏLİDİR: izolyasiya var idimi, neçə lane ilə.
            # Gizli qalsa, sürətli amma sızmış qaçış yaşıl görünərdi.
            "isolation": "admin_reset" if pool.isolated else "none",
            "lanes": pool.size,
            "lane_sessions": [lane.session or "" for lane in pool.lanes],
        },
    )
    return task, cases
