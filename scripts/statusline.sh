#!/bin/bash
# statusline.sh — il peso della sessione, sempre sott'occhio.
#
# Claude Code passa su stdin un JSON con `context_window_size`, `current_usage`
# e `used_percentage`. Qui non si decide niente: si mostra. La decisione la
# prende Elia, eventualmente spinto dall'hook session-weight.py.
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

cost = (d.get("cost") or {}).get("total_cost_usd")
if cost:
    parts.append(f"${float(cost):.2f}")

if parts:
    print("  ".join(parts))
'
