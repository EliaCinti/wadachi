"""
wadachi obsidian — backfill dei wikilink per il grafo di Obsidian. SU RICHIESTA.

Le memorie storiche si citano con "memoria #82" o [[#82]]: il grafo di wadachi
li risolve, Obsidian no (lui vuole [[nome-file]]). Questo comando — ESPLICITO,
mai eseguito automaticamente da init/doctor/sleep/server — appende in coda a
ogni file una sezione generata:

    <!-- wadachi:obsidian-links -->
    **Links:** [[slug-a]] · [[slug-b]]

senza toccare una virgola della prosa. La sezione è delimitata dal marker,
quindi rigenerabile e rimovibile; ogni riscrittura passa dal versioning
non-distruttivo (memory_versions) e azzera l'embedding cache del file toccato.
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from wadachi.graph import _MEM_REF, _ID_REF
from wadachi.mdio import parse_memory_file

MARKER = "<!-- wadachi:obsidian-links -->"
_SECTION_RE = re.compile(re.escape(MARKER) + r".*\Z", re.S)


def _referenced_ids(content: str) -> list[int]:
    ids = []
    for rx in (_MEM_REF, _ID_REF):
        for m in rx.finditer(content):
            ids.append(int(m.group(1)))
    return ids


def run_backfill(brain_dir: str | Path, dry_run: bool = False) -> dict:
    """Appende/rigenera la sezione Links nei file memoria. Ritorna le statistiche."""
    from wadachi.store import MemoryStore
    store = MemoryStore(str(brain_dir))
    brain = Path(store.brain_dir)

    from pathlib import PurePosixPath
    rows = store.list_memories()
    stem_of = {m["id"]: PurePosixPath(m["filepath"].replace("\\", "/")).stem for m in rows}

    stats = {"scanned": 0, "updated": 0, "links": 0, "unresolved": 0}
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(store.db_path)

    for m in rows:
        path = brain / m["filepath"].replace("\\", "/")
        if not path.exists():
            continue
        stats["scanned"] += 1
        raw = path.read_text(encoding="utf-8")
        body = _SECTION_RE.sub("", raw).rstrip()      # contenuto senza la sezione

        content = parse_memory_file(body).content
        targets = []
        for rid in _referenced_ids(content):
            if rid == m["id"]:
                continue
            stem = stem_of.get(rid)
            if stem is None:
                stats["unresolved"] += 1
            elif stem not in targets:
                targets.append(stem)

        if targets:
            section = MARKER + "\n**Links:** " + " · ".join(f"[[{s}]]" for s in targets)
            new_raw = body + "\n\n" + section + "\n"
        else:
            new_raw = body + "\n" if raw.endswith("\n") else body

        if new_raw == raw:
            continue

        stats["updated"] += 1
        stats["links"] += len(targets)
        if dry_run:
            continue

        # non-distruttivo: la versione precedente finisce in memory_versions
        conn.execute(
            "INSERT INTO memory_versions (memory_id, content, replaced_at) VALUES (?, ?, ?)",
            (m["id"], raw, now),
        )
        conn.execute("UPDATE memories SET embedding = NULL WHERE id = ?", (m["id"],))
        path.write_text(new_raw, encoding="utf-8")

    conn.commit()
    conn.close()
    if not dry_run and stats["updated"]:
        store.append_log("obsidian-links",
                         f"{stats['updated']} file, {stats['links']} wikilink generati")
    return stats
