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


# ------------------------------- AP-027: iki sintaksisin QARIŞIĞI səssiz keçmir
#
# TƏLƏ. `id=a|b|c` (AP-025) və `id=a,id=b` (köhnə) — hər ikisi işləyir. Amma
# qarışığı, `id=a|id=b|id=c`, xəta VERMİRDİ: parser `id=` açarına
# `a|id=b|id=c` dəyərini verirdi, yalnız birincisi uyğun gəlirdi və qaçış
# SƏSSİZCƏ 1 case ilə davam edirdi. 25 case gözlənəndə 1 qaçdı.


def test_mixed_syntax_raises_instead_of_silently_selecting_one_case():
    with pytest.raises(ValueError) as exc:
        parse_filter("id=a|id=b|id=c")
    assert "qarışıq sintaksis" in str(exc.value)


def test_mixed_syntax_error_shows_both_correct_forms():
    with pytest.raises(ValueError) as exc:
        parse_filter("tag=rag|tag=policy")
    message = str(exc.value)
    assert "tag=a|b|c" in message
    assert "tag=a,tag=b,tag=c" in message


def test_mixed_syntax_is_caught_for_every_key_and_anywhere_in_the_list():
    for expr in ("id=a|id=b", "severity=high|severity=low",
                 "grader=x|grader=y", "tag=a,id=b|id=c"):
        with pytest.raises(ValueError):
            parse_filter(expr)


def test_mixed_syntax_never_reaches_apply_filter():
    """Səssiz azaltmanın son nöqtəsi: filtr TƏTBİQ olunmadan dayanır."""
    cases = _cases()
    ids = sorted(c.id for c in cases)[:3]
    mixed = "|".join(f"id={i}" for i in ids)
    with pytest.raises(ValueError):
        apply_filter(cases, mixed)
    # eyni seçim düzgün formada işləyir
    assert len(apply_filter(cases, "id=" + "|".join(ids))) == 3


def test_value_containing_equals_is_still_legitimate():
    """Açar-dəyər bölgüsü İLK `=`-ə görədir — `id=a=b` sınmır."""
    assert parse_filter("id=a=b") == [("id", "a=b")]
    assert parse_filter("id=a=b|c=d") == [("id", "a=b"), ("id", "c=d")]
    assert parse_filter("tag=x,id=a=b") == [("tag", "x"), ("id", "a=b")]


def test_both_documented_syntaxes_survive_the_fix():
    cases = _cases()
    ids = sorted(c.id for c in cases)[:3]
    a, b, c = ids
    assert {x.id for x in apply_filter(cases, f"id={a}|{b}|{c}")} == set(ids)
    assert {x.id for x in apply_filter(cases, f"id={a},id={b},id={c}")} == set(ids)
    assert {x.id for x in apply_filter(cases, f"id={a}")} == {a}
