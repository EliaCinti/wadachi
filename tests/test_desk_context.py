"""get_context e la scrivania: in cima, dentro il budget, e muta se non c'è."""

import importlib

import pytest


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_DIR", str(tmp_path / "brain"))
    import wadachi.server as s
    importlib.reload(s)
    s.store.register_project("p", "", [str(tmp_path)])
    return s


def test_with_no_desk_the_context_does_not_mention_one(srv):
    srv.store.store_memory("qualcosa", "T", project="p")
    out = srv.get_context(cwd="/nessun/percorso", task_description="")
    assert "scrivania" not in out.lower()


def test_an_open_desk_comes_before_the_memories(srv, tmp_path):
    srv.store.store_memory("una memoria", "M", project="p")
    srv.store.open_desk("Il lavoro", "Fare X", "i test passano",
                        ["primo passo"], project="p")
    out = srv.get_context(cwd=str(tmp_path), task_description="")
    assert "scrivania" in out.lower()
    assert out.lower().index("scrivania") < out.index("memorie")
    assert "primo passo" in out


def test_two_open_desks_are_listed_not_chosen(srv, tmp_path):
    srv.store.open_desk("Uno", "O", "d", ["a"], project="p")
    srv.store.open_desk("Due", "O", "d", ["b"], project="p")
    out = srv.get_context(cwd=str(tmp_path), task_description="")
    assert "Uno" in out and "Due" in out


def test_a_tight_budget_keeps_both_the_desk_and_a_memory(srv, tmp_path):
    for i in range(5):
        srv.store.store_memory(f"memoria numero {i}", f"M{i}", project="p")
    srv.store.open_desk("Il lavoro", "x" * 400, "d", ["passo lungo " * 20],
                        project="p")
    out = srv.get_context(cwd=str(tmp_path), task_description="", max_tokens=200)
    assert "scrivania" in out.lower()
    assert "M" in out, "un budget stretto non deve cancellare tutte le memorie"
