"""
reflect.py — the brain thinks between sessions (Phase 3, reflection pillar).

Plain memory only answers what you ask. Reflection *combines* memories to surface
knowledge that no single memory holds and that `recall` cannot reach: cross-project
analogies and non-obvious connections.

Efficiency note: instead of paying for a fresh LLM pass, this reuses signal already
computed for free — the Graphify entity graph (its INFERRED "surprising connections")
plus cross-project shared-entity bridges from the memory graph. Candidates are
*proposed* (never auto-accepted); a human (or a later LLM enrichment) curates them
via accept_insight / reject_insight. Pairs that already cite each other are dropped
(not novel).
"""

from __future__ import annotations

from wadachi.entities import EntityGraph
from wadachi.graph import MemoryGraph


class Reflector:
    def __init__(self, store):
        self.store = store

    def _projects(self) -> dict:
        with self.store._conn() as conn:
            rows = conn.execute("SELECT id, project FROM memories").fetchall()
        return {r["id"]: r["project"] for r in rows}

    def candidates(self, project: str | None = None, limit: int = 20) -> list[dict]:
        g = MemoryGraph(self.store).build(project)
        eg = EntityGraph(self.store)
        proj = self._projects()
        cited = {frozenset((e.src, e.dst)) for e in g.edges if e.kind == "citation"}
        existing = {frozenset(i["evidence_ids"]) for i in self.store.list_insights()}
        seen: set = set()
        out: list[dict] = []

        # A) cross-project analogies via shared entity
        if eg.graph_json.exists():
            try:
                g.load_entity_edges(str(eg.graph_json))
            except Exception:  # noqa: BLE001
                pass
        for e in g.edges:
            if e.kind != "entity":
                continue
            pair = frozenset((e.src, e.dst))
            if pair in seen or pair in cited or pair in existing:
                continue
            pa, pb = proj.get(e.src), proj.get(e.dst)
            if pa and pb and pa != pb:
                seen.add(pair)
                ent = e.rel.replace("shares:", "")
                out.append({
                    "itype": "cross_project_analogy",
                    "claim": (f"«{g.nodes[e.src].title[:40]}» ({pa}) e «{g.nodes[e.dst].title[:40]}» "
                              f"({pb}) condividono «{ent}» — possibile pattern/astrazione riutilizzabile."),
                    "evidence_ids": sorted(pair),
                })

        # B) Graphify INFERRED "surprising connections"
        gj = eg._load() if eg.graph_json.exists() else None
        if gj:
            nodes = {n["id"]: n for n in gj["nodes"]}
            with self.store._conn() as conn:
                rows = conn.execute("SELECT id, filepath FROM memories").fetchall()
            flat = {r["filepath"].replace("\\", "/").replace("/", "__"): r["id"] for r in rows}

            def mid(node_id):
                return flat.get((nodes.get(node_id) or {}).get("source_file") or "")

            for link in gj.get("links", []):
                if str(link.get("confidence", "")).upper() != "INFERRED":
                    continue
                a, b = mid(link["source"]), mid(link["target"])
                if not a or not b or a == b or a not in g.nodes or b not in g.nodes:
                    continue
                pair = frozenset((a, b))
                if pair in seen or pair in cited or pair in existing:
                    continue
                seen.add(pair)
                out.append({
                    "itype": "surprising_connection",
                    "claim": (f"Collegamento non ovvio ({link.get('relation')}): "
                              f"«{g.nodes[a].title[:40]}» ⟷ «{g.nodes[b].title[:40]}»."),
                    "evidence_ids": sorted(pair),
                })
        return out[:limit]
