"""La ripresa dopo /clear: la sessione nuova parte con la scrivania nel contesto.

`/clear` costa poco solo se la sessione nuova sa dov'era il lavoro. L'hook
`SessionStart` (su `startup` e `clear`) legge le scrivanie aperte del progetto
direttamente dai file del brain e le inietta, senza che il modello debba
chiamare get_context o desk_read — una tool call in meno, e nessun rischio che
la dimentichi.

Le scrivanie dei test le scrive il vero MemoryStore (`open_desk`, `log_desk`):
il formato è quello che il server produce, non una sua imitazione.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "resume-desk.py"

CAP_TOKENS = 1_200


def run(payload: dict, env: dict | None = None) -> tuple[int, str, str]:
    base = {"PATH": "/usr/bin:/bin"}
    base.update(env or {})
    p = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=base,
    )
    return p.returncode, p.stdout, p.stderr


def context(out: str) -> str:
    d = json.loads(out)
    assert d["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return d["hookSpecificOutput"]["additionalContext"]


@pytest.fixture()
def repo(tmp_path):
    cwd = tmp_path / "repo"
    (cwd / "sub").mkdir(parents=True)
    return cwd


@pytest.fixture()
def brain(tmp_path, repo):
    from wadachi.store import MemoryStore

    s = MemoryStore(str(tmp_path / "brain"))
    s.register_project("proj", paths=[str(repo)])
    return s


def start(repo: Path, brain, source: str = "clear", cwd: Path | None = None):
    payload = {
        "session_id": "s1",
        "transcript_path": "/dev/null",
        "cwd": str(cwd or repo),
        "hook_event_name": "SessionStart",
        "source": source,
    }
    return run(payload, env={"BRAIN_DIR": str(brain.brain_dir)})


def desk(brain, title="La cache ha un orologio", **kw):
    return brain.open_desk(
        title=title,
        objective=kw.get("objective", "Colpire il turno a cache fredda."),
        done_when=kw.get("done_when", "Blocco visto dal vivo."),
        plan=kw.get("plan", ["Approvare il piano", "Scrivere i test", "Scrivere la guardia"]),
        project="proj",
    )


# ── una scrivania ───────────────────────────────────────────────────────────


def test_una_scrivania_entra_nel_contesto(repo, brain):
    d = desk(brain)
    brain.log_desk(d["slug"], "proj", done="Approvare il piano", note="approvato")
    code, out, _ = start(repo, brain)
    assert code == 0
    t = context(out)
    assert d["slug"] in t
    assert "La cache ha un orologio" in t
    assert "Colpire il turno a cache fredda." in t
    assert "Blocco visto dal vivo." in t
    assert "Scrivere i test" in t  # il prossimo passo
    assert "Scrivere la guardia" not in t, "solo il prossimo passo, non tutto il piano"


def test_le_ultime_due_voci_del_registro(repo, brain):
    d = desk(brain)
    for n in ("prima nota", "seconda nota", "terza nota"):
        brain.log_desk(d["slug"], "proj", note=n)
    t = context(start(repo, brain)[1])
    assert "terza nota" in t and "seconda nota" in t
    assert "prima nota" not in t


def test_una_nota_con_un_elenco_resta_una_voce(repo, brain):
    """Un `- ` dentro una nota non apre una voce nuova del registro."""
    d = desk(brain)
    brain.log_desk(d["slug"], "proj", note="vecchia nota")
    brain.log_desk(d["slug"], "proj", note="due cose:\n- la prima\n- la seconda")
    t = context(start(repo, brain)[1])
    assert "la seconda" in t and "vecchia nota" in t


def test_la_sezione_aperto(repo, brain):
    d = desk(brain)
    brain.log_desk(d["slug"], "proj", open_question="il testo bloccato resta nell'input?")
    t = context(start(repo, brain)[1])
    assert "il testo bloccato resta nell'input?" in t


def test_piano_finito_lo_dice(repo, brain):
    d = desk(brain, plan=["unico passo"])
    brain.log_desk(d["slug"], "proj", done="unico passo")
    t = context(start(repo, brain)[1])
    assert "piano finito" in t


def test_da_una_sottodirectory(repo, brain):
    d = desk(brain)
    t = context(start(repo, brain, cwd=repo / "sub")[1])
    assert d["slug"] in t


def test_anche_all_avvio(repo, brain):
    d = desk(brain)
    assert d["slug"] in context(start(repo, brain, source="startup")[1])


def test_resta_sotto_il_tetto(repo, brain):
    lungo = "parola " * 3_000
    d = desk(brain, objective=lungo, done_when=lungo)
    for _ in range(3):
        brain.log_desk(d["slug"], "proj", note=lungo, open_question=lungo)
    t = context(start(repo, brain)[1])
    assert len(t) // 4 <= CAP_TOKENS
    assert d["slug"] in t, "lo slug non si taglia mai: è quello che serve a desk_read"


# ── più scrivanie ───────────────────────────────────────────────────────────


def test_piu_scrivanie_le_elenca_senza_sceglierne_una(repo, brain):
    a = desk(brain, title="Primo lavoro", plan=["passo A"])
    b = desk(brain, title="Secondo lavoro", plan=["passo B"])
    t = context(start(repo, brain)[1])
    assert a["slug"] in t and b["slug"] in t
    assert "passo A" in t and "passo B" in t
    assert "Colpire il turno" not in t, "con più scrivanie niente dettaglio: non si sceglie"


def test_le_scrivanie_chiuse_non_contano(repo, brain):
    a = desk(brain, title="Chiusa")
    brain.close_desk(a["slug"], "done", project="proj")
    b = desk(brain, title="Aperta")
    t = context(start(repo, brain)[1])
    assert b["slug"] in t and a["slug"] not in t


# ── il silenzio ─────────────────────────────────────────────────────────────


def test_nessuna_scrivania_tace(repo, brain):
    assert start(repo, brain)[:2] == (0, "")


def test_scrivanie_di_altri_progetti_non_entrano(repo, brain, tmp_path):
    brain.register_project("altro", paths=[str(tmp_path / "altrove")])
    brain.open_desk(title="Altrui", objective="o", done_when="d", plan=["x"], project="altro")
    assert start(repo, brain)[:2] == (0, "")


def test_progetto_non_rilevato_tace(repo, brain, tmp_path):
    desk(brain)
    fuori = tmp_path / "fuori"
    fuori.mkdir()
    assert start(repo, brain, cwd=fuori)[:2] == (0, "")


@pytest.mark.parametrize("source", ["resume", "compact"])
def test_resume_e_compact_tacciono(repo, brain, source):
    """Su resume il contesto c'è già; su compact non è nel piano."""
    desk(brain)
    assert start(repo, brain, source=source)[:2] == (0, "")


def test_senza_brain_dir_tace(repo, brain):
    desk(brain)
    payload = {"cwd": str(repo), "source": "clear", "hook_event_name": "SessionStart"}
    assert run(payload)[:2] == (0, "")


def test_brain_non_montato_tace_e_non_lo_crea(repo, tmp_path):
    missing = tmp_path / "non-montato" / "wadachi-brain"
    payload = {"cwd": str(repo), "source": "clear", "hook_event_name": "SessionStart"}
    code, out, err = run(payload, env={"BRAIN_DIR": str(missing)})
    assert (code, out) == (0, "") and "Traceback" not in err
    assert not missing.exists()


def test_stdin_non_json_tace():
    p = subprocess.run([sys.executable, str(SCRIPT)], input="{", capture_output=True, text=True)
    assert (p.returncode, p.stdout) == (0, "")


def test_file_della_scrivania_sparito_tace(repo, brain):
    d = desk(brain)
    (brain.brain_dir / d["filepath"]).unlink()
    code, out, err = start(repo, brain)
    assert (code, out) == (0, "") and "Traceback" not in err
