"""Il formato del file: le quattro crepe trovate provando il progetto."""

import pytest

from wadachi.desk import (add_log, add_open, add_steps, desk_slug, done_when,
                          next_step, parse_plan, render_desk, section_text,
                          set_meta, tick_step)

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
    out, status = tick_step(trap, "finto, sono un esempio")
    assert status == "not_found"
    assert out == trap


def test_only_the_plan_section_counts():
    """Una checkbox in Aperto non è un passo."""
    trap = DESK.replace("- una domanda", "- [ ] non sono un passo")
    assert next_step(trap) == "secondo"


def test_ticking_a_step_marks_only_that_line():
    out, status = tick_step(DESK, "secondo")
    assert status == "ticked"
    assert "- [x] secondo" in out
    assert "- [ ] quarto" in out
    assert next_step(out) == "quarto"


def test_ticking_an_already_ticked_step_says_so_and_changes_nothing():
    out, status = tick_step(DESK, "primo")
    assert status == "already"
    assert out == DESK


def test_ticking_a_label_that_does_not_exist_says_so_and_changes_nothing():
    """Un typo non deve avere la stessa forma di un successo (finding 3)."""
    out, status = tick_step(DESK, "passo che non esiste")
    assert status == "not_found"
    assert out == DESK


def test_ticking_strips_the_callers_label_before_matching():
    """Il lato file è già spogliato; anche il lato chiamante deve esserlo."""
    out, status = tick_step(DESK, "secondo ")
    assert status == "ticked"
    assert "- [x] secondo" in out


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


def test_set_meta_replaces_an_existing_key():
    out = set_meta(DESK, "slug", "y")
    assert "\nslug: y\n" in out
    assert "\nslug: x\n" not in out


def test_set_meta_on_an_absent_key_leaves_the_text_unchanged():
    out = set_meta(DESK, "status", "closed")
    assert out == DESK


def test_section_text_reads_the_objective_body():
    assert section_text(DESK, "## Obiettivo") == (
        "Fare la cosa.\n**Fatto quando:** i test passano.")


def test_section_text_is_empty_for_an_absent_heading():
    assert section_text(DESK, "## Non c'è") == ""


def test_section_text_does_not_stop_at_a_markdown_h3_inside_the_body():
    """La crepa che il vecchio `split('\\n##')` aveva: una riga che comincia
    per `###` (h3, contenuto legittimo) contiene comunque `\\n##` come
    sottostringa, e quello split ci si sarebbe fermato — perdendo tutto ciò
    che viene dopo, incluso il `Fatto quando`. `_section` guarda `## ` esatto,
    non una sottostringa, quindi non ci casca."""
    trap = DESK.replace(
        "Fare la cosa.",
        "Fare la cosa.\n### nota interna, non un titolo di sezione",
    )
    body = section_text(trap, "## Obiettivo")
    assert "nota interna" in body
    assert "Fatto quando" in body
    assert done_when(trap) == "i test passano."


def test_done_when_reads_the_stopping_condition():
    assert done_when(DESK) == "i test passano."


def test_done_when_is_none_without_an_objective_section():
    assert done_when("nessuna sezione qui") is None


def test_set_meta_inserts_regex_special_characters_literally():
    """Un valore con `.`, `*`, `\\` non deve essere interpretato come regex.

    Con `re.sub` questo valore nella stringa di sostituzione solleverebbe
    `invalid group reference` (prova: `\\1`, `\\g<0>`) — `set_meta` non passa
    mai dal motore delle espressioni regolari."""
    value = r"a.b*c\1d\g<0>"
    out = set_meta(DESK, "slug", value)
    assert f"slug: {value}" in out
