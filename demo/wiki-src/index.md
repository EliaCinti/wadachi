# Welcome to the wadachi wiki

**Wadachi** (轍, *wa-da-chi* — the tracks wheels leave in a road) is a persistent,
local-first memory server for AI agents, spoken over MCP. Your sessions leave tracks;
future sessions follow them.

This wiki covers **everything**: how the brain works, every one of the 31 tools, every
CLI command, every safety mechanism, and the honest answers in the [[faq]].

> Meta-note: this wiki is itself built the way wadachi's brain is built — markdown
> files with wikilinks, compiled to plain HTML. What you're reading practices what
> it preaches.

## What wadachi is, in one paragraph

Most memory tools store and search. Wadachi's brain **behaves like one**: memories are
[[beliefs]] that can go stale and be superseded; [[decisions]] remember *why* and what
was rejected; a typed [[graph]] connects everything; it can [[time-travel]] to what it
believed at any date; and it periodically "[[sleep|sleeps]]" — proposing consolidations
that *you* approve. All of it local, in plain markdown you own, with zero telemetry.

## The four rules

Everything in wadachi follows four design rules:

1. **Local-first, privacy-first.** No telemetry, no cloud calls, no exceptions.
2. **Memories are sacred.** Nothing is ever lost or silently rewritten — versioning,
   migrations with backups, [[safety|export/restore]].
3. **Propose, never auto-edit.** The software suggests; the human decides.
4. **Degrade gracefully.** Everything works (or fails helpfully) without optional deps.

## Where to start

- What wadachi *is*, and which part of an agent it is → [[harness]]
- New here → [[installation]] then [[connect]]
- Want to understand the design → [[brain]], [[beliefs]], [[graph]]
- Daily workflow → [[get-context]], [[search]], [[sleep]]
- Worried about your data → [[safety]] (you should read it anyway — it's the best part)
- Quick lookups → [[tools]], [[cli]], [[troubleshooting]], [[faq]]
