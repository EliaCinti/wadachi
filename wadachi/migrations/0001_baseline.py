"""
Baseline: lo schema completo di wadachi 0.2.x.

Idempotente (CREATE IF NOT EXISTS): su un DB pre-migrazioni esistente non
tocca i dati, si limita a "adottare" lo schema e a marcarlo come versione 1.
"""

VERSION = 1
DESCRIPTION = "baseline: memories, decisions, projects, memory_versions, beliefs, insights + indici"


_SCHEMA = """
        CREATE TABLE IF NOT EXISTS memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            slug        TEXT NOT NULL,
            project     TEXT NOT NULL DEFAULT 'global',
            tags        TEXT DEFAULT '[]',
            category    TEXT DEFAULT 'note',
            filepath    TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            embedding   BLOB
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project     TEXT NOT NULL DEFAULT 'global',
            decision    TEXT NOT NULL,
            rationale   TEXT,
            alternatives TEXT,
            context     TEXT,
            created_at  TEXT NOT NULL,
            embedding   BLOB
        );

        CREATE TABLE IF NOT EXISTS projects (
            name        TEXT PRIMARY KEY,
            description TEXT,
            paths       TEXT DEFAULT '[]',
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id   INTEGER NOT NULL,
            content     TEXT NOT NULL,
            replaced_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS beliefs (
            memory_id     INTEGER PRIMARY KEY,
            confidence    REAL DEFAULT 0.7,
            status        TEXT DEFAULT 'active',
            valid_until   TEXT,
            sources       TEXT DEFAULT '[]',
            superseded_by INTEGER,
            last_reviewed TEXT,
            review_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS insights (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            claim        TEXT NOT NULL,
            itype        TEXT NOT NULL,
            evidence_ids TEXT NOT NULL DEFAULT '[]',
            status       TEXT NOT NULL DEFAULT 'proposed',
            created_at   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project);
        CREATE INDEX IF NOT EXISTS idx_versions_memory ON memory_versions(memory_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project);
"""


def up(conn):
    # una execute per statement: executescript() auto-committa e romperebbe
    # la transazione del runner (vedi contratto in migrations/__init__.py)
    for stmt in _SCHEMA.split(";"):
        if stmt.strip():
            conn.execute(stmt)
