"""1.1 — Migrazioni DB: runner, baseline, backup, DB corrotto, rollback."""

import sqlite3
import textwrap
from pathlib import Path

import pytest

from wadachi.migrations import MigrationError, run_migrations, _discover
from wadachi.store import MemoryStore

# la catena completa delle migrazioni disponibili: i test restano validi
# anche quando se ne aggiungono di nuove
ALL = [v for v, _, _ in _discover()]
LATEST = ALL[-1]


def test_fresh_db_gets_baseline(tmp_path):
    db = tmp_path / "brain.db"
    applied = run_migrations(db)
    assert applied == ALL
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"memories", "decisions", "projects", "memory_versions",
            "beliefs", "insights", "schema_version"} <= tables
    conn.close()


def test_second_run_is_noop(tmp_path):
    db = tmp_path / "brain.db"
    assert run_migrations(db) == ALL
    assert run_migrations(db) == []          # niente da applicare
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    conn.close()
    assert count == len(ALL)                 # nessuna doppia applicazione


def test_fresh_db_has_no_backup(tmp_path):
    run_migrations(tmp_path / "brain.db")
    assert not (tmp_path / "backups").exists()


def test_legacy_db_adopted_with_backup(tmp_path):
    """Un DB pre-migrazioni (senza schema_version) viene adottato: dati intatti + backup."""
    db = tmp_path / "brain.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT 'global', tags TEXT DEFAULT '[]',
            category TEXT DEFAULT 'note', filepath TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, embedding BLOB
        );
        INSERT INTO memories (title, slug, filepath, created_at, updated_at)
        VALUES ('vecchia memoria', 'vecchia-memoria', 'global/x.md', '2026-01-01', '2026-01-01');
    """)
    conn.commit()
    conn.close()

    applied = run_migrations(db)
    assert applied == ALL

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == LATEST
    conn.close()

    backups = list((tmp_path / "backups").glob("brain.db.bak.*"))
    assert len(backups) == 1
    # il backup è a sua volta un DB sqlite leggibile con i dati pre-migrazione
    bconn = sqlite3.connect(backups[0])
    assert bconn.execute("SELECT title FROM memories").fetchone()[0] == "vecchia memoria"
    bconn.close()


def test_corrupted_db_raises_clear_error(tmp_path):
    db = tmp_path / "brain.db"
    db.write_text("questo non è sqlite")
    with pytest.raises(MigrationError, match="corrotto|non è un DB"):
        run_migrations(db)


def test_failing_migration_rolls_back(tmp_path, monkeypatch):
    """Una migrazione che fallisce non lascia il DB a metà e nomina il backup."""
    db = tmp_path / "brain.db"
    assert run_migrations(db) == ALL

    nxt = LATEST + 1
    boom = tmp_path / f"{nxt:04d}_boom.py"
    boom.write_text(textwrap.dedent(f"""
        VERSION = {nxt}
        DESCRIPTION = "esplode a metà"
        def up(conn):
            conn.execute("CREATE TABLE half_done (id INTEGER)")
            raise RuntimeError("boom")
    """))
    import wadachi.migrations as mig
    real = _discover()
    monkeypatch.setattr(mig, "_discover", lambda: real + [(nxt, boom.stem, boom)])

    with pytest.raises(MigrationError, match="boom.*fallita"):
        mig.run_migrations(db)

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == LATEST
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "half_done" not in tables         # transazione rollbackata
    conn.close()


def test_version_prefix_mismatch_rejected(tmp_path, monkeypatch):
    db = tmp_path / "brain.db"
    nxt = LATEST + 1
    bad = tmp_path / f"{nxt:04d}_bad.py"
    bad.write_text("VERSION = 9999\ndef up(conn): pass\n")
    import wadachi.migrations as mig
    real = _discover()
    monkeypatch.setattr(mig, "_discover", lambda: real + [(nxt, bad.stem, bad)])
    with pytest.raises(MigrationError, match="non corrisponde"):
        mig.run_migrations(db)


def test_store_init_runs_migrations(tmp_path):
    """MemoryStore._init_db passa dal runner: il DB nasce già versionato."""
    s = MemoryStore(str(tmp_path / "b"))
    conn = sqlite3.connect(s.db_path)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == LATEST
    conn.close()


def test_migration_0003_creates_the_desks_index(tmp_path):
    from wadachi.store import MemoryStore
    s = MemoryStore(str(tmp_path / "brain"))
    with s._conn() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(desks)")}
    assert cols == {"slug", "project", "title", "status",
                    "created_at", "updated_at", "filepath"}


def test_migration_0003_keys_a_desk_by_project_and_slug(tmp_path):
    """Lo stesso slug in due progetti è legittimo; due volte nello stesso, no."""
    import sqlite3
    import pytest
    from wadachi.store import MemoryStore
    s = MemoryStore(str(tmp_path / "brain"))
    with s._write() as conn:
        conn.execute("INSERT INTO desks VALUES ('x','a','T','open','t','t','p')")
        conn.execute("INSERT INTO desks VALUES ('x','b','T','open','t','t','p')")
    with pytest.raises(sqlite3.IntegrityError):
        with s._write() as conn:
            conn.execute("INSERT INTO desks VALUES ('x','a','T','open','t','t','p')")
