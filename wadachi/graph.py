"""
Constellation — associative memory graph + spreading-activation recall.

Engram already stores memories that CITE each other in prose ("memoria #82",
"aggiorna #77"). That latent citation graph is currently ignored: `recall` is
pure cosine top-k, so a memory that is strongly *connected* to your query — but
not textually similar to it — never surfaces.

This module surfaces and exploits that graph. It builds a weighted graph over
memories from two edge sources:

  1. CITATION edges (explicit, high precision): references like "memoria #N"
     parsed from the markdown body, typed as updates / contradicts / cites / relates.
  2. SEMANTIC edges (implicit): a k-NN graph over the cached bge-small embeddings.

Recall then runs Personalized PageRank (HippoRAG-style spreading activation):
the query's top semantic hits become "seeds", activation spreads along the
graph, and memories that sit in the seeds' neighbourhood get pulled up even when
their raw cosine score is low. The final ranking blends direct similarity with
graph proximity.

Design constraints:
  * ADDITIVE and READ-ONLY on the live brain. It does not write to brain.db and
    does not touch store.py / search.py / server.py.
  * Pure numpy. No new dependencies (numpy + fastembed are already required).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from wadachi.search import embed_text, embed_texts, cosine_similarity

# Reference like "memoria #82", "memorie 77", "memory #5" → memory id.
# Deliberately word-anchored (requires "memor..."): high precision, avoids
# matching bare "#1" that appears inside quoted external text.
_MEM_REF = re.compile(r"(?i)\bmemor(?:i[ae]|y|ies)\b[^\w#]{0,12}#?\s*(\d{1,4})")
# [[#84]] — riferimento diretto per id (usato da merge_memories/accept_insight)
_ID_REF = re.compile(r"\[\[#(\d{1,5})\]\]")
# "decisione #19" / "decision #4" in prosa, e [[D19]] — le decisioni sono nodi
_DEC_REF = re.compile(r"(?i)\bdecisi(?:one?|ons?)\b[^\w#]{0,12}#?\s*(\d{1,4})")
_DID_REF = re.compile(r"\[\[D(\d{1,5})\]\]")
# [[slug-del-file]] o [[slug|testo mostrato]] — wikilink in stile Obsidian,
# risolto sullo stem del file della memoria (il vault è apribile in Obsidian)
_WIKI_REF = re.compile(r"\[\[([^\]#|][^\]|]{0,120}?)(?:\|[^\]]*)?\]\]")

_EDGE_WEIGHT = {"supersedes": 1.5, "updates": 1.5, "contradicts": 1.2, "cites": 1.0, "relates": 0.8}

_UPDATE_KW = ("aggiorn", "update", "supersed", "sostitu", "rivede", "supera",
              "deprecat", "risolt", "rivalut")
_CONTRA_KW = ("contraddi", "contradic", "smentisc", "invalidan", "rettific")
_CITE_KW = ("vedi", "cfr", "cf.", "come da", "see ", "vedi ")


def _edge_type(window: str) -> str:
    w = window.lower()
    if any(k in w for k in _UPDATE_KW):
        return "updates"
    if any(k in w for k in _CONTRA_KW):
        return "contradicts"
    if any(k in w for k in _CITE_KW):
        return "cites"
    return "relates"


@dataclass
class Node:
    id: int                           # memoria: id positivo · decisione: -id (namespace)
    title: str
    category: str
    tags: list[str]
    content: str
    emb: np.ndarray | None = None
    stem: str = ""                    # nome file senza .md → target dei [[wikilink]]
    ntype: str = "memory"             # memory | decision

    @property
    def label(self) -> str:
        return f"D{-self.id}" if self.ntype == "decision" else f"#{self.id}"


@dataclass
class Edge:
    src: int          # memory id
    dst: int          # memory id
    kind: str         # citation | semantic
    rel: str          # updates / contradicts / cites / relates / similar
    weight: float


@dataclass
class MemoryGraph:
    store: object
    knn: int = 6
    sem_threshold: float = 0.62
    nodes: dict[int, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    _order: list[int] = field(default_factory=list)        # stable id order
    _idx: dict[int, int] = field(default_factory=dict)     # id -> matrix index
    _W: np.ndarray | None = None

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self, project: str | None = None) -> "MemoryGraph":
        rows = self.store.get_memories_for_embedding(project)
        # Materialise nodes + embeddings (compute missing ones IN MEMORY, no persist)
        missing_text, missing_ids = [], []
        for r in rows:
            emb = None
            if r["embedding"] is not None:
                emb = np.frombuffer(r["embedding"], dtype=np.float32)
            from pathlib import Path as _P
            node = Node(r["id"], r["title"], r["category"], r["tags"], r["content"], emb,
                        stem=_P(r.get("filepath", "")).stem)
            self.nodes[r["id"]] = node
            if emb is None:
                missing_ids.append(r["id"])
                missing_text.append(
                    f"{r['title']}. Tags: {', '.join(r['tags'])}. {r['content'][:1000]}"
                )
        # 7.B: le decisioni sono nodi tipizzati (id negativi = namespace separato)
        for d in self.store.get_decisions_for_embedding(project):
            emb = None
            if d["embedding"] is not None:
                emb = np.frombuffer(d["embedding"], dtype=np.float32)
            nid = -d["id"]
            self.nodes[nid] = Node(
                nid, d["decision"][:120], "decision", [],
                f"{d['decision']}\n{d['rationale']}\n{d['context']}",
                emb, ntype="decision",
            )
            if emb is None:
                missing_ids.append(nid)
                missing_text.append(f"{d['decision']}. {d['rationale'][:600]}")

        if missing_text:
            embs = embed_texts(missing_text)
            if embs:
                for mid, e in zip(missing_ids, embs):
                    self.nodes[mid].emb = e

        self._order = sorted(self.nodes)
        self._idx = {mid: i for i, mid in enumerate(self._order)}

        self._build_citation_edges()
        self._build_supersession_edges()
        self._build_semantic_edges()
        self._build_matrix()
        return self

    def _build_citation_edges(self) -> None:
        ids = set(self.nodes)
        by_stem = {n.stem.lower(): n.id for n in self.nodes.values() if n.stem}
        seen: set[tuple[int, int, str]] = set()

        def add(src: int, dst: int, pos: int, content: str) -> None:
            if dst == src or dst not in ids:
                return
            rel = _edge_type(content[max(0, pos - 40):pos])
            key = (src, dst, rel)
            if key in seen:
                return
            seen.add(key)
            self.edges.append(Edge(src, dst, "citation", rel, _EDGE_WEIGHT[rel]))

        for src, node in self.nodes.items():
            # "memoria #82" (prosa storica)
            for m in _MEM_REF.finditer(node.content):
                add(src, int(m.group(1)), m.start(), node.content)
            # [[#82]] (provenienza di merge/insight)
            for m in _ID_REF.finditer(node.content):
                add(src, int(m.group(1)), m.start(), node.content)
            # "decisione #19" e [[D19]] → nodi decisione (id negativi)
            for m in _DEC_REF.finditer(node.content):
                add(src, -int(m.group(1)), m.start(), node.content)
            for m in _DID_REF.finditer(node.content):
                add(src, -int(m.group(1)), m.start(), node.content)
            # [[slug]] Obsidian → risolto per stem del file
            for m in _WIKI_REF.finditer(node.content):
                dst = by_stem.get(m.group(1).strip().lower())
                if dst is not None:
                    add(src, dst, m.start(), node.content)

    def _build_supersession_edges(self) -> None:
        """Belief `superseded_by` → arco tipizzato: la memoria nuova SUPERA la vecchia.

        È la 'contraddizione nel tempo' della roadmap: non rumore, ma struttura.
        """
        ids = set(self.nodes)
        for old_id, new_id in self.store.list_supersessions():
            if old_id in ids and new_id in ids and old_id != new_id:
                self.edges.append(Edge(new_id, old_id, "citation", "supersedes",
                                       _EDGE_WEIGHT["supersedes"]))

    def _build_semantic_edges(self) -> None:
        ids = [mid for mid in self._order if self.nodes[mid].emb is not None]
        if len(ids) < 2:
            return
        M = np.vstack([self.nodes[mid].emb for mid in ids])
        M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
        sims = M @ M.T
        np.fill_diagonal(sims, -1.0)
        for a, mid in enumerate(ids):
            order = np.argsort(-sims[a])[: self.knn]
            for b in order:
                s = float(sims[a, b])
                if s < self.sem_threshold:
                    break
                i, j = mid, ids[b]
                if i < j:  # dedupe undirected
                    self.edges.append(Edge(i, j, "semantic", "similar", s))

    def _build_matrix(self) -> None:
        n = len(self._order)
        W = np.zeros((n, n), dtype=float)
        for e in self.edges:
            i, j = self._idx[e.src], self._idx[e.dst]
            if e.kind == "citation":
                W[i, j] += e.weight          # directed: citer -> cited
                W[j, i] += 0.5 * e.weight    # weaker reverse (related both ways)
            else:                            # semantic / entity: symmetric
                W[i, j] += e.weight
                W[j, i] += e.weight
        self._W = W

    # ── Bridge: ingest Graphify's entity graph ───────────────────────────────

    def load_entity_edges(self, graphify_json: str, weight: float = 0.9) -> int:
        """Enrich the memory graph with Graphify's extracted entities.

        Graphify (run for free via the local `claude` CLI) turns the brain's
        markdown into an entity knowledge graph. Two memories that both touch the
        same entity (e.g. both reference `convert.py`) get linked here — which
        connects memories that have no explicit citation and aren't textually
        similar. Mapping is by Graphify's `source_file`, matched to each memory's
        stored filepath (flattened: '/' -> '__'). Returns the number of edges added.
        """
        import json as _json
        from collections import defaultdict

        g = _json.load(open(graphify_json, encoding="utf-8"))
        gnodes = {n["id"]: n for n in g["nodes"]}
        adj: dict = defaultdict(set)
        for e in g.get("links", []):
            adj[e["source"]].add(e["target"])
            adj[e["target"]].add(e["source"])

        with self.store._conn() as conn:
            rows = conn.execute("SELECT id, filepath FROM memories").fetchall()
        flat_to_id = {r["filepath"].replace("/", "__"): r["id"] for r in rows}

        def mem_id(gnode: dict) -> int | None:
            return flat_to_id.get(gnode.get("source_file") or "")

        added = 0
        for nid, node in gnodes.items():
            if node.get("file_type") == "document":
                continue  # entities only (concept/code/paper/...)
            mems = sorted({mid for d in adj[nid]
                           if (mid := mem_id(gnodes[d])) is not None and mid in self.nodes})
            label = (node.get("label") or "entity")[:30]
            for a in range(len(mems)):
                for b in range(a + 1, len(mems)):
                    self.edges.append(Edge(mems[a], mems[b], "entity", f"shares:{label}", weight))
                    added += 1
        if added:
            self._build_matrix()
        return added

    # ── Personalized PageRank (spreading activation) ─────────────────────────

    def _ppr(self, personalization: np.ndarray, damping: float = 0.85,
             iters: int = 60, tol: float = 1e-7) -> np.ndarray:
        n = len(self._order)
        W = self._W
        cs = W.sum(axis=0)
        M = np.zeros_like(W)
        nz = cs > 0
        M[:, nz] = W[:, nz] / cs[nz]
        M[:, ~nz] = 1.0 / n                  # dangling nodes -> uniform
        p = personalization / (personalization.sum() + 1e-12)
        r = p.copy()
        for _ in range(iters):
            r_new = (1 - damping) * p + damping * (M @ r)
            if np.abs(r_new - r).sum() < tol:
                r = r_new
                break
            r = r_new
        return r

    # ── Associative recall ───────────────────────────────────────────────────

    def associative_recall(self, query: str, limit: int = 5, seeds: int = 5,
                           alpha: float = 0.5) -> dict:
        """Spreading-activation recall.

        alpha blends direct query similarity (alpha) with graph proximity (1-alpha).
        Returns both the associative ranking and the plain-cosine baseline, so the
        difference is auditable.
        """
        q = embed_text(query)
        if q is None:
            raise RuntimeError("No embedding model available (install fastembed).")
        order = self._order
        n = len(order)
        embs = np.vstack([
            (self.nodes[mid].emb if self.nodes[mid].emb is not None else np.zeros_like(q))
            for mid in order
        ])
        qsim = np.array([cosine_similarity(q, embs[i]) for i in range(n)])

        seed_idx = np.argsort(-qsim)[:seeds]
        p = np.zeros(n)
        p[seed_idx] = np.clip(qsim[seed_idx], 0, None)
        ppr = self._ppr(p)

        qn = self._norm(qsim)
        gn = self._norm(ppr)
        final = alpha * qn + (1 - alpha) * gn

        baseline_ids = [order[i] for i in np.argsort(-qsim)[:limit]]
        ranked = np.argsort(-final)
        results = []
        for i in ranked[:limit]:
            mid = order[i]
            n = self.nodes[mid]
            results.append({
                "id": abs(mid),
                "type": n.ntype,
                "label": n.label,
                "title": n.title,
                "final": round(float(final[i]), 3),
                "direct_sim": round(float(qsim[i]), 3),
                "graph_score": round(float(gn[i]), 3),
                "via": [self.nodes[a].label for a in self._activators(mid, seed_idx)],
                "new_vs_cosine": mid not in baseline_ids,
            })
        return {
            "query": query,
            "associative": results,
            "baseline_cosine": [self.nodes[b].label for b in baseline_ids],
            "seeds": [self.nodes[order[i]].label for i in seed_idx],
        }

    def _activators(self, mid: int, seed_idx: np.ndarray) -> list[int]:
        """Which seed memories have an edge to `mid` (explains the activation)."""
        seeds = {self._order[i] for i in seed_idx}
        out = set()
        for e in self.edges:
            if e.src == mid and e.dst in seeds:
                out.add(e.dst)
            if e.dst == mid and e.src in seeds:
                out.add(e.src)
        return sorted(out)

    @staticmethod
    def _norm(v: np.ndarray) -> np.ndarray:
        lo, hi = float(v.min()), float(v.max())
        return (v - lo) / (hi - lo) if hi > lo else np.zeros_like(v)

    # ── Introspection ────────────────────────────────────────────────────────

    def related(self, memory_id: int, limit: int = 8) -> list[dict]:
        """Strongest neighbours of a memory, deduped (one row per neighbour)."""
        best: dict[int, dict] = {}
        for e in self.edges:
            other = e.dst if e.src == memory_id else (e.src if e.dst == memory_id else None)
            if other is None:
                continue
            cur = best.get(other)
            if cur is None or e.weight > cur["weight"]:
                n = self.nodes[other]
                best[other] = {"id": abs(other), "type": n.ntype, "label": n.label,
                               "title": n.title,
                               "kind": e.kind, "rel": e.rel, "weight": round(e.weight, 3)}
        return sorted(best.values(), key=lambda x: x["weight"], reverse=True)[:limit]

    def communities(self, min_size: int = 2, max_iter: int = 10) -> list[list[int]]:
        """Cluster di nodi via label propagation pesata (puro Python, niente networkx).

        Deterministica a parità di grafo: iterazione in ordine stabile di id,
        tie-break sull'etichetta più piccola. È il cuore del 'sonno': le
        community dense sono le candidate naturali al consolidamento.
        """
        import collections
        neigh: dict[int, list[tuple[int, float]]] = collections.defaultdict(list)
        for e in self.edges:
            neigh[e.src].append((e.dst, e.weight))
            neigh[e.dst].append((e.src, e.weight))

        labels = {nid: nid for nid in self._order}
        for _ in range(max_iter):
            changed = False
            for nid in self._order:
                if not neigh[nid]:
                    continue
                scores: dict[int, float] = collections.defaultdict(float)
                for other, w in neigh[nid]:
                    scores[labels[other]] += w
                best = min(scores, key=lambda k: (-scores[k], k))
                if best != labels[nid]:
                    labels[nid] = best
                    changed = True
            if not changed:
                break

        groups: dict[int, list[int]] = collections.defaultdict(list)
        for nid, lab in labels.items():
            groups[lab].append(nid)
        return sorted((sorted(g) for g in groups.values() if len(g) >= min_size),
                      key=len, reverse=True)

    def stats(self) -> dict:
        cit = [e for e in self.edges if e.kind == "citation"]
        sem = [e for e in self.edges if e.kind == "semantic"]
        ent = [e for e in self.edges if e.kind == "entity"]
        deg: dict[int, int] = {mid: 0 for mid in self.nodes}
        for e in self.edges:
            deg[e.src] += 1
            deg[e.dst] += 1
        rel_counts: dict[str, int] = {}
        for e in cit:
            rel_counts[e.rel] = rel_counts.get(e.rel, 0) + 1
        hubs = sorted(deg.items(), key=lambda kv: kv[1], reverse=True)[:5]
        orphans = [self.nodes[mid].label for mid, d in deg.items() if d == 0]
        return {
            "nodes": len(self.nodes),
            "memory_nodes": sum(1 for n in self.nodes.values() if n.ntype == "memory"),
            "decision_nodes": sum(1 for n in self.nodes.values() if n.ntype == "decision"),
            "citation_edges": len(cit),
            "citation_by_rel": rel_counts,
            "semantic_edges": len(sem),
            "entity_edges": len(ent),
            "hubs": [{"label": self.nodes[mid].label, "degree": d,
                      "title": self.nodes[mid].title} for mid, d in hubs],
            "orphans": orphans,
        }

    def to_mermaid(self, focus: int | None = None, max_nodes: int = 30) -> str:
        """Mermaid `graph` of the citation backbone (optionally around one node)."""
        cit = [e for e in self.edges if e.kind == "citation"]
        if focus is not None:
            keep = {focus} | {e.dst for e in cit if e.src == focus} | {e.src for e in cit if e.dst == focus}
            cit = [e for e in cit if e.src in keep and e.dst in keep]
        shown, lines = set(), ["graph LR"]
        arrow = {"supersedes": "==>|supersedes|", "updates": "-->|updates|",
                 "contradicts": "-.->|contradicts|", "cites": "-->|cites|", "relates": "-->"}

        def mmid(nid: int) -> str:                 # id mermaid-safe (niente '-')
            return f"d{-nid}" if nid < 0 else f"m{nid}"

        for e in cit[:max_nodes * 2]:
            for mid in (e.src, e.dst):
                if mid not in shown:
                    n = self.nodes[mid]
                    label = n.title[:34].replace('"', "'")
                    shape = f'{mmid(mid)}{{{{"{n.label} {label}"}}}}' if n.ntype == "decision" \
                        else f'{mmid(mid)}["{n.label} {label}"]'
                    lines.append(f"  {shape}")
                    shown.add(mid)
            lines.append(f"  {mmid(e.src)} {arrow.get(e.rel, '-->')} {mmid(e.dst)}")
        return "\n".join(lines)
