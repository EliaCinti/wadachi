"""
entities.py — Graphify integration: an entity knowledge graph over the brain.

Engram's memories are atomic notes; this layer extracts the *entities* inside
them (e.g. `convert.py`, `council_audio`, `Di Gennaro`, `Opus 4.8`) and the
relations between them, using Graphify (https://github.com/safishamsi/graphify).

Why this matters: two memories that mention the same entity get connected even
when neither cites the other and they aren't textually similar. On Elia's real
brain this linked 38 of 46 citation-orphan memories.

Cost: extraction runs through the **local `claude` CLI** (`--backend=claude-cli`),
so it uses the Claude plan, not metered API → $0. The whole thing degrades
gracefully: if `graphify` isn't installed, Engram keeps working without it.

Install the engine:  pip install graphifyy   (or set GRAPHIFY_BIN to its path)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def _graphify_bin() -> str | None:
    if os.environ.get("GRAPHIFY_BIN"):
        return os.environ["GRAPHIFY_BIN"]
    found = shutil.which("graphify")
    if found:
        return found
    cand = Path(sys.executable).parent / "graphify"   # same venv as the server
    return str(cand) if cand.exists() else None


class EntityGraph:
    """Runs/caches Graphify over the brain corpus and reports its structure."""

    def __init__(self, store, backend: str = "claude-cli"):
        self.store = store
        self.backend = backend
        self.cache_dir = Path(store.brain_dir) / ".constellation"
        self.corpus_dir = self.cache_dir / "corpus"
        self.out_dir = self.corpus_dir / "graphify-out"
        self.graph_json = self.out_dir / "graph.json"
        self.report_md = self.out_dir / "GRAPH_REPORT.md"

    # ── Availability ─────────────────────────────────────────────────────────

    def available(self) -> bool:
        return _graphify_bin() is not None

    # ── Build (expensive; explicit) ──────────────────────────────────────────

    def _export_corpus(self) -> int:
        """Copy each memory .md into a flat corpus dir named by its filepath
        ('/' -> '__') so Graphify's `source_file` maps back to the memory."""
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
        for f in self.corpus_dir.glob("*.md"):
            f.unlink()
        n = 0
        with self.store._conn() as conn:
            rows = conn.execute("SELECT filepath FROM memories").fetchall()
        for r in rows:
            rel = r["filepath"].replace("\\", "/")
            src = Path(self.store.brain_dir) / rel
            if src.exists():
                dst = self.corpus_dir / rel.replace("/", "__")
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                n += 1
        return n

    def rebuild(self) -> dict:
        binp = _graphify_bin()
        if not binp:
            return {"ok": False,
                    "error": "graphify not found. Install with `pip install graphifyy` or set GRAPHIFY_BIN."}
        count = self._export_corpus()
        try:
            subprocess.run([binp, str(self.corpus_dir), f"--backend={self.backend}"],
                           capture_output=True, text=True, timeout=900)
            if self.graph_json.exists():  # name the communities (best-effort)
                subprocess.run([binp, "cluster-only", str(self.corpus_dir),
                                f"--backend={self.backend}", "--no-viz"],
                               capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "graphify extraction timed out"}
        if not self.graph_json.exists():
            return {"ok": False, "error": "extraction produced no graph.json"}
        info = self.summary()
        info["ok"] = True
        info["corpus_files"] = count
        return info

    # ── Read cached graph ────────────────────────────────────────────────────

    def _load(self) -> dict | None:
        if not self.graph_json.exists():
            return None
        return json.loads(self.graph_json.read_text(encoding="utf-8"))

    def _community_names(self) -> list[str]:
        if not self.report_md.exists():
            return []
        text = self.report_md.read_text(encoding="utf-8")
        return re.findall(r"_COMMUNITY_[^|]+\|([^\]]+)\]\]", text)

    def summary(self) -> dict:
        g = self._load()
        if not g:
            return {"ok": False, "error": "No entity graph yet. Run rebuild_entity_graph first."}
        nodes = {n["id"]: n for n in g["nodes"]}
        adj: dict = defaultdict(set)
        for e in g.get("links", []):
            adj[e["source"]].add(e["target"])
            adj[e["target"]].add(e["source"])
        docs = [i for i, n in nodes.items() if n.get("file_type") == "document"]
        ents = [i for i, n in nodes.items() if n.get("file_type") != "document"]
        comm: dict = defaultdict(list)
        for i, n in nodes.items():
            comm[n.get("community")].append(i)
        gods = sorted(((len(adj[i]), nodes[i].get("label", "")) for i in nodes),
                      key=lambda x: x[0], reverse=True)[:10]
        surprising = []
        for e in g.get("links", []):
            if str(e.get("confidence", "")).upper() == "INFERRED":
                surprising.append({
                    "from": nodes.get(e["source"], {}).get("label", "")[:50],
                    "rel": e.get("relation"),
                    "to": nodes.get(e["target"], {}).get("label", "")[:50],
                })
        return {
            "nodes": len(nodes), "memories": len(docs), "entities": len(ents),
            "edges": len(g.get("links", [])),
            "communities": len([k for k in comm if k is not None]),
            "communities_named": self._community_names(),
            "community_sizes": sorted((len(v) for v in comm.values()), reverse=True),
            "god_nodes": [{"label": l[:60], "degree": d} for d, l in gods],
            "surprising_connections": surprising[:8],
            "report_path": str(self.report_md) if self.report_md.exists() else None,
        }
