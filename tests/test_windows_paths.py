"""Percorsi Windows (`\\`) in memories.filepath: scrittura POSIX e recupero in lettura.

Su Windows `str(filepath.relative_to(brain_dir))` salvava `projects\\app\\nota.md`
nel DB: aprendo quel brain su macOS/Linux il file risultava mancante, e anche
su Windows stesso `entities.py` / `graph.py` / `reflect.py` si aspettavano `/`.
"""

import sqlite3
from pathlib import PureWindowsPath

from wadachi.doctor import run_doctor
from wadachi.entities import EntityGraph
from wadachi.graph import MemoryGraph
from wadachi.store import MemoryStore


def test_store_memory_uses_as_posix_even_when_path_is_windows(tmp_path, monkeypatch):
    """Simula un Path Windows su qualunque OS: `store_memory` deve chiamare
    `.as_posix()`, mai `str(...)`, così il DB contiene sempre `/`."""
    s = MemoryStore(str(tmp_path / "brain"))
    orig_relative_to = type(s.brain_dir).relative_to

    def fake_relative_to(self, *other):
        rel = orig_relative_to(self, *other)
        return PureWindowsPath(*rel.parts)

    monkeypatch.setattr(type(s.brain_dir), "relative_to", fake_relative_to)

    res = s.store_memory("contenuto", "Nota da Windows", project="winproj")
    assert res["filepath"] == "projects/winproj/nota-da-windows.md"
    assert "\\" not in res["filepath"]

    with sqlite3.connect(s.db_path) as conn:
        db_fp = conn.execute(
            "SELECT filepath FROM memories WHERE id = ?", (res["id"],)
        ).fetchone()[0]
    assert db_fp == "projects/winproj/nota-da-windows.md"


def _seed_windows_row(tmp_path):
    """Crea una memoria sana e poi riscrive il suo `filepath` nel DB con `\\`
    come avrebbe fatto wadachi <= 0.17.0 su Windows."""
    s = MemoryStore(str(tmp_path / "brain"))
    res = s.store_memory("contenuto prezioso", "Nota migrata", project="app")
    win_fp = res["filepath"].replace("/", "\\")
    with sqlite3.connect(s.db_path) as conn:
        conn.execute("UPDATE memories SET filepath = ? WHERE id = ?", (win_fp, res["id"]))
        conn.commit()
    return s, res["id"], win_fp


def test_legacy_windows_backslash_paths_remain_readable_across_store_graph_entities(tmp_path):
    s, mid, win_fp = _seed_windows_row(tmp_path)
    assert "\\" in win_fp

    # 1. Lettura singola e batch per ricerca
    mem = s.get_memory(mid)
    assert mem["content"] == "contenuto prezioso"

    batch = s.get_memories_for_embedding()
    assert batch[0]["content"] == "contenuto prezioso"

    # 2. index.md: lo stem non deve contenere la directory con backslash
    s.rebuild_index()
    idx = (s.brain_dir / "index.md").read_text(encoding="utf-8")
    assert "[[nota-migrata]]" in idx
    assert "\\" not in idx

    # 3. Grafo e corpus Graphify
    g = MemoryGraph(s).build()
    assert g.nodes[mid].stem == "nota-migrata"

    eg = EntityGraph(s)
    assert eg._export_corpus() == 1
    assert (eg.corpus_dir / "projects__app__nota-migrata.md").exists()

    # 4. Update e delete non falliscono e trovano il file vero
    assert s.update_memory(mid, content="contenuto aggiornato") is True
    assert s.get_memory(mid)["content"] == "contenuto aggiornato"
    assert s.delete_memory(mid) is True
    assert not (s.brain_dir / "projects" / "app" / "nota-migrata.md").exists()


def test_doctor_warns_and_fixes_windows_backslash_paths(tmp_path, capsys):
    s, mid, win_fp = _seed_windows_row(tmp_path)

    # Read-only: nessun falso "file assente", ma warning sul separatore Windows
    assert run_doctor(s.brain_dir, fix=False, check_mcp=False) == 0
    out = capsys.readouterr().out
    assert "assenti su disco" not in out
    assert "backslash" in out.lower() or "windows" in out.lower()
    with sqlite3.connect(s.db_path) as conn:
        assert conn.execute("SELECT filepath FROM memories WHERE id = ?", (mid,)).fetchone()[0] == win_fp

    # --fix: normalizza il DB a POSIX `/`
    assert run_doctor(s.brain_dir, fix=True, check_mcp=False) == 0
    out_fix = capsys.readouterr().out
    assert "normalizzat" in out_fix.lower()
    with sqlite3.connect(s.db_path) as conn:
        fixed_fp = conn.execute("SELECT filepath FROM memories WHERE id = ?", (mid,)).fetchone()[0]
    assert fixed_fp == "projects/app/nota-migrata.md"
