"""
Migration runner — versioned SQLite schema with automatic backups.

Layout:
    wadachi/migrations/
    ├── __init__.py        # this runner
    ├── 0001_baseline.py   # VERSION, DESCRIPTION, up(conn)
    └── 000N_*.py          # future migrations, applied in numeric order

Each migration module defines:
    VERSION      = int   (must match the filename prefix)
    DESCRIPTION  = str
    def up(conn: sqlite3.Connection) -> None

Contract:
- The `schema_version` table records every applied migration.
- Before applying anything to a non-empty DB, the .db file is copied to
  <brain_dir>/backups/brain.db.bak.<timestamp>.v<current_version>.
- Each migration runs in its own transaction (explicit BEGIN/COMMIT): on
  failure it rolls back and the runner raises MigrationError naming the backup.
- IMPORTANT: inside up(conn) use conn.execute(...), one statement at a time.
  Do NOT use conn.executescript(): it issues an implicit COMMIT that breaks
  the rollback guarantee (same reason the runner disables isolation_level).
"""

import importlib.util
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_MIGRATION_RE = re.compile(r"^(\d{4})_[\w-]+\.py$")


class MigrationError(RuntimeError):
    pass


def _discover() -> list[tuple[int, str, Path]]:
    """Find migration files next to this module, sorted by version."""
    here = Path(__file__).parent
    found = []
    for f in here.iterdir():
        m = _MIGRATION_RE.match(f.name)
        if m:
            found.append((int(m.group(1)), f.stem, f))
    found.sort(key=lambda t: t[0])
    versions = [v for v, _, _ in found]
    if len(set(versions)) != len(versions):
        raise MigrationError(f"versioni di migrazione duplicate: {versions}")
    return found


def _load(path: Path, stem: str):
    spec = importlib.util.spec_from_file_location(f"wadachi.migrations.{stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "up") or not hasattr(mod, "VERSION"):
        raise MigrationError(f"{path.name}: deve definire VERSION e up(conn)")
    return mod


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT,
            applied_at  TEXT NOT NULL
        )
    """)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def _backup(db_path: Path, current: int) -> Path:
    backups = db_path.parent / "backups"
    backups.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = backups / f"{db_path.name}.bak.{ts}.v{current}"
    # Fold any WAL into the main file first so this pre-migration safety copy
    # is complete (a WAL-mode brain keeps recent writes in brain.db-wal). We're
    # about to migrate this DB anyway, so checkpointing it is not a mutation we
    # need to avoid. Best-effort: a busy/again checkpoint must not block backup.
    try:
        with sqlite3.connect(str(db_path)) as _c:
            _c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    shutil.copy2(db_path, dest)
    return dest


def run_migrations(db_path: Path) -> list[int]:
    """Apply pending migrations. Returns the list of versions applied."""
    db_path = Path(db_path)
    migrations = _discover()
    if not migrations:
        raise MigrationError("nessuna migrazione trovata (manca 0001_baseline.py?)")

    conn = sqlite3.connect(str(db_path))
    conn.isolation_level = None  # autocommit: le transazioni le gestiamo noi (BEGIN/COMMIT)
    try:
        try:
            current = _current_version(conn)
        except sqlite3.DatabaseError as e:
            raise MigrationError(
                f"impossibile leggere {db_path}: file corrotto o non è un DB SQLite ({e}). "
                f"Ripristina un backup da {db_path.parent / 'backups'}/"
            ) from e

        pending = [(v, stem, p) for v, stem, p in migrations if v > current]
        if not pending:
            return []

        # backup only if the DB already holds something beyond schema_version
        has_data = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name != 'schema_version'"
        ).fetchone()[0] > 0
        backup_path = _backup(db_path, current) if has_data else None

        applied = []
        for version, stem, path in pending:
            mod = _load(path, stem)
            if mod.VERSION != version:
                raise MigrationError(f"{path.name}: VERSION={mod.VERSION} non corrisponde al prefisso {version}")
            try:
                conn.execute("BEGIN")
                mod.up(conn)
                conn.execute(
                    "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
                    (version, getattr(mod, "DESCRIPTION", stem),
                     datetime.now(timezone.utc).isoformat()),
                )
                conn.execute("COMMIT")
                applied.append(version)
            except Exception as e:
                conn.execute("ROLLBACK")
                hint = f" Backup pre-migrazione: {backup_path}" if backup_path else ""
                raise MigrationError(f"migrazione {path.name} fallita: {e}.{hint}") from e
        return applied
    finally:
        conn.close()
