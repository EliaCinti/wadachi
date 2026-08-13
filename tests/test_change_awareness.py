"""ADR-0026 — filigrane e rilevamento delle collisioni.

Il test che conta è l'ultimo: due **processi** separati, non due thread. È la
forma che crea Overmind, ed è la distinzione che il 9 agosto ha lasciato passare
un difetto vero sotto una suite verde (il test a 24 writer usava thread in un
solo processo, e la perdita di memorie avveniva solo fra processi).
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = str(Path(__file__).parent.parent)


# ── A · filigrane ─────────────────────────────────────────────


def test_watermark_of_an_empty_brain_is_zero(store):
    wm = store.watermark()
    assert wm["memories"] == 0 and wm["decisions"] == 0


def test_watermark_moves_forward_and_never_back(store):
    store.store_memory("a", "Prima", project="acme")
    w1 = store.watermark()
    store.store_memory("b", "Seconda", project="acme")
    w2 = store.watermark()
    assert w2["memories"] > w1["memories"]


def test_changed_since_returns_only_what_came_after(store):
    store.store_memory("vecchia", "Prima del checkout", project="acme")
    wm = store.watermark(project="acme")
    store.store_memory("nuova", "Dopo il checkout", project="acme")

    out = store.changed_since(wm, project="acme")
    titoli = [m["title"] for m in out["memories"]]
    assert titoli == ["Dopo il checkout"]


def test_changed_since_is_scoped_to_the_project(store):
    wm = store.watermark()
    store.store_memory("x", "Roba di acme", project="acme")
    store.store_memory("y", "Roba di altro", project="altro")

    solo_acme = [m["title"] for m in store.changed_since(wm, project="acme")["memories"]]
    assert "Roba di acme" in solo_acme
    assert "Roba di altro" not in solo_acme


def test_changed_since_sees_decisions_too(store):
    wm = store.watermark(project="acme")
    store.store_decision("Deprecare il carrello", "i log lo dicono", project="acme")
    assert len(store.changed_since(wm, project="acme")["decisions"]) == 1


# ── B · collisioni ────────────────────────────────────────────


@pytest.fixture()
def brain(store):
    """Un brain con un corpus e gli embedding già scaldati.

    Serve perché i punteggi sono centrati sulla media del corpus (ADR-0026) e
    gli embedding si popolano pigramente, alla prima ricerca. In Overmind questo
    accade da solo — gli agenti fanno `recall` all'inizio del task — ma un brain
    di test nasce vuoto e senza corpus la rilevazione ricade sulle keyword.
    """
    from wadachi.search import SearchEngine
    for i, t in enumerate([
        "il deploy usa nginx in un container docker",
        "le notifiche email partono la domenica mattina",
        "rinominare la colonna user_id in account_id",
        "il logo va centrato nell'header su mobile",
        "aggiungere retry esponenziale alle chiamate al provider",
        "migrare i test da unittest a pytest",
    ]):
        store.store_memory(t, f"Nota di contesto {i}", project="acme")
    SearchEngine(store).search("qualunque cosa", project="acme", limit=1)  # popola gli embedding
    return store


def _collide(store, wm, testo, titolo, project="acme"):
    from wadachi.collisions import find_collisions
    r = store.store_memory(testo, titolo, project=project)
    return r, find_collisions(store, kind="memories", row_id=r["id"],
                              text=f"{titolo}. Tags: . {testo}",
                              project=project, watermark=wm)


def test_no_watermark_means_no_collisions(brain):
    """Senza posizione di partenza non esiste un 'da allora': niente finestra."""
    brain.store_memory("il carrello va deprecato", "Deprecare il carrello", project="acme")
    _, coll = _collide(brain, None, "il carrello va deprecato", "Deprecare il carrello")
    assert coll == []


def test_a_writer_does_not_collide_with_itself(brain):
    wm = brain.watermark(project="acme")
    _, coll = _collide(brain, wm, "il carrello va deprecato", "Deprecare il carrello")
    assert coll == []


def test_unrelated_concurrent_write_is_not_a_collision(brain):
    wm = brain.watermark(project="acme")
    brain.store_memory("aggiornare il colore dei bottoni nel tema scuro",
                       "Palette del tema scuro", project="acme")
    _, coll = _collide(brain, wm,
                       "la fatturazione ricorrente passa a fatture mensili",
                       "Fatturazione mensile")
    assert coll == [], f"falso positivo: {coll}"


@pytest.mark.parametrize("altro_titolo,altro_testo", [
    ("Deprecare il carrello legacy",
     "Decisione: il carrello legacy va deprecato e rimosso dal checkout."),
])
def test_a_close_concurrent_write_is_reported(brain, altro_titolo, altro_testo):
    """Il caso che questa ADR esiste per prendere: due scritture vicine, nella
    stessa finestra, di cui nessuna delle due sa dell'altra."""
    wm = brain.watermark(project="acme")
    brain.store_memory(altro_testo, altro_titolo, project="acme")   # l'altro agente
    _, coll = _collide(brain, wm,
                       "Decisione: il carrello legacy resta e va esteso nel checkout.",
                       "Estendere il carrello legacy")
    assert coll, "collisione non rilevata"
    assert coll[0]["id"] is not None
    assert 0.0 <= coll[0]["similarity"] <= 1.0


def test_collisions_never_block_the_write(brain):
    """Una collisione è un avviso. La memoria si salva comunque."""
    wm = brain.watermark(project="acme")
    brain.store_memory("il carrello legacy va deprecato", "Deprecare il carrello", project="acme")
    r, coll = _collide(brain, wm, "il carrello legacy va esteso", "Estendere il carrello")
    assert brain.get_memory(r["id"])["title"] == "Estendere il carrello"


# ── Il test che conta: PROCESSI, non thread ──────────────────


_WRITER = textwrap.dedent("""
    import json, os, sys
    brain = sys.argv[1]
    os.environ["BRAIN_DIR"] = brain
    sys.path.insert(0, %r)
    from wadachi.migrations import run_migrations
    from wadachi.store import MemoryStore
    from wadachi.collisions import find_collisions
    run_migrations(os.path.join(brain, "brain.db"))
    s = MemoryStore(brain)
    modo, titolo, testo = sys.argv[2], sys.argv[3], sys.argv[4]
    if modo == "seed":
        from wadachi.search import SearchEngine
        for i, t in enumerate(["il deploy usa nginx in un container docker",
                               "le notifiche email partono la domenica mattina",
                               "rinominare la colonna user_id in account_id",
                               "il logo va centrato nell'header su mobile",
                               "aggiungere retry esponenziale al provider",
                               "migrare i test da unittest a pytest"]):
            s.store_memory(t, f"Nota di contesto {i}", project="acme")
        SearchEngine(s).search("qualunque cosa", project="acme", limit=1)
        print(json.dumps({"seeded": True}))
    elif modo == "watermark":
        print(json.dumps(s.watermark(project="acme")))
    else:
        wm = json.loads(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5] else None
        r = s.store_memory(testo, titolo, project="acme")
        c = find_collisions(s, kind="memories", row_id=r["id"],
                            text=f"{titolo}. Tags: . {testo}",
                            project="acme", watermark=wm)
        print(json.dumps({"id": r["id"], "collisions": c}))
""") % REPO


def _run(brain, *args):
    p = subprocess.run([sys.executable, "-c", _WRITER, str(brain), *args],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-800:]
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_two_separate_processes_see_each_others_collision(tmp_path):
    """Agente A e agente B, processi distinti, entrambi partiti dalla stessa
    filigrana. A scrive; B scrive qualcosa di vicino e DEVE vedere A.

    Se questo passa con i thread ma non con i processi, il test è inutile: è
    esattamente l'errore che a luglio ha lasciato in piedi un difetto reale.
    """
    brain = tmp_path / "brain"
    brain.mkdir()

    _run(brain, "seed", "-", "-")                      # corpus + embedding scaldati
    wm = _run(brain, "watermark", "-", "-")            # checkout: entrambi partono qui

    _run(brain, "write", "Deprecare il carrello legacy",
         "Decisione: il carrello legacy va deprecato e rimosso dal checkout.",
         json.dumps(wm))                                # agente A

    b = _run(brain, "write", "Estendere il carrello legacy",
             "Decisione: il carrello legacy resta e va esteso nel checkout.",
             json.dumps(wm))                            # agente B, filigrana vecchia

    assert b["collisions"], "B non ha visto la scrittura di A: la finestra non funziona fra processi"
    assert b["collisions"][0]["kind"] == "memory"


# ── Il percorso di ripiego, esercitato SEMPRE ────────────────
#
# La CI installa `.[dev]`, non l'extra `semantic`: là fastembed non c'è e gira
# il fallback. In locale c'è, e la prima versione di questi test attraversava il
# percorso semantico senza dirlo — CI rossa, verde in casa. Questo test forza il
# ripiego ovunque, così le due macchine provano le stesse cose.


@pytest.fixture()
def keyword_only(monkeypatch):
    import wadachi.collisions as c
    monkeypatch.setattr(c, "_FASTEMBED_AVAILABLE", False)
    return c


def test_fallback_reports_a_close_write(brain, keyword_only):
    wm = brain.watermark(project="acme")
    brain.store_memory("Decisione: il carrello legacy va deprecato e rimosso dal checkout.",
                       "Deprecare il carrello legacy", project="acme")
    _, coll = _collide(brain, wm,
                       "Decisione: il carrello legacy resta e va esteso nel checkout.",
                       "Estendere il carrello legacy")
    assert coll, "il ripiego non ha rilevato la collisione"
    assert coll[0]["method"] == "keyword"


def test_fallback_stays_quiet_on_unrelated_writes(brain, keyword_only):
    wm = brain.watermark(project="acme")
    brain.store_memory("aggiornare il colore dei bottoni nel tema scuro",
                       "Palette del tema scuro", project="acme")
    _, coll = _collide(brain, wm,
                       "la fatturazione ricorrente passa a fatture mensili",
                       "Fatturazione mensile")
    assert coll == [], f"falso positivo nel ripiego: {coll}"
