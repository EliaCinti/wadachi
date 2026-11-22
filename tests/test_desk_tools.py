"""I tre strumenti: presenti, descritti per essere scelti, e funzionanti."""

import importlib
import json

import pytest


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_DIR", str(tmp_path / "brain"))
    import wadachi.server as s
    importlib.reload(s)
    return s


def test_the_three_tools_are_in_the_working_menu(srv):
    exposed = set(srv.exposed_tool_names())
    assert {"desk", "desk_read", "desk_log"} <= exposed


def test_their_first_line_says_when_to_use_them(srv):
    for name in ["desk", "desk_read", "desk_log"]:
        first = (getattr(srv, name).__doc__ or "").strip().split("\n")[0].lower()
        assert any(k in first for k in ("use this", "when ", "before ", "after ")), name


def test_the_round_trip_through_the_tools(srv):
    srv.register_project("p", "", [])
    opened = json.loads(srv.desk(action="open", title="T", objective="O",
                                 done_when="i test passano",
                                 plan=["uno", "due"], project="p"))
    assert opened["slug"]
    assert json.loads(srv.desk_read(slug=opened["slug"], project="p"))["next_step"] == "uno"

    stepped = json.loads(srv.desk_log(slug=opened["slug"], project="p",
                                      done="uno", note="andata"))
    assert stepped["next_step"] == "due"

    closed = json.loads(srv.desk(action="close", slug=opened["slug"],
                                 project="p", outcome="done"))
    assert closed["status"] == "done"
    assert closed["memory_id"] is None


def test_opening_without_a_stopping_condition_is_refused_with_a_sentence(srv):
    out = json.loads(srv.desk(action="open", title="T", objective="O",
                              done_when="", project="p"))
    assert "error" in out and "fatto quando" in out["error"].lower()


def test_the_project_comes_from_the_callers_cwd_not_the_servers(srv, tmp_path):
    """Un server MCP gira dove è stato lanciato: la cwd la dice il chiamante."""
    proj = tmp_path / "un-progetto"
    proj.mkdir()
    srv.store.register_project("rilevato", "", [str(proj)])
    opened = json.loads(srv.desk(action="open", title="T", objective="O",
                                 done_when="fatto", cwd=str(proj)))
    assert opened["project"] == "rilevato"

    found = json.loads(srv.desk_read(cwd=str(proj)))
    assert found["slug"] == opened["slug"]


def test_listing_shows_only_open_desks(srv):
    srv.register_project("p", "", [])
    opened = json.loads(srv.desk(action="open", title="Uno", objective="O",
                                 done_when="fatto", project="p"))
    srv.desk(action="open", title="Due", objective="O",
             done_when="fatto", project="p")
    srv.desk(action="close", slug=opened["slug"], project="p", outcome="done")

    listed = json.loads(srv.desk(action="list", project="p"))
    assert [d["slug"] for d in listed] == [
        d["slug"] for d in listed if d["status"] == "open"
    ]
    assert opened["slug"] not in [d["slug"] for d in listed]
    assert len(listed) == 1


def test_desk_log_takes_a_position_for_new_steps(srv):
    srv.register_project("p", "", [])
    opened = json.loads(srv.desk(action="open", title="T", objective="O",
                                 done_when="fatto", plan=["uno", "tre"],
                                 project="p"))
    refused = json.loads(srv.desk_log(slug=opened["slug"], project="p",
                                      add=["due"]))
    assert "error" in refused and refused["open_steps"] == ["uno", "tre"]

    placed = json.loads(srv.desk_log(slug=opened["slug"], project="p",
                                     add=["due"], before="tre"))
    assert placed["open_steps"] == ["uno", "due", "tre"]

    last = json.loads(srv.desk_log(slug=opened["slug"], project="p",
                                   add=["quattro"], at_end=True))
    assert last["open_steps"] == ["uno", "due", "tre", "quattro"]


# ── Risposte che costano meno (piano 2026-10-28) ──────────────


def test_desk_read_trims_log_by_default_and_full_returns_everything(srv):
    srv.register_project("p", "", [])
    opened = json.loads(srv.desk(action="open", title="Lunga", objective="Obiettivo vero",
                                 done_when="tutto verde", plan=["passo 1", "passo 2"],
                                 project="p"))
    for i in range(1, 9):
        srv.desk_log(slug=opened["slug"], project="p", note=f"tentativo numero {i}")

    short = json.loads(srv.desk_read(slug=opened["slug"], project="p"))
    assert short["log_total"] == 8
    assert short["log_shown"] == 3
    assert "tentativo numero 8" in short["text"]
    assert "tentativo numero 6" in short["text"]
    assert "tentativo numero 5" not in short["text"]
    assert "5 voci omesse" in short["text"]
    assert "full=True" in short["text"]

    full = json.loads(srv.desk_read(slug=opened["slug"], project="p", full=True))
    assert full["log_total"] == 8
    assert full["log_shown"] == 8
    assert "tentativo numero 1" in full["text"]
    assert "voci omesse" not in full["text"]


def test_tool_replies_emit_utf8_without_ascii_escapes(srv):
    """Nessuna risposta MCP deve gonfiarsi con \\u00e8, \\u00ab eccetera."""
    srv.register_project("p", "", [])
    raw_store = srv.store_memory(
        content="È già così — «perché» sì, più veloce.",
        title="Accenti è à ò ù",
        project="p",
    )
    assert "\\u00" not in raw_store
    assert "Accenti è à ò ù" in raw_store

    mid = json.loads(raw_store)["id"]
    raw_get = srv.get_memory(mid)
    assert "\\u00" not in raw_get
    assert "«perché»" in raw_get

    opened = json.loads(srv.desk(action="open", title="Perché è lungo",
                                 objective="Obiettivo con è e —",
                                 done_when="così è fatto",
                                 plan=["primo"], project="p"))
    raw_desk = srv.desk_read(slug=opened["slug"], project="p")
    assert "\\u00" not in raw_desk
    assert "Perché è lungo" in raw_desk


def test_mcp_wire_has_no_structured_result_envelope_and_no_unicode_escapes(srv):
    """Passando dal layer MCP vero (non dalla funzione Python), FastMCP non
    deve avvolgere la risposta in `{"result": ...}` né emettere `\\u00`."""
    import asyncio
    from mcp.shared.memory import create_connected_server_and_client_session

    srv.register_project("p", "", [])
    srv.store_memory(content="Nota con è, à, «virgolette».", title="È viva", project="p")

    async def probe():
        async with create_connected_server_and_client_session(srv.mcp._mcp_server) as session:
            res_status = await session.call_tool("brain_status", {})
            res_list = await session.call_tool("list_memories", {"project": "p"})
            res_ctx = await session.call_tool("get_context", {"cwd": ""})
            return res_status, res_list, res_ctx

    for res in asyncio.run(probe()):
        assert not res.isError
        assert res.structuredContent is None, f"involucro indesiderato: {res.structuredContent!r}"
        assert res.content, "manca il contenuto testuale"
        text = res.content[0].text
        assert "\\u00" not in text
        assert not text.lstrip().startswith('{"result":')


def test_manual_documents_the_desk_rules(srv):
    """Il manuale contiene le tre regole operative della scrivania."""
    m = srv.manual().lower()
    assert "ombrello" in m
    assert "before" in m and "at_end" in m
    assert "open_question" in m
