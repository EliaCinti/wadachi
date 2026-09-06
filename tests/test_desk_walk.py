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
    testi = " ".join(m["title"] + m.get("content", "") for m in fresh.list_memories())
    assert "token_path" in " ".join(
        fresh.get_memory(m["id"])["content"] for m in fresh.list_memories())
    assert "zxqrumore" not in testi


def test_the_cap_is_reached_and_said(s):
    """Il caso di Rizzo: dieci tentativi, e il decimo lo dice."""
    d = s.open_desk("Ottimizzare", "Ridurre il tempo", "sotto i 2 secondi",
                    [f"tentativo {i}" for i in range(1, 11)], project="p")
    for i in range(1, 11):
        out = s.log_desk(project="p", done=f"tentativo {i}",
                         note=f"provato {i}: ancora lento")
    assert out["next_step"] is None, "il piano è finito: non si inventa un undicesimo"
    got = s.read_desk(d["slug"], project="p")
    assert got["text"].count("provato") == 10
