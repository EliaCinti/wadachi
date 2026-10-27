"""Record di transcript nella forma reale, per i test degli hook e della statusline.

Copiati da un transcript di Claude Code 2.1.281, campo per campo dove conta:
`type`, `isSidechain`, `timestamp`, `message.usage` con `cache_creation` diviso
fra `ephemeral_1h` ed `ephemeral_5m`, i prompt umani con `content` a blocchi e
i tool_result che sono anch'essi record `user`. Un finto semplificato
renderebbe la suite verde e cieca: è proprio sui record `user` che non sono
prompt che una regola ingenua sbaglierebbe l'inizio del turno.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc)


def iso(t: datetime) -> str:
    """Il formato del transcript: millisecondi e `Z`."""
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


# ── record nella forma reale ────────────────────────────────────────────────


def _common(sid: str, cwd: str, when: datetime, sidechain: bool = False) -> dict:
    return {
        "parentUuid": str(uuid.uuid4()),
        "isSidechain": sidechain,
        "uuid": str(uuid.uuid4()),
        "timestamp": iso(when),
        "userType": "external",
        "entrypoint": "claude-vscode",
        "cwd": cwd,
        "sessionId": sid,
        "version": "2.1.281",
        "gitBranch": "main",
    }


def prompt(sid: str, cwd: str, when: datetime, text: str = "riprendi") -> dict:
    return {
        **_common(sid, cwd, when),
        "promptId": str(uuid.uuid4()),
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        "permissionMode": "auto",
        "origin": {"kind": "human"},
        "promptSource": "sdk",
        "turnOrigin": "human",
    }


def tool_result(sid: str, cwd: str, when: datetime) -> dict:
    return {
        **_common(sid, cwd, when),
        "promptId": str(uuid.uuid4()),
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_01", "content": "ok"}],
        },
        "toolUseResult": {"stdout": "ok"},
    }


def meta(sid: str, cwd: str, when: datetime) -> dict:
    return {
        **_common(sid, cwd, when),
        "type": "user",
        "message": {"role": "user", "content": "<local-command-caveat>Caveat"},
        "isMeta": True,
    }


def reply(sid: str, cwd: str, when: datetime, ctx: int, *, ttl: str = "1h",
          sidechain: bool = False, model: str = "claude-opus-5-5") -> dict:
    """Un turno dell'assistente. `ctx` è il contesto; la parte nuova va in cache
    con la durata `ttl`, come nei record veri (`ephemeral_1h` / `ephemeral_5m`)."""
    created = 2_000
    read = ctx - created - 2
    split = {
        "ephemeral_1h_input_tokens": created if ttl == "1h" else 0,
        "ephemeral_5m_input_tokens": created if ttl == "5m" else 0,
    }
    return {
        **_common(sid, cwd, when, sidechain),
        "message": {
            "model": model,
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "fatto"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 2,
                "cache_creation_input_tokens": created,
                "cache_read_input_tokens": read,
                "output_tokens": 300,
                "service_tier": "standard",
                "cache_creation": split,
                "iterations": [{
                    "input_tokens": 2,
                    "output_tokens": 300,
                    "cache_read_input_tokens": read,
                    "cache_creation_input_tokens": created,
                    "cache_creation": split,
                    "type": "message",
                }],
            },
        },
        "requestId": "req_01",
        "type": "assistant",
    }


def turn(sid: str, cwd: str, start: datetime, end: datetime, ctx: int, **kw) -> list[dict]:
    """Un turno com'è davvero: prompt, risposta con tool, tool_result, risposta."""
    mid = start + (end - start) / 2
    return [
        prompt(sid, cwd, start),
        reply(sid, cwd, mid, ctx - 1_000, **kw),
        tool_result(sid, cwd, mid + timedelta(seconds=1)),
        reply(sid, cwd, end, ctx, **kw),
    ]


def write(tmp_path: Path, records: list[dict]) -> str:
    f = tmp_path / f"{uuid.uuid4()}.jsonl"
    with f.open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return str(f)
