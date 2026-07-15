"""7.B parte 2 — communities, sleep, evidence scoping, dati della vetrina web."""

import json
from datetime import datetime, timedelta, timezone

from wadachi.graph import MemoryGraph
from wadachi.web import get_graph_data


def j(out: str):
    return json.loads(out)


# ── communities (label propagation) ───────────────────────────


def test_communities_finds_linked_cluster(store):
    a = store.store_memory("nucleo del cluster", "Cluster A")
    b = store.store_memory(f"legata ad [[#{a['id']}]]", "Cluster B")
    c = store.store_memory(f"anche questa cita [[#{a['id']}]]", "Cluster C")
    store.store_memory("completamente isolata", "Isola")
    g = MemoryGraph(store).build()
    comms = g.communities()
    assert any({a["id"], b["id"], c["id"]} <= set(c_) for c_ in comms)


def test_communities_empty_graph(store):
    assert MemoryGraph(store).build().communities() == []


# ── sleep (read-only, propone) ────────────────────────────────


def test_sleep_reports_decay_and_orphans(srv, monkeypatch):
    import wadachi.server as ws
    old_iso = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    m = j(srv.store_memory("roba vecchia mai riletta", "Dimenticata"))
    import sqlite3
    conn = sqlite3.connect(ws.store.db_path)
    conn.execute("UPDATE memories SET created_at = ?, access_count = 0, last_accessed = NULL "
                 "WHERE id = ?", (old_iso, m["id"]))
    conn.commit()
    conn.close()

    out = j(srv.sleep())
    assert "merge_candidates" in out and "decay_candidates" in out and "actions" in out
    assert any(c["id"] == m["id"] for c in out["decay_candidates"]), out["decay_candidates"]


def test_sleep_is_read_only(srv):
    import wadachi.server as ws
    before = ws.store.stats()
    j(srv.sleep())
    assert ws.store.stats() == before


# ── evidence scoping ──────────────────────────────────────────


def test_recall_scoped_annotates_global_evidence(srv, tmp_path):
    pdir = tmp_path / "scopeproj"
    pdir.mkdir()
    j(srv.register_project("scopeproj", "test scoping", [str(pdir)]))
    j(srv.store_memory("il gateway usa il timeout di 30s", "Timeout gateway",
                       project="scopeproj"))
    j(srv.store_memory("regola generale: i timeout si loggano sempre", "Regola timeout",
                       project="global"))
    out = j(srv.recall("timeout gateway regola", project="scopeproj", limit=8))
    scopes = {r["id"]: r.get("scope") for r in out["results"] if r.get("type") == "memory"}
    assert "global" in scopes.values()          # l'evidenza cross-cutting è dichiarata
    assert "project" in scopes.values()


# ── vetrina web: dati dal grafo reale ─────────────────────────


def test_web_graph_data_typed(store):
    m = store.store_memory("memoria del grafo web", "Web Mem")
    d = store.store_decision("decisione del grafo web",
                             rationale=f"per via di memoria #{m['id']}")
    new = store.store_memory("versione nuova", "Web Mem v2")
    store.set_belief(m["id"], status="stale", superseded_by=new["id"])

    data = get_graph_data(store)
    ids = {n["id"] for n in data["nodes"]}
    assert f"m{m['id']}" in ids and f"d{d['id']}" in ids

    dec_node = next(n for n in data["nodes"] if n["id"] == f"d{d['id']}")
    assert dec_node["type"] == "decision"
    assert "memoria" in dec_node["why"]         # il razionale viaggia per il pannello why
    assert dec_node["created_at"]               # serve allo slider temporale

    kinds = {(l["source"], l["target"], l["rel"]) for l in data["links"]}
    assert (f"d{d['id']}", f"m{m['id']}", "relates") in kinds or \
           any(l["source"] == f"d{d['id']}" and l["target"] == f"m{m['id']}"
               for l in data["links"])          # decisione → memoria citata
    assert any(l["rel"] == "supersedes" for l in data["links"])
