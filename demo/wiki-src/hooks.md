# Claude Code hooks

Four optional scripts in `scripts/` keep long sessions cheap, resume work cleanly
after `/clear`, and back up the brain automatically. None of them require extra
MCP tools — they talk to Claude Code's native hook points and stay silent when
nothing needs attention.

> Hooks do not inherit the MCP server's environment. Pass `BRAIN_DIR` in the hook
> command; without it, every script stays silent rather than guessing a brain.

## What each script does

| script | hook | what it does |
|---|---|---|
| `scripts/session-weight.py` | `UserPromptSubmit` | Measures the active context from the session transcript and warns the model once per threshold band as the window fills. After a pause longer than the prompt-cache lifetime, **blocks the prompt once** (`decision: "block"`) before it hits the model, telling you how much the cold cache rewrite would cost (~20 warm turns) and whether the desk was updated on the last turn. Sending again goes through. |
| `scripts/resume-desk.py` | `SessionStart` (`startup\|clear`) | Injects the project's open desk (objective, stopping condition, next step, last two log entries, open questions — capped around 1.2k tokens) so `/clear` picks up at the right step with zero tool calls. Outside any registered project (e.g. an editor opened on `~`), lists the five most recently updated open desks across all projects, with project and calendar age, and asks you which to resume. |
| `scripts/statusline.sh` | `statusLine` | Shows context weight (green / yellow / red on the same thresholds), plan quota, and the prompt-cache countdown: `cache 42m`, then `cache fredda`. |
| `scripts/backup-brain.sh` | `Stop` (`async`) | Creates a compressed snapshot of the brain directory, keeping the last 10 archives. |

## Why the prompt-cache guard exists

Prompt caching keeps your context warm for one hour after the last turn (or five
minutes outside the plan; the script reads the actual TTL from the transcript's
`usage` fields). While warm, rereading context costs 0.1×. After a pause longer
than the TTL, the very first turn rewrites the entire context into cache at 2× —
roughly twenty warm turns' worth of tokens in a single message.

Because the guard runs inside `UserPromptSubmit` and returns `decision: "block"`,
the message never reaches the model and costs **zero tokens**. If your desk is
already up to date, you can run `/clear` instead of paying for a cold rewrite;
`resume-desk.py` immediately puts the desk back in front of the fresh session.

## Setup (`~/.claude/settings.json`)

```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "timeout": 10,
        "command": "BRAIN_DIR=/path/to/brain /path/to/wadachi/venv/bin/python /path/to/wadachi/scripts/session-weight.py"
      }]
    }],
    "SessionStart": [{
      "matcher": "startup|clear",
      "hooks": [{
        "type": "command",
        "timeout": 10,
        "command": "BRAIN_DIR=/path/to/brain /path/to/wadachi/venv/bin/python /path/to/wadachi/scripts/resume-desk.py"
      }]
    }]
  },
  "statusLine": {
    "type": "command",
    "command": "/path/to/wadachi/scripts/statusline.sh"
  }
}
```

## Environment variables (all optional)

| variable | default | effect |
|---|---|---|
| `WADACHI_CACHE_GUARD` | on | Set to `off` to disable the cold-cache block |
| `WADACHI_GUARD_MIN` | `40000` | Minimum context tokens before the cache guard triggers |
| `WADACHI_CACHE_TTL` | read from transcript | Override the cache lifetime in seconds |
| `WADACHI_WEIGHT_NOTICE` | `50` | Context % for the first soft reminder |
| `WADACHI_WEIGHT_WARN` | `75` | Context % for the stronger warning |
| `WADACHI_WEIGHT_URGE` | `90` | Context % to strongly advise distilling and restarting |

See also: [[harness]], [[get-context]], [[tools]].
