"""
wadachi CLI.

    wadachi                # avvia il server MCP (stdio) — comportamento storico,
                           # le config MCP esistenti continuano a funzionare
    wadachi init           # setup guidato: brain dir, DB migrato, config MCP
    wadachi --version

`init` è idempotente: rieseguirlo non danneggia nulla (le migrazioni fanno
backup automatico del DB e i file esistenti non vengono toccati).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from wadachi import __version__


def _default_brain_dir() -> Path:
    legacy = Path.home() / ".engram"
    if legacy.is_dir():
        return legacy
    return Path.home() / ".wadachi"


def _wadachi_bin() -> str:
    """Il binario `wadachi` da mettere nelle config MCP."""
    return shutil.which("wadachi") or sys.argv[0]


_SCHEMA_MD = """---
type: schema
---

# Brain schema — come è organizzato questo wiki

Questo brain segue il pattern **LLM Wiki** (Karpathy) ed è un bundle
**OKF-conforme** (Open Knowledge Format). È anche un vault Obsidian: aprilo
con Obsidian e vedrai il grafo.

## Layout

    brain/
    ├── SCHEMA.md      ← questo file: le convenzioni (modificalo pure, è tuo)
    ├── index.md       ← catalogo generato: una riga per memoria (non editare)
    ├── log.md         ← cronologia append-only delle operazioni
    ├── brain.db       ← indice SQLite: metadata, embeddings, beliefs
    ├── backups/       ← backup automatici pre-migrazione
    ├── logs/          ← log tecnici del server
    ├── global/        ← memorie cross-project (.md)
    └── projects/<p>/  ← memorie per progetto (.md)

## Formato dei file memoria

Markdown con frontmatter YAML. `type` è l'unico campo richiesto (OKF);
title/project/tags/category/created/updated sono le estensioni di wadachi.
Il CONTENUTO è la fonte di verità e puoi editarlo a mano: il parser è
tollerante e `wadachi doctor --fix` ripara il frontmatter dal DB.

## Link tra memorie

- `[[slug-del-file]]` — wikilink Obsidian (risolto sul nome file)
- `[[#42]]` — riferimento diretto per id
- `memoria #42` — prosa, riconosciuta anche questa

Ogni link diventa un arco del grafo: recall associativo, provenienza delle
decisioni e consolidamento ci camminano sopra. Linka generosamente.

## Manutenzione

- `wadachi doctor` diagnostica; `--fix` ripara frontmatter e rigenera l'indice
- le memorie non si perdono mai: versioni su ogni update, belief per lo stale,
  migrazioni con backup automatico
"""


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _skip(msg: str) -> None:
    print(f"  – {msg}")


def cmd_init(args: argparse.Namespace) -> int:
    brain = Path(args.brain_dir or os.environ.get("BRAIN_DIR") or _default_brain_dir()).expanduser()

    print(f"wadachi {__version__} — setup\n")
    print(f"Brain dir: {brain}")

    # 1 · directory
    brain.mkdir(parents=True, exist_ok=True)
    (brain / "global").mkdir(exist_ok=True)
    (brain / "projects").mkdir(exist_ok=True)
    _ok("directory create (global/, projects/)")

    # 2 · DB migrato all'ultima versione (backup automatico se esisteva già)
    from wadachi.migrations import run_migrations
    applied = run_migrations(brain / "brain.db")
    if applied:
        _ok(f"database pronto (migrazioni applicate: {applied})")
    else:
        _ok("database già all'ultima versione dello schema")

    # 2b · LLM Wiki: SCHEMA.md (le convenzioni del brain) + index.md
    schema_path = brain / "SCHEMA.md"
    if not schema_path.exists():
        schema_path.write_text(_SCHEMA_MD, encoding="utf-8")
        _ok("SCHEMA.md creato (le convenzioni del wiki — leggilo, è tuo)")
    else:
        _skip("SCHEMA.md già presente (non lo tocco: è tuo)")
    from wadachi.store import MemoryStore
    MemoryStore(str(brain)).rebuild_index()
    _ok("index.md rigenerato (catalogo del wiki)")

    # 2c · nota ricerca su Python 3.15 se fastembed non è presente
    try:
        import fastembed  # noqa: F401
    except ImportError:
        if sys.version_info >= (3, 15):
            print("  ⚠ ricerca semantica non disponibile su Python 3.15 "
                  "(onnxruntime senza wheel cp315): attiva la ricerca keyword.")
            print("    Per averla subito: uv tool install --python 3.14 \"wadachi[semantic]\"")

    # 3 · registrazione in Claude Code (se il CLI `claude` è disponibile)
    if args.no_claude:
        _skip("Claude Code: saltato (--no-claude)")
    elif shutil.which("claude"):
        bin_path = _wadachi_bin()
        subprocess.run(["claude", "mcp", "remove", "wadachi", "--scope", "user"],
                       capture_output=True)
        r = subprocess.run(
            ["claude", "mcp", "add", "wadachi", "--scope", "user",
             "-e", f"BRAIN_DIR={brain}", "--", bin_path],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            _ok(f"Claude Code: server MCP 'wadachi' registrato ({bin_path})")
        else:
            print(f"  ✗ Claude Code: registrazione fallita: {(r.stderr or r.stdout).strip()[:200]}")
    else:
        _skip("Claude Code: CLI `claude` non trovato — registra a mano con:\n"
              f"      claude mcp add wadachi -e BRAIN_DIR={brain} -- {_wadachi_bin()}")

    # 4 · config Antigravity (solo se l'IDE è presente)
    ag_dir = Path(args.antigravity_dir or (Path.home() / ".gemini" / "antigravity-ide"))
    if args.no_antigravity:
        _skip("Antigravity: saltato (--no-antigravity)")
    elif ag_dir.is_dir():
        cfg_path = ag_dir / "mcp_config.json"
        try:
            cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        except json.JSONDecodeError:
            print(f"  ✗ Antigravity: {cfg_path} non è JSON valido, non lo tocco")
            cfg = None
        if cfg is not None:
            cfg.setdefault("mcpServers", {})["wadachi"] = {
                "command": _wadachi_bin(),
                "args": [],
                "env": {"BRAIN_DIR": str(brain)},
            }
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
            _ok(f"Antigravity: server 'wadachi' scritto in {cfg_path}")
    else:
        _skip("Antigravity: non installato")

    print("\nFatto. Riavvia Claude Code e inizia con `get_context`. 轍")
    return 0


def cmd_sleep(args: argparse.Namespace) -> int:
    """Esegue il sonno e stampa il report umano. La cache scritta dal tool fa sì
    che il prossimo get_context PROPONGA i risultati all'utente."""
    if args.brain_dir:
        os.environ["BRAIN_DIR"] = str(Path(args.brain_dir).expanduser())
    import json as _json
    import wadachi.server as srv          # import qui: carica il brain giusto

    print(f"wadachi {__version__} — sonno 💤 (read-only)\n")
    rep = _json.loads(srv.sleep())

    if rep.get("merge_candidates"):
        print(f"Gruppi di memorie ridondanti ({len(rep['merge_candidates'])}):")
        for g in rep["merge_candidates"]:
            print(f"  ◆ {' + '.join(str(i) for i in g['ids'])}")
            for title in g["titles"][:4]:
                print(f"      {title}")
    else:
        print("Nessun gruppo ridondante trovato. ✓")

    if rep.get("decay_candidates"):
        print(f"\nMemorie in decadimento (mai richiamate, senza link):")
        for c in rep["decay_candidates"]:
            print(f"  ▽ #{c['id']} (decay {c['decay']}) {c['title']}")
    else:
        print("Nessuna memoria in decadimento. ✓")

    if rep.get("orphans"):
        print(f"\nNodi senza collegamenti: {', '.join(rep['orphans'])}")

    print("\nNulla è stato modificato. Le proposte appariranno nel prossimo")
    print("get_context; per agire: merge_memories(...) / flag_stale(...).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="wadachi",
        description="wadachi 轍 — persistent memory for AI agents (MCP). "
                    "Senza argomenti avvia il server MCP su stdio.",
    )
    parser.add_argument("--version", action="version", version=f"wadachi {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="setup guidato: brain dir, DB, config MCP")
    p_init.add_argument("--brain-dir", help="dove vive il brain (default: $BRAIN_DIR, "
                                            "poi ~/.wadachi, o ~/.engram se già esiste)")
    p_init.add_argument("--no-claude", action="store_true",
                        help="non registrare il server in Claude Code")
    p_init.add_argument("--no-antigravity", action="store_true",
                        help="non scrivere la config Antigravity")
    p_init.add_argument("--antigravity-dir", help=argparse.SUPPRESS)  # per i test

    p_doc = sub.add_parser("doctor", help="diagnostica: config, DB, permessi, file, schema")
    p_doc.add_argument("--brain-dir", help="brain da diagnosticare (default come init)")
    p_doc.add_argument("--fix", action="store_true",
                       help="ripara ciò che è sicuro riparare (dir mancanti, frontmatter)")
    p_doc.add_argument("--no-mcp", action="store_true",
                       help="salta il controllo della registrazione in Claude Code")

    p_sleep = sub.add_parser("sleep", help="il sonno del brain: report di consolidamento "
                                           "(read-only, propone e basta — perfetto in cron)")
    p_sleep.add_argument("--brain-dir", help="brain su cui far girare il sonno")

    p_obs = sub.add_parser("obsidian", help="SU RICHIESTA: genera i wikilink [[slug]] per il "
                                            "grafo di Obsidian (sezione Links in coda ai file)")
    p_obs.add_argument("--brain-dir", help="brain su cui generare i link")
    p_obs.add_argument("--dry-run", action="store_true",
                       help="mostra cosa cambierebbe senza toccare nulla")

    p_exp = sub.add_parser("export", help="archivio portabile dell'intero brain (READ-ONLY: "
                                          "sicuro anche PRIMA di un upgrade/migrazione)")
    p_exp.add_argument("--brain-dir", help="brain da esportare")
    p_exp.add_argument("--out", help="file di destinazione (default: ./wadachi-export-<ts>.tar.gz)")

    p_res = sub.add_parser("restore", help="ripristina un export: in una cartella nuova "
                                           "(--to) o SUL brain attivo (--replace)")
    p_res.add_argument("archive", help="archivio wadachi-export-*.tar.gz")
    p_res.add_argument("--to", help="cartella di destinazione (nuova)")
    p_res.add_argument("--replace", action="store_true",
                       help="'riparti da qui': sostituisce il brain attivo (lo stato "
                            "corrente viene PRIMA esportato in backups/)")
    p_res.add_argument("--brain-dir", help="brain attivo da sostituire (con --replace)")
    p_res.add_argument("--force", action="store_true",
                       help="con --to: sovrascrivi una destinazione non vuota")

    args = parser.parse_args()

    if args.command == "init":
        return cmd_init(args)
    if args.command == "doctor":
        from wadachi.doctor import run_doctor
        brain = args.brain_dir or os.environ.get("BRAIN_DIR") or _default_brain_dir()
        return run_doctor(brain, fix=args.fix, check_mcp=not args.no_mcp)
    if args.command == "sleep":
        return cmd_sleep(args)
    if args.command == "export":
        from wadachi.portability import export_brain
        brain = args.brain_dir or os.environ.get("BRAIN_DIR") or _default_brain_dir()
        print(f"wadachi {__version__} — export (read-only, il brain non viene toccato)\n")
        try:
            res = export_brain(brain, out=args.out)
        except FileNotFoundError as e:
            print(f"  ✗ {e}")
            return 1
        m = res["manifest"]
        counts = f"{m['memories']} memorie · {m['decisions']} decisioni" \
            if m["memories"] is not None else "conteggi non disponibili"
        print(f"  ✓ {res['archive']}")
        print(f"    {m['markdown_files']} file markdown · {counts} · schema v{m['schema_version']}")
        print(f"\nMettilo al sicuro. Per ripristinare: wadachi restore <archivio> --to <dir>")
        return 0
    if args.command == "restore":
        from wadachi.portability import restore_brain, restore_in_place
        print(f"wadachi {__version__} — restore\n")
        if bool(args.to) == bool(args.replace):
            print("  ✗ scegli UNA modalità: --to <dir-nuova> oppure --replace")
            return 1
        try:
            if args.replace:
                brain = args.brain_dir or os.environ.get("BRAIN_DIR") or _default_brain_dir()
                res = restore_in_place(args.archive, brain_dir=brain)
                print(f"  ✓ brain sostituito: {res['restored_to']}")
                if res["safety_export"]:
                    print(f"  ✓ lo stato precedente è al sicuro: {res['safety_export']}")
                print("\nRiavvia il client MCP. Per tornare indietro: "
                      "wadachi restore <safety-export> --replace")
            else:
                res = restore_brain(args.archive, to=args.to, force=args.force)
                print(f"  ✓ ripristinato in {res['restored_to']}")
                print(f"\nPer usarlo: BRAIN_DIR={res['restored_to']} — poi `wadachi doctor`.")
        except (FileNotFoundError, FileExistsError, ValueError) as e:
            print(f"  ✗ {e}")
            return 1
        return 0
    if args.command == "obsidian":
        from wadachi.obsidian import run_backfill
        brain = args.brain_dir or os.environ.get("BRAIN_DIR") or _default_brain_dir()
        print(f"wadachi {__version__} — wikilink per Obsidian"
              + (" (DRY RUN, nulla viene toccato)" if args.dry_run else "") + "\n")
        st = run_backfill(brain, dry_run=args.dry_run)
        verbo = "da aggiornare" if args.dry_run else "aggiornati"
        print(f"  ✓ {st['scanned']} file esaminati · {st['updated']} {verbo} · "
              f"{st['links']} wikilink generati"
              + (f" · {st['unresolved']} riferimenti non risolti" if st['unresolved'] else ""))
        if not args.dry_run and st["updated"]:
            print(f"\nApri {brain} come vault in Obsidian: il grafo ora ha i collegamenti. 轍")
        return 0

    # nessun sottocomando → server MCP (import lazy: init non deve toccare
    # il BRAIN_DIR di default solo per colpa dell'import del server)
    from wadachi.server import mcp
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
