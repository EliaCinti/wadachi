#!/usr/bin/env python3
"""
session-weight.py — quanto pesa questa sessione, e se conviene ancora continuarla.

Una chat lunga si ripaga a ogni turno: il contesto intero viene rifatturato a
ogni messaggio. Sotto una certa soglia non importa; sopra, distillare nella
scrivania e ripartire costa meno che tirare avanti.

Questo script è la misura, non la decisione. Legge il transcript che Claude Code
sta già scrivendo, somma il contesto dell'ultimo turno e — solo se si è passata
una soglia — stampa un JSON che l'hook `UserPromptSubmit` inietta nel contesto
del modello.

Sotto soglia non stampa niente ed esce 0: il silenzio costa zero token.

Nessuna misura possibile (transcript assente, vuoto, malformato, senza `usage`)
è un non-evento, non un errore: esce 0 e muto. Un avviso sul peso della sessione
non vale il rischio di rompere il turno.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Finestre note. `[1m]` nel nome del modello vince su tutto.
_DEFAULT_WINDOW = 200_000
_MILLION_WINDOW = 1_000_000

# Soglie in percentuale, sovrascrivibili senza toccare il codice.
_BANDS = (
    ("urge", int(os.environ.get("WADACHI_WEIGHT_URGE", "90"))),
    ("warn", int(os.environ.get("WADACHI_WEIGHT_WARN", "75"))),
    ("notice", int(os.environ.get("WADACHI_WEIGHT_NOTICE", "50"))),
)

# Quanto costa ripartire: distillazione + get_context + desk_read della
# sessione nuova. Serve solo a dire "conviene" con un numero, non a decidere.
_RESTART_COST = 20_000


def _read_hook_input() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _last_usage_and_model(transcript: Path) -> tuple[dict | None, str]:
    """L'ultimo `usage` scritto e il modello che l'ha prodotto.

    Si scorre tutto il file tenendo solo l'ultimo: i record sono append-only e
    l'ultimo è lo stato attuale del contesto. Una riga illeggibile si salta —
    un transcript in scrittura può avere l'ultima riga a metà.
    """
    usage: dict | None = None
    model = ""
    try:
        with transcript.open(errors="ignore") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage")
                if isinstance(u, dict):
                    usage = u
                    model = msg.get("model") or model
    except Exception:
        return None, ""
    return usage, model


def _context_size(usage: dict) -> int:
    """Il contesto che il prossimo turno rifatturerà.

    Sono i token in ingresso: quelli nuovi, quelli riletti dalla cache e quelli
    appena messi in cache. L'output non conta — è già uscito.
    """
    return sum(
        int(usage.get(k) or 0)
        for k in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    )


def _window_for(model: str, ctx: int) -> int:
    """La finestra di questa sessione.

    Il transcript **non** dice quale sia: registra `claude-opus-5` anche quando
    la sessione gira sulla variante `[1m]` (misurato, non dedotto). Quindi la si
    ricava dall'unica prova disponibile — il contesto stesso: un contesto che ha
    superato i 200k dimostra che la finestra è quella grande, perché una sessione
    non può eccedere la propria finestra.

    Resta il controllo sul nome per il giorno in cui il transcript lo dirà.
    """
    override = os.environ.get("WADACHI_CONTEXT_WINDOW")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    if re.search(r"\[1m\]|-1m\b", model or ""):
        return _MILLION_WINDOW
    if ctx > _DEFAULT_WINDOW:
        return _MILLION_WINDOW
    return _DEFAULT_WINDOW


def _band(pct: float) -> str | None:
    for name, floor in _BANDS:
        if pct >= floor:
            return name
    return None


def _already_said(session_id: str, band: str) -> bool:
    """Un invito detto una volta è un consiglio; ripetuto a ogni turno è rumore.

    Lo stato vive in un file temporaneo per sessione: non deve sopravvivere alla
    sessione, e se sparisce il peggio che succede è un avviso in più.
    """
    if not session_id:
        return False
    marker = Path(tempfile.gettempdir()) / "wadachi-session-weight" / f"{session_id}.{band}"
    if marker.exists():
        return True
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except Exception:
        pass  # senza stato si dirà di nuovo: fastidioso, non rotto
    return False


def _message(band: str, ctx: int, window: int, pct: float) -> str:
    k = f"{ctx // 1000}k/{window // 1000}k"
    if band == "notice":
        return (
            f"Peso sessione: {pct:.0f}% ({k}). Da qui in poi ogni turno "
            f"rifattura questo contesto — tienilo presente, non c'è niente da fare ora."
        )
    saving = ctx - _RESTART_COST
    if band == "warn":
        return (
            f"Peso sessione: {pct:.0f}% ({k}). Continuare costa ~{ctx // 1000}k a turno; "
            f"ripartire ne costa ~{_RESTART_COST // 1000}k una volta sola "
            f"(~{saving // 1000}k risparmiati per turno). Se resta più di qualche turno di "
            f"lavoro: aggiorna la scrivania con desk_log, poi proponi a Elia una sessione "
            f"nuova che riprenda con desk_read. Se manca poco, finisci e basta."
        )
    return (
        f"Peso sessione: {pct:.0f}% ({k}) — la compattazione automatica è vicina, e "
        f"compattare perde dettaglio che la scrivania invece tiene. Distilla ora: "
        f"desk_log con quello che manca, poi proponi a Elia di riprendere in una "
        f"sessione nuova con desk_read."
    )


def main() -> int:
    data = _read_hook_input()
    tp = data.get("transcript_path")
    if not tp:
        return 0
    transcript = Path(tp).expanduser()
    if not transcript.is_file():
        return 0

    usage, model = _last_usage_and_model(transcript)
    if not usage:
        return 0

    ctx = _context_size(usage)
    if ctx <= 0:
        return 0

    window = _window_for(model, ctx)
    pct = ctx * 100.0 / window

    band = _band(pct)
    if band is None:
        return 0

    session_id = str(data.get("session_id") or "")
    if _already_said(session_id, band):
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _message(band, ctx, window, pct),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
