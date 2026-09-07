"""Il numero di strumenti dichiarato nei documenti non deve poter mentire.

README.md e demo/wiki-src/tools.md dicevano «31» molto dopo che il conteggio
reale era salito a 37 (menù + manutenzione): nessun test lo controllava, quindi
nessuno se n'è accorto finché non è stato misurato a mano. Questo test lo
misura ad ogni run.
"""

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_DIR", str(tmp_path / "brain"))
    import wadachi.server as s
    importlib.reload(s)
    return s


def _declared_total(text: str, pattern: str, doc: str) -> int:
    m = re.search(pattern, text)
    assert m, f"{doc}: nessun conteggio trovato con {pattern!r} — il testo è cambiato?"
    return int(m.group(1))


def test_readme_tool_count_matches_reality(server):
    real_total = len(server.exposed_tool_names()) + len(server.tools_in(server.MAINTENANCE))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    declared = _declared_total(readme, r"exposes \*\*(\d+) MCP tools\*\*", "README.md")
    assert declared == real_total, (
        f"README.md dichiara {declared} strumenti, ce ne sono {real_total} "
        f"({len(server.exposed_tool_names())} in menù + "
        f"{len(server.tools_in(server.MAINTENANCE))} di manutenzione)")


def test_wiki_tools_page_count_matches_reality(server):
    real_total = len(server.exposed_tool_names()) + len(server.tools_in(server.MAINTENANCE))
    wiki = (ROOT / "demo" / "wiki-src" / "tools.md").read_text(encoding="utf-8")
    declared = _declared_total(wiki, r"Tool reference — all (\d+)", "tools.md")
    assert declared == real_total, (
        f"tools.md dichiara {declared} strumenti, ce ne sono {real_total} "
        f"({len(server.exposed_tool_names())} in menù + "
        f"{len(server.tools_in(server.MAINTENANCE))} di manutenzione)")


def test_wiki_index_tool_count_matches_reality(server):
    """demo/wiki-src/index.md dichiara anche lui il conteggio totale, ed era
    l'unico a non avere una guardia (finding 6)."""
    real_total = len(server.exposed_tool_names()) + len(server.tools_in(server.MAINTENANCE))
    index = (ROOT / "demo" / "wiki-src" / "index.md").read_text(encoding="utf-8")
    declared = _declared_total(index, r"every one of the (\d+) tools", "index.md")
    assert declared == real_total, (
        f"index.md dichiara {declared} strumenti, ce ne sono {real_total} "
        f"({len(server.exposed_tool_names())} in menù + "
        f"{len(server.tools_in(server.MAINTENANCE))} di manutenzione)")


def test_changelog_menu_count_matches_reality(server):
    """CHANGELOG.md diceva «23 strumenti in menù» nella stessa sezione
    [Unreleased] che aggiunge i tre tool della scrivania: il numero reale nel
    menù è 26, come già dice README.md — nessun test lo controllava, quindi
    la contraddizione è passata inosservata (finding 5)."""
    real_menu = len(server.exposed_tool_names())
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    declared = _declared_total(changelog, r"Risultato: (\d+) strumenti in menù",
                                "CHANGELOG.md")
    assert declared == real_menu, (
        f"CHANGELOG.md dichiara {declared} strumenti in menù, ce ne sono {real_menu}")
