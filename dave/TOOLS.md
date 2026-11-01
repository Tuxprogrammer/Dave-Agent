# Dave's tools

Every tool Dave has or will have. **Live** means it is in Dave's process today (when its server script exists,
`dave_cmd.py` registers it automatically). **Planned** tools are deliberately absent from `launch/mcp.json` until
they exist, so Dave never sees a tool that fails. SOUL.md names capabilities generically ("recipe tools",
"chain planner") and says to use only tools in the tool list, so adding a server here needs no SOUL change.

How tools reach Dave: built-in tools are chosen with `--tools`; MCP servers come only from the rendered
`launch/mcp.json` (`--mcp-config` + `--strict-mcp-config`); permissions come only from the rendered
`launch/settings.json` (`--settings`, with `--setting-sources ""` so no other settings file is read). Details
and the full command: `python3 -I dave/launch/dave_cmd.py --print`.

## Built-in Claude Code tools

| Tool | Status | Scope | Notes |
|---|---|---|---|
| `Read` | live | `gtnh-src/` and `data/corpus/` via `--add-dir`, read-only | `gtnh-src/_decompiled/` is denied (superseded decompiles that duplicate every hit) |
| `Grep` | live | same | Read deny rules also govern Grep and Glob |
| `Glob` | live | same | |
| `WebFetch` | live | `wiki.gtnewhorizons.com` only | Allow rule `WebFetch(domain:wiki.gtnewhorizons.com)`; with `dontAsk`, any other domain is refused |
| `Agent` | live, **recipe-planner only** | spawns the one custom agent below | Reported as `Task` (its legacy name) in the CLI's init event. See "Subagent" |
| Bash, Edit, Write, NotebookEdit, WebSearch | **not available** | | Not in `--tools`, and also in the deny list. `--restricted` additionally strips code-running tools |

Permission mode is `dontAsk` with `--permission-prompts none`: anything not explicitly allowed is refused
without a prompt (nobody is at a terminal to answer). `--restricted` also confines the file tools to the
working directories (an empty cwd plus the two add-dirs).

## Subagent: `recipe-planner` (live; model from `[model] planner`, default `opus`)

Defined in `launch/agents.json` (template) with its prompt in `dave/soul/recipe-planner.md`; `dave_cmd.py`
renders it to `<run>/agents.json` and passes `--agents <file>`. Dave delegates multi-step chains, factory
designs and route comparisons; simple lookups stay with Dave (SOUL "Using your tools"). It returns a compact
checked result (ANSWER / CHAIN / TOTALS / RUNNER-UP / ...) that Dave turns into chat markup.

| Field | Value |
|---|---|
| `tools` | Read, Grep, Glob, `gtnh_search`, `memory_recall`, `memory_get`, `player_get` (memory read-only), and the `recipes` tools (`recipe_producers`, `recipe_uses`, `recipe_get`, `item_find`, `plan_chain`). Tools of MCP servers that aren't registered are dropped at render time |
| `maxTurns` | 40 |
| `omitClaudeMd` | true (on top of the global CLAUDE.md shutdown) |

**Only this agent can be spawned.** The Agent tool is in `--tools` for it alone:
- `Agent(recipe-planner)` is allowed in `launch/settings.json`;
- every built-in agent type is denied by name: `claude`, `general-purpose`, `Explore`, `Plan` and
  `statusline-setup`, in both the `Agent(...)` and legacy `Task(...)` spellings (the CLI normalizes `Task` to
  `Agent`, as the debug log shows);
- `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1` removes Explore and Plan entirely.

The CLI's init event still lists claude, general-purpose and statusline-setup (that list isn't
permission-filtered), but a spawn is checked against the deny rules. `dave_cmd.py --probe` fails if any listed
agent type other than recipe-planner lacks a deny rule, so a new built-in agent in a future CLI version is caught.

Opus usage counts more heavily against the subscription's limits than Sonnet, so delegation is for real
planning work only.

## MCP: `dave-memory` (live, owner: Dave core)

`dave/memory/server.py`, store in `dave/memory/store.py`, data in `data/memory/` (`DAVE_MEMORY_DIR`).

| Tool | Does |
|---|---|
| `memory_recall(query, kind?, player?, k=8, include_stale=false)` | Keyword (BM25) ranking over title, tags and body. Stale playbook entries hidden unless asked. Ranking is a swappable hook (`Store.ranker`) for semantic search |
| `memory_get(id)` | One memory in full, with effective status |
| `memory_save(kind, title, body, tags?, player?, supersedes?)` | New playbook / server / lessons entry. Refuses near-duplicate titles (word overlap at least 0.85) and names the entry to update |
| `memory_update(id, body?, title?, tags?, status?, reverify?, note?)` | New logged revision. `reverify` re-stamps a stale entry with the current pack |
| `memory_correct(id, correction, by_player, body?)` | Player correction, credited. Playbook: new entry, old one superseded. Others: in place |
| `memory_forget(id, reason)` | Archive (never deletes) |
| `player_get(player)` | Profile by name, former name or UUID |
| `player_note(player, fact, field?, name?)` | Dated fact into a profile field: tier, base, setup, preferences, client_eval, notes |
| `memory_list(kind, status?)` | Ids, statuses and titles |

Every player is a trusted op (owner's policy), so there is **no per-player gating**: anyone may ask what Dave
knows about them or others, read or edit any memory, or have something forgotten. The write tools take
`asked_by` (the asker from `<player>`), and `.log.jsonl` records it on every change, next to `by` (the writing
process). `memory_correct` logs `by_player` as the asker.

Not an MCP tool: `load_turn_context(player_uuid, query, player_name)` and `Store.ensure_player(uuid, name)` are
Python functions the daemon calls to build the envelope (see `ENVELOPE.md`).

## MCP: `gtnh-search` (live once its agent finishes; owner: gtnh-search agent)

`tools/gtnh-search/server.py`. Registered automatically when that file exists (it does now). Semantic search
over quests, GuideNH, the wiki mirror, item cards, lang, `playbook` (from `data/memory/playbook/`) and `memory`
(server facts and lessons).

| Tool | Does |
|---|---|
| `gtnh_search(query, k, kind)` | Resolve fuzzy names, find prose. Returns item ids for the recipe tools |
| `gtnh_search_status()` | Index state |
| `gtnh_reindex()` | Incremental refresh (only changed passages are embedded), e.g. after a playbook save |

Environment passed by `mcp.json`: `GTNH_SEARCH_ROOT`, `GTNH_SEARCH_DATA`, `GTNH_SEARCH_INDEX_DIR`,
`GTNH_MEMORY_DIR` (its own names), plus `OPENROUTER_API_KEY_FILE`. The key itself is never in Claude's
environment. **Open item for the gtnh-search agent:** today `load_key` reads only `OPENROUTER_API_KEY` or
`<root>/.env`. That works in dev, but in the container it should also read the file named by
`OPENROUTER_API_KEY_FILE` (a docker secret or the 0600 file `dave_cmd.py` writes), as a raw key or a dotenv
line.

## MCP: `living-wiki` (live; `tools/living-wiki/`, design in `docs/plans/living-wiki.md`)

The server's own wiki, which Dave keeps current: a git repo whose `official` branch takes each Miraheze dump and
whose `living` branch adds Dave's edits. It shares `GTNH_SEARCH_STATE` (`[search] state`) with `gtnh-search`.

| Tool | Does |
|---|---|
| `wiki_get(page)` | Read a page |
| `wiki_search_titles(query)` | Find pages by title |
| `wiki_edit(page, text, reason, evidence, asked_by)` | Rewrite a page; becomes a git commit with Reason / Evidence / Asked-by trailers |
| `wiki_create(page, text, reason, evidence, asked_by)` | New page, same commit trailers |
| `wiki_history(page)` | A page's commits |
| `wiki_revert(page, commit, reason)` | Undo an edit |

Rule for Dave (in SOUL): the wiki says what is true now. Pages are written as current fact in a neutral voice,
with no "used to" or "(corrected by Dave)". The old claim and why it changed go in `reason` and `evidence`, and
every edit needs evidence. Allowed in `launch/settings.json`; `recipe-planner` gets read-only `wiki_get`.

## MCP: `recipes` (live; `tools/recipes/`, plan in `docs/plans/recipe-knowledge.md`)

`tools/recipes/server.py` over `data/recipes.sqlite`, exported from **our own pack** (stock 2.9.0 plus the
`tuxmine/server` mods, GregGuns included) by `tools/recipe-export/run.sh` and built by `tools/recipes/build_db.py`.
The database path is `[paths] recipes` / `DAVE_RECIPES_DB` (production: the read-only copy baked into the image,
e.g. `/dave/ro/recipes.sqlite`); a rebuilt file is picked up between calls. Standard library only, except
`plan_chain`, which needs `highspy` (`tools/recipes/requirements.txt`; the image pip-installs it). Without it the
other four tools still work and `plan_chain` says what is missing. In dev, run `dave_cmd.py` with a Python that has
highspy (the MCP servers use `sys.executable`).

| Tool | Does |
|---|---|
| `recipe_producers(item, tier?, heat?, cleanroom?, machine?, limit, offset)` | Recipes that make an item or fluid: machine, tier, EU/t, seconds, total EU, circuit, cleanroom, coil heat, every input and output with amounts, chances and slot alternatives. Real production first, recycling last |
| `recipe_uses(item, ...)` | Recipes that consume or need it, same format |
| `recipe_get(id)` | One recipe by its `#hash` (a content hash, stable across exports of the same pack), with its raw GT metadata and the machines that run its map |
| `item_find(name, k, kind?)` | FTS5 name search: ids, kinds, mods, ore dictionary names, producer and use counts |
| `plan_chain(target, rate?, tier, heat?, cleanroom?, lowgrav?, locks?, free?, banned?, max_depth?, runner_up?)` | LP optimum (HiGHS, lexicographic: EU per item with raw resources priced by class, raw cost, machines, flow): chosen recipes with runs/s and machine counts, EU/t, EU per item, imports, byproducts, the runner-up and why it lost |

Item ids: `<mod>:<name>[@meta]` (lowercase, meta 0 omitted), `fluid:<name>`, `aspect:<tag>`, `ore:<oredict>`.
Allowed with `mcp__recipes`; `recipe-planner` gets all five.

## MCP: `bridge` (planned; owner: the daemon, M2/M3)

Exposed by the Dave daemon over the DaveBridge WebSocket (`DaveBridge/PROTOCOL.md`).

| Tool | Does |
|---|---|
| `say(markup, target?)` | Post mid-turn (progress on a long job). Normal replies are the turn's final text, not this tool |
| `describe(target)` | What a block, entity or item is at runtime: class, meta id, recipe map, tooltip |
| `eval(script, side="server" or "client", confirm?)` | Groovy in the live JVM on the main-thread queue. Anything that changes the world requires the player's in-game confirm; client side only for opted-in players |
| saved queries (`query_run`, `query_save`) | Reusable named scripts that worked |
| `list_players()` | Who is online |

To add it: an entry in `launch/mcp.json` (its transport is the daemon's choice) and an `mcp__bridge` allow
rule.

## Adding a tool (checklist)

1. Server script exists and passes its own tests.
2. Entry in `launch/mcp.json` (paths as `${APP}`, `${ROOT}` and so on; secrets as file paths, never values).
3. `mcp__<server>` (or per-tool `mcp__<server>__<tool>`) in the `allow` list of `launch/settings.json`;
   anything Dave should never call goes in `deny`.
4. Update this file. Change SOUL.md only if Dave needs a new habit, not a new tool name.
5. `python3 -I dave/launch/dave_cmd.py --print` shows the server; the next session sees it.
