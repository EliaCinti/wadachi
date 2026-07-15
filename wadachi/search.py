"""
Search Engine — semantic search with fastembed + keyword fallback.

Two modes:
  1. SEMANTIC (fastembed installed): embed query → cosine similarity against cached embeddings
  2. KEYWORD  (fallback): simple TF-IDF-ish matching on title + content + tags

Embeddings are cached in SQLite as numpy byte arrays.
"""

import numpy as np
import re
from typing import Optional

# Try to import fastembed; if unavailable, fall back to keyword search
_FASTEMBED_AVAILABLE = False
_embedding_model = None

try:
    from fastembed import TextEmbedding
    _FASTEMBED_AVAILABLE = True
except ImportError:
    pass


def _get_model():
    """Lazy-load the embedding model."""
    global _embedding_model
    if _embedding_model is None and _FASTEMBED_AVAILABLE:
        # bge-small handles Italian reasonably well, ~33M params, fast on M4
        _embedding_model = TextEmbedding("BAAI/bge-small-en-v1.5")
    return _embedding_model


def embed_text(text: str) -> np.ndarray | None:
    """Generate embedding for a single text. Returns None if fastembed not available."""
    model = _get_model()
    if model is None:
        return None
    embeddings = list(model.embed([text]))
    return np.array(embeddings[0], dtype=np.float32)


def embed_texts(texts: list[str]) -> list[np.ndarray] | None:
    """Batch embed multiple texts."""
    model = _get_model()
    if model is None:
        return None
    return [np.array(e, dtype=np.float32) for e in model.embed(texts)]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ── Decay (Fase 4.16) ─────────────────────────────────────────

def decay_penalty(mem: dict, now: "datetime | None" = None) -> float:
    """Penalità 0..0.12 per memorie mai (o da tanto non) richiamate.

    Deliberatamente GENTILE e trasparente: -2% di score per ogni mese oltre il
    primo dall'ultimo tocco (creazione o accesso), cap al 12%. Non seppellisce
    mai una memoria: riordina a parità di rilevanza. Ogni accesso la ringiovanisce.
    """
    from datetime import datetime, timezone
    ref = mem.get("last_accessed") or mem.get("created_at")
    if not ref:
        return 0.0
    try:
        then = datetime.fromisoformat(ref)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    now = now or datetime.now(timezone.utc)
    months_idle = max(0.0, ((now - then).days - 30) / 30)
    return min(0.12, 0.02 * months_idle)


# ── Keyword fallback ──────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric, remove short tokens."""
    tokens = re.findall(r"\w{2,}", text.lower())
    return set(tokens)


def keyword_score(query: str, title: str, content: str, tags: list[str]) -> float:
    """Score a memory against a query using keyword overlap."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0

    # Weight title matches higher
    title_tokens = _tokenize(title)
    tag_tokens = _tokenize(" ".join(tags))
    content_tokens = _tokenize(content[:2000])  # Don't process huge files

    title_overlap = len(query_tokens & title_tokens) / len(query_tokens)
    tag_overlap = len(query_tokens & tag_tokens) / len(query_tokens)
    content_overlap = len(query_tokens & content_tokens) / len(query_tokens)

    return title_overlap * 0.5 + tag_overlap * 0.3 + content_overlap * 0.2


# ── Main search interface ────────────────────────────────────

class SearchEngine:
    def __init__(self, store):
        self.store = store
        self.semantic_available = _FASTEMBED_AVAILABLE

    def search(
        self,
        query: str,
        project: str | None = None,
        limit: int = 5,
        min_score: float = 0.15,
        include_decisions: bool = True,
    ) -> list[dict]:
        """
        Search memories (and optionally decisions) by query.
        Uses semantic search if fastembed is available, otherwise keyword matching.
        """
        results = []

        # ── Search memories ──
        memories = self.store.get_memories_for_embedding(project)

        if self.semantic_available:
            results += self._semantic_search_memories(query, memories, limit, min_score)
        else:
            results += self._keyword_search_memories(query, memories, limit, min_score)

        # ── Search decisions ──
        if include_decisions:
            decisions = self.store.get_decisions_for_embedding(project)
            if self.semantic_available:
                results += self._semantic_search_decisions(query, decisions, limit, min_score)
            else:
                results += self._keyword_search_decisions(query, decisions, limit, min_score)

        # Sort by score descending and take top results
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    # ── Semantic search (fastembed) ───────────────────────────

    def _semantic_search_memories(
        self, query: str, memories: list[dict], limit: int, min_score: float
    ) -> list[dict]:
        query_emb = embed_text(query)
        if query_emb is None:
            return []

        # Ensure all memories have embeddings
        self._ensure_memory_embeddings(memories)

        results = []
        for mem in memories:
            emb_bytes = mem.get("embedding")
            if emb_bytes is None:
                continue
            if isinstance(emb_bytes, bytes):
                mem_emb = np.frombuffer(emb_bytes, dtype=np.float32)
            else:
                mem_emb = emb_bytes

            score = cosine_similarity(query_emb, mem_emb)
            if score >= min_score:
                penalty = decay_penalty(mem)
                entry = {
                    "type": "memory",
                    "id": mem["id"],
                    "title": mem["title"],
                    "category": mem["category"],
                    "tags": mem["tags"],
                    "project": mem.get("project", "global"),
                    "preview": mem["content"][:300] + ("..." if len(mem["content"]) > 300 else ""),
                    "score": round(score * (1 - penalty), 3),
                }
                if penalty > 0:
                    entry["decay"] = round(penalty, 3)   # trasparente: si vede perché è scesa
                results.append(entry)
        return results

    def _semantic_search_decisions(
        self, query: str, decisions: list[dict], limit: int, min_score: float
    ) -> list[dict]:
        query_emb = embed_text(query)
        if query_emb is None:
            return []

        self._ensure_decision_embeddings(decisions)

        results = []
        for dec in decisions:
            emb_bytes = dec.get("embedding")
            if emb_bytes is None:
                continue
            if isinstance(emb_bytes, bytes):
                dec_emb = np.frombuffer(emb_bytes, dtype=np.float32)
            else:
                dec_emb = emb_bytes

            score = cosine_similarity(query_emb, dec_emb)
            if score >= min_score:
                results.append({
                    "type": "decision",
                    "id": dec["id"],
                    "decision": dec["decision"],
                    "rationale": dec["rationale"][:200],
                    "project": dec["project"],
                    "score": round(score, 3),
                })
        return results

    def _ensure_memory_embeddings(self, memories: list[dict]):
        """Generate and cache embeddings for memories that don't have them."""
        to_embed = [m for m in memories if not m["has_embedding"]]
        if not to_embed:
            return

        texts = [f"{m['title']}. Tags: {', '.join(m['tags'])}. {m['content'][:1000]}" for m in to_embed]
        embeddings = embed_texts(texts)
        if embeddings is None:
            return

        for mem, emb in zip(to_embed, embeddings):
            emb_bytes = emb.tobytes()
            self.store.save_embedding("memories", mem["id"], emb_bytes)
            mem["embedding"] = emb_bytes
            mem["has_embedding"] = True

    def _ensure_decision_embeddings(self, decisions: list[dict]):
        to_embed = [d for d in decisions if not d["has_embedding"]]
        if not to_embed:
            return

        texts = [f"{d['decision']}. {d['rationale']} {d['context']}" for d in to_embed]
        embeddings = embed_texts(texts)
        if embeddings is None:
            return

        for dec, emb in zip(to_embed, embeddings):
            emb_bytes = emb.tobytes()
            self.store.save_embedding("decisions", dec["id"], emb_bytes)
            dec["embedding"] = emb_bytes
            dec["has_embedding"] = True

    # ── Keyword fallback ──────────────────────────────────────

    def _keyword_search_memories(
        self, query: str, memories: list[dict], limit: int, min_score: float
    ) -> list[dict]:
        results = []
        for mem in memories:
            score = keyword_score(query, mem["title"], mem["content"], mem["tags"])
            if score >= min_score:
                penalty = decay_penalty(mem)
                entry = {
                    "type": "memory",
                    "id": mem["id"],
                    "title": mem["title"],
                    "category": mem["category"],
                    "tags": mem["tags"],
                    "project": mem.get("project", "global"),
                    "preview": mem["content"][:300] + ("..." if len(mem["content"]) > 300 else ""),
                    "score": round(score * (1 - penalty), 3),
                }
                if penalty > 0:
                    entry["decay"] = round(penalty, 3)
                results.append(entry)
        return results

    def _keyword_search_decisions(
        self, query: str, decisions: list[dict], limit: int, min_score: float
    ) -> list[dict]:
        results = []
        for dec in decisions:
            text = f"{dec['decision']} {dec['rationale']} {dec['context']}"
            score = keyword_score(query, dec["decision"], text, [])
            if score >= min_score:
                results.append({
                    "type": "decision",
                    "id": dec["id"],
                    "decision": dec["decision"],
                    "rationale": dec["rationale"][:200],
                    "project": dec["project"],
                    "score": round(score, 3),
                })
        return results
