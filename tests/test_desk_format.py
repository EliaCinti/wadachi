"""Il formato del file: le quattro crepe trovate provando il progetto."""

import pytest

from wadachi.desk import (add_log, add_open, add_steps, desk_slug, done_when,
                          next_step, open_steps, parse_plan, render_desk,
                          resolve_step, section_text, set_meta, tick_step,
                          trim_log)

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


def test_open_steps_are_the_unticked_labels_in_order():
    assert open_steps(DESK) == ["secondo", "quarto"]


def test_new_steps_go_before_the_step_named_in_before():
    out = add_steps(DESK, ["terzo bis"], before="quarto")
    assert open_steps(out) == ["secondo", "terzo bis", "quarto"]


def test_two_additions_before_the_same_step_keep_their_order():
    """Per questo è `before` e non `after`: con `after` la seconda aggiunta
    scavalcherebbe la prima."""
    out = add_steps(DESK, ["a"], before="quarto")
    out = add_steps(out, ["b"], before="quarto")
    assert open_steps(out) == ["secondo", "a", "b", "quarto"]


def test_before_ignores_a_checkbox_inside_a_code_fence():
    trap = DESK.replace(
        "- [ ] secondo",
        "- [ ] secondo\n```\n- [ ] quarto\n```",
    )
    out = add_steps(trap, ["nuovo"], before="quarto")
    assert open_steps(out) == ["secondo", "nuovo", "quarto"]
    assert "```\n- [ ] quarto\n```" in out, "il fence resta com'era"


def test_resolve_step_takes_the_whole_label():
    assert resolve_step(DESK, "quarto") == ("quarto", "ok")


def test_resolve_step_takes_a_unique_prefix_of_an_open_step():
    assert resolve_step(DESK, "quar") == ("quarto", "ok")


def test_resolve_step_says_when_a_prefix_is_ambiguous():
    plan = DESK.replace("- [ ] quarto", "- [ ] F10. collaudo\n- [ ] F11. review")
    assert resolve_step(plan, "F1") == (None, "ambiguous")


def test_resolve_step_prefers_the_whole_label_to_a_prefix():
    plan = DESK.replace("- [ ] quarto", "- [ ] F1\n- [ ] F10. collaudo")
    assert resolve_step(plan, "F1") == ("F1", "ok")


def test_resolve_step_says_when_the_step_is_already_ticked():
    assert resolve_step(DESK, "primo") == (None, "done")


def test_resolve_step_says_when_nothing_matches():
    assert resolve_step(DESK, "non esiste") == (None, "not_found")
    assert resolve_step(DESK, "   ") == (None, "not_found")


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


# ── Taglio del registro (piano 2026-10-28-risposte-che-costano-meno) ──


def _desk_with_logs(n: int) -> str:
    text = DESK.replace("- **20:00** — nota vecchia\n", "")
    for i in range(1, n + 1):
        text = add_log(text, f"voce numero {i}", when=f"10:{i:02d}")
    return text


def test_trim_log_keeps_last_three_entries_and_adds_omission_line():
    raw = _desk_with_logs(8)
    trimmed, total, shown = trim_log(raw, keep=3)
    assert total == 8 and shown == 3
    for i in (8, 7, 6):
        assert f"voce numero {i}" in trimmed
    for i in (5, 4, 3, 2, 1):
        assert f"voce numero {i}" not in trimmed
    assert "5 voci omesse" in trimmed
    assert "full=True" in trimmed
    # Tutte le altre sezioni restano intatte
    assert "## Obiettivo\nFare la cosa.\n**Fatto quando:** i test passano." in trimmed
    assert "## Piano\n- [x] primo\n- [ ] secondo\n- [x] terzo fuori ordine\n- [ ] quarto" in trimmed
    assert "## Aperto\n- una domanda" in trimmed


def test_trim_log_leaves_three_or_fewer_entries_untouched():
    for n in (0, 1, 3):
        raw = _desk_with_logs(n)
        trimmed, total, shown = trim_log(raw, keep=3)
        assert total == n and shown == n
        assert trimmed == raw


def test_trim_log_uses_singular_when_one_entry_is_omitted():
    raw = _desk_with_logs(4)
    trimmed, total, shown = trim_log(raw, keep=3)
    assert total == 4 and shown == 3
    assert "1 voce omessa" in trimmed
    assert "voce numero 1" not in trimmed


def test_trim_log_with_keep_none_returns_full_text_and_counts():
    raw = _desk_with_logs(8)
    out, total, shown = trim_log(raw, keep=None)
    assert out == raw
    assert total == 8 and shown == 8


def test_trim_log_keeps_multiline_entries_together():
    raw = _desk_with_logs(4).replace(
        "voce numero 2", "voce numero 2\n  dettaglio seconda riga",
    ).replace(
        "voce numero 1", "voce numero 1\n  dettaglio da omettere",
    )
    trimmed, total, shown = trim_log(raw, keep=3)
    assert total == 4 and shown == 3
    assert "dettaglio seconda riga" in trimmed
    assert "dettaglio da omettere" not in trimmed
