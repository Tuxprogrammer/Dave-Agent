# Plan: recipe knowledge and chain planning for Dave

Status: Stages 1, 2 and 4 live (2026-11-01): the export, `data/recipes.sqlite`, and the `recipes` MCP server with `recipe_producers`, `recipe_uses`, `recipe_get`, `item_find` and `plan_chain` (`tools/recipe-export/`, `tools/recipes/`). Stage 3 (search) is live separately; Stage 5's item-cost pass and plan JSON export are not done. Planned 2026-10-31. Target: our own GTNH 2.9.0 pack. Expect our custom mods (GregGuns, then TrainHorizons) to add recipes, so every stage below has to be re-runnable from the pack, never hand-patched.

## The question this answers

> "Dave, I am at HV tier, what is the best source of Nitrogen?"

Dave should reply with the best recipe chain. By default "best" means the least EU per item produced. The player can steer the answer:

- **Locks.** "I'm using the Vacuum Freezer route" means that recipe must be in the answer, and the rest of the chain is built around it.
- **Guidance.** "I have plenty of oxygen" makes that input free. "No Thaumcraft" bans those recipes.

## Three tools, each doing what it's good at

| Need | Tool | Why this tool |
|---|---|---|
| Exact facts: what makes X, what X is used in, a recipe's EU/t, duration, tier, cleanroom, coil heat | **Recipe database** (SQLite) + `recipe_*` MCP tools | A join is exact. Embeddings would rank about 290k recipes by similar wording and silently miss some |
| Fuzzy input: "liquid air", "N2", "that blue circuit", and how-to knowledge from the quest book, wiki and GuideNH | **Semantic search** (`gtnh_search`) | This is what embeddings are good at. It returns item IDs and document passages, which Dave then checks against the database |
| "Which chain is best" | **Chain planner** (`plan_chain`, an LP solver) | Comparing alternatives through cycles and byproducts is arithmetic. A model working it out turn by turn gets it wrong and spends a lot of tokens |

Dave's usual sequence:
1. `gtnh_search` to resolve names and gather written advice.
2. `recipe_producers` / `recipe_uses` for the facts.
3. `plan_chain` for the optimum.
4. Explain the result in chat, re-solving with locks if the player pushes back.

---

## Stage 1: Recipe export from our pack

**Exporter:** `gtnh-calc-oracle` from [jackwrichards/gtnh-factory-flow](https://github.com/jackwrichards/gtnh-factory-flow) (`tools/dataset-pipeline/`, MIT). A reference copy is in `.work/ref/`.

- It loops over every GregTech recipe map (`RecipeMap.ALL_RECIPE_MAPS`). GregGuns recipes added through the GregTech API are therefore picked up with no exporter changes.
- It also exports:
  - crafting table and furnace recipes;
  - Thaumcraft recipes;
  - bees and IC2/CropsNH crops;
  - Extreme Entity Crusher mobs;
  - ore veins, small ores and underground fluids;
  - ore dictionary entries.
- It **runs headless on a dedicated server.** Start it with `-Dgtnh.oracle.autorun=true`; it exports on `FMLServerStarted` and then exits. No client or virtual display is needed. Those only matter for icons and NEI layouts, which Dave doesn't use.
- Anything it couldn't export is listed in its report under "unsupported adapters". Treat a new entry there as a to-do. This matters most for TrainHorizons machines that don't go through GregTech.

**Alternatives considered** (from the survey, 2026-10-31):
- ShadowTheAge's NESQL fork: the best relational schema, but it needs a client, LGPL, about an hour and about 600 MB.
- drukoz/gtnh-planner's exporter: MIT and runs on a server, but its script assumes macOS.
- JamesArhy/gtnh-recipe-extractor: Parquet output, but 2.9 is untested.
- GregTech's own `RecipeChangeAudit.dump()`: no tool calls it. Through DaveBridge's eval it's a cheap **cross-check** on the live server.

**To verify before relying on it** (checked 2026-11-01 on our 2.9.0 server pack):
- [x] Cleanroom, low gravity, coil heat and fusion start EU are read from the recipe **metadata**, not the old special-value codes. Upstream only exported `mSpecialValue` (plus fusion start from `FUSION_THRESHOLD` metadata), so our copy of the oracle adds each recipe's whole metadata map ("Dave patch" in `GtnhCalcOracleExporter.java`), and `build_db.py` reads metadata first. Findings over 187,803 GT recipes: `coil_heat` is set on 4,166 and equals `mSpecialValue` on all of them; 18 EBF recipes carry heat only in `mSpecialValue` (kept as the fallback); `cleanroom` is set on 2,044 and **one** EBF recipe (3,200 K) has it only in the metadata, because GT derives the special value from metadata only when none was set explicitly; `low_gravity` (7) always matches; `fusion_threshold` on all 68 fusion recipes.
- [x] Programmed circuits are kept (zero-size stacks exported as not consumed; 34,155 circuit slots), and chanced outputs keep their chances (32,151). Input chances survive too (2).
- [x] The full export runs against a 2.9.0 **server** instance, headless, with `-Dgtnh.oracle.autorun=true`: 261,217 raw recipes, 328 MB JSON, about 80-100 s of server time (Java 25 on the laptop; Java 21 on test-host, which `run.sh` can use through `RECIPE_EXPORT_HOST`). Two exports (Java 25 and Java 21) gave the same recipe hashes except 22 of 252,736 (19 CropsNH crop-breeder entries with rolled values, 2 infusion, 1 assembly line). What a server **cannot** export: Thaumcraft arcane crafting grids (they come from NEI on a client; those 621 recipes keep only output and vis and are flagged `incomplete`), essentia smelting (a client-only creative-tab call; partial) and CropsNH crop cards (client classes). 215 crafting recipes of IRecipe classes the exporter cannot read have no inputs and are flagged `incomplete` too. Neither kind is ever planned.

**What `run.sh` puts in the server:** stock 2.9.0 + GregGuns, Fortunate One and WorldEdit from `tuxmine/server/`. DaveBridge, DiscordIntegration and JourneyMap Unlimited are left out (no recipes; DaveBridge opens a WebSocket listener and DiscordIntegration logs in to Discord); `RECIPE_EXPORT_SKIP` changes that. GregGuns' recipes arrive both through its GT maps (`gregguns.ammoPress`) and the crafting table.

**Running it:**
1. Make a throwaway copy of our server pack under `.work/`. Never use the production container.
2. Add the oracle jar and accept the EULA.
3. Start with autorun on, then collect `GTNH-Calc-Oracle/gtnh-oracle-*.json`.

This is `tools/recipe-export/run.sh <pack-dir>` (pack-dir = the extracted stock server zip, e.g. `.work/gtnh-2.9.0/pack`), run on every pack change. It ends by building the database.

**Recipe IDs change between exports.** Key everything Dave saves on a content hash (map, inputs, outputs, EU/t, ticks), never on the exporter's ID. Their `carry-recipe-ids.mjs` shows the approach.

## Stage 2: Recipe database

Normalize the oracle JSON into `data/recipes.sqlite`:

| Table | Columns / contents |
|---|---|
| `items` | `id`, `kind` (item/fluid/essentia), `name`, `mod`, `oredict[]`, `tooltip` |
| `recipes` | `id`, content hash, `map`, `machine`, `tier`, `eut`, `ticks`, `amps`, `circuit`, `cleanroom`, `lowgrav`, `heat`, `special` (JSON) |
| `recipe_io` | `recipe_id`, `side`, `item_id`, `amount`, `chance`, `consumed`, `oredict_alts[]` |
| `machines` | Machine family, tier range, parallel/overclock kind (from the oracle's catalysts) |
| `raw_resources` | Default cost class per raw input: `free` (water, air, cobble), `cheap` (common ores), `costly`, `never` |
| `pack_meta` | Pack version, export time, list of mods with versions |

FTS5 full-text search over item names is a cheap exact-name fallback alongside the embeddings.

Their `normalize-oracle-export.mjs` (MIT) already has many hard-won rules: machine families, oredict alternatives, cells vs fluids. **Read it and port its rules; don't rediscover them.** Ported in `build_db.py` (its docstring lists them). Not ported: NEI layouts, icons, the synthesized "Tank" recipes, Sparge rolled byproducts, bees, crops, mob drops and ore veins (the export has them; `pack_meta.not_normalized` lists them). As built: 252,736 recipes, 893,977 io rows, 67,180 items, 181 maps, 154 MB, about 15 s and 1.6 GB peak memory. `recipes` also has `recycle` (GT's recycling flag), `fake` and `hidden`; `items` has `producers` and `uses` counts.

## Stage 3: Semantic search (`gtnh_search`)

This is a port of GregGuns' `tools/semantic-search`, which has the same owner. Keep the same shape:
- `semsearch.py` (corpus, chunking, embedding, `.npz` index);
- `index.py` (CLI);
- `server.py` (stdio MCP server);
- `test_semsearch.py` (offline tests).

Keep the same behaviour too: only changed chunks are re-embedded (keyed on a content hash), vectors are normalized so a search is one matrix product, there's a lock file, and the server refreshes in the background.

**What changes:**
- The corpus comes from **generated directories**, not `git ls-files`.
- There's one chunker per source, plus a `kind` filter.

| `kind` | Source | One chunk = |
|---|---|---|
| `quest` | BetterQuesting data and lang in the pack's `config/` (copied to `gtnh-src/config/`) | One quest: chapter, title, description, required items (resolved to names and IDs), rewards, prerequisites |
| `guide` | GuideNH pages from the pack's `config/guidenh/DefaultGuide.zip` (GTNH Guide Pack, CC BY-NC-SA 4.0) | One page section |
| `wiki` | wiki.gtnewhorizons.com from **Miraheze's official monthly XML backup on archive.org** (`miraheze-wiki-gtnhwiki-YYYYMMDD`, imported with `mirror_wiki.py --from-dump`). The wiki is CC BY-SA 4.0, and its robots.txt disallows the API, so we never crawl it | One page section, keeping its heading path |
| `item` | Generated from the recipe DB: name, aliases, oredict, mod, tooltip, the machine types that make it and its top uses | One item or fluid |
| `lang` | `en_US.lang` from every mod jar, which covers machine tooltips and structure hints | One mod's entries, split by size |
| `playbook` | Dave's own saved answers and solved chains (Stage 5) | One saved answer |
| `code` | **Real source** for the core mods, checked out at the exact tags 2.9.0 ships: GT5-Unofficial (with GT++, BartWorks, KubaTech and the rest merged in), GTNHLib, AE2, and our own GregGuns and TrainHorizons. Kept in a **separate index** that uses a code embedding model (`voyage-code-4`, as in GregGuns) | One class member, using the GregGuns Java chunker |

- **Not embedded:**
  - Individual recipes: the database answers those exactly.
  - The decompiled Java in `gtnh-src/` for every other mod. Decompiled code has no comments and garbled local variable names, so it embeds poorly. A whole-pack build would cost tens of dollars and bury the useful hits. Dave greps it instead.
  - A mod moves into the `code` index only when questions keep landing on it.
- **Machine → code is an exact lookup, not search.** DaveBridge reflection on the live server maps a held or targeted machine (or its meta ID) to its Java class, recipe map and tooltip. Item cards for machines carry that class plus its source path. "Where's the code for the Vacuum Freezer" is one lookup; `gtnh_search kind=code` handles behaviour questions ("where is the coil heat discount applied").
- **Version the `code` index too.** It's pinned to the source tags of the pack it was built from and rebuilt incrementally on a pack change. Use `index.py --stats` for the cost before the first build.
- **Model: `voyageai/voyage-4`** (picked 2026-10-31). On 32 player questions:
  - It had the best MRR, 0.753, and recall@10 of 0.97.
  - All four candidates scored within about one question of each other.
  - It won on vector size: 1,024 dimensions, so an index with item cards stays around 0.6 GB in memory, against about 2.5 GB for Qwen3-8b at 4,096.
  - It's in the same family as `voyage-code-4` for the code index.
  - A full prose build costs about $0.26.
  
  Re-run `eval.py` before switching models.
- **Key:** `OPENROUTER_API_KEY` in a git-ignored `.env` at the repo root. It is used only for embeddings and is unrelated to Claude's subscription auth.
- **Privacy:** player questions are sent to OpenRouter as search queries. Keep `provider.data_collection: "deny"`.
- **Rough cost:**
  - item cards: about 100k × 100 tokens;
  - wiki, quests, guide and lang: about 20 to 40M characters.
  
  That's a few dollars for a full build at current embedding prices. Run `index.py --stats` for the real figure before the first build.

### Keeping the wiki fresh (container job)

Our wiki copy is a **living document**, not a mirror. Official Miraheze dumps are upstream updates that arrive roughly monthly; between them, Dave edits the wiki as he discovers what is true on our pack. The design is in [living-wiki.md](living-wiki.md). In short, a git repo in the container's volume has two branches:

- `official`: one commit per imported dump;
- `living`: official plus Dave's evidence-backed edits. Search indexes `living`.

The wiki states what is true now; history goes in commit messages.

- **Schedule.** A cron runner inside the Dave container ([supercronic](https://github.com/aptible/supercronic), which logs to stdout) runs `update_wiki.py` **weekly**.
  - Each run costs one archive.org search query, and the job acts only when a new dump exists.
  - Weekly beats a fixed monthly date because Miraheze's dumps arrive irregularly: on different days of the month, and with gaps (none in Jan–Feb or May–Jul 2026).
- **Each run:**
  1. Find the newest `miraheze-wiki-gtnhwiki-*` item. If it's newer than the newest dump on `official`, download only `gtnhwiki-YYYYMMDD.xml.gz` (about 35 MB; skip the 1.2 GB images) and check its md5 against archive.org's metadata.
  2. Import it as a new commit on `official`.
  3. Merge `official` into `living`:
     - pages Dave never touched update cleanly, and non-overlapping hunks merge automatically;
     - only conflicted pages go to Sonnet (Claude Code CLI on the owner's subscription, no tools), one call per page, with the merge base, the new official text, the living text and Dave's edit reasons and evidence;
     - a contradiction keeps Dave's evidence-backed version and is flagged; the losing text goes to the merge report and the review queue, never the page;
     - output that fails validation falls back to a lossless section merge, which is also flagged;
     - pages deleted officially are deleted on `living` too, unless Dave edited them; those are kept and flagged.
  4. Run an incremental index build of the merged result, which re-embeds only changed chunks (cents).
  5. Move the branches, swap in the search corpus and the index atomically, and log a one-line summary. A JSON merge report records clean, auto-merged, Sonnet-merged, fallback and flagged pages.
  
  Any failure keeps the previous branches, corpus and index. Never half-update.
- **Storage.**
  - The image bakes a seed corpus and index read-only. At startup the container copies them into a **writable volume** if the volume is missing them or is older than the image.
  - The living wiki repo (`<volume>/wiki-git`) is created from the image's baked dump **only when the volume has none**. After that the volume is the source of truth, and a new image never overwrites or rolls back the wiki.
  - If an image carries a newer official dump than the volume has seen, it goes through the same merge as a monthly update.
  - The wiki refresh, Dave's wiki edits, and the playbook and memory embeddings write only to the volume.
  - `living_wiki.py export` writes a git bundle for backup into the dev repo.
- **Reload.** `server.py` notices a new index file (by mtime) and reloads it between queries, with no restart.
- **Secrets.** The job needs `OPENROUTER_API_KEY`, from a runtime secret through `OPENROUTER_API_KEY_FILE`, and `CLAUDE_CODE_OAUTH_TOKEN` for the Sonnet merges.
- **Pack updates** (quest, guide, lang, recipes) still go through an image rebuild from this repo, because they change with the pack, not the calendar.

**Tool for Dave:** `gtnh_search(query, k=8, kind="any"|quest|guide|wiki|item|lang|playbook)`. Each hit returns its source, title, score, a snippet, and **item IDs** when the hit is an item card, ready to pass to the recipe tools.

## Stage 4: Chain planner (`plan_chain`)

No existing GTNH planner chooses recipes for you; they all balance recipes the user has already placed (survey 2026-10-31). We use the pattern general factory planners use.

**1. Candidate graph.** Walk backwards from the target through `recipe_io`. At each step, filter by:
- tier ≤ the player's tier;
- the coil heat and cleanroom they have;
- banned mods and recipes.

Stop at raw resources and at a depth or size limit.

**2. LP** (HiGHS through `highspy`):
- one rate variable per recipe;
- one balance row per item (production − consumption + import − surplus = demand);
- byproducts go to surplus;
- cycles need no special handling.

The objective is **lexicographic**, in the style of OrderedSet86/flow2. Each stage is solved with the previous stage's optimum held:
1. EU per target item.
2. Raw-resource cost, weighted by `raw_resources` class. Without this, "free" lava, air or water routes look absurdly good.
3. Machine count.
4. Total flow.

**As built** (`tools/recipes/planner.py`): stage 1 is EU per item **plus raw resources at an EU-equivalent price by class** (free 0, cheap 2,000, costly 100,000 per item or 1,000 L; anything unexpanded or unavailable at the player's tier 10,000,000). Pure machine EU made every ore-electrolysis byproduct route "best" for nitrogen, because mining costs no EU. Stages 2-4 follow as above. Recipes with 0 EU and no consumed input are never planned (the Eye of Harmony, algae pond and tree growth simulator recipes yield from nothing as data, and won every plan), nor are recycling, display-only (except the assembly line, rock breaker and tree farm maps) and incomplete recipes. Crafting tools are not consumed. Machine counts are at base speed. Golden tests: HV nitrogen = Multiblock Centrifuge on free air, 11,200 EU per 3,900 L = 2,871.8 EU per 1,000 L; the Vacuum Freezer route = air -> liquid air (VF) -> centrifuge, 17,993.5 EU per 1,000 L; EBF steel honours coil heat. Known gaps: ore commonness is not modelled (every ore is "cheap"), slot alternatives are not substituted, and 0-EU primitive machines (Bricked Blast Furnace, Coke Oven) win "least EU" for steel unless the player locks the EBF.

**3. Steering:**

| Player says | Becomes |
|---|---|
| Lock a recipe | `rate ≥ ε` (or a fixed rate). As built: a lock (recipe `#hash` or machine) holds in the strongest feasible form: the locked step makes the target and nothing else does; else the target is made 1-3 steps downstream from what it makes (a flow constraint per link; empty cells and buckets are not links); else it only has to run. The plan says which |
| "I have plenty of X" | X's import is free |
| "No X" | X's import is 0 |
| "Don't use machine Y" | Drop those recipes |

**4. Item costs** (YAFC's dual pass, optional): one solve per tier gives an EU-per-unit price for every item. "Best source of X" then becomes a ranked lookup, and Dave can say why one route beats another.

**5. Machine counts and overclocks.**
- Don't copy the formulas by hand; gtnh-flow's EBF heat rule has already drifted from GregTech.
- Ask the live server through DaveBridge eval to run GregTech's own `OverclockCalculator`.
- Note: with standard overclocking, EU per item goes **up**, so the least-EU answer usually means not overclocking. Overclocks change machine counts, not the ranking.

**Tool output:**
- the chosen recipes with rates;
- machines and counts per tier;
- EU/t total and EU per item;
- imports and byproducts;
- the runner-up route and why it lost.

That is enough for Dave to explain the answer in three chat lines and go deeper when asked.

## Stage 5: Playbook and delivery

- **Playbook.** This is the priority in this stage, because it's what makes Dave a knowledge base that grows over time rather than a stateless answerer.
  - Good solved answers are saved under `data/memory/playbook/` (one Markdown file each, written by the `dave-memory` MCP server; see [dave-core.md](dave-core.md)) with the question, constraints, result and pack version.
  - They are embedded as `kind=playbook` and marked stale when the pack version changes.
  - Dave checks the playbook before solving from scratch, and cites earlier answers ("last time Alex asked this…").
  - Players can correct an answer in chat, and a corrected answer replaces the old one.
- **Plans in game (later).** Write the result as Factory Flow plan JSON. The player can open it at gtnhplanner.com, or Dave can hand it to the client-side GTNH Planner mod (jackwrichards/gtnh-planner-mod, MIT). That mod accepts plans over localhost after asking the player, which fits DaveBridge's opt-in client side. PlanNH (GTNewHorizons, MIT) is the other in-game target.

## Build order

1. **Export:** run the oracle on a throwaway 2.9.0 server copy, then check the "verify" list above.
2. **Database:** SQLite plus the `recipe_producers`, `recipe_uses`, `recipe_get` and `item_find` (FTS) tools.
3. **Search:**
   1. Port the semantic-search code and add the item and quest corpora.
   2. Run the model eval, then do the full build.
   3. Add the wiki, guide and lang corpora.
4. **Planner:** `plan_chain` with lexicographic HiGHS, raw-resource costs, and locks and bans. Use a golden set of known-good chains (HV nitrogen, EBF steel, …) as tests.
5. **Playbook, item-cost pass, and plan JSON export.**

All of these become MCP tools in one Python server under `tools/`, registered with Dave's long-lived Claude process through `--mcp-config` / `--strict-mcp-config`.
