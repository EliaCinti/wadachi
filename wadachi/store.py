"""
Memory Store — SQLite metadata + markdown files on disk.

Storage layout:
    ~/.brain/
    ├── config.json
    ├── brain.db              # SQLite: metadata, embeddings cache, decisions
    ├── global/               # Cross-project memories
    │   └── *.md
    └── projects/
        ├── feynotes/
        │   └── *.md
        └── laplacebo/
            └── *.md
"""

import sqlite3
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _slugify(text: str) -> str:
    """Turn a title into a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:80].strip("-")


def _atomic_write_text(path: Path, text: str) -> None:
    """Write a file atomically: a concurrent reader (or writer) never sees a
    torn/half-written file. Write to a unique temp file in the same directory,
    then os.replace (atomic on the same filesystem)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{id(text) & 0xffffff}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class MemoryStore:
    def __init__(self, brain_dir: Optional[str] = None):
        # default: ~/.wadachi, ma un brain legacy in ~/.engram continua a funzionare
        _legacy = os.path.expanduser("~/.engram")
        _default = _legacy if os.path.isdir(_legacy) else os.path.expanduser("~/.wadachi")
        self.brain_dir = Path(brain_dir or os.environ.get("BRAIN_DIR", _default))
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        (self.brain_dir / "global").mkdir(exist_ok=True)
        (self.brain_dir / "projects").mkdir(exist_ok=True)

        self.db_path = self.brain_dir / "brain.db"
        self._init_db()

    # ── Database ──────────────────────────────────────────────

    def _init_db(self):
        """Porta il DB all'ultima versione dello schema (vedi wadachi/migrations/).

        Il runner fa il backup del .db prima di applicare qualsiasi migrazione
        a un DB non vuoto; lo schema vive negli script 000N_*.py, non qui.
        """
        from wadachi.migrations import run_migrations
        run_migrations(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        # WAL + busy_timeout make the brain safe under concurrent access from
        # several MCP clients at once (e.g. multiple Overmind agents): readers
        # never block the writer, and a writer *waits* for the lock instead of
        # failing immediately with "database is locked". journal_mode=WAL
        # persists in the DB file header; re-applying it per connection is
        # idempotent and cheap.
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    # ── Memory CRUD ───────────────────────────────────────────

    def store_memory(
        self,
        content: str,
        title: str,
        project: str = "global",
        tags: list[str] | None = None,
        category: str = "note",
    ) -> dict:
        """Store a memory as markdown file + metadata row."""
        now = datetime.now(timezone.utc).isoformat()
        slug = _slugify(title)
        tags = tags or []

        # Ensure project directory exists
        proj_dir = self._project_dir(project)
        proj_dir.mkdir(parents=True, exist_ok=True)

        # Render first, then claim a filename race-free: O_CREAT|O_EXCL means
        # two concurrent stores with the same title get distinct files instead
        # of one silently overwriting the other (the old exists()-check was a
        # TOCTOU race).
        from wadachi.mdio import render_memory_file
        rendered = render_memory_file(
            {"title": title, "project": project, "tags": tags,
             "category": category, "created": now},
            content,
        )
        counter = 0
        while True:
            candidate = proj_dir / (f"{slug}.md" if counter == 0 else f"{slug}-{counter}.md")
            try:
                fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                counter += 1
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(rendered)
            filepath = candidate
            break

        # Insert metadata
        rel_path = str(filepath.relative_to(self.brain_dir))
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO memories (title, slug, project, tags, category, filepath, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, slug, project, json.dumps(tags), category, rel_path, now, now),
            )
            memory_id = cursor.lastrowid

        self.rebuild_index()
        self.append_log("store", f"[[{filepath.stem}]] #{memory_id} · {title[:80]}")

        return {
            "id": memory_id,
            "title": title,
            "project": project,
            "filepath": rel_path,
            "created_at": now,
        }

    def get_memory(self, memory_id: int) -> dict | None:
        """Retrieve a memory by ID, including file content."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return None

        filepath = self.brain_dir / row["filepath"]
        if filepath.exists():
            # parser tollerante: file editati a mano o con frontmatter rotto
            # non fanno mai fallire la lettura (vedi wadachi/mdio.py)
            from wadachi.mdio import parse_memory_file
            content = parse_memory_file(filepath.read_text(encoding="utf-8")).content
        else:
            content = "[file missing]"

        self.touch_access([memory_id])

        return {
            "id": row["id"],
            "title": row["title"],
            "project": row["project"],
            "tags": json.loads(row["tags"]),
            "category": row["category"],
            "content": content,
            "filepath": row["filepath"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_memories(self, project: str | None = None, category: str | None = None) -> list[dict]:
        """List memories, optionally filtered by project and/or category."""
        query = "SELECT id, title, project, tags, category, filepath, created_at FROM memories WHERE 1=1"
        params: list = []
        if project:
            query += " AND project = ?"
            params.append(project)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY updated_at DESC"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "project": r["project"],
                "tags": json.loads(r["tags"]),
                "category": r["category"],
                "filepath": r["filepath"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def delete_memory(self, memory_id: int) -> bool:
        """Delete a memory (db row + file)."""
        with self._conn() as conn:
            row = conn.execute("SELECT filepath FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if not row:
                return False
            filepath = self.brain_dir / row["filepath"]
            if filepath.exists():
                filepath.unlink()
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.rebuild_index()
        self.append_log("delete", f"#{memory_id} ({row['filepath']})")
        return True

    def update_memory(self, memory_id: int, content: str | None = None, tags: list[str] | None = None) -> bool:
        """Update a memory's content and/or tags."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if not row:
                return False

            now = datetime.now(timezone.utc).isoformat()

            if content is not None:
                filepath = self.brain_dir / row["filepath"]
                # Non-destructive: snapshot the previous version before overwriting.
                if filepath.exists():
                    conn.execute(
                        "INSERT INTO memory_versions (memory_id, content, replaced_at) VALUES (?, ?, ?)",
                        (memory_id, filepath.read_text(encoding="utf-8"), now),
                    )
                from wadachi.mdio import render_memory_file
                filepath.write_text(
                    render_memory_file(
                        {"title": row["title"], "project": row["project"],
                         "tags": tags or json.loads(row["tags"]),
                         "category": row["category"],
                         "created": row["created_at"], "updated": now},
                        content,
                    ),
                    encoding="utf-8",
                )

            updates = ["updated_at = ?"]
            params: list = [now]
            if tags is not None:
                updates.append("tags = ?")
                params.append(json.dumps(tags))
            # Clear cached embedding so it gets recomputed
            updates.append("embedding = NULL")
            params.append(memory_id)

            conn.execute(f"UPDATE memories SET {', '.join(updates)} WHERE id = ?", params)
        return True

    def get_memory_history(self, memory_id: int) -> list[dict]:
        """Return prior versions of a memory, newest first (see update_memory)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, replaced_at, content FROM memory_versions "
                "WHERE memory_id = ? ORDER BY replaced_at DESC",
                (memory_id,),
            ).fetchall()
        return [
            {"version_id": r["id"], "replaced_at": r["replaced_at"], "content": r["content"]}
            for r in rows
        ]

    # ── Beliefs (epistemic envelope over a memory) ────────────

    _BELIEF_DEFAULTS = {"confidence": 0.7, "status": "active", "valid_until": None,
                        "sources": [], "superseded_by": None,
                        "last_reviewed": None, "review_reason": None}

    def get_belief(self, memory_id: int) -> dict:
        """Belief envelope for a memory. Missing row → sensible defaults (active, 0.7)."""
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM beliefs WHERE memory_id = ?", (memory_id,)).fetchone()
        if not r:
            return {"memory_id": memory_id, **self._BELIEF_DEFAULTS}
        return {
            "memory_id": memory_id, "confidence": r["confidence"], "status": r["status"],
            "valid_until": r["valid_until"], "sources": json.loads(r["sources"] or "[]"),
            "superseded_by": r["superseded_by"], "last_reviewed": r["last_reviewed"],
            "review_reason": r["review_reason"],
        }

    def set_belief(self, memory_id: int, confidence: float | None = None,
                   status: str | None = None, valid_until: str | None = None,
                   sources: list | None = None, superseded_by: int | None = None,
                   review_reason: str | None = None) -> dict:
        """Upsert a belief; None args keep the current value."""
        cur = self.get_belief(memory_id)
        now = datetime.now(timezone.utc).isoformat()
        m = {
            "confidence": cur["confidence"] if confidence is None else confidence,
            "status": cur["status"] if status is None else status,
            "valid_until": cur["valid_until"] if valid_until is None else valid_until,
            "sources": cur["sources"] if sources is None else sources,
            "superseded_by": cur["superseded_by"] if superseded_by is None else superseded_by,
            "review_reason": cur["review_reason"] if review_reason is None else review_reason,
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO beliefs (memory_id, confidence, status, valid_until, sources,
                        superseded_by, last_reviewed, review_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(memory_id) DO UPDATE SET
                        confidence=excluded.confidence, status=excluded.status,
                        valid_until=excluded.valid_until, sources=excluded.sources,
                        superseded_by=excluded.superseded_by, last_reviewed=excluded.last_reviewed,
                        review_reason=excluded.review_reason""",
                (memory_id, m["confidence"], m["status"], m["valid_until"],
                 json.dumps(m["sources"]), m["superseded_by"], now, m["review_reason"]),
            )
        return self.get_belief(memory_id)

    def get_beliefs(self, project: str | None = None) -> dict:
        """All stored belief rows (memories without a row use defaults elsewhere)."""
        q = "SELECT b.* FROM beliefs b JOIN memories m ON m.id = b.memory_id"
        params: list = []
        if project:
            q += " WHERE m.project = ? OR m.project = 'global'"
            params.append(project)
        with self._conn() as conn:
            rows = conn.execute(q, params).fetchall()
        return {r["memory_id"]: {
            "confidence": r["confidence"], "status": r["status"],
            "valid_until": r["valid_until"], "superseded_by": r["superseded_by"],
            "review_reason": r["review_reason"],
        } for r in rows}

    # ── Insights (reflection candidates) ──────────────────────

    def store_insight(self, claim: str, itype: str, evidence_ids: list[int],
                      status: str = "proposed") -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO insights (claim, itype, evidence_ids, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (claim, itype, json.dumps(evidence_ids), status, now),
            )
            return {"id": cur.lastrowid, "claim": claim, "itype": itype,
                    "evidence_ids": evidence_ids, "status": status}

    def list_insights(self, status: str | None = None) -> list[dict]:
        q = "SELECT * FROM insights"
        params: list = []
        if status:
            q += " WHERE status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC"
        with self._conn() as conn:
            rows = conn.execute(q, params).fetchall()
        return [{"id": r["id"], "claim": r["claim"], "itype": r["itype"],
                 "evidence_ids": json.loads(r["evidence_ids"]), "status": r["status"],
                 "created_at": r["created_at"]} for r in rows]

    def get_insight(self, insight_id: int) -> dict | None:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "claim": r["claim"], "itype": r["itype"],
                "evidence_ids": json.loads(r["evidence_ids"]), "status": r["status"]}

    def set_insight_status(self, insight_id: int, status: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("UPDATE insights SET status = ? WHERE id = ?", (status, insight_id))
            return cur.rowcount > 0

    # ── Decisions ─────────────────────────────────────────────

    def store_decision(
        self,
        decision: str,
        rationale: str = "",
        alternatives: str = "",
        context: str = "",
        project: str = "global",
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO decisions (project, decision, rationale, alternatives, context, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project, decision, rationale, alternatives, context, now),
            )
            return {
                "id": cursor.lastrowid,
                "decision": decision,
                "project": project,
                "created_at": now,
            }

    def list_decisions(self, project: str | None = None, limit: int = 20) -> list[dict]:
        query = "SELECT * FROM decisions"
        params: list = []
        if project:
            query += " WHERE project = ?"
            params.append(project)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": r["id"],
                "decision": r["decision"],
                "rationale": r["rationale"],
                "alternatives": r["alternatives"],
                "context": r["context"],
                "project": r["project"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def get_decision(self, decision_id: int) -> dict | None:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        if not r:
            return None
        return {
            "id": r["id"], "decision": r["decision"], "rationale": r["rationale"],
            "alternatives": r["alternatives"], "context": r["context"],
            "project": r["project"], "created_at": r["created_at"],
        }

    def get_content_as_of(self, memory_id: int, date: str) -> str | None:
        """Il contenuto della memoria com'era a `date` (ISO), ricostruito dalle versioni.

        La versione più vecchia rimpiazzata DOPO la data era quella viva alla data;
        se nessuna versione è stata rimpiazzata dopo, vale il contenuto corrente.
        Ritorna None se la memoria non esisteva ancora.
        """
        with self._conn() as conn:
            row = conn.execute("SELECT created_at FROM memories WHERE id = ?",
                               (memory_id,)).fetchone()
            if not row or row["created_at"] > date:
                return None
            v = conn.execute(
                "SELECT content FROM memory_versions WHERE memory_id = ? AND replaced_at > ? "
                "ORDER BY replaced_at ASC LIMIT 1",
                (memory_id, date),
            ).fetchone()
        if v is not None:
            from wadachi.mdio import parse_memory_file
            return parse_memory_file(v["content"]).content
        current = self.get_memory(memory_id)
        return current["content"] if current else None

    # ── Projects ──────────────────────────────────────────────

    def register_project(self, name: str, description: str = "", paths: list[str] | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        paths = paths or []
        (self.brain_dir / "projects" / name).mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO projects (name, description, paths, created_at)
                   VALUES (?, ?, ?, ?)""",
                (name, description, json.dumps(paths), now),
            )
        return {"name": name, "description": description, "paths": paths}

    def detect_project(self, cwd: str) -> str | None:
        """Detect project from current working directory."""
        cwd = os.path.realpath(cwd)
        with self._conn() as conn:
            rows = conn.execute("SELECT name, paths FROM projects").fetchall()
        for row in rows:
            for path in json.loads(row["paths"]):
                if cwd.startswith(os.path.realpath(path)):
                    return row["name"]
        return None

    def list_projects(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [
            {
                "name": r["name"],
                "description": r["description"],
                "paths": json.loads(r["paths"]),
            }
            for r in rows
        ]

    # ── Embedding helpers (used by search.py) ─────────────────

    def get_memories_for_embedding(self, project: str | None = None) -> list[dict]:
        """Get memories that need embedding or all memories for search."""
        query = ("SELECT id, title, tags, category, filepath, embedding, project, "
                 "created_at, access_count, last_accessed FROM memories WHERE 1=1")
        params: list = []
        if project:
            query += " AND (project = ? OR project = 'global')"
            params.append(project)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()

        from wadachi.mdio import parse_memory_file
        results = []
        for r in rows:
            filepath = self.brain_dir / r["filepath"]
            content = ""
            if filepath.exists():
                content = parse_memory_file(filepath.read_text(encoding="utf-8")).content

            results.append({
                "id": r["id"],
                "title": r["title"],
                "tags": json.loads(r["tags"]),
                "category": r["category"],
                "content": content,
                "filepath": r["filepath"],
                "project": r["project"],
                "has_embedding": r["embedding"] is not None,
                "embedding": r["embedding"],
                "created_at": r["created_at"],
                "access_count": r["access_count"],
                "last_accessed": r["last_accessed"],
            })
        return results

    def get_decisions_for_embedding(self, project: str | None = None) -> list[dict]:
        query = "SELECT id, decision, rationale, context, project, embedding FROM decisions WHERE 1=1"
        params: list = []
        if project:
            query += " AND (project = ? OR project = 'global')"
            params.append(project)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "id": r["id"],
                "decision": r["decision"],
                "rationale": r["rationale"] or "",
                "context": r["context"] or "",
                "project": r["project"],
                "has_embedding": r["embedding"] is not None,
                "embedding": r["embedding"],
            }
            for r in rows
        ]

    def save_embedding(self, table: str, row_id: int, embedding_bytes: bytes):
        with self._conn() as conn:
            conn.execute(f"UPDATE {table} SET embedding = ? WHERE id = ?", (embedding_bytes, row_id))

    def list_supersessions(self) -> list[tuple[int, int]]:
        """Coppie (vecchia, nuova) dai belief: chi ha superato chi."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT memory_id, superseded_by FROM beliefs WHERE superseded_by IS NOT NULL"
            ).fetchall()
        return [(r["memory_id"], r["superseded_by"]) for r in rows]

    def touch_access(self, memory_ids: list[int]) -> None:
        """Registra un accesso esplicito (get_memory/expand_memory) — alimenta il decay."""
        if not memory_ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.executemany(
                "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                [(now, mid) for mid in memory_ids],
            )

    # ── LLM Wiki: index.md + log.md (nomi riservati OKF, alla radice del brain) ──

    def rebuild_index(self) -> None:
        """Rigenera index.md: il catalogo del wiki, una riga per memoria.

        Best-effort: un problema qui non deve mai bloccare l'operazione primaria.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT title, project, category, filepath FROM memories "
                    "ORDER BY project, updated_at DESC"
                ).fetchall()
            lines = ["---", "type: index", "---", "", "# Brain index", ""]
            current = None
            for r in rows:
                if r["project"] != current:
                    current = r["project"]
                    lines += [f"## {current}", ""]
                stem = Path(r["filepath"]).stem
                lines.append(f"- [[{stem}]] — {r['title']} `{r['category']}`")
            lines.append("")
            _atomic_write_text(self.brain_dir / "index.md", "\n".join(lines))
        except OSError:
            pass

    def append_log(self, op: str, detail: str) -> None:
        """log.md append-only: la cronologia delle operazioni (grep-abile)."""
        try:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with open(self.brain_dir / "log.md", "a", encoding="utf-8") as f:
                f.write(f"## [{ts}] {op} — {detail}\n")
        except OSError:
            pass

    # ── Helpers ────────────────────────────────────────────────

    def _project_dir(self, project: str) -> Path:
        if project == "global":
            return self.brain_dir / "global"
        return self.brain_dir / "projects" / project

    def stats(self) -> dict:
        with self._conn() as conn:
            mem_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            dec_count = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            proj_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        return {"memories": mem_count, "decisions": dec_count, "projects": proj_count}
