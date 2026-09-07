"""get_context e la scrivania: in cima, dentro il budget, e muta se non c'è."""

import importlib
import re

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


def test_an_unregistered_cwd_does_not_leak_another_projects_desks(srv, tmp_path):
    """Finding 2: `project=None` non deve tradursi in «tutti i progetti».

    Il test sopra non lo scopre perché non semina nessuna scrivania: qui ce
    ne sono due in un progetto vero, e la cwd del chiamante non è
    registrata da nessuna parte — il §3 della spec dice «nessuna → non
    dice niente», non «tutte»."""
    srv.store.open_desk("Uno", "O", "d", ["a"], project="p")
    srv.store.open_desk("Due", "O", "d", ["b"], project="p")
    out = srv.get_context(cwd="/nessun/percorso/mai/registrato", task_description="")
    assert "scrivania" not in out.lower()
    assert "Uno" not in out and "Due" not in out


def test_an_open_desk_comes_before_the_memories(srv, tmp_path):
    srv.store.store_memory("una memoria", "M", project="p")
    srv.store.open_desk("Il lavoro", "Fare X", "i test passano",
                        ["primo passo"], project="p")
    out = srv.get_context(cwd=str(tmp_path), task_description="")
    assert "scrivania" in out.lower()
    assert out.lower().index("scrivania") < out.index("memorie")
    assert "primo passo" in out


def test_a_deleted_desk_file_does_not_crash_get_context(srv, tmp_path):
    """Finding 1: cancellare il .md a mano (Obsidian lo invita a fare) non
    deve mandare in FileNotFoundError l'intera get_context — è lo strumento
    obbligatorio a inizio sessione, quindi il crash peggiore possibile."""
    d = srv.store.open_desk("Il lavoro", "Fare X", "i test passano",
                            ["primo"], project="p")
    (srv.store.brain_dir / d["filepath"]).unlink()
    out = srv.get_context(cwd=str(tmp_path), task_description="")
    assert out
    assert "non c'è più" in out


def test_two_open_desks_are_listed_not_chosen(srv, tmp_path):
    srv.store.open_desk("Uno", "O", "d", ["a"], project="p")
    srv.store.open_desk("Due", "O", "d", ["b"], project="p")
    out = srv.get_context(cwd=str(tmp_path), task_description="")
    assert "Uno" in out and "Due" in out


def test_a_tight_budget_keeps_the_cap_and_a_memory(srv, tmp_path):
    for i in range(5):
        srv.store.store_memory(f"memoria numero {i}", f"M{i}", project="p")
    long_step = "passo molto lungo da completare, con parecchi dettagli " * 10
    long_objective = "un obiettivo scritto con dovizia di dettagli inutili " * 10
    srv.store.open_desk("Un titolo di scrivania piuttosto lungo e descrittivo",
                        long_objective, "d", [long_step], project="p")
    max_tokens = 200
    out = srv.get_context(cwd=str(tmp_path), task_description="", max_tokens=max_tokens)
    assert srv._est_tokens(out) <= max_tokens, "il budget include la scrivania: non va sforato"
    assert re.search(r"#\d+", out), "un budget stretto non deve cancellare tutte le memorie"
    assert "🖿" in out, "la scrivania degradata deve restare presente, non sparire"


def test_many_long_titled_desks_still_respect_the_budget(srv, tmp_path):
    titles = [
        "Refactor the entire authentication and session management subsystem",
        "Migrate the legacy billing pipeline to the new event-driven architecture",
        "Investigate and fix the intermittent flakiness in the CI test suite",
        "Write comprehensive documentation for the new plugin API surface",
    ]
    for t in titles:
        srv.store.open_desk(t, "obiettivo", "fatto quando è fatto", ["passo"], project="p")
    max_tokens = 200
    out = srv.get_context(cwd=str(tmp_path), task_description="", max_tokens=max_tokens)
    assert srv._est_tokens(out) <= max_tokens, "più scrivanie non devono sforare il budget"
    assert "🖿" in out, "il blocco scrivanie deve restare presente, anche degradato"


def test_a_pathological_budget_never_lets_a_slug_look_whole(srv, tmp_path):
    """cap() può tagliare uno slug a metà — è proprio quello che si incolla in
    desk_read(slug). Il taglio deve dirlo, non nasconderlo."""
    long_title = ("Un titolo pensato apposta per produrre uno slug lunghissimo "
                  "che nessun budget patologico può contenere per intero")
    srv.store.open_desk(long_title, "obiettivo", "fatto quando è fatto",
                        ["passo"], project="p")
    out = srv._desk_block("p", 10)
    assert out, "il blocco non deve sparire, nemmeno tagliato"
    assert out.endswith("…"), "una stringa tagliata non deve sembrare una intera"
