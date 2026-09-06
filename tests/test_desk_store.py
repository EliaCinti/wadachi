"""La scrivania nello store: ciclo di vita, ripresa, confine con le memorie."""

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


def test_two_notes_do_not_overwrite_each_other(s, tmp_path):
    """Due sessioni che annotano: entrambe le righe restano."""
    d = _open(s)
    other = MemoryStore(str(tmp_path / "brain"))
    s.log_desk(project="overmind", note="dalla prima sessione")
    other.log_desk(project="overmind", note="dalla seconda sessione")
    text = s.read_desk(d["slug"], project="overmind")["text"]
    assert "dalla prima sessione" in text
    assert "dalla seconda sessione" in text


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
