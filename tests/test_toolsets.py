"""I toolset: quali strumenti sono in menù, e perché non tutti.

Misurato su 741 trascrizioni (memoria #226, decisione D40): 19 strumenti su 33
non sono mai stati chiamati. Classificati per *momento d'uso* invece che per
funzione, gli strumenti di manutenzione sono 1 usato su 11 — non perché siano
descritti male, ma perché richiedono il momento in cui ci si siede a curare il
brain, che dentro una sessione di lavoro non arriva mai.
"""

import importlib
import os
import re
from pathlib import Path

import pytest


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Il modulo server importato fresco, con un brain temporaneo."""
    monkeypatch.setenv("BRAIN_DIR", str(tmp_path / "brain"))
    import wadachi.server as s
    importlib.reload(s)
    return s


# ── Cosa è in menù ────────────────────────────────────────────────────


def test_maintenance_tools_are_not_in_the_working_menu(server):
    """Gli strumenti del rituale non stanno nel menù del lavoro."""
    exposed = set(server.exposed_tool_names())
    for name in ["sleep", "consolidate", "merge_memories", "reflect",
                 "review_beliefs", "set_belief", "review_procedures",
                 "list_insights", "accept_insight", "reject_insight",
                 "rebuild_entity_graph"]:
        assert name not in exposed, f"{name} è manutenzione, non lavoro"


def test_the_working_tools_are_all_there(server):
    """Nessuno strumento del lavoro è stato perso per strada."""
    exposed = set(server.exposed_tool_names())
    for name in ["store_memory", "recall", "get_context", "store_decision",
                 "get_memory", "expand_memory", "update_memory", "flag_stale",
                 "recall_associative", "why", "as_of", "related_memories"]:
        assert name in exposed, f"{name} serve mentre si lavora"


def test_the_menu_stays_under_the_threshold(server):
    """Oltre i 20-25 strumenti la scelta degrada: il menù resta sotto."""
    assert len(server.exposed_tool_names()) <= 25


def test_no_tool_is_lost_only_moved(server):
    """Ogni strumento di manutenzione resta invocabile: nascosto, non rimosso."""
    for name in ["sleep", "consolidate", "reflect", "review_procedures"]:
        fn = getattr(server, name, None)
        assert callable(fn), f"{name} deve restare una funzione chiamabile"


# ── Come sono descritti ───────────────────────────────────────────────


SITUAZIONE = ("use this", "use it", "when ", "before ", "after ", "reach for",
              "call this", "if you", "you already")


def _prima_riga(fn):
    doc = (fn.__doc__ or "").strip()
    return doc.split("\n")[0].lower()


def test_every_exposed_tool_says_when_to_use_it(server):
    """La prima riga dice la situazione, non l'implementazione.

    L'unico strumento di ricerca che veniva scelto era l'unico la cui prima riga
    conteneva un momento («before starting work»); gli altri descrivevano
    HippoRAG e la spreading activation, che al momento della scelta non servono.
    """
    manca = []
    for name in server.exposed_tool_names():
        fn = getattr(server, name, None)
        if fn and not any(s in _prima_riga(fn) for s in SITUAZIONE):
            manca.append(name)
    assert not manca, f"la prima riga non dice quando usarli: {manca}"


def test_descriptions_do_not_lead_with_implementation(server):
    """Niente gergo di implementazione nella prima riga."""
    gergo = ["hipporag", "spreading-activation", "personalized pagerank",
             "cosine", "top-k", "sqlite", "embedding"]
    colpevoli = []
    for name in server.exposed_tool_names():
        fn = getattr(server, name, None)
        if fn and any(g in _prima_riga(fn) for g in gergo):
            colpevoli.append(name)
    assert not colpevoli, f"la prima riga parla di implementazione: {colpevoli}"


# ── Il manuale, accessibile su richiesta ──────────────────────────────


def test_the_manual_is_reachable_without_costing_context(server):
    """«Tipo man»: il manuale esiste come risorsa, non dentro le descrizioni."""
    manual = server.manual()
    assert isinstance(manual, str) and len(manual) > 200
    assert "sleep" in manual.lower(), "il manuale copre anche ciò che è fuori menù"


def test_the_manual_lists_the_hidden_tools_with_how_to_reach_them(server):
    """Chi legge il manuale scopre gli strumenti nascosti e come raggiungerli."""
    manual = server.manual().lower()
    assert "wadachi sleep" in manual or "cli" in manual
