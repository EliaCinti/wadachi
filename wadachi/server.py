"""
Wadachi MCP Server — persistent memory + semantic search for Claude Code / Desktop.

Tools (30), grouped by area:
  Memory:       store_memory, get_memory, list_memories, update_memory, delete_memory, memory_history
  Search/Ctx:   recall, get_context, expand_memory, brain_status
  Decisions:    store_decision, list_decisions
  Projects:     register_project, list_projects
  Constellation: recall_associative, related_memories, memory_graph, rebuild_entity_graph
  Beliefs:      review_beliefs, set_belief, flag_stale
  Reflection:   reflect, list_insights, accept_insight, reject_insight
  Procedural:   review_procedures
  Consolidation: consolidate, merge_memories
  Provenance/Time: why, as_of
"""

import functools
import json
import os
import sys
import time

# Add parent dir to path so imports work when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from wadachi import __version__
from wadachi.log import setup as _log_setup
from wadachi.store import MemoryStore
from wadachi.search import SearchEngine
from wadachi.graph import MemoryGraph
from wadachi.entities import EntityGraph
from wadachi.beliefs import BeliefReviewer
from wadachi.reflect import Reflector
from wadachi.procedural import ProceduralReviewer

# ── Init ──────────────────────────────────────────────────────

# default: ~/.wadachi, ma se esiste un brain legacy in ~/.engram continua a usarlo
_legacy_brain = os.path.expanduser("~/.engram")
_default_brain = _legacy_brain if os.path.isdir(_legacy_brain) else os.path.expanduser("~/.wadachi")
brain_dir = os.environ.get("BRAIN_DIR", _default_brain)
log = _log_setup(brain_dir)
store = MemoryStore(brain_dir)
search_engine = SearchEngine(store)
log.info("wadachi %s — brain: %s, search: %s", __version__, brain_dir,
         "semantic" if search_engine.semantic_available else "keyword")


def _instrumented(fn):
    """Ogni tool loggato: durata a DEBUG, eccezioni con traceback a ERROR.

    Le eccezioni vengono ri-alzate (il protocollo MCP le riporta al client);
    il log su file è ciò che l'utente può allegare a una segnalazione.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            out = fn(*args, **kwargs)
            log.debug("tool %s ok (%.0f ms)", fn.__name__, (time.perf_counter() - t0) * 1000)
            return out
        except Exception:
            log.exception("tool %s FALLITO (args=%r kwargs=%r)", fn.__name__, args, kwargs)
            raise
    return wrapper


def tool(*dargs, **dkwargs):
    """Come @mcp.tool(), ma con logging trasparente."""
    def deco(fn):
        return mcp.tool(*dargs, **dkwargs)(_instrumented(fn))
    return deco

mcp = FastMCP(
    "wadachi",
    instructions="""You have access to a persistent Brain — a knowledge base that survives across sessions.

## How to use the Brain effectively:

1. **START of every session**: Call `get_context` with the current working directory to load relevant memories and decisions. This saves you from re-analyzing everything.

2. **BEFORE deep-diving into files**: Call `recall` with keywords about what you're about to do. The Brain may already have insights, patterns, or decisions from previous sessions.

3. **AFTER completing work**: Call `store_memory` to save:
   - Architecture decisions and WHY they were made
   - Patterns discovered in the codebase
   - Bugs found and how they were fixed
   - Configuration details that took time to figure out
   - Any insight that would save time if you had it at the start

4. **For decisions**: Use `store_decision` when making choices between alternatives. Record what you chose, why, and what you rejected. Future sessions will thank you.

5. **Projects**: Use `register_project` to associate directory paths with project names. Then `get_context` will automatically scope memories to the relevant project.

## Categories for memories:
- `architecture`: System design, patterns, structure decisions
- `bugfix`: Bugs found and their solutions
- `config`: Configuration, setup, environment details
- `pattern`: Code patterns, conventions, style rules
- `context`: General project context and background
- `reference`: API details, library usage, external docs
- `note`: General notes

## Golden rule: If you spent time figuring something out, store it. The 30 seconds to store a memory saves 5 minutes next session.

## Linking (LLM Wiki): when a memory relates to another, LINK it in the content — `[[#42]]` by id or `[[file-slug]]` Obsidian-style. Links become graph edges: associative recall, provenance and consolidation all travel on them. The brain dir is a valid Obsidian vault and an OKF bundle.
""",
)


# ── Memory Tools ──────────────────────────────────────────────


@tool()
def store_memory(
    content: str,
    title: str,
    project: str = "global",
    tags: list[str] | None = None,
    category: str = "note",
) -> str:
    """Store knowledge in the Brain for future sessions.

    Args:
        content: The information to remember (markdown supported).
        title: Short descriptive title for this memory.
        project: Project name (use 'global' for cross-project knowledge).
        tags: Keywords for easier retrieval (e.g. ["python", "fastapi", "auth"]).
        category: One of: architecture, bugfix, config, pattern, context, reference, note.
    """
    result = store.store_memory(content, title, project, tags, category)
    return json.dumps(result, indent=2)


@tool()
def recall(
    query: str,
    project: str | None = None,
    limit: int = 5,
    neighbors: bool = False,
) -> str:
    """Search the Brain semantically. Use this to find relevant memories before starting work.

    Args:
        query: Natural language query describing what you're looking for.
        project: Scope search to a specific project (None = search all).
        limit: Maximum number of results to return.
        neighbors: Attach each result's strongest graph neighbours (1 hop, typed) —
            graph-aware recall: what's CONNECTED surfaces even if not textually similar.
    """
    results = search_engine.search(query, project=project, limit=limit)
    results = _annotate_beliefs(results)
    if neighbors and results:
        g = _assoc_graph(project)
        for r in results:
            if r.get("type") == "memory" and r["id"] in g.nodes:
                linked = g.related(r["id"], limit=3)
                if linked:
                    r["linked"] = [{"label": x["label"], "rel": x["rel"],
                                    "title": x["title"][:70]} for x in linked]
    if not results:
        mode = "semantic" if search_engine.semantic_available else "keyword"
        return json.dumps({
            "results": [],
            "message": f"No relevant memories found (search mode: {mode}). Consider storing useful information as you work.",
        })

    return json.dumps({
        "results": results,
        "search_mode": "semantic" if search_engine.semantic_available else "keyword",
        "count": len(results),
    }, indent=2)


@tool()
def get_memory(memory_id: int) -> str:
    """Retrieve the full content of a specific memory by its ID.

    Args:
        memory_id: The numeric ID of the memory to retrieve.
    """
    result = store.get_memory(memory_id)
    if result is None:
        return json.dumps({"error": f"Memory #{memory_id} not found."})
    return json.dumps(result, indent=2)


@tool()
def list_memories(
    project: str | None = None,
    category: str | None = None,
) -> str:
    """List all memories in the Brain, optionally filtered.

    Args:
        project: Filter by project name.
        category: Filter by category (architecture, bugfix, config, pattern, context, reference, note).
    """
    results = store.list_memories(project, category)
    return json.dumps({"memories": results, "count": len(results)}, indent=2)


@tool()
def update_memory(
    memory_id: int,
    content: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update an existing memory's content or tags.

    Args:
        memory_id: The numeric ID of the memory to update.
        content: New content (replaces existing). Pass None to keep current content.
        tags: New tags (replaces existing). Pass None to keep current tags.
    """
    success = store.update_memory(memory_id, content, tags)
    if success:
        return json.dumps({"status": "updated", "id": memory_id})
    return json.dumps({"error": f"Memory #{memory_id} not found."})


@tool()
def delete_memory(memory_id: int) -> str:
    """Permanently delete a memory from the Brain.

    Args:
        memory_id: The numeric ID of the memory to delete.
    """
    success = store.delete_memory(memory_id)
    if success:
        return json.dumps({"status": "deleted", "id": memory_id})
    return json.dumps({"error": f"Memory #{memory_id} not found."})


# ── Decision Tools ────────────────────────────────────────────


@tool()
def store_decision(
    decision: str,
    rationale: str = "",
    alternatives: str = "",
    context: str = "",
    project: str = "global",
) -> str:
    """Log a decision for future reference. Invaluable for understanding past choices.

    Args:
        decision: What was decided.
        rationale: Why this choice was made.
        alternatives: What other options were considered and why they were rejected.
        context: Surrounding context that influenced the decision.
        project: Project this decision belongs to.
    """
    result = store.store_decision(decision, rationale, alternatives, context, project)
    return json.dumps(result, indent=2)


@tool()
def list_decisions(
    project: str | None = None,
    limit: int = 20,
) -> str:
    """List recent decisions, optionally filtered by project.

    Args:
        project: Filter by project name.
        limit: Maximum number of decisions to return.
    """
    results = store.list_decisions(project, limit)
    return json.dumps({"decisions": results, "count": len(results)}, indent=2)


# ── Project Tools ─────────────────────────────────────────────


@tool()
def register_project(
    name: str,
    description: str = "",
    paths: list[str] | None = None,
) -> str:
    """Register a project so the Brain can auto-detect it from the working directory.

    Args:
        name: Short project identifier (e.g. 'feynotes', 'laplacebo').
        description: What this project is about.
        paths: Filesystem paths associated with this project (for auto-detection).
    """
    result = store.register_project(name, description, paths)
    return json.dumps(result, indent=2)


@tool()
def list_projects() -> str:
    """List all registered projects."""
    results = store.list_projects()
    return json.dumps({"projects": results, "count": len(results)}, indent=2)


# ── Context Tool (the killer feature) ────────────────────────


def _est_tokens(text: str) -> int:
    """Stima grossolana ma stabile: ~4 caratteri per token."""
    return len(text) // 4


def _render_context_dense(context: dict, max_tokens: int) -> str:
    """Formato a livelli (Fase 4.12/4.14): righe compatte con puntatori #id.

    Se il budget non basta, si tronca PER RILEVANZA (le memorie sono già
    ordinate per score): prima si accorciano needs_review e decisioni,
    poi le memorie dalla coda. Header, stats e footer restano sempre.
    """
    proj = context["project"].get("name", "unknown")
    head = [f"# wadachi · project: {proj} · search: {context['search_mode'].split()[0]}"]
    if "note" in context["project"]:
        head.append(f"({context['project']['note']})")

    mem_lines = []
    for m in context.get("relevant_memories", []):
        mark = ""
        if m.get("belief"):
            mark = f" ⚠{m['belief']['status']}"
        score = f" ·{m['score']}·" if "score" in m else " ·"
        kind = "D" if m.get("type") == "decision" else "#"
        label = m.get("title") or m.get("decision", "")
        mem_lines.append(f"{kind}{m['id']} {m.get('category', 'decision')}{score} {label[:95]}{mark}")
    for m in context.get("recent_memories", []):
        mem_lines.append(f"#{m['id']} {m['category']} · {m['title'][:95]}")

    dec_lines = [f"D{d['id']} {d['created_at'][:10]} · {d['decision'][:100]}"
                 for d in context.get("recent_decisions", [])]
    rev_lines = [f"#{f['memory_id']} [{','.join(f.get('signals', []))}] {f.get('reason', '')[:75]}"
                 for f in context.get("needs_review", [])]

    s = context["stats"]
    footer = [f"stats: {s['memories']} mem · {s['decisions']} dec · {s['projects']} prog",
              "→ contenuto completo: expand_memory(ids=[…])"]

    def assemble(n_mem, n_dec, n_rev):
        parts = list(head)
        if mem_lines[:n_mem]:
            parts += ["## memorie (rilevanza ↓)"] + mem_lines[:n_mem]
        if dec_lines[:n_dec]:
            parts += ["## decisioni recenti"] + dec_lines[:n_dec]
        if rev_lines[:n_rev]:
            parts += ["## da rivedere"] + rev_lines[:n_rev]
        return "\n".join(parts + footer)

    n_mem, n_dec, n_rev = len(mem_lines), len(dec_lines), len(rev_lines)
    out = assemble(n_mem, n_dec, n_rev)
    while _est_tokens(out) > max_tokens:
        if n_rev > 1:
            n_rev -= 1
        elif n_dec > 2:
            n_dec -= 1
        elif n_mem > 1:
            n_mem -= 1
        else:
            break                      # sotto il minimo utile non si scende
        out = assemble(n_mem, n_dec, n_rev)
    return out


@tool()
def get_context(
    cwd: str = "",
    task_description: str = "",
    limit: int = 8,
    max_tokens: int = 600,
    format: str = "dense",
) -> str:
    """Auto-inject relevant context at the start of a session. Call this FIRST.

    Detects the current project from cwd, then returns a COMPACT overview
    (~300-600 tokens): memory/decision pointers with ids, what needs review,
    stats. Drill into anything with expand_memory(ids=[...]).

    Args:
        cwd: Current working directory (for project auto-detection).
        task_description: Brief description of what you're about to do (improves relevance).
        limit: Max memories to include.
        max_tokens: Token budget for the dense format — truncated by relevance, not by age.
        format: "dense" (default, compact markdown) or "json" (full previews, verbose).
    """
    # Detect project
    project = None
    project_info = None
    if cwd:
        project = store.detect_project(cwd)
    if project:
        projects = store.list_projects()
        project_info = next((p for p in projects if p["name"] == project), None)

    context = {
        "project": project_info or {"name": project or "unknown", "note": "No project detected. Use register_project to set up project auto-detection."},
        "search_mode": "semantic" if search_engine.semantic_available else "keyword (install fastembed for semantic search)",
    }

    # Get relevant memories
    if task_description:
        search_results = search_engine.search(task_description, project=project, limit=limit)
        context["relevant_memories"] = _annotate_beliefs(search_results)
    else:
        # Just get recent memories for this project
        memories = store.list_memories(project=project)
        context["recent_memories"] = memories[:limit]

    # Get recent decisions
    decisions = store.list_decisions(project=project, limit=5)
    context["recent_decisions"] = decisions

    # Beliefs needing review (so a session opens knowing what's stale)
    try:
        context["needs_review"] = BeliefReviewer(store).scan(project=project, limit=5)
    except Exception:  # noqa: BLE001 — review is best-effort, never block context
        context["needs_review"] = []

    # Stats
    context["stats"] = store.stats()

    if format == "json":
        return json.dumps(context, indent=2)
    return _render_context_dense(context, max_tokens)


@tool()
def expand_memory(ids: list[int]) -> str:
    """Drill-down dal contesto compatto: il contenuto COMPLETO di una o più memorie.

    Args:
        ids: Gli id (max 10) presi dai puntatori #id di get_context/recall.
    """
    out = []
    for mid in ids[:10]:
        m = store.get_memory(mid)
        out.append(m if m else {"id": mid, "error": "not found"})
    return json.dumps({"memories": out, "count": len(out)}, indent=2)


# ── Status Tool ───────────────────────────────────────────────


@tool()
def brain_status() -> str:
    """Check Brain health and statistics."""
    stats = store.stats()
    return json.dumps({
        "brain_dir": str(store.brain_dir),
        "search_mode": "semantic (fastembed)" if search_engine.semantic_available else "keyword (fastembed not installed)",
        "stats": stats,
        "projects": store.list_projects(),
    }, indent=2)


# ── Constellation: graph-aware recall (the differentiator) ───


def _assoc_graph(project: str | None) -> MemoryGraph:
    """Build the memory graph (citations + semantic kNN), enriched with the
    cached Graphify entity edges if an entity graph has been built."""
    g = MemoryGraph(store).build(project)
    eg = EntityGraph(store)
    if eg.graph_json.exists():
        try:
            g.load_entity_edges(str(eg.graph_json))
        except Exception:  # noqa: BLE001 — entity enrichment is best-effort
            pass
    return g


@tool()
def recall_associative(query: str, project: str | None = None, limit: int = 5) -> str:
    """Spreading-activation recall over the memory graph (HippoRAG-style).

    Unlike `recall` (pure cosine top-k), this seeds the query's best matches and
    propagates activation along citation, semantic, and shared-entity edges, so
    strongly-connected memories surface even when not textually similar. Returns
    the associative ranking AND the plain-cosine baseline for comparison.

    Args:
        query: Natural language query.
        project: Scope to a project (None = whole brain).
        limit: Number of results.
    """
    g = _assoc_graph(project)
    try:
        return json.dumps(g.associative_recall(query, limit=limit), indent=2)
    except RuntimeError as e:
        # senza fastembed il recall associativo non può embeddare la query:
        # niente crash MCP — errore chiaro + fallback keyword utilizzabile
        return json.dumps({
            "error": str(e),
            "hint": "recall_associative richiede la ricerca semantica: pip install 'wadachi[semantic]'.",
            "keyword_fallback": json.loads(recall(query, project=project, limit=limit)),
        }, indent=2)


@tool()
def related_memories(memory_id: int, limit: int = 8) -> str:
    """Show the memories most strongly linked to a given one (typed neighbours).

    Args:
        memory_id: The memory to expand from.
        limit: Max neighbours to return.
    """
    g = _assoc_graph(None)
    return json.dumps({"id": memory_id, "related": g.related(memory_id, limit)}, indent=2)


@tool()
def memory_graph(project: str | None = None, focus_id: int | None = None,
                 include_entities: bool = True) -> str:
    """Overview of the brain as a graph: hubs, orphans, components, a Mermaid
    diagram of the citation backbone, and (if built) the Graphify entity graph
    with communities, god-nodes and surprising connections.

    Args:
        project: Scope to a project (None = whole brain).
        focus_id: If set, the Mermaid diagram is centred on this memory.
        include_entities: Include the Graphify entity-graph summary.
    """
    g = _assoc_graph(project)
    out = g.stats()
    out["mermaid"] = g.to_mermaid(focus=focus_id)
    if include_entities:
        out["entity_graph"] = EntityGraph(store).summary()
    return json.dumps(out, indent=2)


@tool()
def rebuild_entity_graph(project: str | None = None) -> str:
    """(Re)build the Graphify entity knowledge graph over the brain.

    Runs extraction via the local `claude` CLI (free; uses your Claude plan).
    Requires `graphifyy` installed (pip install graphifyy). Cached under
    BRAIN_DIR/.constellation so other tools read it instantly.
    """
    return json.dumps(EntityGraph(store).rebuild(), indent=2)


@tool()
def memory_history(memory_id: int) -> str:
    """Show prior versions of a memory (preserved on every update — non-destructive).

    Args:
        memory_id: The memory whose edit history to retrieve.
    """
    return json.dumps({"id": memory_id, "history": store.get_memory_history(memory_id)}, indent=2)


# ── Belief revision (Phase 2) ────────────────────────────────


def _annotate_beliefs(results: list[dict]) -> list[dict]:
    """Attach belief status to memory results and hide retired ones. Additive."""
    out = []
    for r in results:
        if r.get("type") == "memory":
            b = store.get_belief(r["id"])
            if b["status"] == "retired":
                continue
            if b["status"] != "active" or b["superseded_by"] or b["confidence"] < 0.7:
                note = {"status": b["status"], "confidence": b["confidence"]}
                if b["superseded_by"]:
                    note["superseded_by"] = b["superseded_by"]
                if b["review_reason"]:
                    note["reason"] = b["review_reason"]
                r["belief"] = note
        out.append(r)
    return out


@tool()
def review_beliefs(project: str | None = None) -> str:
    """Scan the brain for memories that have likely gone stale and need review:
    superseded by a newer memory, past a temporal deadline, conditional/provisional,
    or already flagged. Read-only — it suggests, never deletes. Confirm with flag_stale.

    Args:
        project: Scope to a project (None = whole brain).
    """
    flagged = BeliefReviewer(store).scan(project=project)
    return json.dumps({"flagged": flagged, "count": len(flagged)}, indent=2)


@tool()
def set_belief(memory_id: int, confidence: float | None = None, status: str | None = None,
               valid_until: str | None = None, review_reason: str | None = None,
               superseded_by: int | None = None) -> str:
    """Update a memory's belief envelope. None args keep the current value.

    Args:
        memory_id: The memory.
        confidence: 0..1 how sure we are.
        status: active | stale | retired.
        valid_until: ISO date after which the claim expires.
        review_reason: why the status/confidence changed.
        superseded_by: id of the memory that replaced this one.
    """
    return json.dumps(store.set_belief(memory_id, confidence=confidence, status=status,
                                       valid_until=valid_until, review_reason=review_reason,
                                       superseded_by=superseded_by), indent=2)


@tool()
def flag_stale(memory_id: int, reason: str, superseded_by: int | None = None) -> str:
    """Mark a memory as stale: kept and recoverable, but annotated in recall.

    Args:
        memory_id: The memory to flag.
        reason: Why it's stale.
        superseded_by: id of the memory that replaced it, if any.
    """
    return json.dumps(store.set_belief(memory_id, status="stale", review_reason=reason,
                                       superseded_by=superseded_by), indent=2)


# ── Reflection & procedural (Phase 3) ────────────────────────


@tool()
def reflect(project: str | None = None, limit: int = 15, store_them: bool = True) -> str:
    """Think across memories: surface cross-project analogies and non-obvious
    connections that recall cannot reach (reuses the Graphify graph — no extra LLM
    cost). Candidates are saved as `proposed` insights (unless store_them=False)
    for you to accept_insight / reject_insight.

    Args:
        project: Scope to a project (None = whole brain).
        limit: Max candidates.
        store_them: Persist candidates as proposed insights.
    """
    cands = Reflector(store).candidates(project=project, limit=limit)
    saved = [store.store_insight(c["claim"], c["itype"], c["evidence_ids"]) for c in cands] if store_them else []
    return json.dumps({"candidates": cands, "stored": len(saved), "count": len(cands)}, indent=2)


@tool()
def list_insights(status: str | None = "proposed") -> str:
    """List reflection insights, optionally by status (proposed | accepted | rejected)."""
    items = store.list_insights(status=status)
    return json.dumps({"insights": items, "count": len(items)}, indent=2)


@tool()
def accept_insight(insight_id: int, project: str = "global") -> str:
    """Accept an insight: mark it accepted and promote it to a real memory linked
    to its source memories.

    Args:
        insight_id: The insight to accept.
        project: Project for the promoted memory.
    """
    ins = store.get_insight(insight_id)
    if not ins:
        return json.dumps({"error": f"Insight #{insight_id} not found."})
    store.set_insight_status(insight_id, "accepted")
    refs = " ".join(f"[[#{m}]]" for m in ins["evidence_ids"])
    mem = store.store_memory(
        content=f"{ins['claim']}\n\nDeriva da: {refs}",
        title=f"Insight: {ins['claim'][:60]}",
        project=project, tags=["insight", ins["itype"]], category="context")
    return json.dumps({"status": "accepted", "insight_id": insight_id, "memory": mem}, indent=2)


@tool()
def reject_insight(insight_id: int) -> str:
    """Reject an insight (kept on record, marked rejected).

    Args:
        insight_id: The insight to reject.
    """
    ok = store.set_insight_status(insight_id, "rejected")
    return json.dumps({"status": "rejected" if ok else "not_found", "insight_id": insight_id})


# ── Provenienza e tempo (Fase 7.B) ───────────────────────────


@tool()
def why(question: str, project: str | None = None, limit: int = 2) -> str:
    """Interrogate decision provenance: WHY are things the way they are?

    Ask "why do we use X and not Y?" — returns the matching decision(s) with
    rationale, the rejected alternatives, the context, plus the memories that
    cite each decision (its evidence in the graph) and what supersedes what.

    Args:
        question: The "why" question, natural language.
        project: Scope to a project (None = whole brain).
        limit: Max decisions to explain.
    """
    hits = [r for r in search_engine.search(question, project=project,
                                            limit=limit * 4, include_decisions=True)
            if r.get("type") == "decision"][:limit]
    if not hits:
        return json.dumps({"answers": [], "message":
                           "Nessuna decisione registrata corrisponde. Prova recall(), "
                           "o registra la scelta con store_decision la prossima volta."})

    g = _assoc_graph(project)
    answers = []
    for h in hits:
        d = store.get_decision(h["id"])
        nid = -h["id"]
        evidence = [{"label": g.nodes[e.src].label, "rel": e.rel,
                     "title": g.nodes[e.src].title[:80]}
                    for e in g.edges
                    if e.dst == nid and e.kind == "citation" and e.src in g.nodes]
        answers.append({
            "decision_id": d["id"],
            "decided": d["decision"],
            "why": d["rationale"],
            "rejected_alternatives": d["alternatives"],
            "context": d["context"],
            "when": d["created_at"],
            "project": d["project"],
            "cited_by": evidence,
            "score": h["score"],
        })
    return json.dumps({"question": question, "answers": answers}, indent=2)


@tool()
def as_of(date: str, query: str | None = None, project: str | None = None,
          limit: int = 15) -> str:
    """Time-travel: what did the brain believe at a given date?

    Memories that existed then, with their content AS IT WAS (reconstructed from
    the non-destructive version history), and which of them were already
    superseded or expired at that date.

    Args:
        date: ISO date ("2026-03-01") — the point in time to reconstruct.
        query: Optional filter — only memories relevant to this (searched today,
            content returned as of the date).
        project: Scope to a project.
        limit: Max memories.
    """
    if len(date) == 10:
        date = date + "T23:59:59+00:00"        # fine giornata, comodo per date pure

    candidates = store.list_memories(project=project)
    existed = [m for m in candidates if m["created_at"] <= date]

    if query:
        found = search_engine.search(query, project=project, limit=limit * 3)
        keep = {r["id"] for r in found if r.get("type") == "memory"}
        existed = [m for m in existed if m["id"] in keep]

    supers = dict(store.list_supersessions())   # old_id -> new_id
    created = {m["id"]: m["created_at"] for m in candidates}

    out = []
    for m in existed[:limit]:
        b = store.get_belief(m["id"])
        status = "active"
        new_id = supers.get(m["id"])
        if new_id and created.get(new_id, "9999") <= date:
            status = f"already superseded by #{new_id}"
        elif b["valid_until"] and b["valid_until"] < date:
            status = "expired"
        entry = {"id": m["id"], "title": m["title"], "created_at": m["created_at"],
                 "status_at_date": status}
        if query:                               # col filtro: anche il contenuto d'epoca
            content = store.get_content_as_of(m["id"], date)
            if content:
                entry["content_as_of"] = content[:1500]
        out.append(entry)

    return json.dumps({"as_of": date, "memories": out, "count": len(out)}, indent=2)


# ── Consolidamento (Fase 4.15) ───────────────────────────────


@tool()
def consolidate(project: str | None = None, threshold: float = 0.86, max_groups: int = 8) -> str:
    """Propose groups of redundant/overlapping memories to merge (READ-ONLY).

    Finds clusters of highly-similar memories. Nothing is modified: review the
    groups, write a synthesis yourself, then call merge_memories(...) — the
    sources get marked superseded (never deleted, always recoverable).

    Args:
        project: Scope to a project (None = whole brain).
        threshold: Cosine similarity above which two memories are considered redundant.
        max_groups: Max candidate groups to return.
    """
    if not search_engine.semantic_available:
        return json.dumps({"error": "consolidate richiede la ricerca semantica",
                           "hint": "pip install 'wadachi[semantic]'"})
    import numpy as np
    mems = [m for m in store.get_memories_for_embedding(project)
            if store.get_belief(m["id"])["status"] == "active"]
    if len(mems) < 2:
        return json.dumps({"groups": [], "count": 0})
    search_engine._ensure_memory_embeddings(mems)
    mems = [m for m in mems if m.get("embedding") is not None]

    vecs = np.vstack([np.frombuffer(m["embedding"], dtype=np.float32)
                      if isinstance(m["embedding"], bytes) else m["embedding"] for m in mems])
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
    sims = vecs @ vecs.T

    # union-find sulle coppie sopra soglia
    parent = list(range(len(mems)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pair_sims = {}
    for i in range(len(mems)):
        for k in range(i + 1, len(mems)):
            if sims[i, k] >= threshold:
                parent[find(i)] = find(k)
                pair_sims.setdefault(frozenset((i, k)), float(sims[i, k]))

    clusters: dict[int, list[int]] = {}
    for i in range(len(mems)):
        clusters.setdefault(find(i), []).append(i)

    groups = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        pair_vals = [v for key, v in pair_sims.items() if key <= set(members)]
        groups.append({
            "ids": [mems[i]["id"] for i in members],
            "similarity": round(max(pair_vals), 3) if pair_vals else threshold,
            "memories": [{"id": mems[i]["id"], "title": mems[i]["title"],
                          "preview": mems[i]["content"][:140]} for i in members],
        })
    groups.sort(key=lambda g: -g["similarity"])
    return json.dumps({
        "groups": groups[:max_groups],
        "count": len(groups[:max_groups]),
        "how_to_merge": "scrivi tu la sintesi, poi: merge_memories(source_ids=[...], title=..., content=...)",
    }, indent=2)


@tool()
def merge_memories(source_ids: list[int], title: str, content: str,
                   project: str = "global", tags: list[str] | None = None) -> str:
    """Merge redundant memories: store the synthesis as a NEW memory and mark
    the sources superseded (kept and recoverable — never deleted).

    Args:
        source_ids: The memories being consolidated (≥2).
        title: Title of the merged memory.
        content: The synthesis you wrote (the sources' provenance is appended automatically).
        project: Project for the merged memory.
        tags: Tags for the merged memory.
    """
    if len(source_ids) < 2:
        return json.dumps({"error": "servono almeno 2 memorie da fondere"})
    missing = [i for i in source_ids if store.get_memory(i) is None]
    if missing:
        return json.dumps({"error": f"memorie inesistenti: {missing}"})

    refs = " ".join(f"[[#{i}]]" for i in source_ids)
    mem = store.store_memory(
        content=f"{content}\n\nConsolida: {refs}",
        title=title, project=project,
        tags=(tags or []) + ["consolidata"], category="context",
    )
    for sid in source_ids:
        store.set_belief(sid, status="stale", superseded_by=mem["id"],
                         review_reason=f"consolidata in #{mem['id']}")
    return json.dumps({"status": "merged", "memory": mem,
                       "superseded": source_ids}, indent=2)


@tool()
def review_procedures(project: str | None = None) -> str:
    """Find recurring-incident clusters and propose always-on rules for review.
    Read-only — never edits your operating instructions.

    Args:
        project: Scope to a project (None = whole brain).
    """
    rules = ProceduralReviewer(store).review(project=project)
    return json.dumps({"candidate_rules": rules, "count": len(rules)}, indent=2)


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
