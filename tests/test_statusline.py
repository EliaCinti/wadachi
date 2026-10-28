"""La statusline: quanto resta alla cache, sempre sott'occhio e a costo zero.

La guardia ferma il messaggio dopo la pausa; la statusline serve a non
arrivarci. `cache 42m` dice quanto manca prima che il prossimo turno riscriva
tutto, `cache fredda` che è già successo. È passiva: nessun token speso.

La statusline si ridisegna spesso, quindi legge solo la coda del transcript:
il test con un transcript grosso controlla che la coda basti.
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path

from _transcript import NOW, prompt, reply, write

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "statusline.sh"


def line(payload: dict, env: dict | None = None) -> str:
    base = {"PATH": "/usr/bin:/bin"}
    base.update(env or {})
    p = subprocess.run(["bash", str(SCRIPT)], input=json.dumps(payload),
                       capture_output=True, text=True, env=base)
    assert p.returncode == 0, p.stderr
    return re.sub(r"\033\[[0-9;]*m", "", p.stdout)  # senza colori


def session(tmp_path: Path, ago: timedelta, *, ttl: str = "1h", extra: list | None = None) -> dict:
    sid, cwd = str(uuid.uuid4()), str(tmp_path)
    end = NOW - ago
    recs = [prompt(sid, cwd, end - timedelta(minutes=1)), reply(sid, cwd, end, 90_000, ttl=ttl)]
    tp = write(tmp_path, (extra or []) + recs)
    return {"session_id": sid, "transcript_path": tp, "cwd": cwd,
            "model": {"display_name": "Opus"}}


def test_minuti_residui(tmp_path):
    assert "cache 42m" in line(session(tmp_path, timedelta(minutes=18)))


def test_cache_fredda(tmp_path):
    out = line(session(tmp_path, timedelta(hours=2)))
    assert "cache fredda" in out and "cache 0m" not in out


def test_la_durata_si_legge_dal_transcript(tmp_path):
    assert "cache 3m" in line(session(tmp_path, timedelta(minutes=2), ttl="5m"))


def test_la_durata_da_ambiente_vince(tmp_path):
    out = line(session(tmp_path, timedelta(minutes=18)), env={"WADACHI_CACHE_TTL": "1800"})
    assert "cache 12m" in out


def test_i_subagenti_non_contano(tmp_path):
    p = session(tmp_path, timedelta(hours=2))
    with open(p["transcript_path"], "a") as fh:
        fh.write(json.dumps(reply(p["session_id"], p["cwd"], NOW, 90_000, sidechain=True)) + "\n")
    assert "cache fredda" in line(p)


def test_basta_la_coda_di_un_transcript_grosso(tmp_path):
    """Qualche MB di storia prima dell'ultimo turno: la riga arriva lo stesso."""
    sid = str(uuid.uuid4())
    vecchi = [prompt(sid, str(tmp_path), NOW - timedelta(days=1), text="x" * 20_000)
              for _ in range(200)]
    p = session(tmp_path, timedelta(minutes=18), extra=vecchi)
    assert Path(p["transcript_path"]).stat().st_size > 3_000_000
    assert "cache 42m" in line(p)


def test_senza_transcript_niente_cache(tmp_path):
    out = line({"model": {"display_name": "Opus"}})
    assert "Opus" in out and "cache" not in out


def test_transcript_senza_turni_niente_cache(tmp_path):
    f = tmp_path / "vuoto.jsonl"
    f.write_text("non json\n")
    out = line({"transcript_path": str(f), "model": {"display_name": "Opus"}})
    assert "Opus" in out and "cache" not in out
