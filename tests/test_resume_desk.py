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
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


# ── fuori da un progetto ────────────────────────────────────────────────────
#
# Elia apre spesso VSCode sulla home, che non è di nessun progetto: lì la
# ripresa mostra le scrivanie aperte più recenti di tutti i progetti.


@pytest.fixture()
def fuori(tmp_path):
    d = tmp_path / "fuori"
    d.mkdir()
    return d


def aged(brain, d, days: float):
    """Sposta indietro l'ultimo aggiornamento della scrivania, file e indice."""
    from wadachi import desk as D

    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    path = brain.brain_dir / d["filepath"]
    path.write_text(D.set_meta(path.read_text(), "updated", stamp))
    with sqlite3.connect(brain.brain_dir / "brain.db") as conn:
        conn.execute("UPDATE desks SET updated_at = ? WHERE slug = ? AND project = ?",
                     (stamp, d["slug"], d["project"]))
    return d


def test_fuori_progetto_le_piu_recenti_di_tutti(repo, brain, fuori):
    vecchia = aged(brain, desk(brain, title="Lavoro vecchio", plan=["passo vecchio"]), 3)
    nuova = brain.open_desk(title="Lavoro di stamattina", objective="o", done_when="d",
                            plan=["passo nuovo"], project="global")
    t = context(start(repo, brain, cwd=fuori)[1])
    assert str(fuori) in t
    assert nuova["slug"] in t and vecchia["slug"] in t
    assert "(global, oggi)" in t and "(proj, 3 g fa)" in t
    assert "passo nuovo" in t and "passo vecchio" in t
    assert t.index("passo nuovo") < t.index("passo vecchio"), "la più recente prima"
    assert "chiedi a Elia" in t


def test_fuori_progetto_il_piede_dice_project(repo, brain, fuori):
    """Dalla home, desk_read con la cwd risolverebbe a `global`."""
    desk(brain)
    t = context(start(repo, brain, cwd=fuori)[1])
    assert "project=" in t and "cwd=" not in t


@pytest.mark.parametrize("days, label", [(0, "oggi"), (1, "ieri"), (5, "5 g fa")])
def test_fuori_progetto_l_eta(repo, brain, fuori, days, label):
    aged(brain, desk(brain), days)
    assert f"(proj, {label})" in context(start(repo, brain, cwd=fuori)[1])


def test_fuori_progetto_una_data_illeggibile_non_spegne_le_altre(repo, brain, fuori):
    a = desk(brain, title="Data rotta")
    b = desk(brain, title="Data buona")
    with sqlite3.connect(brain.brain_dir / "brain.db") as conn:
        conn.execute("UPDATE desks SET updated_at = '28 Ott' WHERE slug = ?", (a["slug"],))
    t = context(start(repo, brain, cwd=fuori)[1])
    assert a["slug"] in t and b["slug"] in t
    assert "(proj, oggi)" in t


def test_fuori_progetto_al_massimo_cinque(repo, brain, fuori):
    made = [aged(brain, desk(brain, title=f"Lavoro {i}"), i) for i in range(7)]
    t = context(start(repo, brain, cwd=fuori)[1])
    assert all(d["slug"] in t for d in made[:5])
    assert not any(d["slug"] in t for d in made[5:]), "le più vecchie si contano, non si mostrano"
    assert "e altre 2" in t


def test_fuori_progetto_niente_dettaglio_nemmeno_con_una(repo, brain, fuori):
    """Senza progetto non si sa quale sia quella giusta: solo la riga."""
    desk(brain)
    t = context(start(repo, brain, cwd=fuori)[1])
    assert "Colpire il turno a cache fredda." not in t


def test_fuori_progetto_le_chiuse_non_contano(repo, brain, fuori):
    a = desk(brain, title="Chiusa")
    brain.close_desk(a["slug"], "done", project="proj")
    assert start(repo, brain, cwd=fuori)[:2] == (0, "")


def test_fuori_progetto_nessuna_scrivania_tace(repo, brain, fuori):
    assert start(repo, brain, cwd=fuori)[:2] == (0, "")


def test_fuori_progetto_resta_sotto_il_tetto(repo, brain, fuori):
    lungo = "parola " * 3_000
    for i in range(7):
        desk(brain, title=f"Lavoro {i} " + "lungo " * 40, plan=[lungo])
    t = context(start(repo, brain, cwd=fuori)[1])
    assert len(t) // 4 <= CAP_TOKENS
    assert "project=" in t, "il piede non si taglia mai"


# ── il silenzio ─────────────────────────────────────────────────────────────


def test_nessuna_scrivania_tace(repo, brain):
    assert start(repo, brain)[:2] == (0, "")


def test_scrivanie_di_altri_progetti_non_entrano(repo, brain, tmp_path):
    brain.register_project("altro", paths=[str(tmp_path / "altrove")])
    brain.open_desk(title="Altrui", objective="o", done_when="d", plan=["x"], project="altro")
    assert start(repo, brain)[:2] == (0, "")


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
