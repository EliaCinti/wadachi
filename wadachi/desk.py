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
OBJECTIVE = "## Obiettivo"

_STEP = re.compile(r"^- \[( |x)\] (.+)$")
_FENCE = re.compile(r"^\s*```")
_DONE_WHEN = re.compile(r"^\*\*Fatto quando:\*\*\s*(.+)$")


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


def set_meta(text: str, key: str, value: str) -> str:
    """Aggiorna una chiave del frontmatter sul posto.

    Cerca solo fra le due righe `---` iniziali — mai nel corpo, dove una nota
    o una riga di registro potrebbe iniziare per caso con `chiave: `. Una
    chiave assente lascia il testo invariato; il valore è inserito così
    com'è, senza passare da una sostituzione con espressioni regolari (che
    interpreterebbe `\\1`, `\\g<0>` eccetera dentro il valore)."""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return text
    try:
        end = lines.index("---", 1)
    except ValueError:
        return text
    prefix = f"{key}: "
    for i in range(1, end):
        if lines[i].startswith(prefix):
            lines[i] = f"{key}: {value}"
            return "\n".join(lines)
    return text


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


def section_text(text: str, heading: str) -> str:
    """Il corpo di una sezione, spogliato agli estremi.

    Stringa vuota se la sezione non c'è. Il confine è una riga che inizia
    per `## ` (via `_section`), non una sottostringa `\\n##` che potrebbe
    comparire dentro il corpo — quella troncherebbe un registro che contiene
    letteralmente `\\n##` da qualche parte, un caso reale trovato provando
    il progetto."""
    start, end = _section(text, heading)
    if start < 0:
        return ""
    return "\n".join(text.split("\n")[start:end]).strip()


def done_when(text: str) -> str | None:
    """La condizione d'arresto dichiarata in `## Obiettivo`, o None se manca
    o il file non la scrive nella forma attesa."""
    for line in section_text(text, OBJECTIVE).split("\n"):
        m = _DONE_WHEN.match(line.strip())
        if m:
            return m.group(1).strip()
    return None


def tick_step(text: str, label: str) -> tuple[str, str]:
    """Spunta un passo. Restituisce `(testo, esito)`.

    `esito` è uno tra `"ticked"` (spuntato ora), `"already"` (era già
    spuntato, testo invariato) o `"not_found"` (nessuna etichetta corrisponde,
    testo invariato) — un'etichetta sbagliata non deve avere la stessa forma
    di un successo, altrimenti chi chiama non si accorge mai del typo.
    L'etichetta del chiamante è spogliata prima del confronto, come lo è
    già quella letta dal file."""
    label = (label or "").strip()
    start, end = _section(text, PLAN)
    if start < 0:
        return (text, "not_found")
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
                return (text, "already")
            lines[i] = f"- [x] {label}"
            return ("\n".join(lines), "ticked")
    return (text, "not_found")


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
    if not labels:
        return text
    start, end = _section(text, PLAN)
    if start < 0:
        return text.rstrip("\n") + f"\n\n{PLAN}\n" + "\n".join(f"- [ ] {l}" for l in labels) + "\n"
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
