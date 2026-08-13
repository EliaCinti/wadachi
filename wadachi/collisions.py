"""
collisions.py — did someone else touch this while I was not looking? (ADR-0026)

When several agents work one brain at once, each reads at the start and writes
at the end. Between those moments the brain moves and nothing tells anybody, so
two agents can reach opposite conclusions, store both, and leave the
organisation holding a contradiction no one noticed.

This module answers one narrow question at write time: *of the things written
since this writer started, is any of them close to what it just wrote?*

Three properties are deliberate:

**The window, not the brain.** Comparison is scoped to `id > watermark` in the
same project — the handful of rows that appeared during this writer's task. The
cost is bounded by how much happened while it worked, not by how much the brain
knows.

**Proximity, not contradiction.** Cosine similarity cannot tell agreement from
disagreement: two memories can be near-identical and concur entirely. What is
detected is *proximity under concurrency*, and it is reported as a candidate for
a human to judge. Claiming more would produce a system that silently resolves
conflicts wrongly, which is worse than the problem it replaces.

**Report, never decide.** Nothing here blocks, rejects or rewrites a write. It
returns a list. The caller — Overmind — is the one that knows who is working on
what and owns the approval gate.


## Why scores are centred, and why that is not a detail

`bge-small-en-v1.5` is an English model, and on non-English text it compresses
everything toward one region of the space. Measured 2026-08-12 on raw cosine:

    Italian   collision 0.900   ·   unrelated pairs up to 0.709
    English   collision 0.767   ·   unrelated pairs up to 0.428

The ranges overlap across languages: English collisions (0.767) sit *below*
where Italian noise still reaches, so **no single absolute threshold separates
both**. A first attempt with 0.72 was caught by a test in which two entirely
unrelated Italian memories scored 0.753 — exactly the false positive that turns
a gate into something people learn to click through.

Subtracting the corpus mean removes the component every vector shares — language,
domain, and the boilerplate in the embedded text — and the separation opens up:

    Italian   collision 0.818   ·   noise 0.371, 0.336
    English   collision 0.700   ·   noise 0.106, 0.248

`THRESHOLD` sits in that gap with room on both sides.

The mean is taken over the **brain's own** embeddings, not the window's. Centring
on the window is degenerate when the window is small: with one item, the new
vector and the window vector are symmetric about their own midpoint and the
cosine is exactly -1.0 whether they collide or not. A window of one is the
common case, so that failure would have been the normal one.
"""

from __future__ import annotations

import numpy as np

from wadachi.search import (
    _FASTEMBED_AVAILABLE,
    cosine_similarity,
    embed_text,
    keyword_score,
)

# In centred space. Above this, two items in the same window are close enough to
# be worth a human glance. Tuned to be quiet: a gate that fires on everything
# gets ignored, which is the failure mode this whole design exists to avoid.
THRESHOLD = 0.55

# Keyword overlap is a blunter instrument; it is held to its own bar.
KEYWORD_THRESHOLD = 0.5

# A stale watermark should cost a bounded amount, not a full scan.
WINDOW_CAP = 200

# Below this many embedded rows there is no corpus to centre against, and an
# uncalibrated score is worse than no score.
MIN_CORPUS = 5


def _memory_text(m: dict) -> str:
    """The same shape `search.py` embeds — otherwise scores are not comparable."""
    return f"{m['title']}. Tags: {', '.join(m.get('tags') or [])}. {(m.get('content') or '')[:1000]}"


def _decision_text(d: dict) -> str:
    return f"{d['decision']}. {d.get('rationale') or ''} {d.get('context') or ''}"


def _corpus_mean(store, project: str | None) -> np.ndarray | None:
    blobs = store.embedding_sample(project=project, limit=WINDOW_CAP)
    if len(blobs) < MIN_CORPUS:
        return None
    V = np.array([np.frombuffer(b, dtype=np.float32) for b in blobs])
    return V.mean(axis=0)


def _vector(store, row: dict, kind: str, text_fn) -> np.ndarray | None:
    """The row's embedding, computing and caching it if absent."""
    emb = row.get("embedding")
    if emb is not None:
        return np.frombuffer(emb, dtype=np.float32)
    v = embed_text(text_fn(row))
    if v is None:
        return None
    store.save_embedding(kind, row["id"], v.tobytes())
    return v


def find_collisions(
    store,
    *,
    kind: str,
    row_id: int,
    text: str,
    project: str | None,
    watermark: dict | None,
    threshold: float = THRESHOLD,
    limit: int = 5,
) -> list[dict]:
    """Rows written after `watermark`, in `project`, close to `text`.

    Args:
        kind: "memories" or "decisions" — which table the new row landed in.
        row_id: the row just written, excluded from its own comparison.
        text: the new item's searchable text.
        watermark: as returned by `MemoryStore.watermark()`. Falsy → no window,
            so no candidates: without a start position there is no "since".

    Returns a list ordered by descending similarity. Empty is the common case
    and the good one.
    """
    if not watermark:
        return []

    since_mem = int(watermark.get("memories") or 0)
    since_dec = int(watermark.get("decisions") or 0)

    # A writer's own row sits above its watermark; exclude it explicitly rather
    # than trusting id arithmetic, which breaks the moment a retry renumbers.
    mems = store.get_memories_for_embedding(
        project=project, since_id=since_mem,
        exclude_id=row_id if kind == "memories" else None, limit=WINDOW_CAP,
    )
    decs = store.get_decisions_for_embedding(
        project=project, since_id=since_dec,
        exclude_id=row_id if kind == "decisions" else None, limit=WINDOW_CAP,
    )
    if not mems and not decs:
        return []

    candidates: list[dict] = []
    mu = _corpus_mean(store, project) if _FASTEMBED_AVAILABLE else None

    if _FASTEMBED_AVAILABLE and mu is not None:
        q = embed_text(text)
        if q is None:
            return []
        qc = q - mu
        for m in mems:
            v = _vector(store, m, "memories", _memory_text)
            if v is None:
                continue
            s = cosine_similarity(qc, v - mu)
            if s >= threshold:
                candidates.append({"kind": "memory", "id": m["id"],
                                   "title": m["title"], "project": m["project"],
                                   "similarity": round(float(s), 3)})
        for d in decs:
            v = _vector(store, d, "decisions", _decision_text)
            if v is None:
                continue
            s = cosine_similarity(qc, v - mu)
            if s >= threshold:
                candidates.append({"kind": "decision", "id": d["id"],
                                   "title": d["decision"][:120], "project": d["project"],
                                   "similarity": round(float(s), 3)})
    else:
        # No embeddings, or a brain too young to have a corpus to calibrate
        # against. Keyword overlap needs neither, and it is language-neutral
        # because it compares tokens rather than positions in a learned space.
        for m in mems:
            s = keyword_score(text, m["title"], m.get("content") or "", m.get("tags") or [])
            if s >= KEYWORD_THRESHOLD:
                candidates.append({"kind": "memory", "id": m["id"], "title": m["title"],
                                   "project": m["project"], "similarity": round(float(s), 3),
                                   "method": "keyword"})
        for d in decs:
            s = keyword_score(text, d["decision"], d.get("rationale") or "", [])
            if s >= KEYWORD_THRESHOLD:
                candidates.append({"kind": "decision", "id": d["id"],
                                   "title": d["decision"][:120], "project": d["project"],
                                   "similarity": round(float(s), 3), "method": "keyword"})

    candidates.sort(key=lambda c: c["similarity"], reverse=True)
    return candidates[:limit]
