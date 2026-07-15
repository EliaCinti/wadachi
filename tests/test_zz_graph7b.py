"""7.B — grafo tipizzato: decisioni come nodi, supersedes, why(), as_of(), neighbors."""

import json
from datetime import datetime, timezone

from wadachi.graph import MemoryGraph


def j(out: str):
    return json.loads(out)


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── nodi tipizzati e archi ────────────────────────────────────


def test_decision_becomes_typed_node_with_edge(store):
    d = store.store_decision("usiamo sqlite non postgres", rationale="semplice, locale")
    m = store.store_memory(f"il db è sqlite, come da decisione #{d['id']}", "Setup DB")
    g = MemoryGraph(store).build()
    assert -d["id"] in g.nodes
    assert g.nodes[-d["id"]].ntype == "decision"
    assert g.nodes[-d["id"]].label == f"D{d['id']}"
    cites = [(e.src, e.dst) for e in g.edges if e.kind == "citation"]
    assert (m["id"], -d["id"]) in cites


def test_decision_wikilink_D_ref(store):
    d = store.store_decision("brand Sumi")
    m = store.store_memory(f"vedi [[D{d['id']}]] per il razionale", "Nota brand")
    g = MemoryGraph(store).build()
    assert (m["id"], -d["id"]) in [(e.src, e.dst) for e in g.edges if e.kind == "citation"]


def test_decision_rationale_cites_memory(store):
    """Le decisioni citano memorie: l'arco parte dal nodo decisione."""
    m = store.store_memory("benchmark: sqlite 5x più veloce qui", "Benchmark DB")
    d = store.store_decision("usiamo sqlite", rationale=f"vedi memoria #{m['id']}")
    g = MemoryGraph(store).build()
    assert (-d["id"], m["id"]) in [(e.src, e.dst) for e in g.edges if e.kind == "citation"]


def test_supersession_belief_becomes_edge(store):
    old = store.store_memory("si usa il metodo A", "Metodo A")
    new = store.store_memory("si usa il metodo B", "Metodo B")
    store.set_belief(old["id"], status="stale", superseded_by=new["id"])
    g = MemoryGraph(store).build()
    sup = [(e.src, e.dst) for e in g.edges if e.rel == "supersedes"]
    assert (new["id"], old["id"]) in sup


def test_mermaid_renders_decision_shape(store):
    d = store.store_decision("decisione mostrata")
    store.store_memory(f"come da decisione #{d['id']}", "Che la cita")
    g = MemoryGraph(store).build()
    mm = g.to_mermaid()
    assert f'd{d["id"]}{{{{' in mm            # esagono mermaid per le decisioni
    assert "D" + str(d["id"]) in mm


def test_stats_counts_node_types(store):
    store.store_memory("x", "Una memoria")
    store.store_decision("una decisione")
    st = MemoryGraph(store).build().stats()
    assert st["memory_nodes"] == 1
    assert st["decision_nodes"] == 1


# ── tool: why / as_of / recall neighbors ──────────────────────


def test_why_returns_provenance(srv):
    d = j(srv.store_decision("usiamo pandoc per i pdf",
                             rationale="già installato e affidabile",
                             alternatives="weasyprint scartato: font rotti",
                             project="provproj"))
    j(srv.store_memory(f"pipeline pdf con pandoc, come da decisione #{d['id']}",
                       "Pipeline PDF", project="provproj"))
    out = j(srv.why("perché usiamo pandoc?", project="provproj"))
    assert out["answers"], out
    a = out["answers"][0]
    assert a["decision_id"] == d["id"]
    assert "affidabile" in a["why"]
    assert "weasyprint" in a["rejected_alternatives"]
    assert any("Pipeline PDF" in e["title"] for e in a["cited_by"])


def test_why_no_match(srv, monkeypatch):
    # percorso keyword: deterministico (il semantico dà similarità alte anche al nonsense)
    monkeypatch.setattr(srv.search_engine, "semantic_available", False)
    out = j(srv.why("xyzzy quix argomento inesistente"))
    assert out["answers"] == []
    assert "message" in out


def test_as_of_time_travel_content(srv):
    m = j(srv.store_memory("il limite è 10 richieste al secondo", "Rate limit"))
    t_before_update = _now()
    j(srv.update_memory(m["id"], content="il limite è 50 richieste al secondo"))

    out = j(srv.as_of(t_before_update, query="rate limit richieste"))
    hit = next((x for x in out["memories"] if x["id"] == m["id"]), None)
    assert hit is not None, out
    assert "10 richieste" in hit["content_as_of"]      # il contenuto D'EPOCA

    # oggi invece vale il contenuto nuovo
    assert "50 richieste" in j(srv.get_memory(m["id"]))["content"]


def test_as_of_excludes_not_yet_created(srv):
    out = j(srv.as_of("2001-01-01"))
    assert out["count"] == 0


def test_as_of_marks_superseded(srv):
    old = j(srv.store_memory("config vecchia", "Config v1"))
    new = j(srv.store_memory("config nuova", "Config v2"))
    j(srv.flag_stale(old["id"], reason="sostituita", superseded_by=new["id"]))
    out = j(srv.as_of(_now()))
    hit = next(x for x in out["memories"] if x["id"] == old["id"])
    assert f"superseded by #{new['id']}" in hit["status_at_date"]


def test_recall_neighbors_attaches_linked(srv):
    a = j(srv.store_memory("il collettore solare scalda l'acqua", "Collettore solare"))
    j(srv.store_memory(f"il serbatoio accumula, vedi [[#{a['id']}]]", "Serbatoio termico"))
    out = j(srv.recall("serbatoio termico accumulo", neighbors=True))
    linked = [r.get("linked", []) for r in out["results"]]
    flat = [x for sub in linked for x in sub]
    assert any(x["label"] == f"#{a['id']}" for x in flat), out
