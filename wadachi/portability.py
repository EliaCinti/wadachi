"""
wadachi export / restore — la rete di sicurezza portabile.

`export` produce un archivio tar.gz datato dell'INTERO brain (markdown, DB,
schema/index/log) con un MANIFEST.json (versione, conteggi, schema). È
RIGOROSAMENTE READ-ONLY: niente MemoryStore (il suo init applicherebbe le
migrazioni), DB aperto in modalità ro solo per i conteggi. Un utente della
vecchia era Engram può quindi: installare wadachi → esportare SUBITO →
e solo dopo lasciare che le migrazioni facciano il loro lavoro.

`restore` ripristina un archivio in una cartella, rifiutandosi di toccare
una destinazione non vuota senza --force.
"""

import json
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from wadachi import __version__

# cosa entra nell'export: il brain vero, non le sue scorie
_INCLUDE = ("brain.db", "global", "projects", "SCHEMA.md", "index.md", "log.md")
# escluse deliberatamente: backups/ (matrioska) e logs/ (tecnici)


def _read_only_stats(db: Path) -> dict:
    """Conteggi e versione schema senza mai scrivere. Tollera DB legacy/corrotti."""
    stats = {"memories": None, "decisions": None, "schema_version": None}
    if not db.exists():
        return stats
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for key, table in (("memories", "memories"), ("decisions", "decisions")):
            try:
                stats[key] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                pass
        try:
            stats["schema_version"] = conn.execute(
                "SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        except sqlite3.OperationalError:
            stats["schema_version"] = 0          # era pre-migrazioni (Engram)
        conn.close()
    except sqlite3.DatabaseError:
        stats["schema_version"] = "unreadable"
    return stats


def _clear_db_sidecars(brain: Path) -> None:
    """Remove SQLite WAL sidecars so a restored brain.db can't inherit a stale
    -wal/-shm from whatever brain was there before."""
    for suffix in ("-wal", "-shm"):
        side = brain / f"brain.db{suffix}"
        if side.exists():
            side.unlink()


def _snapshot_db(src: Path, dst: Path) -> bool:
    """Write a complete, standalone copy of the SQLite DB to `dst`, reading
    through the WAL so recent writes are included — **without modifying the
    source** (export must stay strictly read-only). Returns True on success."""
    if not src.exists():
        return False
    import sqlite3
    try:
        # VACUUM INTO produces a fresh, self-contained DB file that reflects
        # all committed data (WAL included) and touches only `dst`.
        with sqlite3.connect(str(src)) as conn:
            conn.execute("VACUUM INTO ?", (str(dst),))
        return True
    except sqlite3.Error:
        return False


def export_brain(brain_dir: str | Path, out: str | Path | None = None) -> dict:
    """Esporta il brain in un tar.gz portabile. Ritorna {archive, manifest}."""
    brain = Path(brain_dir).expanduser()
    if not brain.is_dir():
        raise FileNotFoundError(f"brain dir non trovata: {brain}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = Path(out).expanduser() if out else Path.cwd() / f"wadachi-export-{ts}.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)

    present = [name for name in _INCLUDE if (brain / name).exists()]
    if not present:
        raise FileNotFoundError(f"{brain} non contiene un brain (né brain.db né global/)")

    md_files = sum(1 for d in ("global", "projects") if (brain / d).is_dir()
                   for _ in (brain / d).rglob("*.md"))
    manifest = {
        "format": "wadachi-export/1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "wadachi_version": __version__,
        "source": str(brain),
        "contents": present,
        "markdown_files": md_files,
        **_read_only_stats(brain / "brain.db"),
        "restore": "wadachi restore <archivio> --to <nuova-dir>",
    }

    # Snapshot brain.db to a temp file (WAL folded in, source untouched) and
    # archive that instead of the raw file, so a WAL-mode brain exports a
    # complete DB while export stays strictly read-only.
    import tempfile
    snapshot: Path | None = None
    with tempfile.TemporaryDirectory() as tmp:
        if "brain.db" in present:
            candidate = Path(tmp) / "brain.db"
            if _snapshot_db(brain / "brain.db", candidate):
                snapshot = candidate

        with tarfile.open(archive, "w:gz") as tar:
            for name in present:
                source = snapshot if (name == "brain.db" and snapshot) else brain / name
                tar.add(source, arcname=name)
            # manifest come file virtuale in radice
            import io
            data = json.dumps(manifest, indent=2).encode("utf-8")
            info = tarfile.TarInfo("MANIFEST.json")
            info.size = len(data)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            tar.addfile(info, io.BytesIO(data))

    return {"archive": str(archive), "manifest": manifest}


def restore_in_place(archive: str | Path, brain_dir: str | Path) -> dict:
    """"Riparti da qui": sostituisce il brain ATTIVO con l'export.

    Sicurezza prima di tutto: lo stato corrente viene esportato in
    backups/pre-restore-<ts>.tar.gz PRIMA di toccare qualsiasi cosa —
    anche il viaggio nel passato è reversibile. backups/ e logs/ del
    brain corrente vengono preservati.
    """
    import shutil
    archive = Path(archive).expanduser()
    brain = Path(brain_dir).expanduser()
    if not archive.exists():
        raise FileNotFoundError(f"archivio non trovato: {archive}")
    brain.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safety = None
    if any((brain / n).exists() for n in _INCLUDE):
        (brain / "backups").mkdir(exist_ok=True)
        safety = export_brain(brain, out=brain / "backups" / f"pre-restore-{ts}.tar.gz")["archive"]

    # via lo stato corrente (backups/ e logs/ restano)
    for name in _INCLUDE:
        target = brain / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    # Also clear the WAL sidecars: leaving a stale brain.db-wal/-shm next to a
    # freshly restored brain.db makes SQLite re-apply the *old* WAL to the new
    # database. They are not in _INCLUDE (never archived), so remove explicitly.
    _clear_db_sidecars(brain)

    with tarfile.open(archive, "r:gz") as tar:
        for m in tar.getmembers():
            resolved = (brain / m.name).resolve()
            if not str(resolved).startswith(str(brain.resolve())):
                raise ValueError(f"percorso sospetto nell'archivio: {m.name}")
        tar.extractall(brain)

    manifest = {}
    mpath = brain / "MANIFEST.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text())
        mpath.unlink()                      # non è parte del brain vivo
    return {"restored_to": str(brain), "safety_export": safety, "manifest": manifest}


def restore_brain(archive: str | Path, to: str | Path, force: bool = False) -> dict:
    """Ripristina un export in `to`. Rifiuta destinazioni non vuote senza force."""
    archive = Path(archive).expanduser()
    dest = Path(to).expanduser()
    if not archive.exists():
        raise FileNotFoundError(f"archivio non trovato: {archive}")
    if dest.exists() and any(dest.iterdir()) and not force:
        raise FileExistsError(
            f"{dest} esiste e non è vuota — scegli una cartella nuova o usa --force")
    dest.mkdir(parents=True, exist_ok=True)

    _clear_db_sidecars(dest)  # never inherit a prior brain's stale WAL
    with tarfile.open(archive, "r:gz") as tar:
        # guardia path-traversal: tutto deve restare dentro dest
        for m in tar.getmembers():
            target = (dest / m.name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"percorso sospetto nell'archivio: {m.name}")
        tar.extractall(dest)

    manifest = {}
    mpath = dest / "MANIFEST.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text())
    return {"restored_to": str(dest), "manifest": manifest}
