"""La scrivania nello store: ciclo di vita, ripresa, confine con le memorie."""

import random
import threading
import time

import pytest

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
