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


def test_the_menu_stays_under_the_threshold(srv):
    assert len(srv.exposed_tool_names()) <= 27


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
