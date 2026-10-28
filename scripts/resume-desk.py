#!/usr/bin/env python3
"""
resume-desk.py — dopo /clear, la sessione nuova sa già dov'era il lavoro.

`/clear` è il modo più economico di alleggerire una sessione, ma solo se quella
nuova riparte dal punto giusto. Questo script, agganciato a `SessionStart`
(`startup` e `clear`), legge le scrivanie aperte del progetto e le inietta nel
contesto: niente get_context né desk_read a mano, e nessun rischio che il
modello se ne dimentichi.

- **una scrivania aperta:** titolo, obiettivo, «fatto quando», il prossimo
  passo, le ultime due voci del registro e la sezione «Aperto»;
- **più scrivanie:** per ognuna slug e prossimo passo, senza sceglierne una;
- **nessuna:** silenzio.

Il progetto si rileva con la logica del server (`MemoryStore.detect_project`,
importata, non riscritta). Il brain è quello di `BRAIN_DIR`, aperto con
`create=False`: senza `BRAIN_DIR` non si cade sul default, e con l'SSD
scollegato non si inventa un brain vuoto.

Qualunque errore è un non-evento: esce 0 e muto. Una ripresa mancata costa un
desk_read; una sessione che non parte costa molto di più.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Il tetto del testo iniettato, in token stimati (~4 caratteri l'uno, come
# `_est_tokens` del server). Entra in ogni sessione nuova: deve restare piccolo.
_CAP_TOKENS = 1_200

# Le fonti di SessionStart su cui si parla. Su `resume` il contesto c'è già.
_SOURCES = {"startup", "clear"}


def _clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _entries(section: str, n: int) -> list[str]:
    """Le prime `n` voci del registro, che ha in cima la più recente.

    Una voce comincia con `- **quando** —` (`desk.add_log`); un `- ` qualunque
    può stare dentro una nota che elenca qualcosa, e non apre una voce nuova.
    """
    out: list[str] = []
    for line in section.split("\n"):
        if line.startswith("- **"):
            out.append(line[2:])
        elif out and line.strip():
            out[-1] += " " + line.strip()  # una voce che va a capo
    return out[:n]


def _one(got: dict, project: str) -> str:
    from wadachi import desk as D

    text = got["text"]
    objective = "\n".join(
        l for l in D.section_text(text, D.OBJECTIVE).split("\n")
        if not l.startswith("**Fatto quando:**")
    )
    step = got.get("next_step") or "— piano finito, valuta di chiudere la scrivania"
    lines = [
        f"## Scrivania aperta — `{got['slug']}` (progetto `{project}`)",
        f"**{_clip(got['title'], 120)}**",
        f"Obiettivo: {_clip(objective, 500)}",
        f"Fatto quando: {_clip(D.done_when(text) or '—', 400)}",
        f"Prossimo passo: **{_clip(step, 200)}**",
    ]
    log = _entries(D.section_text(text, D.LOG), 2)
    if log:
        lines.append("Registro, ultime voci:")
        lines += [f"- {_clip(e, 700)}" for e in log]
    opened = D.section_text(text, D.OPEN)
    if opened:
        lines.append(f"Aperto: {_clip(opened, 500)}")
    return "\n".join(lines)


def _many(found: list[dict], project: str) -> str:
    lines = [f"## {len(found)} scrivanie aperte (progetto `{project}`)"]
    for got in found:
        step = got.get("next_step") or "piano finito"
        lines.append(f"- `{got['slug']}` — prossimo: {_clip(step, 120)}")
    lines.append("Non sceglierne una da solo: chiedi a Elia quale riprendere.")
    return "\n".join(lines)


def _cap(text: str, footer: str) -> str:
    """Taglia il corpo, mai il piede: lo slug per desk_read sta in testa e il
    modo di riprendere in fondo, ed entrambi devono arrivare interi."""
    room = _CAP_TOKENS * 4 - len(footer) - 2
    if len(text) > room:
        text = text[: max(room - 1, 0)].rstrip() + "…"
    return f"{text}\n\n{footer}"


def build(cwd: str, brain: str) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from wadachi.store import MemoryStore

    store = MemoryStore(brain, create=False)
    project = store.detect_project(cwd)
    if not project:
        return ""
    found = []
    for d in store.list_desks(project=project, status="open"):
        got = store.read_desk(d["slug"], project)
        if got and not got.get("missing_file") and "text" in got:
            found.append(got)
    if not found:
        return ""
    if len(found) == 1:
        slug = found[0]["slug"]
        body = _one(found[0], project)
        footer = (f"Iniettata all'avvio da resume-desk: è dove si era fermato il lavoro, "
                  f"non un ordine di riprenderlo. Testo completo: "
                  f"desk_read(slug=\"{slug}\", cwd=\"{cwd}\").")
    else:
        body = _many(found, project)
        footer = "Iniettate all'avvio da resume-desk. Testo completo: desk_read(slug=…, cwd=…)."
    return _cap(body, footer)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict) or data.get("source") not in _SOURCES:
        return 0
    cwd = str(data.get("cwd") or "")
    brain = os.environ.get("BRAIN_DIR")
    if not cwd or not brain:
        return 0
    try:
        text = build(cwd, brain)
    except Exception:
        return 0
    if not text:
        return 0
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": text,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
