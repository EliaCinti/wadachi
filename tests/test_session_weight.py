"""Il peso della sessione: la misura, le soglie, e il silenzio.

La regola che governa questi test: **un avviso sul peso non vale il rischio di
rompere il turno.** Ogni input impossibile — transcript assente, vuoto, a metà,
senza `usage` — deve uscire 0 e muto, perché l'hook gira prima di ogni messaggio
e un suo errore si mangerebbe il messaggio.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "session-weight.py"


def run(payload: dict, env: dict | None = None) -> tuple[int, str]:
    base = {
        "WADACHI_WEIGHT_NOTICE": "50",
        "WADACHI_WEIGHT_WARN": "75",
        "WADACHI_WEIGHT_URGE": "90",
        "WADACHI_CONTEXT_WINDOW": "200000",
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
    return p.returncode, p.stdout


def transcript(tmp_path: Path, *usages: dict, model: str = "claude-opus-5") -> str:
    f = tmp_path / "t.jsonl"
    with f.open("w") as fh:
        for u in usages:
            fh.write(json.dumps({"message": {"model": model, "usage": u}}) + "\n")
    return str(f)


def usage(ctx: int) -> dict:
    return {"input_tokens": 2, "cache_read_input_tokens": ctx - 2, "output_tokens": 500}


def fresh(tp: str) -> dict:
    """Un payload con una sessione mai vista, così lo stato non interferisce."""
    return {"transcript_path": tp, "session_id": str(uuid.uuid4())}


# ── il silenzio ────────────────────────────────────────────────────────────


def test_niente_transcript_esce_muto():
    assert run({"session_id": "x"}) == (0, "")


def test_transcript_inesistente_esce_muto(tmp_path):
    assert run({"transcript_path": str(tmp_path / "manca.jsonl")}) == (0, "")


def test_transcript_vuoto_esce_muto(tmp_path):
    f = tmp_path / "vuoto.jsonl"
    f.write_text("")
    assert run(fresh(str(f))) == (0, "")


def test_righe_malformate_escono_mute(tmp_path):
    f = tmp_path / "rotto.jsonl"
    f.write_text("non json\n{a metà\n")
    assert run(fresh(str(f))) == (0, "")


def test_record_senza_usage_escono_muti(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({"message": {"model": "claude-opus-5"}}) + "\n")
    assert run(fresh(str(f))) == (0, "")


def test_stdin_non_json_esce_muto():
    p = subprocess.run(
        [sys.executable, str(SCRIPT)], input="{", capture_output=True, text=True
    )
    assert p.returncode == 0 and p.stdout == ""


def test_ultima_riga_a_meta_usa_la_precedente(tmp_path):
    """Un transcript in scrittura può avere l'ultima riga tronca."""
    f = tmp_path / "t.jsonl"
    with f.open("w") as fh:
        fh.write(json.dumps({"message": {"model": "m", "usage": usage(160_000)}}) + "\n")
        fh.write('{"message": {"usage": {"input_to')
    code, out = run(fresh(str(f)))
    assert code == 0 and "80%" in out


# ── le soglie ──────────────────────────────────────────────────────────────


def test_sotto_soglia_non_dice_niente(tmp_path):
    tp = transcript(tmp_path, usage(80_000))  # 40%
    assert run(fresh(tp)) == (0, "")


@pytest.mark.parametrize(
    "ctx,atteso",
    [(110_000, "55%"), (160_000, "80%"), (190_000, "95%")],
)
def test_ogni_banda_riporta_la_sua_percentuale(tmp_path, ctx, atteso):
    tp = transcript(tmp_path, usage(ctx))
    code, out = run(fresh(tp))
    assert code == 0
    assert atteso in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_la_banda_bassa_non_propone_di_ripartire(tmp_path):
    tp = transcript(tmp_path, usage(110_000))
    _, out = run(fresh(tp))
    testo = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "sessione nuova" not in testo


def test_la_banda_alta_propone_la_scrivania(tmp_path):
    tp = transcript(tmp_path, usage(160_000))
    _, out = run(fresh(tp))
    testo = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "desk_log" in testo and "desk_read" in testo


# ── i conti con la cache ───────────────────────────────────────────────────


def _testo(out: str) -> str:
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("ctx", [110_000, 160_000, 190_000])
def test_il_turno_caldo_costa_un_decimo_del_contesto(tmp_path, ctx):
    """Il contesto si rilegge dalla cache a 0,1×: a 160k un turno vale ~16k, non 160k."""
    tp = transcript(tmp_path, usage(ctx))
    t = _testo(run(fresh(tp))[1])
    assert f"≈{ctx // 10_000}k" in t
    assert f"~{ctx // 1000}k a turno" not in t, "il conto senza cache sbaglia di 10×"


@pytest.mark.parametrize("ctx", [110_000, 160_000])
def test_il_turno_freddo_costa_il_doppio_del_contesto(tmp_path, ctx):
    """Dopo la pausa il contesto si riscrive in cache a 2×."""
    tp = transcript(tmp_path, usage(ctx))
    t = _testo(run(fresh(tp))[1])
    assert f"≈{ctx * 2 // 1000}k" in t and "1 h" in t


def test_la_durata_della_cache_si_vede_nel_messaggio(tmp_path):
    """Sforato il piano, la cache dura cinque minuti: il messaggio deve dirlo,
    e il turno freddo costa 1,25× invece di 2×."""
    tp = transcript(tmp_path, usage(160_000))
    t = _testo(run(fresh(tp), env={"WADACHI_CACHE_TTL": "300"})[1])
    assert "5 min" in t and "≈200k" in t


def test_soglie_configurabili_da_ambiente(tmp_path):
    tp = transcript(tmp_path, usage(60_000))  # 30%
    assert run(fresh(tp)) == (0, "")
    code, out = run(fresh(tp), env={"WADACHI_WEIGHT_NOTICE": "25"})
    assert code == 0 and "30%" in out


def test_forma_dell_output_e_quella_che_l_hook_si_aspetta(tmp_path):
    tp = transcript(tmp_path, usage(160_000))
    _, out = run(fresh(tp))
    d = json.loads(out)
    assert d["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert isinstance(d["hookSpecificOutput"]["additionalContext"], str)


# ── la finestra ────────────────────────────────────────────────────────────


def test_il_modello_1m_non_fa_scattare_la_soglia(tmp_path):
    """160k su 200k è allarme; sullo stesso lavoro con [1m] è il 16%."""
    tp = transcript(tmp_path, usage(160_000), model="claude-opus-5[1m]")
    assert run(fresh(tp), env={"WADACHI_CONTEXT_WINDOW": ""}) == (0, "")


def test_finestra_esplicita_vince_sul_modello(tmp_path):
    tp = transcript(tmp_path, usage(160_000), model="claude-opus-5[1m]")
    code, out = run(fresh(tp), env={"WADACHI_CONTEXT_WINDOW": "200000"})
    assert code == 0 and "80%" in out


def test_finestra_non_numerica_ricade_sul_default(tmp_path):
    tp = transcript(tmp_path, usage(160_000))
    code, out = run(fresh(tp), env={"WADACHI_CONTEXT_WINDOW": "tanti"})
    assert code == 0 and "80%" in out


# ── non ripetersi ──────────────────────────────────────────────────────────


def test_lo_stesso_invito_non_si_ripete_nella_stessa_sessione(tmp_path):
    tp = transcript(tmp_path, usage(160_000))
    payload = fresh(tp)
    code1, out1 = run(payload)
    code2, out2 = run(payload)
    assert code1 == 0 and out1 != ""
    assert (code2, out2) == (0, ""), "il secondo turno deve tacere"


def test_una_banda_piu_alta_parla_anche_se_la_bassa_ha_gia_parlato(tmp_path):
    sid = str(uuid.uuid4())
    (tmp_path / "a").mkdir()
    tp1 = transcript(tmp_path / "a", usage(110_000))
    (tmp_path / "b").mkdir()
    tp2 = transcript(tmp_path / "b", usage(190_000))
    _, out1 = run({"transcript_path": tp1, "session_id": sid})
    _, out2 = run({"transcript_path": tp2, "session_id": sid})
    assert out1 != "" and out2 != "", "peggiorare merita una parola nuova"


def test_sessioni_diverse_ricevono_ciascuna_il_proprio_invito(tmp_path):
    tp = transcript(tmp_path, usage(160_000))
    _, out1 = run(fresh(tp))
    _, out2 = run(fresh(tp))
    assert out1 != "" and out2 != ""


def test_un_contesto_oltre_i_200k_dimostra_la_finestra_grande(tmp_path):
    """Il transcript registra `claude-opus-5` anche su `[1m]`: il nome non basta.

    Ma una sessione non può eccedere la propria finestra, quindi 215k di
    contesto sono la prova che la finestra non è da 200k.
    """
    tp = transcript(tmp_path, usage(215_000), model="claude-opus-5")
    assert run(fresh(tp), env={"WADACHI_CONTEXT_WINDOW": ""}) == (0, "")


def test_sotto_i_200k_resta_la_finestra_piccola(tmp_path):
    tp = transcript(tmp_path, usage(160_000), model="claude-opus-5")
    code, out = run(fresh(tp), env={"WADACHI_CONTEXT_WINDOW": ""})
    assert code == 0 and "80%" in out
