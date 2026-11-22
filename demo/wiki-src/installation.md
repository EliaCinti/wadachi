# Installation

Wadachi is a Python package. Requirements: **Python 3.11+** on macOS, Linux or Windows.

## Recommended install

Includes local semantic search — a ~30M-parameter embedding model
(`BAAI/bge-small-en-v1.5`) that runs entirely on your machine. It downloads once
(~200 MB with runtime) on first use; after that, no network is ever touched.

```bash
pipx install "wadachi[semantic]"
# or
uv tool install "wadachi[semantic]"
```

> **Python 3.15 note:** `onnxruntime` (used by `fastembed`) currently publishes
> prebuilt wheels up to Python 3.14 only. On Python 3.15, `wadachi[semantic]`
> installs cleanly and falls back to keyword search instead of failing. To get
> local semantic search right away on a machine whose default Python is 3.15,
> pin Python 3.14 for the tool:
>
> ```bash
> uv tool install --python 3.14 "wadachi[semantic]"
> # or: pipx install --python python3.14 "wadachi[semantic]"
> ```

## Minimal install

No ML dependencies at all. Search falls back to keyword matching — everything else
works identically:

```bash
pipx install wadachi
```

You can add semantic search later: `pipx install --force "wadachi[semantic]"`.

## From source

```bash
git clone https://github.com/EliaCinti/wadachi.git
cd wadachi
pip install -e ".[semantic,dev]"   # dev adds pytest
pytest tests/ -q                   # everything should be green
```

## Set up the brain: wadachi init

```bash
wadachi init
```

One idempotent command:

1. creates the **brain directory** — default `~/.wadachi`; an existing legacy
   `~/.engram` (the Engram era) is detected and reused in place;
2. brings the database to the latest schema — **backing it up first** if it existed;
3. writes `SCHEMA.md` (the wiki conventions, yours to edit) and generates `index.md`;
4. registers the MCP server in **Claude Code** and **Antigravity** automatically.

| flag | effect |
|---|---|
| `--brain-dir PATH` | put the brain elsewhere (external SSD, synced folder) |
| `--no-claude` | skip Claude Code registration |
| `--no-antigravity` | skip Antigravity config |

Verify with `wadachi doctor` — see [[troubleshooting]].

> Coming from Engram and nervous about your memories? Read [[safety]] first:
> `wadachi export` snapshots everything **before** anything migrates.

## Upgrading

```bash
wadachi export              # optional but wise — read-only snapshot first
pipx upgrade wadachi
wadachi doctor              # tells you if migrations are pending
```

Migrations run on first start after an upgrade, each inside a transaction, each
**after an automatic backup** of `brain.db`. Details in [[safety]].

## Uninstalling

```bash
pipx uninstall wadachi
```

Remove the server entry from your MCP client. Your brain directory remains — plain
markdown you can keep forever, grep, or open in Obsidian ([[obsidian-okf]]).
Exit is as easy as entry.
