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

Prima del peso guarda il tempo. Il contesto resta nella cache dei prompt per
un'ora (o cinque minuti) dall'ultimo turno: il primo messaggio dopo la
scadenza lo riscrive tutto, e a 132k costa quanto venti turni normali. In quel
caso l'hook **blocca il messaggio una volta**, dice a Elia quanto costerebbe e
com'è messa la scrivania, e lascia passare il secondo invio. Un messaggio
bloccato non arriva al modello: il blocco costa zero.

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
from datetime import datetime, timezone
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

# Il prezzo di un token in ingresso, in multipli dell'input base. Fonte: la
# tabella di https://docs.claude.com/en/docs/build-with-claude/prompt-caching
# (rilettura 0,1×; scrittura con durata 5 min 1,25×; con durata 1 h 2×).
# Sull'abbonamento i limiti non sono pubblicati al token, ma seguono lo stesso
# principio: servono a dire «quanti turni vale», non a fare una fattura.
_CACHE_READ = 0.1
_CACHE_WRITE = {300: 1.25, 3600: 2.0}

# Quanto dura la cache quando il transcript non lo dice.
_DEFAULT_TTL = 3600

# Sotto questo contesto un turno a cache fredda non vale un blocco.
_GUARD_MIN = 40_000


def _read_hook_input() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _when(rec: dict) -> datetime | None:
    """Il `timestamp` di un record, o None se manca o non si legge."""
    try:
        t = datetime.fromisoformat(str(rec["timestamp"]).replace("Z", "+00:00"))
    except Exception:
        return None
    return t if t.tzinfo else None


def _is_prompt(rec: dict) -> bool:
    """Un messaggio di Elia, non un tool_result né un record meta.

    Anche i tool_result sono record `user`: contarli come inizio del turno lo
    sposterebbe a metà turno, dopo il desk_log che il turno stesso ha fatto.
    """
    if rec.get("type") != "user" or rec.get("isMeta"):
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return isinstance(content, str)


def _ttl_of(usage: dict) -> int | None:
    """La durata con cui questo turno ha scritto in cache, se l'ha detta."""
    split = usage.get("cache_creation")
    if not isinstance(split, dict):
        return None
    if int(split.get("ephemeral_1h_input_tokens") or 0) > 0:
        return 3600
    if int(split.get("ephemeral_5m_input_tokens") or 0) > 0:
        return 300
    return None


def _scan(transcript: Path) -> dict:
    """Quello che serve sapere della sessione, in un solo passaggio.

    - `usage` e `model`: l'ultimo turno dell'assistente, cioè lo stato attuale
      del contesto;
    - `reply_at`: quando è finito, cioè da quando corre la cache;
    - `turn_at`: quando è cominciato l'ultimo turno (l'ultimo prompt di Elia);
    - `ttl`: la durata dell'ultima scrittura in cache che l'ha dichiarata.

    I record dei subagenti (`isSidechain`) si saltano: hanno un contesto e una
    cache loro. Una riga illeggibile si salta — un transcript in scrittura può
    avere l'ultima riga a metà.
    """
    out: dict = {"usage": None, "model": "", "reply_at": None, "turn_at": None, "ttl": None}
    try:
        with transcript.open(errors="ignore") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict) or rec.get("isSidechain"):
                    continue
                if _is_prompt(rec):
                    out["turn_at"] = _when(rec)
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage")
                if isinstance(u, dict):
                    out["usage"] = u
                    out["model"] = msg.get("model") or out["model"]
                    out["reply_at"] = _when(rec)
                    out["ttl"] = _ttl_of(u) or out["ttl"]
    except Exception:
        return {"usage": None, "model": "", "reply_at": None, "turn_at": None, "ttl": None}
    return out


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


def _message(band: str, ctx: int, window: int, pct: float, ttl: int) -> str:
    """L'avviso, con i conti fatti come li fa la cache.

    A cache calda un turno rilegge il contesto a 0,1×: continuare è economico.
    Lo spreco vero è il turno dopo una pausa oltre la durata della cache, che
    riscrive tutto a 1,25× o 2×. I numeri sono token equivalenti all'input
    base, arrotondati: dicono l'ordine di grandezza, non la fattura.
    """
    k = f"{ctx // 1000}k/{window // 1000}k"
    warm = int(ctx * _CACHE_READ) // 1000
    cold = int(ctx * _CACHE_WRITE.get(ttl, _CACHE_WRITE[_DEFAULT_TTL])) // 1000
    pause = _span(ttl)
    costs = (f"A cache calda un turno costa ≈{warm}k token equivalenti; dopo una pausa "
             f"oltre {pause} il primo turno riscrive tutto in cache, ≈{cold}k.")
    if band == "notice":
        return f"Peso sessione: {pct:.0f}% ({k}). {costs} Niente da fare ora."
    if band == "warn":
        return (
            f"Peso sessione: {pct:.0f}% ({k}). {costs} Ripartire costa "
            f"~{_RESTART_COST // 1000}k una volta: mentre si lavora senza pause continuare "
            f"conviene, il rischio è la pausa. Prima di una pausa, o se resta molto lavoro: "
            f"aggiorna la scrivania con desk_log e proponi a Elia /clear — la sessione "
            f"nuova riprende dalla scrivania (desk_read)."
        )
    return (
        f"Peso sessione: {pct:.0f}% ({k}). {costs} La compattazione automatica è "
        f"vicina: rilegge tutto, riassume e perde dettaglio che la scrivania invece "
        f"tiene. Distilla ora: desk_log con quello che manca, poi proponi a Elia /clear "
        f"— la sessione nuova riprende dalla scrivania (desk_read)."
    )


def _env_int(name: str, default: int | None) -> int | None:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _ttl(seen: dict) -> int:
    """La durata della cache: l'ambiente vince, poi il transcript, poi l'ora."""
    return _env_int("WADACHI_CACHE_TTL", None) or seen["ttl"] or _DEFAULT_TTL


def _span(seconds: float) -> str:
    """`1 h 14 min`, o `14 min` sotto l'ora."""
    m = int(seconds // 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def _desk_state(cwd: str, turn_at: datetime | None) -> str:
    """Com'è messa la scrivania del progetto, in una frase. Vuota se non si sa.

    Il brain si apre con `create=False`: con l'SSD scollegato `BRAIN_DIR` punta
    a un percorso che non c'è, e crearlo inventerebbe un brain vuoto. Senza
    `BRAIN_DIR` non si cade sul default (`~/.engram` è il brain vecchio): si tace.

    «Aggiornata» si confronta con l'*inizio* dell'ultimo turno, non con la sua
    fine: il desk_log avviene dentro il turno, quindi precede sempre l'ultima
    risposta.
    """
    brain = os.environ.get("BRAIN_DIR")
    if not brain or not cwd:
        return ""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from wadachi.store import MemoryStore

        store = MemoryStore(brain, create=False)
        project = store.detect_project(cwd)
        if not project:
            return ""
        desks = store.list_desks(project=project, status="open")
    except Exception:
        return ""

    if not desks:
        return "Nessuna scrivania aperta: dopo /clear il filo andrebbe ricostruito."

    # list_desks ordina per updated_at decrescente: la prima è la più recente.
    d = desks[0]
    head = f"{len(desks)} scrivanie aperte; la più recente, `{d['slug']}`," if len(desks) > 1 \
        else f"Scrivania `{d['slug']}`"
    try:
        updated = datetime.fromisoformat(d["updated_at"])
        at = updated.astimezone().strftime("%H:%M")
    except Exception:
        return f"{head}: data di aggiornamento illeggibile."
    if turn_at is None or updated >= turn_at:
        return f"{head} aggiornata alle {at}, durante l'ultimo turno → /clear riparte da lì."
    return (f"{head} ferma alle {at}, da prima dell'ultimo turno: /clear perderebbe "
            f"quel turno, valuta prima di farlo.")


def _cold_guard(data: dict, seen: dict, ctx: int) -> str | None:
    """Il motivo per bloccare questo messaggio, o None per lasciarlo passare.

    Blocca solo se la cache è scaduta **e** il contesto è grande, e una volta
    sola per pausa: il marker è legato all'ultima risposta, quindi il secondo
    invio passa e una pausa dopo un turno nuovo è un'altra pausa. Senza
    `session_id` non c'è dove ricordarselo e si bloccherebbe per sempre: meglio
    un turno freddo che un messaggio che non passa mai.
    """
    if os.environ.get("WADACHI_CACHE_GUARD", "").lower() == "off":
        return None
    reply_at = seen["reply_at"]
    session_id = str(data.get("session_id") or "")
    if reply_at is None or not session_id:
        return None
    if ctx < (_env_int("WADACHI_GUARD_MIN", _GUARD_MIN) or 0):
        return None

    ttl = _ttl(seen)
    expired = (datetime.now(timezone.utc) - reply_at).total_seconds() - ttl
    if expired <= 0:
        return None
    if _already_said(session_id, "cold-" + re.sub(r"\D", "", reply_at.isoformat())):
        return None

    turns = _CACHE_WRITE.get(ttl, _CACHE_WRITE[_DEFAULT_TTL]) / _CACHE_READ
    parts = [
        f"Cache scaduta da {_span(expired)}: questo messaggio riscriverebbe in cache "
        f"{ctx // 1000}k token (≈ {turns:.0f} turni a cache calda).",
        _desk_state(str(data.get("cwd") or ""), seen["turn_at"]),
        "Il messaggio non è stato inviato: per proseguire comunque, rimandalo.",
    ]
    return " ".join(p for p in parts if p)


def main() -> int:
    data = _read_hook_input()
    tp = data.get("transcript_path")
    if not tp:
        return 0
    transcript = Path(tp).expanduser()
    if not transcript.is_file():
        return 0

    seen = _scan(transcript)
    usage, model = seen["usage"], seen["model"]
    if not usage:
        return 0

    ctx = _context_size(usage)
    if ctx <= 0:
        return 0

    try:
        reason = _cold_guard(data, seen, ctx)
    except Exception:
        reason = None  # la guardia non deve mai rompere un turno
    if reason:
        json.dump({"decision": "block", "reason": reason}, sys.stdout)
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
                "additionalContext": _message(band, ctx, window, pct, _ttl(seen)),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
