"""3.11 — wadachi doctor: diagnosi read-only, --fix ripara solo il sicuro."""

import sqlite3

from wadachi.doctor import run_doctor
from wadachi.store import MemoryStore


def _healthy_brain(tmp_path):
    s = MemoryStore(str(tmp_path / "brain"))
    s.store_memory("contenuto sano", "Memoria sana", tags=["ok"])
    return s


def test_doctor_healthy_brain_exit_zero(tmp_path, capsys):
    s = _healthy_brain(tmp_path)
    assert run_doctor(s.brain_dir, check_mcp=False) == 0
    out = capsys.readouterr().out
    assert "integrity_check: ok" in out
    assert "tutti i file referenziati" in out


def test_doctor_missing_brain(tmp_path, capsys):
    assert run_doctor(tmp_path / "inesistente", check_mcp=False) == 1
    assert "wadachi init" in capsys.readouterr().out


def test_doctor_corrupted_db(tmp_path, capsys):
    brain = tmp_path / "b"
    (brain / "global").mkdir(parents=True)
    (brain / "projects").mkdir()
    (brain / "brain.db").write_text("non sono un database")
    assert run_doctor(brain, check_mcp=False) == 1
    assert "backup" in capsys.readouterr().out


def test_doctor_detects_missing_file(tmp_path, capsys):
    s = _healthy_brain(tmp_path)
    m = s.list_memories()[0]
    (s.brain_dir / m["filepath"]).unlink()          # file sparito
    assert run_doctor(s.brain_dir, check_mcp=False) == 1
    assert "assenti su disco" in capsys.readouterr().out


def test_doctor_detects_orphan_and_malformed(tmp_path, capsys):
    s = _healthy_brain(tmp_path)
    # orfano: su disco ma non nel DB
    (s.brain_dir / "global" / "appunto-a-mano.md").write_text("scritto a mano")
    # malformato: frontmatter non chiuso
    m = s.list_memories()[0]
    (s.brain_dir / m["filepath"]).write_text("---\ntitle: X\ncorpo senza chiusura")
    code = run_doctor(s.brain_dir, check_mcp=False)
    out = capsys.readouterr().out
    assert code == 0                                 # sono warning, non errori
    assert "orfano" in out or "non indicizzati" in out
    assert "malformato" in out or "frontmatter" in out


def test_doctor_fix_repairs_frontmatter(tmp_path, capsys):
    s = _healthy_brain(tmp_path)
    m = s.list_memories()[0]
    path = s.brain_dir / m["filepath"]
    path.write_text("contenuto prezioso senza frontmatter")

    assert run_doctor(s.brain_dir, fix=True, check_mcp=False) == 0
    assert "riscritti nel formato canonico OKF" in capsys.readouterr().out
    text = path.read_text()
    assert text.startswith("---")
    assert "contenuto prezioso" in text              # il contenuto non si tocca
    # e ora la memoria si rilegge normalmente
    assert s.get_memory(m["id"])["content"] == "contenuto prezioso senza frontmatter"


def test_doctor_is_read_only_without_fix(tmp_path):
    """La diagnosi non applica migrazioni né modifica file."""
    brain = tmp_path / "b"
    (brain / "global").mkdir(parents=True)
    (brain / "projects").mkdir()
    conn = sqlite3.connect(brain / "brain.db")      # DB legacy senza schema_version
    conn.executescript("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT 'global', tags TEXT DEFAULT '[]',
            category TEXT DEFAULT 'note', filepath TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, embedding BLOB
        );
    """)
    conn.commit()
    conn.close()
    before = (brain / "brain.db").read_bytes()

    run_doctor(brain, check_mcp=False)

    assert (brain / "brain.db").read_bytes() == before   # nessuna mutazione
    assert not (brain / "backups").exists()              # nessuna migrazione partita


def test_doctor_reports_pending_migrations(tmp_path, capsys):
    brain = tmp_path / "b"
    (brain / "global").mkdir(parents=True)
    (brain / "projects").mkdir()
    conn = sqlite3.connect(brain / "brain.db")
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, title TEXT, slug TEXT, "
                 "project TEXT, tags TEXT, category TEXT, filepath TEXT, "
                 "created_at TEXT, updated_at TEXT, embedding BLOB)")
    conn.commit()
    conn.close()
    run_doctor(brain, check_mcp=False)
    out = capsys.readouterr().out
    assert "schema v0" in out and "migrazioni" in out


def test_doctor_warns_specifically_on_python_315_without_fastembed(tmp_path, capsys, monkeypatch):
    """Su Python 3.15 onnxruntime non ha ancora wheel cp315: doctor deve dirlo
    in chiaro con il comando funzionante invece del generico pip install."""
    import builtins
    import sys

    s = _healthy_brain(tmp_path)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fastembed":
            raise ImportError("no fastembed on 3.15")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(sys, "version_info", (3, 15, 0, "final", 0))

    code = run_doctor(s.brain_dir, check_mcp=False)
    out = capsys.readouterr().out
    assert code == 0
    assert "3.15" in out
    assert "onnxruntime" in out
    assert "--python 3.14" in out


def test_pyproject_semantic_extra_gates_fastembed_below_315():
    """L'extra `semantic` non deve far fallire pip/uv su Python 3.15 finché
    onnxruntime non pubblica wheel cp315."""
    import tomllib
    from pathlib import Path

    data = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())
    semantic = data["project"]["optional-dependencies"]["semantic"]
    assert any("fastembed" in dep and 'python_version < "3.15"' in dep for dep in semantic), semantic
