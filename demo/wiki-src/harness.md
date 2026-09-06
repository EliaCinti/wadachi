# The harness — where wadachi sits

A stack is forming under AI agents, and it has renamed itself roughly once a year:

```
prompt  →  context  →  harness  →  loop
```

**Prompt engineering** was wording one request well. **Context engineering** was
curating what the model sees before each call. Both run into the same wall: the
context window fills up, quality falls off a cliff — *context rot* — and the usual
remedy, summarising the conversation to make room (*compaction*), buys that room by
throwing away precision.

**Harness engineering** is the answer to that wall. A harness is scaffolding *outside*
the model that re-initialises the agent step by step: every step opens with a fresh
context, reads the durable state the previous step left on disk, and resumes exactly
where the work stopped. Nothing gets summarised, because nothing had to fit.

> *Agent = Model + Harness.* The model is the part you rent. The harness is the part
> you build — and it is the part that decides whether an agent is reliable or merely
> clever.

## Wadachi is not a harness. It is the memory of one.

This is the boundary, and it is deliberate:

> **Wadachi never executes anything, and never decides when something starts.**

No runner, no sandbox, no scheduler — and it will not grow one. Wadachi answers what
is known and records what is learned. Running the agent, holding the cage, choosing
the moment: that all belongs to whatever harness is driving your agent — your coding
CLI, your agent framework, your own script.

That is a boundary, not a shortfall. A memory that also decided when to act would be
two products fighting inside one process, and you could not swap either half.

## The two layers

A harness needs memory over two very different horizons, and they are not the same
thing:

| | keeps | survives | status |
|---|---|---|---|
| **The hippocampus** | what you *learned* | the end of a **session** | built — most of this wiki |
| **The desk** | what you are *doing* | the end of a **context window** | on the roadmap |

### The hippocampus — built

The durable half. [[memories]] with versions, [[decisions]] that keep their rationale
and their rejected alternatives, [[beliefs]] that can go stale and be superseded, a
typed [[graph]] that connects them, and [[sleep]] to consolidate. It is what lets a
new session know what the last one figured out.

[[get-context]] is the resume step for this layer: one call at the start of a session,
and the knowledge is back without re-deriving it.

### The desk — not built yet

The working half: the plan for the task in flight, the steps already done, what was
tried and failed, where the thread was dropped. Today, when a session gets too long,
that state is either lost to compaction or written out by hand as a handover note.
The desk is the roadmap item that makes the harness's step-by-step resume real for
*work in progress*, not just for knowledge. Until it ships, this page says so plainly.

## Why the two must not be merged

Different lifetimes. What you learned should outlive everything; what you are doing
right now should be distilled or discarded when the task closes. Tip the desk into
the hippocampus and recall gets worse — the brain fills with the debris of finished
work, and the ranking has more noise to beat.

Wadachi already has a documented case of exactly that failure mode: recency-ranked
recall once *hid* the right rule and let the same mistake happen twice. That incident
is why procedural memory exists (see [[tools]] → `review_procedures`). The lesson
generalises: keep the layers apart.

## What about the loop?

**Wadachi has no agent loop, and is not getting one.** `reflect`, `sleep` and
`consolidate` look loop-shaped, but they are background maintenance of the brain: they
*propose*, and you approve. Deciding that work should start, iterating until a goal is
verified, capping the attempts — that is the loop, it lives in the harness, and it is
not wadachi's job.

This is just rule 3 of the [[index|four rules]] applied to the stack: **propose, never
auto-edit.** The software suggests; the human — or the harness the human chose —
decides.
