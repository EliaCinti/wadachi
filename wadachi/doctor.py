"""
wadachi doctor — diagnostica del brain: config, DB, permessi, file, versione schema.

Principio: la diagnosi è READ-ONLY (il DB viene aperto in modalità ro e nessuna
migrazione viene applicata). Solo `--fix` ripara — e ripara soltanto ciò che è
sicuro riparare: directory mancanti e frontmatter dei file .md (backfill dal DB,
il contenuto non si tocca mai). File mancanti e orfani vengono solo segnalati.
"""

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from wadachi import __version__
from wadachi.mdio import parse_memory_file, backfill_file


class Report:
    def __init__(self):
        self.errors = 0
        self.warnings = 0

    def ok(self, msg):
        print(f"  ✓ {msg}")

    def warn(self, msg):
        self.warnings += 1
        print(f"  ⚠ {msg}")

    def fail(self, msg):
        self.errors += 1
        print(f"  ✗ {msg}")

    def info(self, msg):
        print(f"  – {msg}")


def _latest_migration_version() -> int:
    from wadachi.migrations import _discover
    migs = _discover()
    return migs[-1][0] if migs else 0


def run_doctor(brain_dir: str | Path, fix: bool = False, check_mcp: bool = True) -> int:
    brain = Path(brain_dir).expanduser()
    r = Report()

    print(f"wadachi {__version__} — doctor")
    print(f"Python {sys.version.split()[0]} · brain: {brain}\n")

    # ── brain dir e permessi ──────────────────────────────────
    print("Brain dir")
    if not brain.is_dir():
        r.fail(f"non esiste: {brain} — esegui `wadachi init`")
        return 1
    probe = brain / ".doctor-probe"
    try:
        probe.write_text("x")
        probe.unlink()
        r.ok("esiste ed è scrivibile")
    except OSError as e:
        r.fail(f"non scrivibile: {e}")

    for sub in ("global", "projects"):
        d = brain / sub
        if d.is_dir():
            r.ok(f"{sub}/ presente")
        elif fix:
            d.mkdir(parents=True)
            r.ok(f"{sub}/ mancante → creata (--fix)")
        else:
            r.warn(f"{sub}/ mancante (riparabile con --fix)")

    # ── database ──────────────────────────────────────────────
    print("\nDatabase")
    db = brain / "brain.db"
    conn = None
    if not db.exists():
        r.fail("brain.db non esiste — esegui `wadachi init`")
    else:
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity == "ok":
                r.ok("integrity_check: ok")
            else:
                r.fail(f"integrity_check: {integrity} — ripristina un backup da {brain / 'backups'}/")
        except sqlite3.DatabaseError as e:
            r.fail(f"non apribile ({e}) — ripristina un backup da {brain / 'backups'}/")
            conn = None

    counts = {}
    if conn is not None:
        latest = _latest_migration_version()
        try:
            current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        except sqlite3.OperationalError:
            current = 0
        if current == latest:
            r.ok(f"schema alla versione {current} (ultima disponibile)")
        elif current < latest:
            r.warn(f"schema v{current}, disponibile v{latest} — le migrazioni verranno "
                   "applicate (con backup) al prossimo avvio del server o con `wadachi init`")
        else:
            r.fail(f"schema v{current} più NUOVO del codice (v{latest}) — wadachi va aggiornato: "
                   "pipx upgrade wadachi")
        try:
            for table in ("memories", "decisions", "projects"):
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            r.info(f"{counts['memories']} memorie · {counts['decisions']} decisioni · "
                   f"{counts['projects']} progetti")
        except sqlite3.OperationalError as e:
            r.warn(f"tabelle incomplete ({e})")

    # ── file markdown ─────────────────────────────────────────
    print("\nFile memoria (.md)")
    if conn is not None and "memories" in counts:
        rows = conn.execute("SELECT id, title, project, tags, category, filepath, "
                            "created_at, updated_at FROM memories").fetchall()
        missing, malformed, fixed = [], [], 0
        referenced = set()
        for row in rows:
            (mid, title, project, tags, category, fp, created, updated) = row
            path = brain / fp
            referenced.add(path.resolve())
            if not path.exists():
                missing.append((mid, fp))
                continue
            parsed = parse_memory_file(path.read_text(encoding="utf-8"))
            # "riparabile" = rotto, senza frontmatter, o non OKF-conforme (manca `type`)
            if parsed.malformed or not parsed.had_frontmatter or "type" not in parsed.meta:
                if fix:
                    db_meta = {"title": title, "project": project,
                               "tags": json.loads(tags or "[]"), "category": category,
                               "created": created, "updated": updated}
                    backfill_file(path, db_meta)
                    fixed += 1
                else:
                    malformed.append((mid, fp))

        if missing:
            r.fail(f"{len(missing)} file referenziati dal DB ma assenti su disco: "
                   + ", ".join(f"#{m} {f}" for m, f in missing[:5])
                   + (" …" if len(missing) > 5 else ""))
        else:
            r.ok("tutti i file referenziati dal DB esistono")

        if fixed:
            r.ok(f"{fixed} file riscritti nel formato canonico OKF (--fix)")
        elif malformed:
            r.warn(f"{len(malformed)} file con frontmatter assente/malformato/non-OKF "
                   f"(riparabile con --fix): " + ", ".join(f"#{m}" for m, _ in malformed[:8]))
        else:
            r.ok("frontmatter canonico (OKF) in tutti i file")

        on_disk = {p.resolve() for d in (brain / "global", brain / "projects")
                   if d.is_dir() for p in d.rglob("*.md")}
        orphans = on_disk - referenced
        if orphans:
            r.warn(f"{len(orphans)} file .md su disco non indicizzati nel DB "
                   f"(creati a mano? es. {next(iter(orphans)).name})")
        else:
            r.ok("nessun file orfano")

    if conn is not None:
        conn.close()

    # ── LLM Wiki: index + schema ──────────────────────────────
    print("\nLLM Wiki")
    if (brain / "SCHEMA.md").exists():
        r.ok("SCHEMA.md presente")
    elif fix:
        from wadachi.cli import _SCHEMA_MD
        (brain / "SCHEMA.md").write_text(_SCHEMA_MD, encoding="utf-8")
        r.ok("SCHEMA.md mancante → creato (--fix)")
    else:
        r.warn("SCHEMA.md mancante (riparabile con --fix, o con `wadachi init`)")
    if fix:
        from wadachi.store import MemoryStore
        MemoryStore(str(brain)).rebuild_index()
        r.ok("index.md rigenerato (--fix)")
    elif (brain / "index.md").exists():
        r.ok("index.md presente")
    else:
        r.warn("index.md mancante (riparabile con --fix)")

    # ── ricerca semantica ─────────────────────────────────────
    print("\nRicerca")
    try:
        import fastembed  # noqa: F401
        r.ok("fastembed installato (ricerca semantica)")
    except ImportError:
        if sys.version_info >= (3, 15):
            r.warn(
                "fastembed non disponibile su Python 3.15 (onnxruntime non pubblica "
                "ancora wheel cp315) — ricerca keyword attiva; per la ricerca semantica: "
                "uv tool install --python 3.14 'wadachi[semantic]'"
            )
        else:
            r.warn("fastembed non installato — ricerca solo keyword "
                   "(pip install 'wadachi[semantic]')")

    # ── integrazione MCP ──────────────────────────────────────
    if check_mcp:
        print("\nIntegrazione MCP")
        if shutil.which("claude"):
            import subprocess
            q = subprocess.run(["claude", "mcp", "get", "wadachi"],
                               capture_output=True, text=True)
            if q.returncode == 0:
                r.ok("server 'wadachi' registrato in Claude Code")
            else:
                r.warn("server non registrato in Claude Code — esegui `wadachi init`")
        else:
            r.info("CLI `claude` non trovato (ok se usi un altro client MCP)")

    # ── verdetto ──────────────────────────────────────────────
    print()
    if r.errors:
        print(f"✗ {r.errors} problemi seri, {r.warnings} avvisi. "
              f"Log utili in {brain / 'logs' / 'wadachi.log'}")
        return 1
    if r.warnings:
        print(f"⚠ nessun problema serio, {r.warnings} avvisi.")
        return 0
    print("✓ tutto in ordine. 轍")
    return 0
