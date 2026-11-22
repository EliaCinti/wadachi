# Troubleshooting

## First stop, always

```bash
wadachi doctor
```

It checks the brain dir, permissions, database integrity, schema version, every
memory file, the wiki files, the search mode and the MCP registration — and tells
you what to do about anything it finds, including where the backups are.

## The log file

`<brain>/logs/wadachi.log` — every tool error with a full traceback, rotated at
1 MB. `WADACHI_LOG=DEBUG` adds per-tool timings. Nothing is ever printed to stdout:
that's the MCP protocol channel (a corrupted stdout is how MCP servers break
mysteriously — wadachi's logging is stderr + file only, by hard rule).

## Common situations

| symptom | likely cause → fix |
|---|---|
| client shows wadachi as disconnected | wrong command path or BRAIN_DIR → `claude mcp list`, re-run `wadachi init` |
| "search feels dumb" | keyword mode → install `wadachi[semantic]`; check `brain_status` |
| Python 3.15 runs in keyword mode | `onnxruntime` has no `cp315` wheels yet → pin 3.14: `uv tool install --python 3.14 "wadachi[semantic]"` |
| recall_associative returns an error | no fastembed → expected; it includes keyword fallback results |
| doctor: "schema vN, available vM" | pending migrations → next server start or `wadachi init` applies them (with backup) |
| doctor: files with non-canonical frontmatter | hand edits → `wadachi doctor --fix` (prose untouched) |
| doctor: orphan .md files | files created outside wadachi → link or import them; they're listed by name |
| DB "corrotto / unreadable" | restore from `backups/` (doctor names the path) or `wadachi restore` an export |
| first semantic search is slow | one-time embedding model download (~200 MB) |

## Reporting a bug

Open a GitHub issue with the **doctor output** and the **last log lines** — the
issue template asks for exactly those two things, and they're usually enough to
diagnose anything. Never paste memory contents you consider private.
