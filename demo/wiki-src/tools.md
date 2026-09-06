# Tool reference — all 37

Grouped by area, as this page always has been. The server itself groups tools
by *moment of use* instead: **26 in the menu** by default (the work toolset,
below with no tag) and **11 more for brain maintenance**, marked
*(maintenance)*, that stay out of the menu until asked for — from the CLI
(`wadachi sleep`, `wadachi doctor`) or by setting
`WADACHI_TOOLSETS=work,maintenance` for a session. `manual` prints the full
description of any of the 37. Args in *italics* are optional.

## Memory

| tool | args | does |
|---|---|---|
| store_memory | content, title, *project, tags, category* | save knowledge ([[memories]]) |
| get_memory | memory_id | full content by id; counts as access |
| list_memories | *project, category* | browse the index |
| update_memory | memory_id, *content, tags* | replace — previous version kept |
| delete_memory | memory_id | permanent (prefer flag_stale) |
| memory_history | memory_id | all prior versions |

## Search & context

| tool | args | does |
|---|---|---|
| get_context | *cwd, task_description, limit, max_tokens, format* | dense session start + proposals ([[get-context]]) |
| recall | query, *project, limit, neighbors* | semantic/keyword search, annotated ([[search]]) |
| expand_memory | ids | batch pointer → full content (max 10) |
| brain_status | — | health, search mode, stats, projects |
| brain_watermark | *project* | current position (highest id per table) — take it before starting work |
| changed_since | watermark, *project* | what appeared after a position taken earlier |
| manual | — | full description of every tool, in the menu and out |

## Decisions & projects

| tool | args | does |
|---|---|---|
| store_decision | decision, *rationale, alternatives, context, project* | record a choice ([[decisions]]) |
| list_decisions | *project, limit* | recent decisions |
| register_project | name, *description, paths* | enable auto-detection ([[projects]]) |
| list_projects | — | all registered |

## Desk

| tool | args | does |
|---|---|---|
| desk | action, *title, objective, done_when, plan, slug, outcome, distil, cwd, project* | open, close, or list a desk — the plan and progress for a task in flight |
| desk_read | *slug, cwd, project* | pick a desk's thread back up: plan, next step, what was already tried |
| desk_log | *slug, done, note, open_question, add, cwd, project* | tick the step that landed, note what failed, get the next step back |

## Graph

| tool | args | does |
|---|---|---|
| recall_associative | query, *project, limit* | spreading activation + baseline ([[graph]]) |
| related_memories | memory_id, *limit* | strongest typed neighbours |
| memory_graph | *project, focus_id, include_entities* | stats, hubs, orphans, Mermaid |
| rebuild_entity_graph | *project* | optional entity layer (local claude CLI) *(maintenance)* |

## Beliefs

| tool | args | does |
|---|---|---|
| review_beliefs | *project* | read-only stale scan ([[beliefs]]) *(maintenance)* |
| set_belief | memory_id, *confidence, status, valid_until, review_reason, superseded_by* | edit the envelope *(maintenance)* |
| flag_stale | memory_id, reason, *superseded_by* | confirm staleness — recoverable |

## Reflection & procedures — all maintenance

| tool | args | does |
|---|---|---|
| reflect | *project, limit, store_them* | cross-memory insight candidates ([[consolidation]]) |
| list_insights | *status* | the proposal queue |
| accept_insight | insight_id, *project* | promote to linked memory |
| reject_insight | insight_id | keep as rejected |
| review_procedures | *project* | incident clusters → candidate rules |

## Consolidation & time

| tool | args | does |
|---|---|---|
| sleep | *project, min_similarity* | the full housekeeping report ([[sleep]]) *(maintenance)* |
| consolidate | *project, threshold, max_groups* | similarity-based merge groups *(maintenance)* |
| merge_memories | source_ids, title, content, *project, tags* | your synthesis + supersession *(maintenance)* |
| why | question, *project, limit* | decision provenance ([[time-travel]]) |
| as_of | date, *query, project, limit* | the brain at a past date |
