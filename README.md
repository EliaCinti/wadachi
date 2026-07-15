<div align="center">

```
┌─────────────────────────────────────────────┐
│                                             │
│           轍  w a d a c h i  轍             │
│                                             │
│      Your sessions leave tracks.            │
│      Future sessions follow them.           │
│                                             │
└─────────────────────────────────────────────┘
```

**Your AI forgets everything between sessions. Wadachi fixes that.**\
*Wadachi (轍): the tracks wheels leave in a road — formerly known as Engram.*

**The MCP-native memory server for the LLM Wiki pattern.**\
Persistent memory + semantic search for Claude Code, Claude Desktop, Cursor, and any MCP client.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![MCP](https://img.shields.io/badge/protocol-MCP-e64a19?style=flat-square)](https://modelcontextprotocol.io)
[![CI](https://img.shields.io/github/actions/workflow/status/EliaCinti/wadachi/ci.yml?style=flat-square&label=CI&labelColor=18181B)](https://github.com/EliaCinti/wadachi/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/wadachi?style=flat-square&color=D9442B&labelColor=18181B)](https://pypi.org/project/wadachi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)](LICENSE)
[![Live demo](https://img.shields.io/badge/demo-wadachi.eliacinti.dev-D9442B?style=flat-square)](https://wadachi.eliacinti.dev)

**[Live graph demo →](https://wadachi.eliacinti.dev)** &nbsp;·&nbsp; *(coming soon — explore a real brain as an interactive constellation)*

</div>

---

## The Problem

Every time you open Claude Code on a project, it starts from zero. It re-reads files, re-analyzes architecture, re-discovers patterns — burning tokens and time on things it already figured out yesterday.

You end up repeating yourself:
> *"Remember, we're using the observer pattern here..."*\
> *"The deploy script needs the --feynotes flag..."*\
> *"We already tried that approach, it doesn't work because..."*

## The Solution

Wadachi gives your AI a **persistent brain** — a local knowledge base where it stores insights, decisions, and patterns, then retrieves them instantly at the start of every session.

One tool call at session start. All relevant context loaded. Zero wasted tokens re-discovering.

---

## Features

**Persistent Memory** — Knowledge stored as markdown files with SQLite metadata. Survives across sessions, searchable, human-readable.

**Semantic Search** — Finds memories by meaning, not just keywords. Ask for "linearizzazione sistemi" and it finds your notes on equilibrium points, even if the word "linearizzazione" never appears in them. Powered by local embeddings via [fastembed](https://github.com/qdrant/fastembed) — no API calls, no costs, runs on your machine.

**Project Profiles** — Register your projects with their filesystem paths. Wadachi auto-detects which project you're in and scopes memories accordingly. Your FeyNotes memories stay separate from your LaPlacebo memories.

**Auto-Context** — `get_context` is the killer tool: one call at session start that detects the project, gathers relevant memories, loads recent decisions, and returns everything your AI needs to hit the ground running.

**Decision Log** — Not just *what* you know, but *what you decided and why*. When a future session faces the same choice, it sees the rationale and the rejected alternatives — no more re-debating solved problems.

**Constellation — Graph-Aware Recall** — Plain `recall` is pure cosine top-k, so a memory that's strongly *connected* to your query but not textually similar never surfaces. Wadachi builds a weighted graph over your brain from **citation** edges (`"memoria #82"`, `"aggiorna #77"` parsed from the prose), **semantic** k-NN edges, and **shared-entity** edges, then runs HippoRAG-style spreading activation (Personalized PageRank). `recall_associative` pulls up neighbours of your best hits even when their raw similarity is low — and returns the plain-cosine baseline alongside, so you can compare.

**Entity Knowledge Graph (Graphify)** — Extracts the entities inside your notes (`convert.py`, `Di Gennaro`, `Opus 4.8`) and the relations between them, linking memories that mention the same thing even when neither cites the other. Extraction runs through the **local `claude` CLI** — it uses your Claude plan, not metered API, so it costs **$0** — and degrades gracefully when not installed.

**Belief Revision** — A plain store treats every memory as true forever; a brain shouldn't. `review_beliefs` does a read-only pass that flags memories likely gone stale — superseded by a newer note, past a temporal deadline (`"resets 1 Jul"`), or provisional/fallback wording — and annotates them in `recall` instead of silently trusting them. It never deletes: it suggests, you confirm with `flag_stale` / `set_belief`. Every update is **non-destructive**, so prior versions stay recoverable via `memory_history`.

**Reflection & Insights** — The brain thinks *between* sessions. `reflect` combines memories to surface cross-project analogies and non-obvious connections that no single memory holds — reusing the entity graph it already built, so no extra LLM cost. Candidates are *proposed*, never auto-trusted: you `accept_insight` (promoted to a real linked memory) or `reject_insight`.

**Procedural Memory** — Recency-ranked recall can *hide* the right rule and let you repeat a mistake twice. `review_procedures` clusters recurring incident memories by root theme and proposes a single always-on rule for review — human-in-the-loop, it never rewrites your operating instructions itself.

---

## Architecture

```mermaid
graph TB
    subgraph Client
        CC[Claude Code]
        CD[Claude Desktop]
        CU[Cursor]
    end

    subgraph Server ["Wadachi MCP Server — FastMCP · 30 tools"]
        S[server.py<br><i>tool surface</i>]
        ST[store.py<br><i>SQLite + markdown, versioned</i>]
        SE[search.py<br><i>semantic + keyword</i>]
        GR[graph.py<br><i>constellation: PPR recall</i>]
        EN[entities.py<br><i>Graphify entity graph</i>]
        BE[beliefs.py<br><i>belief revision</i>]
        RE[reflect.py<br><i>cross-memory insights</i>]
        PR[procedural.py<br><i>recurring-incident rules</i>]
        WE[web.py<br><i>graph visualizer</i>]
    end

    subgraph Storage ["~/.wadachi (BRAIN_DIR)"]
        DB[(brain.db<br><i>metadata · embeddings · beliefs</i>)]
        GL[global/<br><i>cross-project memories</i>]
        PJ[projects/.../<br><i>scoped memories</i>]
        CO[.constellation/<br><i>entity-graph cache</i>]
    end

    CC & CD & CU <-->|MCP protocol| S
    S --> SE & ST & GR & BE & RE & PR
    GR --> EN
    RE --> EN
    SE --> DB
    ST --> DB & GL & PJ
    EN --> CO
    WE -.->|reads| ST

    style S fill:#1a1a2e,stroke:#e94560,color:#fff
    style ST fill:#1a1a2e,stroke:#0f3460,color:#fff
    style SE fill:#1a1a2e,stroke:#0f3460,color:#fff
    style GR fill:#1a1a2e,stroke:#8b5cf6,color:#fff
    style EN fill:#1a1a2e,stroke:#8b5cf6,color:#fff
    style BE fill:#1a1a2e,stroke:#0f3460,color:#fff
    style RE fill:#1a1a2e,stroke:#0f3460,color:#fff
    style PR fill:#1a1a2e,stroke:#0f3460,color:#fff
    style WE fill:#1a1a2e,stroke:#533483,color:#fff
    style DB fill:#16213e,stroke:#533483,color:#fff
```

---

## Quick Start

Three commands and your AI has a memory:

```bash
# 1 · install (pipx or uv — semantic search included, runs locally)
pipx install "wadachi[semantic]"        # or: uv tool install "wadachi[semantic]"

# 2 · guided setup: brain dir, database, Claude Code registration
wadachi init

# 3 · restart Claude Code — every session now starts with get_context
```

`wadachi init` creates the brain directory (default `~/.wadachi`), brings the
database to the latest schema, and registers the MCP server in Claude Code and
Antigravity automatically. It is idempotent — safe to re-run anytime.

<details>
<summary>Install from source</summary>

```bash
git clone https://github.com/EliaCinti/wadachi.git
cd wadachi
pip install -e ".[semantic]"
wadachi init
```

</details>

<details>
<summary>Manual configuration (Claude Code / Desktop / Cursor)</summary>

**Claude Code** — `~/.claude.json` or project-level `.mcp.json`:
```json
{
  "mcpServers": {
    "wadachi": {
      "command": "wadachi",
      "args": [],
      "env": {
        "BRAIN_DIR": "/Users/you/.wadachi"
      }
    }
  }
}
```

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "wadachi": {
      "command": "wadachi",
      "args": []
    }
  }
}
```

**Cursor** — `.cursor/mcp_servers.json`:
```json
{
  "mcpServers": {
    "wadachi": {
      "command": "wadachi",
      "args": []
    }
  }
}
```

</details>

### Register a project

In your first Claude session with Wadachi connected:

```
Register my project "feynotes" with description "Lecture audio to interactive web pages"
and path "/Volumes/ExtremeSSD/University/Lecture_From_Audio/"
```

### Use it

From now on, every session can start with `get_context` and your AI already knows what's going on. As you work, important discoveries get stored automatically. Over time, the brain compounds — each session is smarter than the last.

---

## Tools

Wadachi exposes **30 MCP tools**, grouped by area.

**Memory**

| Tool | What it does |
|:-----|:-------------|
| `store_memory` | Save an insight, pattern, fix, or reference for future sessions. |
| `get_memory` | Load the full content of a specific memory by ID. |
| `list_memories` | Browse all memories. Filter by project or category. |
| `update_memory` | Modify a memory's content or tags — non-destructive, prior versions kept. |
| `delete_memory` | Permanently remove a memory. |
| `memory_history` | Show prior versions of a memory (preserved on every update). |

**Search & Context**

| Tool | What it does |
|:-----|:-------------|
| `get_context` | **Start here.** Auto-detects project, returns relevant memories + decisions + stats + what needs review. |
| `recall` | Semantic (or keyword) search across stored knowledge, annotated with belief status. |
| `expand_memory` | Drill down from the compact context: full content of one or more memories by id. |
| `brain_status` | Health check, search mode, stats, and registered projects. |

**Decisions**

| Tool | What it does |
|:-----|:-------------|
| `store_decision` | Log a decision with rationale and rejected alternatives. |
| `list_decisions` | Browse the decision history. |

**Projects**

| Tool | What it does |
|:-----|:-------------|
| `register_project` | Map filesystem paths to a project name for auto-detection. |
| `list_projects` | Show all registered projects. |

**Constellation — Graph**

| Tool | What it does |
|:-----|:-------------|
| `recall_associative` | Spreading-activation recall over the memory graph (HippoRAG-style PPR); returns the cosine baseline too. |
| `related_memories` | Show the memories most strongly linked to a given one (typed neighbours). |
| `memory_graph` | Graph overview: hubs, orphans, components, a Mermaid backbone + the entity graph. |
| `rebuild_entity_graph` | (Re)build the Graphify entity knowledge graph via the local `claude` CLI ($0). |

**Belief Revision**

| Tool | What it does |
|:-----|:-------------|
| `review_beliefs` | Read-only scan for memories likely gone stale (superseded / temporal / provisional). |
| `set_belief` | Update a memory's belief envelope: confidence, status, validity, supersession. |
| `flag_stale` | Mark a memory stale — kept and recoverable, but annotated in recall. |

**Reflection & Insights**

| Tool | What it does |
|:-----|:-------------|
| `reflect` | Surface cross-project analogies and non-obvious connections as *proposed* insights. |
| `list_insights` | List reflection insights by status (proposed / accepted / rejected). |
| `accept_insight` | Accept an insight and promote it to a real memory linked to its sources. |
| `reject_insight` | Reject an insight (kept on record, marked rejected). |

**Procedural Memory**

| Tool | What it does |
|:-----|:-------------|
| `review_procedures` | Cluster recurring incidents and propose always-on rules for review (read-only). |

**Consolidation**

| Tool | What it does |
|:-----|:-------------|
| `consolidate` | Propose groups of redundant memories to merge (read-only, you review). |
| `merge_memories` | Store your synthesis as a new memory; sources marked superseded, never deleted. |

**Provenance & Time**

| Tool | What it does |
|:-----|:-------------|
| `why` | Ask "why do we use X and not Y?" — decision, rationale, rejected alternatives, and the memories that cite it. |
| `as_of` | Time-travel: what the brain believed at a date, with content reconstructed from version history. |

### Memory Categories

| Category | Use for |
|:---------|:--------|
| `architecture` | System design, structure, high-level patterns |
| `bugfix` | Bugs found and their solutions |
| `config` | Setup details, environment variables, infrastructure |
| `pattern` | Code conventions, recurring patterns, style rules |
| `context` | General project background and context |
| `reference` | API details, library usage, external documentation |
| `note` | Everything else |

---

## Storage

All data lives locally in `~/.wadachi` (configurable via `BRAIN_DIR` env var; a legacy `~/.engram` dir keeps working):

```
~/.wadachi/
├── brain.db                    # SQLite: metadata + cached embeddings
├── global/                     # Cross-project knowledge
│   ├── python-venv-tips.md
│   └── git-workflow.md
└── projects/
    ├── feynotes/
    │   ├── pipeline-architecture.md
    │   ├── katex-gotchas.md
    │   └── deploy-workflow.md
    └── laplacebo/
        └── solver-design.md
```

Memories are plain markdown files with YAML frontmatter — readable and editable by hand.

### LLM Wiki native · Obsidian vault · OKF bundle

The brain follows [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
an agent-maintained markdown wiki with `[[wikilinks]]`, a generated `index.md`
catalog, an append-only `log.md`, and a `SCHEMA.md` documenting the conventions
(edit it — the schema file is yours). Every link becomes a graph edge that
associative recall and consolidation travel on.

- **Obsidian**: the brain dir *is* a vault — open it and get the graph view for free. Zero lock-in.
- **OKF**: every file carries the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog) `type` field — the brain is a conformant OKF bundle, portable to any OKF consumer.
- `wadachi doctor --fix` upgrades pre-OKF brains in place (content never touched).

---

## Upgrading

**Your memories always survive an upgrade.** The database schema is versioned:
on first start after an update, wadachi applies any pending migrations — and
**backs up your `brain.db` automatically** (to `<brain>/backups/`) before
touching anything. Existing brains from older versions (including the Engram
era, `~/.engram`) are adopted in place: nothing to export, nothing to lose.

```bash
pipx upgrade wadachi        # or: uv tool upgrade wadachi
# restart Claude Code — migrations (if any) run on first start, after a backup
```

---

## Search Modes

Wadachi ships with two search backends:

| Mode | Install | How it works | Speed |
|:-----|:--------|:-------------|:------|
| **Semantic** | `pip install fastembed` | Local embeddings + cosine similarity. Finds by meaning. | ~50ms |
| **Keyword** | Built-in | Token overlap scoring on title + tags + content. | ~5ms |

Semantic search runs entirely on your machine — no API calls, no cloud, no costs. The embedding model (`BAAI/bge-small-en-v1.5`, ~33M params) downloads once and runs locally.

---

## Recently shipped

- [x] **Constellation** — graph-aware associative recall (citation + semantic + entity edges, HippoRAG-style spreading activation)
- [x] **Graphify entity graph** — entity/relation extraction over the brain via the local `claude` CLI ($0)
- [x] **Belief revision** — stale / superseded / temporal flagging, annotated in recall, non-destructive
- [x] **Reflection & insights** — cross-memory analogies proposed for accept/reject
- [x] **Procedural memory** — recurring-incident clustering into candidate rules
- [x] **Non-destructive memory history** — every update preserves prior versions
- [x] **Web graph visualizer** — interactive constellation view *(live demo coming to [wadachi.eliacinti.dev](https://wadachi.eliacinti.dev))*

## Roadmap

- [ ] Auto-summarize old memories to reduce token usage
- [ ] Memory importance decay (surface recent and frequently-accessed memories first)
- [ ] Claude Code hooks for automatic context injection + brain backup on session stop
- [ ] Export/sync with Notion
- [ ] Conversation history indexing
- [ ] Multi-language embedding model for better Italian support

---

## Contributing

PRs welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) first (philosophy: local-first,
memories are sacred, propose don't auto-edit). Not a coder? The most valuable
contribution is [telling us how you use wadachi](https://github.com/EliaCinti/wadachi/issues/new?template=share_your_setup.yml) —
there's no telemetry, feedback is all we have.

## Acknowledgments

Inspired by [mstrehse/mcp-brain](https://github.com/mstrehse/mcp-brain) — a Go-based MCP memory server that sparked the idea. Wadachi is a ground-up rewrite in Python with semantic search, project awareness, and auto-context injection.

## License

[MIT](LICENSE)

---

<div align="center">
<sub>Built by <a href="https://eliacinti.dev">Elia Cinti</a></sub>
</div>
