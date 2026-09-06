# La scrivania — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Wadachi a second layer of memory — a markdown *progress record* per thread of work, so a new session resumes exactly where the last one stopped instead of having its handover typed by hand.

**Architecture:** A desk is a markdown file at `<brain>/desks/<project>/<slug>.md` with a fixed skeleton (Objective, Plan as checkboxes, Log, Open). SQLite holds an **index only** — never content — exactly as memories already work. Three MCP tools (`desk`, `desk_read`, `desk_log`) operate by *editing one section* and rewriting atomically inside the existing `BEGIN IMMEDIATE` transaction, so concurrent sessions append rather than overwrite. `get_context` surfaces a capped summary above the memories.

**Tech Stack:** Python 3.11+, SQLite (`sqlite3`), FastMCP, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-la-scrivania-design.md`

## Global Constraints

- **The file is the source of truth; the database holds metadata only.** Same contract as memories (`brain.md`: "Files are the source of truth").
- **Every write goes through `MemoryStore._write()`** (`BEGIN IMMEDIATE`) and `_atomic_write_text(path, text)` — never a bare `open(...).write()`.
- **No tool ever rewrites a whole desk file.** Every operation edits one section.
- **A desk never enters recall.** Not `recall`, not `recall_associative`, not embeddings, not beliefs, not versioning.
- **Propose, never auto-edit** (rule 3 of the brain): the software suggests, the human or the model that was there decides.
- **New tools are registered `@tool()`** — the `work` toolset — and their first docstring line must name a *situation* (`use this when…`), never an implementation. Enforced by `tests/test_toolsets.py`.
- Tests run with `venv/bin/python -m pytest -q`. The full suite is 173 tests and must stay green.

---

### Task 1: The index table (migration 0003)

**Files:**
- Create: `wadachi/migrations/0003_desks.py`
- Test: `tests/test_migrations.py` (append)

**Interfaces:**
- Consumes: the migration loader in `wadachi/migrations/__init__.py`, which imports modules exposing `VERSION`, `DESCRIPTION`, and `up(conn)`.
- Produces: table `desks(slug TEXT, project TEXT, title TEXT, status TEXT, created_at TEXT, updated_at TEXT, filepath TEXT)` with `PRIMARY KEY (project, slug)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_migrations.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_migrations.py -k desks -q`
Expected: FAIL — `no such table: desks`

- [ ] **Step 3: Write minimal implementation**

Create `wadachi/migrations/0003_desks.py`:

```python
"""
La scrivania (P1): stato di lavoro che sopravvive alla finestra di contesto.

Indice soltanto — il contenuto vive nel file markdown, come per le memorie.
`filepath` è relativo alla brain dir, così un brain spostato resta valido.
"""

VERSION = 3
DESCRIPTION = "desks: indice delle scrivanie (il contenuto sta nei file)"


def up(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS desks (
            slug       TEXT NOT NULL,
            project    TEXT NOT NULL,
            title      TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            filepath   TEXT NOT NULL,
            PRIMARY KEY (project, slug)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_desks_open "
        "ON desks(project, status, updated_at DESC)"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_migrations.py -k desks -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add wadachi/migrations/0003_desks.py tests/test_migrations.py
git commit -m "A desk needs an index, and only an index: the content lives in the file"
```

---

### Task 2: Parsing and rendering the file

**Files:**
- Create: `wadachi/desk.py`
- Test: `tests/test_desk_format.py`

**Interfaces:**
- Consumes: nothing from Task 1 (pure functions, no database).
- Produces, all importable from `wadachi.desk`:
  - `SKELETON: str` — the empty desk template
  - `render_desk(meta: dict, objective: str, done_when: str, plan: list[str]) -> str`
  - `parse_plan(text: str) -> list[tuple[bool, str]]` — `(done, label)`, Plan section only, code fences skipped
  - `next_step(text: str) -> str | None` — first unticked label, `None` if none
  - `tick_step(text: str, label: str) -> tuple[str, bool]` — `(new_text, was_already_done)`
  - `add_log(text: str, line: str, when: str) -> str` — prepends into `## Registro`
  - `add_open(text: str, line: str) -> str` — appends into `## Aperto`
  - `add_steps(text: str, labels: list[str]) -> str` — appends unticked steps to `## Piano`
  - `desk_slug(title: str, taken: set[str]) -> str` — raises `ValueError` on an empty slug, suffixes on collision

- [ ] **Step 1: Write the failing test**

Create `tests/test_desk_format.py`:

```python
"""Il formato del file: le quattro crepe trovate provando il progetto."""

import pytest

from wadachi.desk import (add_log, add_open, add_steps, desk_slug, next_step,
                          parse_plan, render_desk, tick_step)

DESK = """---
type: desk
slug: x
---

## Obiettivo
Fare la cosa.
**Fatto quando:** i test passano.

## Piano
- [x] primo
- [ ] secondo
- [x] terzo fuori ordine
- [ ] quarto

## Registro
- **20:00** — nota vecchia

## Aperto
- una domanda
"""


def test_the_next_step_is_the_first_unticked_even_out_of_order():
    assert next_step(DESK) == "secondo"


def test_a_finished_plan_has_no_next_step():
    done = DESK.replace("- [ ]", "- [x]")
    assert next_step(done) is None


def test_a_checkbox_inside_a_code_fence_is_not_a_step():
    """Un registro che annota `- [ ] X` non deve spostare il cursore."""
    trap = DESK.replace(
        "- **20:00** — nota vecchia",
        "- **20:00** — provato a scrivere:\n```\n- [ ] finto\n```",
    )
    assert [l for _, l in parse_plan(trap)] == [
        "primo", "secondo", "terzo fuori ordine", "quarto"]
    assert next_step(trap) == "secondo"


def test_only_the_plan_section_counts():
    """Una checkbox in Aperto non è un passo."""
    trap = DESK.replace("- una domanda", "- [ ] non sono un passo")
    assert next_step(trap) == "secondo"


def test_ticking_a_step_marks_only_that_line():
    out, already = tick_step(DESK, "secondo")
    assert already is False
    assert "- [x] secondo" in out
    assert "- [ ] quarto" in out
    assert next_step(out) == "quarto"


def test_ticking_an_already_ticked_step_says_so_and_changes_nothing():
    out, already = tick_step(DESK, "primo")
    assert already is True
    assert out == DESK


def test_a_log_line_goes_on_top():
    out = add_log(DESK, "cosa nuova", when="21:00")
    reg = out.split("## Registro")[1]
    assert reg.index("cosa nuova") < reg.index("nota vecchia")


def test_an_open_question_goes_at_the_bottom():
    out = add_open(DESK, "un'altra domanda")
    ap = out.split("## Aperto")[1]
    assert ap.index("una domanda") < ap.index("un'altra domanda")


def test_new_steps_are_appended_unticked():
    out = add_steps(DESK, ["quinto", "sesto"])
    assert [l for _, l in parse_plan(out)][-2:] == ["quinto", "sesto"]
    assert next_step(out) == "secondo"


def test_a_title_that_slugifies_to_nothing_is_refused():
    with pytest.raises(ValueError):
        desk_slug("   ", taken=set())
    with pytest.raises(ValueError):
        desk_slug("☕", taken=set())


def test_two_desks_with_the_same_title_get_different_slugs():
    first = desk_slug("Sistemare il deploy", taken=set())
    second = desk_slug("Sistemare il deploy", taken={first})
    assert first != second and second.startswith(first)


def test_render_produces_a_file_the_parser_understands():
    text = render_desk(
        meta={"slug": "s", "title": "T", "project": "p",
              "status": "open", "created": "t", "updated": "t"},
        objective="Fare la cosa.",
        done_when="i test passano.",
        plan=["uno", "due"],
    )
    assert text.startswith("---\n")
    assert next_step(text) == "uno"
    assert "**Fatto quando:** i test passano." in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_desk_format.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'wadachi.desk'`

- [ ] **Step 3: Write minimal implementation**

Create `wadachi/desk.py`:

```python
"""
desk.py — il formato del file di una scrivania.

Funzioni pure: nessun database, nessun IO. Il file è la verità (come per le
memorie), quindi tutto ciò che sa leggerlo e modificarlo vive qui e si può
provare senza brain.

La regola che governa il parsing: **una checkbox conta solo dentro `## Piano`,
e mai dentro un blocco di codice.** Un registro che annota «ho provato a
scrivere `- [ ] X`» sposterebbe altrimenti il cursore — caso reale, non
teorico.
"""

from __future__ import annotations

import re

from .store import _slugify

PLAN = "## Piano"
LOG = "## Registro"
OPEN = "## Aperto"

_STEP = re.compile(r"^- \[( |x)\] (.+)$")
_FENCE = re.compile(r"^\s*```")


def render_desk(meta: dict, objective: str, done_when: str, plan: list[str]) -> str:
    """Il file iniziale di una scrivania."""
    front = "\n".join(f"{k}: {v}" for k, v in meta.items())
    steps = "\n".join(f"- [ ] {s}" for s in plan) or "- [ ] (nessun passo ancora)"
    return (
        f"---\ntype: desk\n{front}\n---\n\n"
        f"## Obiettivo\n{objective}\n**Fatto quando:** {done_when}\n\n"
        f"{PLAN}\n{steps}\n\n"
        f"{LOG}\n\n"
        f"{OPEN}\n"
    )


def _section(text: str, heading: str) -> tuple[int, int]:
    """Gli indici di riga [inizio, fine) del corpo di una sezione."""
    lines = text.split("\n")
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return (-1, -1)
    end = start
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    return (start, end)


def parse_plan(text: str) -> list[tuple[bool, str]]:
    """I passi del piano: `(fatto, etichetta)`. Solo `## Piano`, fence esclusi."""
    start, end = _section(text, PLAN)
    if start < 0:
        return []
    out: list[tuple[bool, str]] = []
    in_fence = False
    for line in text.split("\n")[start:end]:
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _STEP.match(line)
        if m:
            out.append((m.group(1) == "x", m.group(2).strip()))
    return out


def next_step(text: str) -> str | None:
    """La prima etichetta non spuntata, o None se il piano è finito."""
    return next((label for done, label in parse_plan(text) if not done), None)


def tick_step(text: str, label: str) -> tuple[str, bool]:
    """Spunta un passo. Restituisce `(testo, era_già_fatto)`."""
    start, end = _section(text, PLAN)
    lines = text.split("\n")
    in_fence = False
    for i in range(start, end):
        if _FENCE.match(lines[i]):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _STEP.match(lines[i])
        if m and m.group(2).strip() == label:
            if m.group(1) == "x":
                return (text, True)
            lines[i] = f"- [x] {label}"
            return ("\n".join(lines), False)
    return (text, False)


def add_log(text: str, line: str, when: str) -> str:
    """Una riga in cima al registro: il più recente per primo."""
    start, _ = _section(text, LOG)
    if start < 0:
        return text.rstrip("\n") + f"\n\n{LOG}\n- **{when}** — {line}\n"
    lines = text.split("\n")
    lines.insert(start, f"- **{when}** — {line}")
    return "\n".join(lines)


def add_open(text: str, line: str) -> str:
    """Una riga in fondo alle questioni aperte."""
    start, end = _section(text, OPEN)
    if start < 0:
        return text.rstrip("\n") + f"\n\n{OPEN}\n- {line}\n"
    lines = text.split("\n")
    while end > start and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, f"- {line}")
    return "\n".join(lines)


def add_steps(text: str, labels: list[str]) -> str:
    """Passi nuovi in fondo al piano, non spuntati."""
    start, end = _section(text, PLAN)
    if start < 0 or not labels:
        return text
    lines = text.split("\n")
    while end > start and not lines[end - 1].strip():
        end -= 1
    for i, label in enumerate(labels):
        lines.insert(end + i, f"- [ ] {label}")
    return "\n".join(lines)


def desk_slug(title: str, taken: set[str]) -> str:
    """Lo slug dal titolo. Rifiuta un titolo che si riduce a niente."""
    base = _slugify(title)
    if not base:
        raise ValueError(
            "il titolo non produce un nome di file: dagli un titolo con "
            "qualche lettera o numero"
        )
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_desk_format.py -q`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add wadachi/desk.py tests/test_desk_format.py
git commit -m "The file format of a desk, and the four ways parsing it naively goes wrong"
```

---

### Task 3: Store operations

**Files:**
- Modify: `wadachi/store.py` (append methods to `MemoryStore`)
- Test: `tests/test_desk_store.py`

**Interfaces:**
- Consumes: `wadachi.desk` (Task 2) and the `desks` table (Task 1); `self._write()`, `_atomic_write_text`, `self._project_dir(project)`, `self.append_log(op, detail)`, `self.store_memory(content, title, project, tags, category)`.
- Produces, on `MemoryStore`:
  - `open_desk(title, objective, done_when, plan, project="global") -> dict` — keys `slug, project, title, filepath`
  - `read_desk(slug=None, project=None) -> dict | None` — keys `slug, project, title, status, text, next_step, updated_at`
  - `list_desks(project=None, status="open") -> list[dict]`
  - `log_desk(slug=None, project=None, done=None, note=None, open_question=None, add=None) -> dict` — keys `next_step, already_done, slug`
  - `close_desk(slug, outcome, project=None, distil=None) -> dict` — keys `slug, status, memory_id`

- [ ] **Step 1: Write the failing test**

Create `tests/test_desk_store.py`:

```python
"""La scrivania nello store: ciclo di vita, ripresa, confine con le memorie."""

import pytest

from wadachi.store import MemoryStore


@pytest.fixture
def s(tmp_path):
    return MemoryStore(str(tmp_path / "brain"))


def _open(s, **kw):
    kw.setdefault("title", "M34 fetta 4")
    kw.setdefault("objective", "Spostare sign_in nel tratto.")
    kw.setdefault("done_when", "la suite passa")
    kw.setdefault("plan", ["leggere", "estrarre", "verificare"])
    kw.setdefault("project", "overmind")
    return s.open_desk(**kw)


def test_a_desk_opens_and_is_found_again(s):
    d = _open(s)
    got = s.read_desk(d["slug"], project="overmind")
    assert got["title"] == "M34 fetta 4"
    assert got["next_step"] == "leggere"
    assert (s.brain_dir / got["filepath"]).exists()


def test_a_desk_without_a_stopping_condition_is_refused(s):
    with pytest.raises(ValueError):
        _open(s, done_when="   ")
    assert s.list_desks(project="overmind") == []


def test_a_brand_new_store_resumes_the_work(s, tmp_path):
    """Il test che conta: una sessione aperta domani ritrova il punto."""
    _open(s)
    s.log_desk(project="overmind", done="leggere", note="fatto in fretta")

    fresh = MemoryStore(str(tmp_path / "brain"))     # nessuno stato in memoria
    got = fresh.read_desk(project="overmind")
    assert got["next_step"] == "estrarre"
    assert "fatto in fretta" in got["text"]


def test_reading_without_a_slug_needs_exactly_one_open_desk(s):
    _open(s, title="prima")
    _open(s, title="seconda")
    got = s.read_desk(project="overmind")
    assert got is None or got.get("ambiguous")
    assert len(s.list_desks(project="overmind")) == 2


def test_ticking_a_step_already_done_says_so(s):
    _open(s)
    s.log_desk(project="overmind", done="leggere")
    out = s.log_desk(project="overmind", done="leggere")
    assert out["already_done"] is True
    assert out["next_step"] == "estrarre"


def test_two_notes_do_not_overwrite_each_other(s, tmp_path):
    """Due sessioni che annotano: entrambe le righe restano."""
    d = _open(s)
    other = MemoryStore(str(tmp_path / "brain"))
    s.log_desk(project="overmind", note="dalla prima sessione")
    other.log_desk(project="overmind", note="dalla seconda sessione")
    text = s.read_desk(d["slug"], project="overmind")["text"]
    assert "dalla prima sessione" in text
    assert "dalla seconda sessione" in text


def test_a_desk_never_appears_in_recall(s):
    _open(s, objective="zxqwvunicorno parola irripetibile")
    from wadachi.search import SearchEngine
    hits = SearchEngine(s).search("zxqwvunicorno", limit=10)
    assert hits == [] or all("zxqwvunicorno" not in str(h) for h in hits)


def test_closing_without_a_distillate_creates_no_memory(s):
    d = _open(s)
    before = len(s.list_memories())
    out = s.close_desk(d["slug"], "done", project="overmind")
    assert out["memory_id"] is None
    assert len(s.list_memories()) == before
    assert s.list_desks(project="overmind", status="open") == []


def test_closing_with_a_distillate_creates_one_linked_memory(s):
    d = _open(s)
    out = s.close_desk(d["slug"], "done", project="overmind",
                       distil="token_path deve essere per provider.")
    assert out["memory_id"]
    m = s.get_memory(out["memory_id"])
    assert f"[[{d['slug']}]]" in m["content"]


def test_closing_archives_the_file_and_deletes_nothing(s):
    d = _open(s)
    s.close_desk(d["slug"], "abandoned", project="overmind")
    archived = s.brain_dir / "desks" / "overmind" / "archived" / f"{d['slug']}.md"
    assert archived.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_desk_store.py -q`
Expected: FAIL — `AttributeError: 'MemoryStore' object has no attribute 'open_desk'`

- [ ] **Step 3: Write minimal implementation**

Append to `wadachi/store.py`, inside `class MemoryStore`, before `def stats`:

```python
    # ── La scrivania (P1) ─────────────────────────────────────

    def _desk_dir(self, project: str) -> Path:
        return self.brain_dir / "desks" / project

    def _desk_path(self, project: str, slug: str, archived: bool = False) -> Path:
        base = self._desk_dir(project)
        return (base / "archived" / f"{slug}.md") if archived else (base / f"{slug}.md")

    def open_desk(self, title: str, objective: str, done_when: str,
                  plan: list[str] | None = None, project: str = "global") -> dict:
        """Apre una scrivania. `done_when` è la condizione d'arresto: obbligatoria."""
        from . import desk as D
        if not (done_when or "").strip():
            raise ValueError(
                "una scrivania senza «fatto quando» è un diario: dì come si "
                "riconosce che il lavoro è finito"
            )
        with self._write() as conn:
            taken = {r["slug"] for r in conn.execute(
                "SELECT slug FROM desks WHERE project = ?", (project,))}
            slug = D.desk_slug(title, taken)
            now = _utcnow()
            rel = f"desks/{project}/{slug}.md"
            text = D.render_desk(
                meta={"slug": slug, "title": title, "project": project,
                      "status": "open", "created": now, "updated": now},
                objective=objective, done_when=done_when, plan=plan or [])
            path = self._desk_path(project, slug)
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(path, text)
            conn.execute(
                "INSERT INTO desks (slug, project, title, status, created_at, "
                "updated_at, filepath) VALUES (?, ?, ?, 'open', ?, ?, ?)",
                (slug, project, title, now, now, rel))
        self.append_log("desk_open", f"{project}/{slug}")
        return {"slug": slug, "project": project, "title": title, "filepath": rel}

    def _resolve_desk(self, conn, slug: str | None, project: str | None):
        if slug:
            return conn.execute(
                "SELECT * FROM desks WHERE slug = ? AND project = ?",
                (slug, project or "global")).fetchone()
        rows = conn.execute(
            "SELECT * FROM desks WHERE status = 'open'"
            + (" AND project = ?" if project else "")
            + " ORDER BY updated_at DESC",
            ((project,) if project else ())).fetchall()
        return rows[0] if len(rows) == 1 else None

    def read_desk(self, slug: str | None = None, project: str | None = None) -> dict | None:
        """La scrivania e il suo prossimo passo. Senza slug: l'unica aperta."""
        from . import desk as D
        with self._conn() as conn:
            row = self._resolve_desk(conn, slug, project)
            if row is None:
                open_ones = self.list_desks(project=project)
                if len(open_ones) > 1:
                    return {"ambiguous": True, "desks": open_ones}
                return None
            text = (self.brain_dir / row["filepath"]).read_text(encoding="utf-8")
            return {"slug": row["slug"], "project": row["project"],
                    "title": row["title"], "status": row["status"],
                    "filepath": row["filepath"], "updated_at": row["updated_at"],
                    "text": text, "next_step": D.next_step(text)}

    def list_desks(self, project: str | None = None, status: str | None = "open") -> list[dict]:
        q = "SELECT slug, project, title, status, updated_at FROM desks WHERE 1=1"
        args: list = []
        if project:
            q += " AND project = ?"; args.append(project)
        if status:
            q += " AND status = ?"; args.append(status)
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(q + " ORDER BY updated_at DESC", args)]

    def log_desk(self, slug: str | None = None, project: str | None = None,
                 done: str | None = None, note: str | None = None,
                 open_question: str | None = None,
                 add: list[str] | None = None) -> dict:
        """Spunta un passo e/o annota. Restituisce il prossimo passo."""
        from . import desk as D
        already = False
        with self._write() as conn:
            row = self._resolve_desk(conn, slug, project)
            if row is None:
                return {"error": "nessuna scrivania — dammi lo slug",
                        "desks": self.list_desks(project=project)}
            path = self.brain_dir / row["filepath"]
            text = path.read_text(encoding="utf-8")
            if done:
                text, already = D.tick_step(text, done)
            if note:
                text = D.add_log(text, note, when=_utcnow()[11:16])
            if open_question:
                text = D.add_open(text, open_question)
            if add:
                text = D.add_steps(text, add)
            now = _utcnow()
            text = re.sub(r"^updated: .*$", f"updated: {now}", text, count=1, flags=re.M)
            _atomic_write_text(path, text)
            conn.execute("UPDATE desks SET updated_at = ? WHERE slug = ? AND project = ?",
                         (now, row["slug"], row["project"]))
        return {"slug": row["slug"], "already_done": already,
                "next_step": D.next_step(text)}

    def close_desk(self, slug: str, outcome: str, project: str | None = None,
                   distil: str | None = None) -> dict:
        """Chiude e archivia. Con `distil`, ne nasce UNA memoria collegata."""
        project = project or "global"
        memory_id = None
        with self._write() as conn:
            row = conn.execute("SELECT * FROM desks WHERE slug = ? AND project = ?",
                               (slug, project)).fetchone()
            if row is None:
                return {"error": f"nessuna scrivania {project}/{slug}"}
            src = self.brain_dir / row["filepath"]
            dst = self._desk_path(project, slug, archived=True)
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            text = re.sub(r"^status: .*$", f"status: {outcome}", text, count=1, flags=re.M)
            _atomic_write_text(dst, text)
            src.unlink(missing_ok=True)
            rel = f"desks/{project}/archived/{slug}.md"
            conn.execute(
                "UPDATE desks SET status = ?, filepath = ?, updated_at = ? "
                "WHERE slug = ? AND project = ?",
                (outcome, rel, _utcnow(), slug, project))
        if distil:
            m = self.store_memory(
                content=f"{distil}\n\nDalla scrivania [[{slug}]] ({outcome}).",
                title=row["title"], project=project,
                tags=["scrivania", outcome], category="note")
            memory_id = m["id"]
        self.append_log("desk_close", f"{project}/{slug} → {outcome}")
        return {"slug": slug, "status": outcome, "memory_id": memory_id}
```

`store.py` has **no** timestamp helper — it inlines `datetime.now(timezone.utc).isoformat()` at each site (see `store_memory`, line 157). Add one beside `_slugify` so the methods above resolve:

```python
def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
```

`re`, `datetime` and `timezone` are already imported at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_desk_store.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Run the whole suite**

Run: `venv/bin/python -m pytest -q`
Expected: 195 passed (173 + 12 + 10)

- [ ] **Step 6: Commit**

```bash
git add wadachi/store.py tests/test_desk_store.py
git commit -m "A desk in the store: opened, resumed by a brand-new store, closed without inventing a memory"
```

---

### Task 4: The three MCP tools

**Files:**
- Modify: `wadachi/server.py` (new section before `# ── Il manuale`)
- Test: `tests/test_desk_tools.py`

**Interfaces:**
- Consumes: `store.open_desk / read_desk / list_desks / log_desk / close_desk` (Task 3).
- Produces MCP tools `desk`, `desk_read`, `desk_log`, all in the `work` toolset, returning `json.dumps(..., indent=2)` like every other tool.

- [ ] **Step 1: Write the failing test**

Create `tests/test_desk_tools.py`:

```python
"""I tre strumenti: presenti, descritti per essere scelti, e funzionanti."""

import importlib
import json

import pytest


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_DIR", str(tmp_path / "brain"))
    import wadachi.server as s
    importlib.reload(s)
    return s


def test_the_three_tools_are_in_the_working_menu(srv):
    exposed = set(srv.exposed_tool_names())
    assert {"desk", "desk_read", "desk_log"} <= exposed


def test_the_menu_stays_under_the_threshold(srv):
    assert len(srv.exposed_tool_names()) <= 27


def test_their_first_line_says_when_to_use_them(srv):
    for name in ["desk", "desk_read", "desk_log"]:
        first = (getattr(srv, name).__doc__ or "").strip().split("\n")[0].lower()
        assert any(k in first for k in ("use this", "when ", "before ", "after ")), name


def test_the_round_trip_through_the_tools(srv):
    srv.register_project("p", "", [])
    opened = json.loads(srv.desk(action="open", title="T", objective="O",
                                 done_when="i test passano",
                                 plan=["uno", "due"], project="p"))
    assert opened["slug"]
    assert json.loads(srv.desk_read(slug=opened["slug"], project="p"))["next_step"] == "uno"

    stepped = json.loads(srv.desk_log(slug=opened["slug"], project="p",
                                      done="uno", note="andata"))
    assert stepped["next_step"] == "due"

    closed = json.loads(srv.desk(action="close", slug=opened["slug"],
                                 project="p", outcome="done"))
    assert closed["status"] == "done"
    assert closed["memory_id"] is None


def test_opening_without_a_stopping_condition_is_refused_with_a_sentence(srv):
    out = json.loads(srv.desk(action="open", title="T", objective="O",
                              done_when="", project="p"))
    assert "error" in out and "fatto quando" in out["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_desk_tools.py -q`
Expected: FAIL — `AttributeError: module 'wadachi.server' has no attribute 'desk'`

- [ ] **Step 3: Write minimal implementation**

Insert into `wadachi/server.py`, just before the `# ── Il manuale` section:

```python
# ── La scrivania: lo stato del lavoro in corso ────────────────


@tool()
def desk(action: str, title: str = "", objective: str = "", done_when: str = "",
         plan: list[str] | None = None, slug: str = "", outcome: str = "done",
         distil: str = "", project: str | None = None) -> str:
    """Use this when a piece of work will outlive this conversation: open a desk
    at the start, close it when it lands.

    A desk is the working state a session cannot carry — the plan, what has been
    tried and failed, where the thread was dropped. Memories hold what you
    learned; a desk holds what you are doing.

    Args:
        action: "open", "close" or "list".
        title: open — a short name for the thread of work.
        objective: open — what this work is for.
        done_when: open — how a machine (or you) can tell it is finished.
            Required: without it a desk is a diary, not a desk.
        plan: open — the steps, as a list. Thinking them through now is half the value.
        slug: close — which desk (the id `open` returned).
        outcome: close — "done" or "abandoned". An abandoned desk is often worth
            more than a clean one: it says what does not work.
        distil: close — the lesson worth keeping. Given, it becomes a real
            memory linked to the archived desk; omitted, nothing is stored, and
            that is a fine answer for work that taught nothing.
        project: defaults to the project detected from the working directory.
    """
    project = project or store.detect_project(os.getcwd()) or "global"
    try:
        if action == "open":
            return json.dumps(store.open_desk(title, objective, done_when,
                                              plan or [], project), indent=2)
        if action == "close":
            return json.dumps(store.close_desk(slug, outcome, project,
                                               distil or None), indent=2)
        if action == "list":
            return json.dumps(store.list_desks(project, status=None), indent=2)
        return json.dumps({"error": f"action sconosciuta: {action}"}, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)


@tool()
def desk_read(slug: str = "", project: str | None = None) -> str:
    """Use this when you are picking work back up and need to know where it
    stopped — the plan, the next step, and what was already tried and failed.

    Without a slug it opens the one desk left open in this project; if several
    are open it lists them rather than guessing.
    """
    project = project or store.detect_project(os.getcwd()) or "global"
    got = store.read_desk(slug or None, project)
    if got is None:
        return json.dumps({"desks": store.list_desks(project),
                           "note": "nessuna scrivania aperta qui"}, indent=2)
    return json.dumps(got, indent=2)


@tool()
def desk_log(slug: str = "", done: str = "", note: str = "",
             open_question: str = "", add: list[str] | None = None,
             project: str | None = None) -> str:
    """Use this after every attempt on a desk: tick the step that landed, and
    write down what failed and why.

    The failures are the point — they are what stops the next attempt from
    repeating this one. Returns the next unfinished step, so this is also how
    you ask "what now?".

    Args:
        done: the exact label of the step that is finished.
        note: what happened, especially when it did not work.
        open_question: something unresolved that is not a step.
        add: steps discovered along the way.
    """
    project = project or store.detect_project(os.getcwd()) or "global"
    return json.dumps(store.log_desk(slug or None, project, done or None,
                                     note or None, open_question or None,
                                     add or None), indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_desk_tools.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the whole suite**

Run: `venv/bin/python -m pytest -q`
Expected: 200 passed

- [ ] **Step 6: Commit**

```bash
git add wadachi/server.py tests/test_desk_tools.py
git commit -m "Three tools for a desk, described by the moment you would reach for them"
```

---

### Task 5: `get_context` surfaces the desk

**Files:**
- Modify: `wadachi/server.py` — `_render_context_dense` and `get_context`
- Test: `tests/test_desk_context.py`

**Interfaces:**
- Consumes: `store.read_desk` / `store.list_desks` (Task 3), `_est_tokens(text)` and `_render_context_dense(context, max_tokens)` already in `server.py`.
- Produces: no new public name; the rendered context gains a leading `## 🖿 scrivania aperta` block.

- [ ] **Step 1: Write the failing test**

Create `tests/test_desk_context.py`:

```python
"""get_context e la scrivania: in cima, dentro il budget, e muta se non c'è."""

import importlib

import pytest


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_DIR", str(tmp_path / "brain"))
    import wadachi.server as s
    importlib.reload(s)
    s.store.register_project("p", "", [str(tmp_path)])
    return s


def test_with_no_desk_the_context_does_not_mention_one(srv):
    srv.store.store_memory("qualcosa", "T", project="p")
    out = srv.get_context(cwd="/nessun/percorso", task_description="")
    assert "scrivania" not in out.lower()


def test_an_open_desk_comes_before_the_memories(srv, tmp_path):
    srv.store.store_memory("una memoria", "M", project="p")
    srv.store.open_desk("Il lavoro", "Fare X", "i test passano",
                        ["primo passo"], project="p")
    out = srv.get_context(cwd=str(tmp_path), task_description="")
    assert "scrivania" in out.lower()
    assert out.lower().index("scrivania") < out.index("memorie")
    assert "primo passo" in out


def test_two_open_desks_are_listed_not_chosen(srv, tmp_path):
    srv.store.open_desk("Uno", "O", "d", ["a"], project="p")
    srv.store.open_desk("Due", "O", "d", ["b"], project="p")
    out = srv.get_context(cwd=str(tmp_path), task_description="")
    assert "Uno" in out and "Due" in out


def test_a_tight_budget_keeps_both_the_desk_and_a_memory(srv, tmp_path):
    for i in range(5):
        srv.store.store_memory(f"memoria numero {i}", f"M{i}", project="p")
    srv.store.open_desk("Il lavoro", "x" * 400, "d", ["passo lungo " * 20],
                        project="p")
    out = srv.get_context(cwd=str(tmp_path), task_description="", max_tokens=200)
    assert "scrivania" in out.lower()
    assert "M" in out, "un budget stretto non deve cancellare tutte le memorie"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_desk_context.py -q`
Expected: FAIL — `assert "scrivania" in out.lower()`

- [ ] **Step 3: Write minimal implementation**

In `wadachi/server.py`, add this helper immediately above `_render_context_dense`:

```python
def _desk_block(project: str | None, budget: int) -> str:
    """Il riassunto della scrivania, con un tetto proprio.

    Entra nel bilancio di `get_context` come prima voce ma limitato, così una
    scrivania lunga non svuota la lista delle memorie. Sotto il minimo si
    riduce a titolo e prossimo passo, che è quanto basta per riprendere.
    """
    open_ones = store.list_desks(project=project, status="open")
    if not open_ones:
        return ""
    if len(open_ones) > 1:
        names = " · ".join(f"`{d['slug']}` ({d['title']})" for d in open_ones)
        return f"## 🖿 scrivanie aperte\n{names}\n→ desk_read(slug)\n\n"

    got = store.read_desk(open_ones[0]["slug"], project)
    if not got:
        return ""
    head = (f"## 🖿 scrivania aperta — `{got['slug']}`\n"
            f"**{got['title']}**\n"
            f"Prossimo passo: **{got['next_step'] or '— piano finito, valuta di chiudere'}**\n")
    if _est_tokens(head) > budget:
        return f"## 🖿 `{got['slug']}` — prossimo: {got['next_step'] or 'finito'}\n\n"

    body = ""
    for label, marker in (("Obiettivo", "## Obiettivo"), ("Registro", "## Registro")):
        chunk = got["text"].split(marker)[1].split("\n##")[0].strip() if marker in got["text"] else ""
        first = next((l for l in chunk.split("\n") if l.strip()), "")
        if first and _est_tokens(head + body + first) <= budget:
            body += f"{label}: {first.strip()}\n"
    return head + body + "→ desk_read() per il resto\n\n"
```

Then, inside `_render_context_dense`, prepend the block to the rendered output. Find the line that builds the first `out` string and put the desk block before it, passing `max_tokens // 4` as the desk's own cap. Finally, in `get_context`, pass the detected project through to `_desk_block`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_desk_context.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the whole suite**

Run: `venv/bin/python -m pytest -q`
Expected: 204 passed

- [ ] **Step 6: Commit**

```bash
git add wadachi/server.py tests/test_desk_context.py
git commit -m "Where we were comes before what we know: the desk opens get_context"
```

---

### Task 6: The two end-to-end tests, the docs, and the changelog

**Files:**
- Create: `tests/test_desk_walk.py`
- Modify: `README.md`, `demo/wiki-src/harness.md`, `scripts/build-wiki.py`, `CHANGELOG.md`

**Interfaces:**
- Consumes: everything above. Produces nothing new in code.

- [ ] **Step 1: Write the two tests that check the design, not the code**

Create `tests/test_desk_walk.py`:

```python
"""I due giri che dicono se la scrivania serve a qualcosa."""

import pytest

from wadachi.store import MemoryStore


@pytest.fixture
def s(tmp_path):
    return MemoryStore(str(tmp_path / "brain"))


def test_the_whole_walk_leaves_the_lesson_and_not_the_noise(s, tmp_path):
    d = s.open_desk("Il lavoro", "Fare X", "i test passano",
                    ["primo", "secondo"], project="p")
    s.log_desk(project="p", done="primo", note="zxqrumore effimero di lavorazione")
    s.log_desk(project="p", done="secondo", note="altro zxqrumore")
    s.close_desk(d["slug"], "done", project="p",
                 distil="La lezione: token_path va per provider.")

    fresh = MemoryStore(str(tmp_path / "brain"))
    testi = " ".join(m["title"] + m.get("content", "") for m in fresh.list_memories())
    assert "token_path" in " ".join(
        fresh.get_memory(m["id"])["content"] for m in fresh.list_memories())
    assert "zxqrumore" not in testi


def test_the_cap_is_reached_and_said(s):
    """Il caso di Rizzo: dieci tentativi, e il decimo lo dice."""
    d = s.open_desk("Ottimizzare", "Ridurre il tempo", "sotto i 2 secondi",
                    [f"tentativo {i}" for i in range(1, 11)], project="p")
    for i in range(1, 11):
        out = s.log_desk(project="p", done=f"tentativo {i}",
                         note=f"provato {i}: ancora lento")
    assert out["next_step"] is None, "il piano è finito: non si inventa un undicesimo"
    got = s.read_desk(d["slug"], project="p")
    assert got["text"].count("provato") == 10
```

- [ ] **Step 2: Run them**

Run: `venv/bin/python -m pytest tests/test_desk_walk.py -q`
Expected: PASS (2 passed)

- [ ] **Step 3: Document it where a reader lands**

In `README.md`, in the section `## Where Wadachi sits: the harness`, replace the desk bullet's `**On the roadmap** — today that state is either lost to compaction or written out by hand as a handover note.` with:

```markdown
  **Built.** `desk` opens one, `desk_log` records each attempt — especially the
  failures — and `desk_read` (or `get_context`, which surfaces it automatically)
  picks the work back up in a session that knows nothing.
```

In `README.md` `## Roadmap`, delete the three-line `**The desk**` item — it has shipped.

In `demo/wiki-src/harness.md`, replace the `### The desk — not built yet` section body with a description of the three tools and the file layout, and change its heading to `### The desk — built`. Update the table row `| **The desk** | what you are *doing* | the end of a **context window** | on the roadmap |` to `| built |`.

- [ ] **Step 4: Rebuild the wiki and check the links**

Run: `venv/bin/python scripts/build-wiki.py`
Expected: `✓ 21 pagine wiki generate`

Run: `grep -o '\[\[[^]]*\]\]' demo/wiki/*.html | grep -v '#'`
Expected: no unresolved wikilinks other than the sample `[[#42]]` style ids.

- [ ] **Step 5: Changelog**

Add under `## [Unreleased]` in `CHANGELOG.md`, in the changelog's voice: an `### Added — la scrivania` section stating the problem (memory #222 was fifteen hundred words of handover typed by hand), the shape (a markdown progress record per thread of work, three tools, `get_context` surfacing it), and the boundary (a desk never enters recall; closing creates at most one memory, written by whoever did the work).

- [ ] **Step 6: Run everything and commit**

```bash
venv/bin/python -m pytest -q          # expected: 206 passed
git add -A
git commit -m "The desk, walked end to end: the lesson is kept and the noise is not"
```

---

## Self-Review

**Spec coverage** — §1 the file → Task 2 · §2 the three tools → Task 4 · §3 `get_context` → Task 5 · §4 concurrency → Task 3 (`test_two_notes_do_not_overwrite_each_other`) · §5 closing → Task 3 (three closing tests) · §6 promises → Tasks 2-6, each named · migration → Task 1 · the four cracks → Task 2 (fence, empty slug, collision) and Task 5 (budget).

**Placeholders** — none: every step carries the code or the exact text. Task 3 step 3 names one thing to check in the file (`_utcnow()`), which is a lookup, not a decision. Task 6 step 3 describes documentation prose rather than quoting it, because it must match surrounding copy the writer will be reading.

**Type consistency** — `next_step` returns `str | None` in Task 2 and is consumed as such in Tasks 3-5. `tick_step` returns `(str, bool)` everywhere. `log_desk` returns `next_step` / `already_done` / `slug`, matching the tool tests. `close_desk` returns `memory_id`, asserted `None` without a distillate in both Task 3 and Task 4.
