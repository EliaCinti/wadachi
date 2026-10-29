"""La scrivania nello store: ciclo di vita, ripresa, confine con le memorie."""

import random
import threading
import time

import pytest

from wadachi.desk import parse_plan
from wadachi.store import MemoryStore


@pytest.fixture
def s(tmp_path):
    return MemoryStore(str(tmp_path / "brain"))


def _open(s, **kw):
    kw.setdefault("title", "M34 fetta 4")
    kw.setdefault("objective", "Spostare sign_in nel tratto.")
    kw.setdefault("done_when", "la suite passa")
    kw.setdefault("plan", ["leggere", "estrarre", "verificare"])
    kw.setdefault("project", "overmind")
    return s.open_desk(**kw)


def test_a_desk_opens_and_is_found_again(s):
    d = _open(s)
    got = s.read_desk(d["slug"], project="overmind")
    assert got["title"] == "M34 fetta 4"
    assert got["next_step"] == "leggere"
    assert (s.brain_dir / got["filepath"]).exists()


def test_a_desk_without_a_stopping_condition_is_refused(s):
    with pytest.raises(ValueError):
        _open(s, done_when="   ")
    assert s.list_desks(project="overmind") == []


def test_a_brand_new_store_resumes_the_work(s, tmp_path):
    """Il test che conta: una sessione aperta domani ritrova il punto."""
    _open(s)
    s.log_desk(project="overmind", done="leggere", note="fatto in fretta")

    fresh = MemoryStore(str(tmp_path / "brain"))     # nessuno stato in memoria
    got = fresh.read_desk(project="overmind")
    assert got["next_step"] == "estrarre"
    assert "fatto in fretta" in got["text"]


def test_reading_without_a_slug_needs_exactly_one_open_desk(s):
    _open(s, title="prima")
    _open(s, title="seconda")
    got = s.read_desk(project="overmind")
    assert got is None or got.get("ambiguous")
    assert len(s.list_desks(project="overmind")) == 2


def test_ticking_a_step_already_done_says_so(s):
    _open(s)
    s.log_desk(project="overmind", done="leggere")
    out = s.log_desk(project="overmind", done="leggere")
    assert out["already_done"] is True
    assert out["next_step"] == "estrarre"


def test_ticking_a_typo_says_so_instead_of_pretending_success(s):
    """Un'etichetta sbagliata non deve avere la forma di una spunta riuscita
    (finding 3): niente avanza, e il chiamante riceve i nomi veri."""
    _open(s)
    out = s.log_desk(project="overmind", done="passo che non esiste")
    assert out["already_done"] is False
    assert out["next_step"] == "leggere", "il cursore non deve muoversi su un typo"
    assert "error" in out
    assert out["known_steps"] == ["leggere", "estrarre", "verificare"]


def test_ticking_strips_a_trailing_space_the_caller_left_on(s):
    """Il lato file è già spogliato; il lato chiamante deve esserlo anche lui."""
    _open(s)
    out = s.log_desk(project="overmind", done="leggere ")
    assert "error" not in out
    assert out["next_step"] == "estrarre"


def test_reading_a_desk_whose_file_was_deleted_does_not_crash(s):
    """Finding 1: un file cancellato a mano (Obsidian, o `rm`) non deve far
    esplodere read_desk — e la riga che lo rivendicava esce dall'indice."""
    d = _open(s)
    (s.brain_dir / d["filepath"]).unlink()
    out = s.read_desk(d["slug"], project="overmind")
    assert out is not None
    assert out.get("missing_file") is True
    assert "error" in out
    assert d["slug"] not in [row["slug"] for row in s.list_desks(project="overmind", status=None)]


def test_logging_to_a_desk_whose_file_was_deleted_does_not_crash(s):
    d = _open(s)
    (s.brain_dir / d["filepath"]).unlink()
    out = s.log_desk(project="overmind", done="leggere")
    assert out.get("missing_file") is True
    assert "error" in out


def test_a_missing_desk_file_leaves_a_trace_whichever_tool_finds_it(s):
    """read_desk registrava `desk_missing` nel log delle operazioni,
    log_desk lo cancellava in silenzio — una cancellazione senza traccia,
    l'unica cosa che questo progetto non accetta. Ora passano dallo stesso
    punto (_forget_missing_desk): qualunque strumento scopra il file
    sparito, il log lo sa."""
    via_read = _open(s, title="via read_desk")
    (s.brain_dir / via_read["filepath"]).unlink()
    s.read_desk(via_read["slug"], project="overmind")

    via_log = _open(s, title="via log_desk")
    (s.brain_dir / via_log["filepath"]).unlink()
    s.log_desk(via_log["slug"], project="overmind", done="leggere")

    log = (s.brain_dir / "log.md").read_text(encoding="utf-8")
    assert f"desk_missing — overmind/{via_read['slug']}" in log
    assert f"desk_missing — overmind/{via_log['slug']}" in log


def test_closing_updates_the_files_updated_frontmatter_too(s):
    """close_desk aggiornava `updated_at` nel DB ma non `updated:` nel file,
    mentre `status:` sì — un'incoerenza economica da chiudere."""
    d = _open(s)
    before = (s.brain_dir / d["filepath"]).read_text(encoding="utf-8")
    before_updated = next(l for l in before.split("\n") if l.startswith("updated: "))
    s.close_desk(d["slug"], "done", project="overmind")
    archived = s.brain_dir / "desks" / "overmind" / "archived" / f"{d['slug']}.md"
    after = archived.read_text(encoding="utf-8")
    after_updated = next(l for l in after.split("\n") if l.startswith("updated: "))
    assert after_updated != before_updated


def test_two_sequential_sessions_reading_back_both_see_both_notes(s, tmp_path):
    """Due sessioni che annotano una dopo l'altra: nessuna sovrascrive l'altra.

    Le due scritture qui sono in sequenza (la prima commit-a e chiude prima
    che la seconda cominci) — prova solo che due `MemoryStore` diversi
    rileggono lo stesso file dal disco, non che le scritture in corsa sono
    serializzate. Per quella vedi
    `test_concurrent_notes_from_many_threads_are_all_preserved` sotto."""
    d = _open(s)
    other = MemoryStore(str(tmp_path / "brain"))
    s.log_desk(project="overmind", note="dalla prima sessione")
    other.log_desk(project="overmind", note="dalla seconda sessione")
    text = s.read_desk(d["slug"], project="overmind")["text"]
    assert "dalla prima sessione" in text
    assert "dalla seconda sessione" in text


def test_concurrent_notes_from_many_threads_are_all_preserved(s, tmp_path):
    """Il test che conta davvero: scritture in corsa, non in sequenza.

    Sei thread — ciascuno con il proprio `MemoryStore` sullo stesso brain,
    come sei sessioni MCP separate — annotano la stessa scrivania quasi nello
    stesso istante. Se `_write()` (BEGIN IMMEDIATE) non serializzasse
    davvero le scritture sul file, l'ultima a fare `_atomic_write_text`
    vincerebbe e le note delle altre sparirebbero. Una breve pausa casuale
    prima della chiamata incoraggia la sovrapposizione."""
    d = _open(s)
    n = 6
    notes = [f"nota concorrente numero {i}" for i in range(n)]
    errors: list[BaseException] = []

    def worker(note: str) -> None:
        try:
            time.sleep(random.uniform(0, 0.05))
            store = MemoryStore(str(tmp_path / "brain"))
            store.log_desk(project="overmind", note=note)
        except BaseException as exc:  # captured, not raised, from a thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(note,)) for note in notes]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "un thread non è mai tornato (lock timeout?)"
    assert not errors, f"scritture concorrenti fallite: {errors!r}"

    text = s.read_desk(d["slug"], project="overmind")["text"]
    missing = [note for note in notes if note not in text]
    assert not missing, f"note perse in scrittura concorrente: {missing}"


def test_a_desk_never_appears_in_recall(s):
    _open(s, objective="zxqwvunicorno parola irripetibile")
    from wadachi.search import SearchEngine
    hits = SearchEngine(s).search("zxqwvunicorno", limit=10)
    assert hits == [] or all("zxqwvunicorno" not in str(h) for h in hits)


def test_closing_without_a_distillate_creates_no_memory(s):
    d = _open(s)
    before = len(s.list_memories())
    out = s.close_desk(d["slug"], "done", project="overmind")
    assert out["memory_id"] is None
    assert len(s.list_memories()) == before
    assert s.list_desks(project="overmind", status="open") == []


def test_closing_with_a_distillate_creates_one_linked_memory(s):
    d = _open(s)
    out = s.close_desk(d["slug"], "done", project="overmind",
                       distil="token_path deve essere per provider.")
    assert out["memory_id"]
    m = s.get_memory(out["memory_id"])
    assert f"[[{d['slug']}]]" in m["content"]


def test_closing_archives_the_file_and_deletes_nothing(s):
    d = _open(s)
    s.close_desk(d["slug"], "abandoned", project="overmind")
    archived = s.brain_dir / "desks" / "overmind" / "archived" / f"{d['slug']}.md"
    assert archived.exists()


# ── Dove va un passo nuovo (piano 2026-10-29-passi-rimandati) ──
#
# Chi aggiunge sa dove va il passo; il server lo esegue e non indovina mai.
# Un'aggiunta senza posizione su un piano con passi aperti è rifiutata per
# intero: nessuna scrittura, nemmeno la spunta o la nota della stessa chiamata.


def _text(s, d):
    return (s.brain_dir / d["filepath"]).read_text(encoding="utf-8")


def test_adding_without_a_position_while_steps_are_open_is_refused(s):
    d = _open(s)
    before = _text(s, d)
    out = s.log_desk(project="overmind", done="leggere", note="fatto",
                     add=["nuovo"])
    assert "error" in out
    assert out["open_steps"] == ["leggere", "estrarre", "verificare"]
    assert out["next_step"] == "leggere"
    assert _text(s, d) == before, "un rifiuto non scrive niente, spunta compresa"


def test_adding_before_a_step_puts_it_there_and_lists_the_open_steps(s):
    _open(s)
    out = s.log_desk(project="overmind", add=["capire"], before="estrarre")
    assert "error" not in out
    assert out["open_steps"] == ["leggere", "capire", "estrarre", "verificare"]


def test_before_takes_a_unique_prefix(s):
    _open(s)
    out = s.log_desk(project="overmind", add=["capire"], before="estr")
    assert out["open_steps"] == ["leggere", "capire", "estrarre", "verificare"]


def test_before_an_unknown_step_is_refused_with_the_open_steps(s):
    d = _open(s)
    before = _text(s, d)
    out = s.log_desk(project="overmind", add=["x"], before="non esiste")
    assert "error" in out and out["open_steps"] == ["leggere", "estrarre", "verificare"]
    assert _text(s, d) == before


def test_before_a_ticked_step_is_refused(s):
    """Si risolve sul piano dopo la spunta della stessa chiamata: davanti a un
    passo appena fatto non c'è niente da mettere."""
    d = _open(s)
    before = _text(s, d)
    out = s.log_desk(project="overmind", done="leggere", add=["x"], before="leggere")
    assert "error" in out
    assert _text(s, d) == before


def test_before_and_at_end_together_are_refused(s):
    d = _open(s)
    before = _text(s, d)
    out = s.log_desk(project="overmind", add=["x"], before="estrarre", at_end=True)
    assert "error" in out
    assert _text(s, d) == before


def test_a_position_without_steps_to_add_is_refused(s):
    d = _open(s)
    before = _text(s, d)
    out = s.log_desk(project="overmind", note="n", before="estrarre")
    assert "error" in out
    assert _text(s, d) == before


def test_at_end_appends_on_purpose(s):
    _open(s)
    out = s.log_desk(project="overmind", add=["dopo tutto"], at_end=True)
    assert out["open_steps"] == ["leggere", "estrarre", "verificare", "dopo tutto"]


def test_on_a_finished_plan_adding_needs_no_position(s):
    """Non c'è niente da scavalcare: si accoda come prima."""
    _open(s, plan=["solo"])
    out = s.log_desk(project="overmind", done="solo", add=["un altro"])
    assert "error" not in out
    assert out["next_step"] == "un altro"


def test_case_29_oct_new_work_lands_before_the_deferred_step(s):
    """`la-cache-ha-un-orologio`: i passi nuovi finivano dietro «Dopo la PR»
    e il cursore indicava quello."""
    _open(s, plan=["[PM] resume-desk senza progetto",
                   "Dopo la PR: valutare gli accenti"])
    refused = s.log_desk(project="overmind", done="[PM] resume-desk senza progetto",
                         add=["Ripresa: branch", "Ripresa: test"])
    assert "error" in refused
    out = s.log_desk(project="overmind", done="[PM] resume-desk senza progetto",
                     add=["Ripresa: branch", "Ripresa: test"], before="Dopo la PR")
    assert out["next_step"] == "Ripresa: branch"
    assert out["open_steps"][-1] == "Dopo la PR: valutare gli accenti"


def test_case_feynotes_substeps_land_before_the_review(s):
    """`figure-per-ogni-corso`: F5b e F5c finivano dopo F11 [REVIEW]."""
    _open(s, plan=["F1. banco", "F5. figure per corso", "F6. blocca",
                   "F10. collaudo", "F11. [REVIEW] chiusura"])
    s.log_desk(project="overmind", done="F1. banco")
    assert "error" in s.log_desk(project="overmind", add=["F5b"], before="F1"), \
        "F1 è fatto e il prefisso prende F10 e F11: ambiguo"
    s.log_desk(project="overmind", add=["F5b. porta TikZ"], before="F6")
    s.log_desk(project="overmind", add=["F5c. revisione schemi"], before="F6")
    out = s.log_desk(project="overmind", done="F5. figure per corso")
    assert out["next_step"] == "F5b. porta TikZ"
    assert s.read_desk(project="overmind")["next_step"] == "F5b. porta TikZ"
    plan = [label for _, label in parse_plan(s.read_desk(project="overmind")["text"])]
    assert plan.index("F5c. revisione schemi") < plan.index("F6. blocca")


def test_case_risposte_new_steps_land_before_the_review_not_after_the_release(s):
    """`risposte-che-costano-meno`: sei passi da mettere prima della review,
    mentre `add` li avrebbe messi dietro il rilascio."""
    _open(s, plan=["Misura prima/dopo", "CHANGELOG, /code-review medium",
                   "Rilascio 0.17.0"])
    out = s.log_desk(project="overmind", add=["Posizione dei passi"],
                     before="CHANGELOG")
    assert out["open_steps"] == ["Misura prima/dopo", "Posizione dei passi",
                                 "CHANGELOG, /code-review medium",
                                 "Rilascio 0.17.0"]
