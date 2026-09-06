"""I due giri che dicono se la scrivania serve a qualcosa."""

import pytest

from wadachi.store import MemoryStore


@pytest.fixture
def s(tmp_path):
    return MemoryStore(str(tmp_path / "brain"))


def test_the_whole_walk_leaves_the_lesson_and_not_the_noise(s, tmp_path):
    d = s.open_desk("Il lavoro", "Fare X", "i test passano",
                    ["primo", "secondo"], project="p")
    s.log_desk(project="p", done="primo", note="zxqrumore effimero di lavorazione")
    s.log_desk(project="p", done="secondo", note="altro zxqrumore")
    s.close_desk(d["slug"], "done", project="p",
                 distil="La lezione: token_path va per provider.")

    fresh = MemoryStore(str(tmp_path / "brain"))
    # list_memories() non porta il campo "content" (solo id/titolo/metadati):
    # cercare il rumore lì sarebbe un controllo che non controlla niente.
    # Il contenuto vero si legge solo con get_memory — per ogni memoria.
    memorie = [fresh.get_memory(m["id"]) for m in fresh.list_memories()]
    testi = " ".join(m["title"] + m["content"] for m in memorie)
    assert "token_path" in testi
    assert "zxqrumore" not in testi


def test_the_cap_is_reached_and_said(s):
    """Il caso di Rizzo: dieci tentativi, e il decimo lo dice.

    Non basta guardare l'ultima chiamata: un passo saltato o ripetuto per
    errore lascerebbe comunque `next_step is None` alla decima. Si registra
    la sequenza intera e si confronta con l'ordine atteso.
    """
    d = s.open_desk("Ottimizzare", "Ridurre il tempo", "sotto i 2 secondi",
                    [f"tentativo {i}" for i in range(1, 11)], project="p")
    passi_successivi = []
    for i in range(1, 11):
        out = s.log_desk(project="p", done=f"tentativo {i}",
                         note=f"provato {i}: ancora lento")
        passi_successivi.append(out["next_step"])
    attesi = [f"tentativo {i}" for i in range(2, 11)] + [None]
    assert passi_successivi == attesi, (
        "ogni tentativo deve annunciare il successivo nell'ordine giusto, e "
        "solo il decimo dice che il piano è finito — non se ne inventa un "
        "undicesimo")
    got = s.read_desk(d["slug"], project="p")
    assert got["text"].count("provato") == 10
