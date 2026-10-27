#!/bin/bash
# statusline.sh — il peso della sessione, sempre sott'occhio.
#
# Claude Code passa su stdin un JSON con `context_window_size`, `current_usage`
# e `used_percentage`. Qui non si decide niente: si mostra. La decisione la
# prende Elia, eventualmente spinto dall'hook session-weight.py.
#
# Accanto al peso, il tempo: `cache 42m` è quanto resta prima che il prossimo
# turno riscriva tutto il contesto in cache, `cache fredda` che è già scaduta.
#
# Muto su ciò che non sa: un campo mancante sparisce dalla riga invece di
# stampare "null" o zero.

input=$(cat)

printf '%s' "$input" | /usr/bin/python3 -c '
import json, os, sys

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

parts = []

model = (d.get("model") or {}).get("display_name")
if model:
    parts.append(model)

cwd = (d.get("workspace") or {}).get("current_dir") or d.get("cwd")
if cwd:
    parts.append(os.path.basename(cwd.rstrip("/")))

branch = (d.get("workspace") or {}).get("git_branch") or d.get("git_branch")
if branch:
    parts.append(f"⎇ {branch}")

# Il peso: la percentuale se la CLI la dà, altrimenti calcolata dai due numeri.
usage = d.get("current_usage") or {}
pct = d.get("used_percentage") or usage.get("used_percentage")
window = d.get("context_window_size") or usage.get("context_window_size")
used = usage.get("total_input_tokens") or usage.get("input_tokens")

if pct is None and window and used:
    pct = float(used) * 100.0 / float(window)

if pct is not None:
    pct = float(pct)
    # Verde sotto 50, giallo fino a 75, rosso oltre: le stesse soglie dell hook.
    color = "32" if pct < 50 else ("33" if pct < 75 else "31")
    label = f"{pct:.0f}%"
    if window:
        label += f" di {int(window)//1000}k"
    parts.append(f"\033[{color}mctx {label}\033[0m")


# La cache: quanti minuti restano prima che il prossimo turno riscriva tutto
# il contesto (vedi la guardia in session-weight.py). La statusline si
# ridisegna spesso, quindi legge solo la coda del transcript; se lultimo turno
# non sta nella coda piccola si prova una coda grande, poi si rinuncia.
def cache_left(path):
    import math
    from datetime import datetime, timezone
    try:
        size = os.path.getsize(path)
    except (OSError, TypeError):
        return None
    when = ttl = None
    for tail in (512 * 1024, 8 * 1024 * 1024):
        with open(path, "rb") as fh:
            fh.seek(max(size - tail, 0))
            rows = fh.read().decode("utf-8", "ignore").split("\n")
        if size > tail:
            rows = rows[1:]  # la prima riga della coda e tagliata a meta
        for raw in reversed(rows):
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            if not isinstance(rec, dict) or rec.get("isSidechain"):
                continue
            msg = rec.get("message")
            u = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(u, dict):
                continue
            if when is None:
                try:
                    when = datetime.fromisoformat(str(rec.get("timestamp")).replace("Z", "+00:00"))
                except Exception:
                    return None
            split = u.get("cache_creation") or {}
            if (split.get("ephemeral_1h_input_tokens") or 0) > 0:
                ttl = 3600
            elif (split.get("ephemeral_5m_input_tokens") or 0) > 0:
                ttl = 300
            if ttl:
                break
        if when is not None or size <= tail:
            break
    if when is None or when.tzinfo is None:
        return None
    try:
        ttl = int(os.environ["WADACHI_CACHE_TTL"])
    except (KeyError, ValueError):
        ttl = ttl or 3600
    left = ttl - (datetime.now(timezone.utc) - when).total_seconds()
    return math.ceil(left / 60) if left > 0 else 0


try:
    left = cache_left(d.get("transcript_path"))
except Exception:
    left = None
if left == 0:
    parts.append("\033[31mcache fredda\033[0m")
elif left is not None:
    color = "32" if left > 15 else "33"
    parts.append(f"\033[{color}mcache {left}m\033[0m")

# La quota del piano. Esiste SOLO sull abbonamento: con ANTHROPIC_API_KEY
# impostata la CLI non la riporta (rate_limits_available: false), perche la
# chiave scavalca il piano. Se manca, la riga semplicemente non la mostra.
limits = d.get("rate_limits") or {}
for chiave, etichetta in (("five_hour", "5h"), ("seven_day", "7g")):
    w = limits.get(chiave) or {}
    u = w.get("used_percentage")
    if u is None:
        continue
    u = float(u)
    color = "32" if u < 50 else ("33" if u < 80 else "31")
    parts.append(f"\033[{color}m{etichetta} {u:.0f}%\033[0m")

cost = (d.get("cost") or {}).get("total_cost_usd")
if cost:
    parts.append(f"${float(cost):.2f}")

if parts:
    print("  ".join(parts))
'
