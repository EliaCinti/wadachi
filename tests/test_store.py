"""1.2 — MemoryStore: CRUD, casi limite, versioning, beliefs, insights, progetti."""

import os
import time
from pathlib import Path


# ── CRUD di base e casi limite ────────────────────────────────


def test_store_and_get_roundtrip(store):
    r = store.store_memory("il contenuto", "Titolo di prova", tags=["a", "b"], category="config")
    m = store.get_memory(r["id"])
    assert m["title"] == "Titolo di prova"
    assert m["content"] == "il contenuto"          # frontmatter strippato
    assert m["tags"] == ["a", "b"]
    assert m["category"] == "config"
    # il file markdown esiste davvero su disco, con frontmatter
    f = store.brain_dir / m["filepath"]
    assert f.exists()
    assert f.read_text().startswith("---\n")


def test_get_nonexistent_returns_none(store):
    assert store.get_memory(9999) is None


def test_update_nonexistent_returns_false(store):
    assert store.update_memory(9999, content="x") is False


def test_delete_nonexistent_returns_false(store):
    assert store.delete_memory(9999) is False


def test_delete_removes_row_and_file(store):
    r = store.store_memory("x", "Da cancellare")
    path = store.brain_dir / r["filepath"]
    assert path.exists()
    assert store.delete_memory(r["id"]) is True
    assert store.get_memory(r["id"]) is None
    assert not path.exists()


def test_duplicate_title_no_file_collision(store):
    """Stesso titolo due volte: due memorie distinte, due file distinti (-1 suffix)."""
    a = store.store_memory("primo", "Titolo Uguale")
    b = store.store_memory("secondo", "Titolo Uguale")
    assert a["id"] != b["id"]
    assert a["filepath"] != b["filepath"]
    assert store.get_memory(a["id"])["content"] == "primo"
    assert store.get_memory(b["id"])["content"] == "secondo"


def test_weird_titles_survive(store):
    """Titoli vuoti/emoji/solo simboli non fanno crashare né perdere la memoria."""
    for title in ["", "🎉🎉🎉", "///???///", "a" * 300]:
        r = store.store_memory("contenuto", title)
        m = store.get_memory(r["id"])
        assert m is not None
        assert m["content"] == "contenuto"


def test_empty_content_roundtrip(store):
    r = store.store_memory("", "Vuota")
    assert store.get_memory(r["id"])["content"] == ""


def test_list_memories_filters(store):
    store.store_memory("a", "M1", project="p1", category="bugfix")
    store.store_memory("b", "M2", project="p1", category="note")
    store.store_memory("c", "M3", project="p2", category="bugfix")
    assert len(store.list_memories()) == 3
    assert len(store.list_memories(project="p1")) == 2
    assert len(store.list_memories(category="bugfix")) == 2
    assert len(store.list_memories(project="p1", category="bugfix")) == 1


# ── Versioning non distruttivo ────────────────────────────────


def test_update_preserves_history(store):
    r = store.store_memory("versione uno", "Storia")
    store.update_memory(r["id"], content="versione due")
    store.update_memory(r["id"], content="versione tre")
    hist = store.get_memory_history(r["id"])
    assert len(hist) == 2                          # le due versioni precedenti
    assert "versione uno" in hist[-1]["content"]
    assert store.get_memory(r["id"])["content"] == "versione tre"


def test_update_tags_only_keeps_content(store):
    r = store.store_memory("intatto", "Solo tag")
    store.update_memory(r["id"], tags=["nuovo"])
    m = store.get_memory(r["id"])
    assert m["content"] == "intatto"
    assert m["tags"] == ["nuovo"]


def test_history_of_nonexistent_is_empty(store):
    assert store.get_memory_history(9999) == []


# ── Beliefs ───────────────────────────────────────────────────


def test_belief_defaults(store):
    r = store.store_memory("x", "Credenza")
    b = store.get_belief(r["id"])
    assert b["status"] == "active"
    assert b["confidence"] == 0.7


def test_set_belief_and_flag(store):
    r = store.store_memory("x", "Da flaggare")
    store.set_belief(r["id"], status="stale", review_reason="superata", confidence=0.3)
    b = store.get_belief(r["id"])
    assert b["status"] == "stale"
    assert b["confidence"] == 0.3
    assert b["review_reason"] == "superata"


def test_belief_of_nonexistent_memory_returns_defaults(store):
    # documentato: nessun errore, envelope di default
    b = store.get_belief(424242)
    assert b["status"] == "active"


# ── Decisions ─────────────────────────────────────────────────


def test_decisions_roundtrip_and_limit(store):
    for i in range(5):
        store.store_decision(f"decisione {i}", rationale="perché sì", project="p1")
    ds = store.list_decisions(project="p1", limit=3)
    assert len(ds) == 3
    assert all("decisione" in d["decision"] for d in ds)
    assert store.list_decisions(project="inesistente") == []


# ── Projects / auto-detection ─────────────────────────────────


def test_register_and_detect_project(store, tmp_path):
    proj_path = tmp_path / "codice" / "mioprogetto"
    proj_path.mkdir(parents=True)
    store.register_project("mio", "desc", [str(proj_path)])
    assert any(p["name"] == "mio" for p in store.list_projects())
    # match esatto e su sottodirectory
    assert store.detect_project(str(proj_path)) == "mio"
    assert store.detect_project(str(proj_path / "src" / "sub")) == "mio"


def test_detect_project_unknown_path(store):
    assert store.detect_project("/percorso/che/non/esiste") is None


# ── Insights ──────────────────────────────────────────────────


def test_insight_lifecycle(store):
    i = store.store_insight("A e B sono collegati", "analogy", [1, 2])
    proposed = store.list_insights(status="proposed")
    assert any(x["id"] == i["id"] for x in proposed)
    assert store.set_insight_status(i["id"], "rejected") is True
    assert store.list_insights(status="proposed") == []
    assert store.set_insight_status(9999, "accepted") is False


# ── Stats ─────────────────────────────────────────────────────


def test_stats_counts(store):
    store.store_memory("x", "Uno")
    store.store_decision("d1")
    s = store.stats()
    assert s["memories"] == 1
    assert s["decisions"] == 1


# ── Concorrenza: accesso multi-client (Overmind: più agenti in parallelo) ──


def test_concurrent_writes_all_succeed(store):
    """N thread che scrivono insieme non devono perdere scritture né fallire
    con 'database is locked' — WAL + busy_timeout serializzano al livello di
    SQLite invece di far esplodere il secondo writer."""
    import threading

    n = 24
    errors: list[Exception] = []
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        try:
            barrier.wait()  # massimizza la sovrapposizione
            store.store_memory(f"contenuto {i}", f"Memoria concorrente {i}")
        except Exception as e:  # noqa: BLE001 — vogliamo raccoglierli tutti
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"scritture concorrenti fallite: {errors}"
    assert store.stats()["memories"] == n


def test_concurrent_same_title_no_overwrite(store):
    """Stesso titolo da più thread: creazione file O_EXCL → file distinti,
    nessuna scrittura sovrascrive un'altra."""
    import threading

    n = 10
    barrier = threading.Barrier(n)

    def worker() -> None:
        barrier.wait()
        store.store_memory("corpo", "Titolo identico")

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.stats()["memories"] == n
    # Ogni memoria ha un file distinto ed esistente su disco.
    paths = {m["filepath"] for m in store.list_memories()}
    assert len(paths) == n
    for m in store.list_memories():
        assert (store.brain_dir / m["filepath"]).exists()


def test_wal_mode_enabled(store):
    """Il DB del brain gira in WAL (concorrenza lettori/scrittore)."""
    with store._conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"



# ── Concorrenza fra PROCESSI (il caso reale di Overmind) ──────────────────
#
# I due test sopra usano thread in UN processo, ed è per questo che non
# prendevano nulla: al confine Python il GIL serializza abbastanza da rendere
# le collisioni rare. Overmind lancia invece *processi* separati — il pool
# stdio ne apre fino a OVERMIND_MEMORY_POOL per brain — che girano su core
# diversi e collidono davvero. I due test qui sotto coprono i due momenti in
# cui si collide: l'apertura del brain e la scrittura.

_CHILD_WRITE = r'''
import sys, time
from pathlib import Path
from wadachi.store import MemoryStore

brain, sync, n, per = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
store = MemoryStore(brain)
(sync / f"ready-{n}").touch()
deadline = time.time() + 60
while not (sync / "go").exists():
    if time.time() > deadline:
        print("TIMEOUT attesa via", file=sys.stderr); sys.exit(3)
    time.sleep(0.0005)      # stretto, ma cede la CPU: lo spin puro affama il padre
for k in range(per):
    store.store_memory(f"corpo {n}-{k}", f"processo {n} memoria {k}")
'''

_CHILD_OPEN = r'''
import sys
from wadachi.store import MemoryStore
MemoryStore(sys.argv[1])
'''


def _spawn(code: str, *args: str):
    import subprocess
    import sys

    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    return subprocess.Popen(
        [sys.executable, "-c", code, *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )


def _reap(children, timeout=180):
    """Attende i figli e restituisce gli stderr di quelli falliti."""
    import subprocess

    bad = []
    for i, c in enumerate(children):
        try:
            _, err = c.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            c.kill()
            bad.append(f"figlio {i}: timeout")
            continue
        if c.returncode != 0:
            last = err.strip().splitlines()[-1] if err.strip() else f"rc={c.returncode}"
            bad.append(f"figlio {i}: {last}")
    return bad


def test_concurrent_open_of_a_new_brain(tmp_path):
    """N processi che aprono lo STESSO brain nuovo insieme: nessuno deve morire.

    `run_migrations` legge la versione corrente, decide cosa è pendente e poi
    applica — tre passi corretti solo se nessun altro sta facendo lo stesso. Su
    un brain nuovo tutti leggevano 0, tutti decidevano che 0001 era pendente, e
    il primo che committava faceva morire gli altri con
    `UNIQUE constraint failed: schema_version.version`.

    È esattamente ciò che succede la prima volta che gli agenti di un'azienda
    partono insieme su un brain appena creato — e chi perde non perde una
    memoria: non riesce ad aprire il brain.
    """
    brain = str(tmp_path / "brain")
    children = [_spawn(_CHILD_OPEN, brain) for _ in range(8)]
    assert _reap(children) == [], "aprire un brain nuovo in parallelo ha ucciso qualcuno"

    from wadachi.store import MemoryStore

    assert MemoryStore(brain).stats()["memories"] == 0


def test_concurrent_writes_across_processes(tmp_path):
    """N *processi* che scrivono lo stesso brain: nessuna perdita, nessun errore,
    nessun file orfano.

    L'ultima asserzione è quella che il test a thread non fa. `store_memory`
    scrive il .md prima della riga, quindi un insert fallito lasciava il payload
    nel vault e invisibile a `list_memories`. Misurato prima del fix: 176 file
    contro 175 righe. Contare solo le righe direbbe "perse 25"; contare anche i
    file dice che il brain era *incoerente*, che è peggio.
    """
    procs, per = 12, 50
    expected = procs * per
    brain_dir = tmp_path / "brain"
    sync = tmp_path / "sync"
    sync.mkdir()

    children = [
        _spawn(_CHILD_WRITE, str(brain_dir), str(sync), str(i), str(per))
        for i in range(procs)
    ]
    try:
        deadline = time.time() + 90
        while len(list(sync.glob("ready-*"))) < procs:
            dead = [i for i, c in enumerate(children) if c.poll() is not None]
            assert not dead, f"figli morti prima del via: {dead} — {_reap(children)}"
            assert time.time() < deadline, "i figli non sono mai diventati pronti"
            time.sleep(0.005)
        (sync / "go").touch()          # tutti partono nello stesso istante
        bad = _reap(children)
    finally:
        for c in children:
            if c.poll() is None:
                c.kill()

    assert bad == [], f"scritture concorrenti fallite: {bad}"

    from wadachi.store import MemoryStore

    store = MemoryStore(str(brain_dir))
    rows = store.list_memories()
    assert len(rows) == expected, f"memorie perse: {len(rows)}/{expected}"

    # Coerenza file ↔ righe: ogni riga ha il suo file, nessun file è orfano.
    on_disk = {p.name for p in (store.brain_dir / "global").glob("*.md")}
    in_db = {Path(m["filepath"]).name for m in rows}
    assert on_disk == in_db, (
        f"vault incoerente — solo su disco: {sorted(on_disk - in_db)}, "
        f"solo nel db: {sorted(in_db - on_disk)}"
    )
    assert len({m["id"] for m in rows}) == expected, "id duplicati"
