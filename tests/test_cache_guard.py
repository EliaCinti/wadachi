"""La guardia della cache fredda: un messaggio dopo la pausa costa venti turni.

Il contesto resta nella cache dei prompt per un tempo fisso dall'ultimo turno
(un'ora, o cinque minuti). Il primo messaggio dopo la scadenza riscrive in
cache tutto il contesto: a 132k sono ~264k token equivalenti, quanto una
ventina di turni normali. La guardia lo ferma **una volta**, dice quanto
costerebbe e com'è messa la scrivania, e lascia passare il secondo invio.

I record del transcript hanno la **forma reale**: stanno in `_transcript.py`,
condivisi con i test della statusline, e lì è spiegato perché.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from _transcript import NOW, meta, reply, turn, write

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "session-weight.py"


# ── il brain con la scrivania, scritto dal vero MemoryStore ─────────────────


def brain_with_desk(tmp_path: Path, cwd: Path, updated: datetime | None,
                    *, extra: int = 0) -> Path:
    """Un brain con il progetto registrato su `cwd` e una scrivania aperta.

    La scrivania la apre `open_desk`, quindi il file e la riga nell'indice sono
    quelli che il server scrive. Poi la si data a `updated`, nell'indice e nel
    frontmatter, perché il test deve poter dire «prima» o «durante» il turno.
    """
    import sqlite3

    from wadachi import desk as D
    from wadachi.store import MemoryStore

    brain = tmp_path / "brain"
    s = MemoryStore(str(brain))
    s.register_project("proj", paths=[str(cwd)])
    if updated is None:
        return brain
    for i in range(1 + extra):
        d = s.open_desk(title=f"Il lavoro {i}", objective="o", done_when="d",
                        plan=["primo passo", "secondo passo"], project="proj")
        stamp = updated.isoformat()
        path = brain / d["filepath"]
        path.write_text(D.set_meta(path.read_text(), "updated", stamp))
        with sqlite3.connect(brain / "brain.db") as conn:
            conn.execute("UPDATE desks SET updated_at = ? WHERE slug = ?", (stamp, d["slug"]))
    return brain


# ── l'esecuzione ────────────────────────────────────────────────────────────


def run(payload: dict, env: dict | None = None) -> tuple[int, str, str]:
    base = {
        "WADACHI_CONTEXT_WINDOW": "1000000",  # niente avvisi di peso: qui conta la guardia
        "PATH": "/usr/bin:/bin",
    }
    base.update(env or {})
    p = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=base,
    )
    return p.returncode, p.stdout, p.stderr


def payload(tp: str, cwd: Path, sid: str | None = None) -> dict:
    return {
        "session_id": sid or str(uuid.uuid4()),
        "transcript_path": tp,
        "cwd": str(cwd),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "eccomi",
    }


def blocked(out: str) -> str | None:
    """Il motivo, se l'hook ha bloccato; None altrimenti."""
    if not out:
        return None
    d = json.loads(out)
    return d.get("reason") if d.get("decision") == "block" else None


def cold_session(tmp_path: Path, *, pause: timedelta = timedelta(hours=2),
                 ctx: int = 132_000, **kw) -> tuple[str, Path, str]:
    """Una sessione il cui ultimo turno è finito `pause` fa."""
    cwd = tmp_path / "repo"
    cwd.mkdir(exist_ok=True)
    sid = str(uuid.uuid4())
    end = NOW - pause
    recs = [meta(sid, str(cwd), end - timedelta(hours=1))]
    recs += turn(sid, str(cwd), end - timedelta(minutes=30), end - timedelta(minutes=20), ctx - 20_000, **kw)
    recs += turn(sid, str(cwd), end - timedelta(minutes=5), end, ctx, **kw)
    return write(tmp_path, recs), cwd, sid


# ── il blocco ───────────────────────────────────────────────────────────────


def test_cache_scaduta_e_contesto_grande_blocca(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    code, out, _ = run(payload(tp, cwd, sid))
    assert code == 0
    reason = blocked(out)
    assert reason, f"doveva bloccare, ha detto: {out!r}"
    assert "132k" in reason
    assert "20" in reason  # ≈ 20 turni a cache calda


def test_il_secondo_invio_passa(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    p = payload(tp, cwd, sid)
    _, out1, _ = run(p)
    _, out2, _ = run(p)
    assert blocked(out1)
    assert blocked(out2) is None, "una pausa si paga una volta sola: il secondo invio passa"


def test_una_pausa_nuova_blocca_di_nuovo(tmp_path):
    """Il marker è legato all'ultimo turno: una pausa dopo un turno nuovo è un'altra pausa."""
    tp1, cwd, sid = cold_session(tmp_path, pause=timedelta(hours=3))
    assert blocked(run(payload(tp1, cwd, sid))[1])
    tp2, _, _ = cold_session(tmp_path, pause=timedelta(hours=2))
    assert blocked(run(payload(tp2, cwd, sid))[1])


def test_il_motivo_dice_da_quanto_e_scaduta(tmp_path):
    tp, cwd, sid = cold_session(tmp_path, pause=timedelta(hours=2, minutes=14))
    reason = blocked(run(payload(tp, cwd, sid))[1])
    assert "1 h 14 min" in reason  # 2 h 14 min di pausa meno l'ora di cache


# ── quando tace ─────────────────────────────────────────────────────────────


def test_contesto_piccolo_non_blocca(tmp_path):
    tp, cwd, sid = cold_session(tmp_path, ctx=30_000)
    assert run(payload(tp, cwd, sid))[:2] == (0, "")


def test_pausa_breve_non_blocca(tmp_path):
    tp, cwd, sid = cold_session(tmp_path, pause=timedelta(minutes=40))
    assert run(payload(tp, cwd, sid))[:2] == (0, "")


def test_soglia_del_contesto_configurabile(tmp_path):
    tp, cwd, sid = cold_session(tmp_path, ctx=30_000)
    assert blocked(run(payload(tp, cwd, sid), env={"WADACHI_GUARD_MIN": "20000"})[1])


def test_spenta_da_ambiente(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    assert run(payload(tp, cwd, sid), env={"WADACHI_CACHE_GUARD": "off"})[:2] == (0, "")


def test_senza_session_id_non_blocca(tmp_path):
    """Senza sessione non c'è dove ricordarsi di aver già bloccato: bloccherebbe
    per sempre. Meglio un turno freddo che un messaggio che non passa mai."""
    tp, cwd, _ = cold_session(tmp_path)
    p = payload(tp, cwd)
    del p["session_id"]
    assert blocked(run(p)[1]) is None


def test_senza_dove_ricordarselo_non_blocca(tmp_path):
    """Se il marker non si scrive, il secondo invio non saprebbe di essere il
    secondo e si bloccherebbe per sempre. Qui al posto della directory dei
    marker c'è un file: la guardia deve lasciar passare, non insistere."""
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    (tmp / "wadachi-session-weight").write_text("non sono una directory")
    tp, cwd, sid = cold_session(tmp_path)
    p = payload(tp, cwd, sid)
    env = {"TMPDIR": str(tmp)}
    assert blocked(run(p, env=env)[1]) is None
    assert blocked(run(p, env=env)[1]) is None


def test_record_senza_timestamp_non_bloccano(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    lines = [json.loads(l) for l in Path(tp).read_text().splitlines()]
    for r in lines:
        r.pop("timestamp", None)
    Path(tp).write_text("".join(json.dumps(r) + "\n" for r in lines))
    assert run(payload(tp, cwd, sid))[:2] == (0, "")


def test_timestamp_illeggibile_non_blocca(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    text = Path(tp).read_text().replace('"timestamp": "', '"timestamp": "ieri ')
    Path(tp).write_text(text)
    code, out, err = run(payload(tp, cwd, sid))
    assert (code, out) == (0, "") and "Traceback" not in err


def test_l_ultima_riga_a_meta_non_rompe(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    with open(tp, "a") as fh:
        fh.write('{"type": "assistant", "timestamp": "2026-')
    code, out, _ = run(payload(tp, cwd, sid))
    assert code == 0 and blocked(out)


# ── la durata della cache ───────────────────────────────────────────────────


def test_la_durata_si_legge_dal_transcript(tmp_path):
    """Con `ephemeral_5m` la cache dura cinque minuti: dieci minuti di pausa bastano."""
    tp, cwd, sid = cold_session(tmp_path, pause=timedelta(minutes=10), ttl="5m")
    assert blocked(run(payload(tp, cwd, sid))[1])


def test_la_durata_da_ambiente_vince(tmp_path):
    tp, cwd, sid = cold_session(tmp_path, pause=timedelta(minutes=40))
    assert blocked(run(payload(tp, cwd, sid), env={"WADACHI_CACHE_TTL": "1800"})[1])


def test_i_turni_dei_subagenti_non_contano(tmp_path):
    """Un subagente ha il suo contesto e la sua cache: non dice niente di questa."""
    tp, cwd, sid = cold_session(tmp_path)
    with open(tp, "a") as fh:
        fh.write(json.dumps(reply(sid, str(cwd), NOW - timedelta(minutes=1), 132_000,
                                  sidechain=True)) + "\n")
    assert blocked(run(payload(tp, cwd, sid))[1])


# ── la scrivania nel motivo ─────────────────────────────────────────────────


def test_scrivania_aggiornata_nell_ultimo_turno(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    # l'ultimo turno è andato da (fine - 5 min) a fine: desk_log a metà
    brain = brain_with_desk(tmp_path, cwd, NOW - timedelta(hours=2, minutes=2))
    reason = blocked(run(payload(tp, cwd, sid), env={"BRAIN_DIR": str(brain)})[1])
    assert "il-lavoro-0" in reason
    assert "/clear" in reason
    assert "prima dell'ultimo turno" not in reason


def test_scrivania_ferma_da_prima_dell_ultimo_turno(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    brain = brain_with_desk(tmp_path, cwd, NOW - timedelta(hours=5))
    reason = blocked(run(payload(tp, cwd, sid), env={"BRAIN_DIR": str(brain)})[1])
    assert "il-lavoro-0" in reason
    assert "prima dell'ultimo turno" in reason


def test_nessuna_scrivania_aperta_lo_dice(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    brain = brain_with_desk(tmp_path, cwd, None)
    reason = blocked(run(payload(tp, cwd, sid), env={"BRAIN_DIR": str(brain)})[1])
    assert reason and "nessuna scrivania" in reason.lower()


def test_piu_scrivanie_aperte_le_conta(tmp_path):
    tp, cwd, sid = cold_session(tmp_path)
    brain = brain_with_desk(tmp_path, cwd, NOW - timedelta(hours=2, minutes=2), extra=1)
    reason = blocked(run(payload(tp, cwd, sid), env={"BRAIN_DIR": str(brain)})[1])
    assert "2 scrivanie aperte" in reason


def test_brain_assente_blocca_lo_stesso_senza_scrivania(tmp_path):
    """L'SSD scollegato non deve né rompere il turno né creare un brain vuoto."""
    tp, cwd, sid = cold_session(tmp_path)
    missing = tmp_path / "non-montato" / "wadachi-brain"
    code, out, err = run(payload(tp, cwd, sid), env={"BRAIN_DIR": str(missing)})
    assert code == 0 and blocked(out) and "Traceback" not in err
    assert not missing.exists(), "un brain che manca non si inventa"
