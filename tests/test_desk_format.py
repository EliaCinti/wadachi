"""Il formato del file: le quattro crepe trovate provando il progetto."""

import pytest

from wadachi.desk import (add_log, add_open, add_steps, desk_slug, next_step,
                          parse_plan, render_desk, tick_step)

DESK = """---
type: desk
slug: x
---

## Obiettivo
Fare la cosa.
**Fatto quando:** i test passano.

## Piano
- [x] primo
- [ ] secondo
- [x] terzo fuori ordine
- [ ] quarto

## Registro
- **20:00** — nota vecchia

## Aperto
- una domanda
"""


def test_the_next_step_is_the_first_unticked_even_out_of_order():
    assert next_step(DESK) == "secondo"


def test_a_finished_plan_has_no_next_step():
    done = DESK.replace("- [ ]", "- [x]")
    assert next_step(done) is None


def test_a_checkbox_inside_a_code_fence_is_not_a_step():
    """Un passo che contiene un esempio di codice non genera passi fantasma."""
    trap = DESK.replace(
        "- [ ] secondo",
        "- [ ] secondo\n```\n- [ ] finto, sono un esempio\n- [x] anche io\n```",
    )
    assert [l for _, l in parse_plan(trap)] == [
        "primo", "secondo", "terzo fuori ordine", "quarto"]
    assert next_step(trap) == "secondo"


def test_tick_step_respects_code_fences_in_the_plan():
    """Una linea dentro un fence non è un passo, quindi non si può spuntare."""
    trap = DESK.replace(
        "- [ ] secondo",
        "- [ ] secondo\n```\n- [ ] finto, sono un esempio\n```",
    )
    out, already = tick_step(trap, "finto, sono un esempio")
    assert already is False
    assert out == trap


def test_only_the_plan_section_counts():
    """Una checkbox in Aperto non è un passo."""
    trap = DESK.replace("- una domanda", "- [ ] non sono un passo")
    assert next_step(trap) == "secondo"


def test_ticking_a_step_marks_only_that_line():
    out, already = tick_step(DESK, "secondo")
    assert already is False
    assert "- [x] secondo" in out
    assert "- [ ] quarto" in out
    assert next_step(out) == "quarto"


def test_ticking_an_already_ticked_step_says_so_and_changes_nothing():
    out, already = tick_step(DESK, "primo")
    assert already is True
    assert out == DESK


def test_a_log_line_goes_on_top():
    out = add_log(DESK, "cosa nuova", when="21:00")
    reg = out.split("## Registro")[1]
    assert reg.index("cosa nuova") < reg.index("nota vecchia")


def test_an_open_question_goes_at_the_bottom():
    out = add_open(DESK, "un'altra domanda")
    ap = out.split("## Aperto")[1]
    assert ap.index("una domanda") < ap.index("un'altra domanda")


def test_new_steps_are_appended_unticked():
    out = add_steps(DESK, ["quinto", "sesto"])
    assert [l for _, l in parse_plan(out)][-2:] == ["quinto", "sesto"]
    assert next_step(out) == "secondo"


def test_a_title_that_slugifies_to_nothing_is_refused():
    with pytest.raises(ValueError):
        desk_slug("   ", taken=set())
    with pytest.raises(ValueError):
        desk_slug("☕", taken=set())


def test_two_desks_with_the_same_title_get_different_slugs():
    first = desk_slug("Sistemare il deploy", taken=set())
    second = desk_slug("Sistemare il deploy", taken={first})
    assert first != second and second.startswith(first)


def test_render_produces_a_file_the_parser_understands():
    text = render_desk(
        meta={"slug": "s", "title": "T", "project": "p",
              "status": "open", "created": "t", "updated": "t"},
        objective="Fare la cosa.",
        done_when="i test passano.",
        plan=["uno", "due"],
    )
    assert text.startswith("---\n")
    assert next_step(text) == "uno"
    assert "**Fatto quando:** i test passano." in text
