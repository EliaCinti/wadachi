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
from contextlib import contextmanager
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


def _ensure_wal(conn: sqlite3.Connection) -> None:
    """Put the brain in WAL, once, and never fight for the lock to re-confirm it.

    `journal_mode` lives in the database file header, so it survives every
    close and only ever needs setting once. Setting it is not free, though:
    it needs a brief exclusive lock, and SQLite does **not** invoke the busy
    handler for a journal-mode change — so a connection that re-applies it
    while another process is mid-write gets `SQLITE_BUSY` immediately, with the
    30-second `busy_timeout` never getting a say.

    That is why this reads first and only writes when the mode is actually
    wrong. On an existing brain it is a lock-free read on every open; on a new
    one it is a single write, at creation, with nobody else around.
    """
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if str(mode).lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")


@contextmanager
def _exclusive(db_path: Path):
    """Serialize migration across processes with an OS file lock.

    `run_migrations` reads the current version, decides what is pending, and
    then applies it — three steps that are only correct if nobody else is doing
    the same thing. Without a lock, N processes opening a *new* brain at the
    same moment all read version 0, all decide 0001 is pending, and all apply
    it: the first commits, the rest die with
    `UNIQUE constraint failed: schema_version.version`.

    That is not a corner case — it is what happens the first time a company's
    agents start together on a freshly provisioned brain, and the loser does
    not lose a memory, it fails to open the brain at all.

    A file lock rather than `BEGIN IMMEDIATE` because each migration
    deliberately runs in its own transaction (see the module docstring), so
    there is no single transaction to widen. Best-effort by design: a platform
    without `fcntl` keeps the old behaviour rather than refusing to run.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover — non-POSIX
        yield
        return
    lock_path = db_path.with_name(db_path.name + ".migrate.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def run_migrations(db_path: Path) -> list[int]:
    """Apply pending migrations. Returns the list of versions applied."""
    db_path = Path(db_path)
    migrations = _discover()
    if not migrations:
        raise MigrationError("nessuna migrazione trovata (manca 0001_baseline.py?)")

    with _exclusive(db_path):
        return _run_locked(db_path, migrations)


def _run_locked(db_path: Path, migrations: list[tuple[int, str, Path]]) -> list[int]:
    conn = sqlite3.connect(str(db_path))
    conn.isolation_level = None  # autocommit: le transazioni le gestiamo noi (BEGIN/COMMIT)
    try:
        try:
            # Inside the guard: reading the journal mode is the first thing
            # that touches the file, so a corrupt one fails here and must still
            # get the message that names the backup directory.
            _ensure_wal(conn)
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
