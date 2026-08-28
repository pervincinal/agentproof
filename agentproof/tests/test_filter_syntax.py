"""AP-025 — `--filter` çoxlu dəyər sintaksisi və xəta mesajı.

TƏLƏ. `--filter id=a,b,c` yazmaq təbii görünür, amma vergül **ayrı şərtləri**
ayırır, yəni `b` və `c` açarsız şərt kimi oxunur. Köhnə mesaj səbəbi izah
etmirdi:

    ValueError: --filter sintaksisi: key=value; alındı: 'base-g7-...'

Bu, real bir qaçışı itirdi. İki tərəfli düzəliş:

1. `|` ilə bir açara bir neçə dəyər verilir: `id=a|b|c` = `id=a,id=b,id=c`.
2. Xəta mesajı düzgün formatı GÖSTƏRİR (hər iki variantı).

Mövcud davranış qorunur: `key=value`, təkrar açar = VƏ YA, fərqli açar = VƏ.
"""

from __future__ import annotations

import pytest

from agentproof.runner.task import apply_filter, load_cases, parse_filter
from agentproof.types import Case

DATASET = "evals/datasets/spike.jsonl"


def _cases() -> list[Case]:
    return load_cases(DATASET)


# ------------------------------------------------------------ yeni sintaksis
def test_pipe_expands_into_repeated_key_clauses():
    assert parse_filter("id=a|b|c") == [("id", "a"), ("id", "b"), ("id", "c")]


def test_pipe_is_identical_to_repeating_the_key():
    cases = _cases()
    ids = {c.id for c in cases}
    a, b = sorted(ids)[:2]
    assert (
        {c.id for c in apply_filter(cases, f"id={a}|{b}")}
        == {c.id for c in apply_filter(cases, f"id={a},id={b}")}
        == {a, b}
    )


def test_pipe_works_for_every_key():
    cases = _cases()
    assert {c.id for c in apply_filter(cases, "tag=gap|budget")} == {
        "spike-02-giftcard-gap",
        "spike-03-giftcard-escalates",
        "spike-05-latency-budget",
    }
    assert apply_filter(cases, "severity=high|low")
    assert {c.id for c in apply_filter(cases, "grader=retrieval_hit_at_k|latency_under")} == {
        "spike-04-order-retrieval",
        "spike-05-latency-budget",
    }


def test_pipe_combines_with_other_keys_using_and():
    cases = _cases()
    selected = apply_filter(cases, "tag=gap|budget,severity=low")
    assert {c.id for c in selected} == {"spike-05-latency-budget"}


def test_pipe_tolerates_spaces_around_values():
    assert parse_filter("id=a | b") == [("id", "a"), ("id", "b")]


# ------------------------------------------------------- köhnə davranış sınmır
def test_plain_key_value_still_works():
    assert parse_filter("tag=policy") == [("tag", "policy")]
    assert parse_filter("tag=policy,severity=high") == [
        ("tag", "policy"), ("severity", "high")
    ]
    assert parse_filter(None) == [] and parse_filter("") == []


def test_repeated_key_is_still_or():
    cases = _cases()
    assert {c.id for c in apply_filter(cases, "tag=gap,tag=budget")} == {
        "spike-02-giftcard-gap",
        "spike-03-giftcard-escalates",
        "spike-05-latency-budget",
    }


def test_value_containing_equals_is_kept_whole():
    assert parse_filter("id=a=b") == [("id", "a=b")]


# ------------------------------------------------------------- xəta mesajları
def test_comma_list_error_shows_the_correct_syntax():
    """`id=a,b,c` tələsi: mesaj NƏ yazmaq lazım olduğunu göstərməlidir."""
    with pytest.raises(ValueError) as exc:
        parse_filter("id=base-g7-cancel,base-g8-wording")
    message = str(exc.value)
    assert "id=a|b|c" in message            # dəstəklənən qısa forma
    assert "id=a,id=b,id=c" in message      # təkrar açar forması
    assert "ŞƏRT ayırıcısıdır" in message   # SƏBƏB izah olunur
    assert "tag|severity|grader|id" in message


def test_unknown_key_error_also_shows_the_syntax():
    with pytest.raises(ValueError) as exc:
        apply_filter(_cases(), "kateqoriya=policy")
    assert "naməlum filter açarı" in str(exc.value)
    assert "id=a|b|c" in str(exc.value)


def test_empty_value_is_rejected_with_the_syntax_help():
    for expr in ("id=", "id=a|", "id=|b"):
        with pytest.raises(ValueError) as exc:
            parse_filter(expr)
        assert "boşdur" in str(exc.value)
        assert "id=a|b|c" in str(exc.value)


def test_cli_help_documents_the_pipe_syntax(capsys):
    """`--help` mətni tələni göstərməlidir — sənəd tək yerdə qalmasın."""
    import evals.run as run_module

    with pytest.raises(SystemExit):
        run_module.parse_args(["--help"])
    out = capsys.readouterr().out
    assert "id=a|b|c" in out
    assert "--skip-anchor-check" in out
