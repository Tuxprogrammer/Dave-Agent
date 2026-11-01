# GTNH search

Gives Dave a `gtnh_search` tool that searches GT New Horizons knowledge by meaning, not by exact wording. It covers:

- the 2.9.0 quest book: one passage per quest, with its quest line, tasks, rewards and prerequisites;
- the GuideNH guide pages: GregTech machines and multiblocks, power, overclocking, AE2, Thaumcraft;
- the `en_US.lang` player text of every mod: item and machine names, tooltips, structure hints;
- an offline copy of wiki.gtnewhorizons.com, from Miraheze's archive.org backups and refreshed weekly (see [The wiki](#the-wiki));
- Dave's own saved answers (`playbook`) and server notes (`memory`);
- item cards, once the recipe database exists.

Dave uses it to turn a player's loose wording ("liquid air", "N2", "that blue circuit") into real item names and IDs, and to find written advice: which quest covers a machine, what a multiblock needs, how a mechanic works.

**Search resolves names and finds prose. It never decides which recipes exist.** Exact recipe facts come from the recipe tools, and the best chain comes from the planner (see [`docs/plans/recipe-knowledge.md`](../../docs/plans/recipe-knowledge.md)). Hits carry item and quest IDs so Dave can pass them straight on.

The code is ported from GregGuns' `tools/semantic-search` (same owner, itself ported from TrainHorizons, MIT).

## How it works

- **Corpus.** A registry of sources, one per `kind`. Each has a discover function, which reads its inputs into documents, and a chunker. The pack is parsed as data and never executed.

  | `kind` | Read from | One document = |
  |---|---|---|
  | `quest` | `config/betterquesting/DefaultQuests/` in the pack. In 2.9.0 the quest text is inline in each quest's JSON (`name:8`, `desc:8`), not in a lang file. Chapters come from `QuestLines/`. | One quest: quest line, title, description, tasks with item names, rewards, prerequisites and the quests it unlocks. Metadata: `quest_id` (BetterQuesting's base64 ID, as in the file names), `item_ids`. |
  | `guide` | `config/guidenh/DefaultGuide.zip` (the GTNH Guide Pack 0.1.26 resource pack, CC BY-NC-SA 4.0), plus any `assets/<ns>/guidenh/_en_us/*.md` in mod jars or `resourcepacks/`. | One page. Front matter gives `item_ids` and `quest_ids`; item tags become item names; 3D scenes and recipe widgets are dropped. Split at headings. |
  | `lang` | `assets/<ns>/lang/en_US.lang` in every jar and in the vanilla server jar, GregTech's multiblock tooltip Markdown (`assets/gregtech/lang/en_US/tooltip/*.md`), and a runtime `GregTech.lang` when one is in the pack directory or `data/corpus/lang/extra/`. | One mod's entries, split by size; one tooltip file. |
  | `wiki` | `data/corpus/wiki/`, written by `mirror_wiki.py --from-dump` and `update_wiki.py`. | One page, split at section headings, keeping the heading path. |
  | `item` | Stub. Will read `data/recipes.sqlite` (Stage 2 of the plan). | One item or fluid card, keyed `item:<mod:reg:damage>`: name, aliases, ore dictionary names, mod, tooltip, the machine types that make it and its top uses, with `item_ids` in metadata. Returns nothing until the database exists. |
  | `playbook` | `data/memory/playbook/*.md` | One saved answer: front matter (title, status, pack, asked-by, …) plus body. |
  | `memory` | `data/memory/server/` and `data/memory/lessons/` | One note. |

  `data/memory/players/` is never indexed. Memories whose `status` is `archived` or `superseded` are skipped.
- **Extraction cache.** `quest`, `guide` and `lang` documents are saved to `data/corpus/<kind>/docs.jsonl`, keyed on a fingerprint of their input files, so a refresh re-reads the pack only when it changed.
  - The fingerprint covers the pack files and the derived files the text depends on: the lang cache, `items.tsv`, GregTech's source in `gtnh-src/`, and `data/corpus/lang/extra/`.
  - Without the pack (the image, the volume), the cache is used as is and is never re-extracted from fallbacks such as `gtnh-src/config`.
  - An extraction that finds nothing never replaces a non-empty cache.
  - A refresh loads `lang` first and rebuilds item names on every pass, so a long-running server renders with current names.
- **Item names.** Quest tasks and guide tags name items by registry ID and damage. Names are looked up in this order:
  1. `data/corpus/names/items.tsv` (`mod:reg<TAB>damage-or-*<TAB>name`). Generate it from the recipe database once that exists; it fixes every name below.
  2. GregTech's generated items, worked out from its source in `gtnh-src/` (material IDs, ore prefixes, special metaitems, machine IDs; cached in `data/corpus/names/gregtech.json`, keyed on the source files, so a regenerated `gtnh-src` refreshes it).
  3. The `en_US.lang` keys a registry name usually maps to.

  On 2.9.0 this resolves 6,137 of the 9,601 quest task items (64%). The rest keep their raw ID, for example bees, Bartworks materials and some AE2 and GT++ parts.
- **Chunks.** At most 6,000 characters each; small neighbours are merged and long sections split. Each chunk is embedded as `[kind] title` plus its text.
- **Embeddings.** OpenRouter, with `input_type` set to `document` or `query` and provider data collection denied. Models that don't take `input_type` get a query instruction instead (`MODEL_OPTIONS` in `semsearch.py`). A refresh embeds only chunks whose text changed.
  - Document batches get 7 attempts with a 180 s timeout. A player's query gets 2 attempts with a 20 s timeout (`QUERY_ATTEMPTS`, `QUERY_TIMEOUT`).
  - Connection resets and truncated responses are retried like timeouts.
  - Redirects are refused, so the key is only ever sent to `openrouter.ai`.
- **Profiles.** Each index profile has its own model and index file (`PROFILES` in `semsearch.py`). Only `prose` exists now. The planned `code` index (a code model over real source) becomes a second profile plus its sources, with no other change.
- **Index.** `data/index/<profile>__<model>.npz`: git-ignored, written atomically (unique temporary file, fsync, rename), with a lock file so two builds never run at once. Vectors are normalized, so a search is one matrix product.
  - A build saves the vectors it has paid for every 1,024 chunks to `<index>.partial.npz`; after a failure, the next build of the same model starts from them.
  - An unreadable index file is moved to `<index>.npz.corrupt` and rebuilt. Until then the server answers as if there were no index.
- **Ranking.** Cosine similarity, at most three chunks per document. In a mixed search, `lang` gets at most a third of the slots, because its long key lists match item names strongly and would crowd out prose. Use `kind` to search one kind only.

## Setup

1. Put the OpenRouter key in `.env` at the repository root (git-ignored): `OPENROUTER_API_KEY=...`. If the `OPENROUTER_API_KEY` environment variable is set, it is used instead. The key is only for embeddings and has nothing to do with Claude's auth.
2. Extract the corpus from the pack (no API calls): `python3 -I tools/gtnh-search/index.py --extract`. It uses the newest `.work/gtnh-*/pack`, or `GTNH_PACK_DIR`.
3. Check the size and cost: `python3 -I tools/gtnh-search/index.py --stats`.
4. The model is `voyageai/voyage-4`, picked with the eval (see [Eval](#eval)). To change it, set `PROFILES` in `semsearch.py` and `PRICE_PER_MTOK` in `index.py`.
5. Build: `python3 -I tools/gtnh-search/index.py`.

The server refreshes the index in the background when it starts, and again when a search runs more than 10 minutes after the last refresh.

### MCP config for Dave

Dave's long-lived Claude process loads this with `--mcp-config <file> --strict-mcp-config`:

```json
{
  "mcpServers": {
    "gtnh-search": {
      "command": "python3",
      "args": ["-I", "/path/to/Dave-Agent/tools/gtnh-search/server.py"]
    }
  }
}
```

### In the container

The image bakes the corpus and index in read-only as a **seed**. At run time the container gets a **writable volume** for its own copy, and the OpenRouter key arrives as a runtime secret (it is needed to embed each query, and for the weekly wiki refresh). Everything can be moved with environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | — | The key itself. Takes precedence over the next two. |
| `OPENROUTER_API_KEY_FILE` | — | A file holding the key, e.g. a Docker secret. Used when `OPENROUTER_API_KEY` is unset. |
| (`.env`) | `<root>/.env` | Last fallback, for development. |
| `GTNH_SEARCH_ROOT` | the repository | Base for the defaults below. |
| `GTNH_SEARCH_DATA` | `<root>/data/corpus` | Corpus and extraction caches; with a state directory, the baked seed corpus. |
| `GTNH_SEARCH_INDEX_DIR` | `<root>/data/index` | Index files; with a state directory, the baked seed index. |
| `GTNH_SEARCH_STATE` | unset | The writable volume. When set, the live corpus and index are `<state>/corpus` and `<state>/index`, and every write goes there. |
| `GTNH_MEMORY_DIR` | `<root>/data/memory` | Dave's memories (written by `dave-memory`, only read here). |
| `GTNH_PACK_DIR` | newest `<root>/.work/gtnh-*/pack` | The extracted server pack; absent in the image. |
| `GTNH_SEARCH_READONLY` | off | `1`: serve the index as built and write nothing. |

- **Seeding.** `index.py --seed` copies the seed corpus and index into the state directory when it lacks them, or when its copy came from a different image. The image is identified by a stamp: the seed files' paths, sizes and mtimes, recorded in `<state>/seed.json`. It runs under `<state>/jobs.lock` and swaps each directory in whole. `server.py` also seeds at start, so forgetting the entrypoint step is harmless. `--seed` also creates the volume's living wiki (`<state>/wiki-git`, see [The wiki](#the-wiki)) from the baked wiki, **only when the volume has none**. After that, a re-seed keeps the volume's `corpus/wiki`: the living wiki is the source of truth, and a newer dump baked into an image is merged by `update_wiki.py`, never copied over it.
- **Writes.** The wiki refresh, and the playbook and memory embeddings from the server's background refresh, write only to the state directory. The seed is never touched.
- **Concurrency.** Tool calls run on worker threads, so a slow search never blocks status, ping or other searches. `gtnh_reindex` waits up to 2 minutes for its refresh, then reports that it continues in the background.
- **Reload.** The server checks the index file's mtime before each tool call (one `stat`) and reloads it when another process replaced it, so the weekly job needs no restart.
- **Read-only mode.** Set by `GTNH_SEARCH_READONLY=1` or `server.py --readonly`, and used automatically when the index directory isn't writable. The server skips the background refresh and the lock file, `gtnh_reindex` returns an error, and `gtnh_search_status` says read-only.

Wiring for the future Dockerfile (not written yet):

1. Build the seed in the build context (`index.py --extract`, `index.py`), then copy:
   - `data/corpus` and `data/index` to `/app/data/`;
   - `tools/gtnh-search/` and `tools/living-wiki/` to `/app/tools/`;
   - `dave/` (the Sonnet merger imports its config and launch helpers).
   
   The baked `data/corpus/wiki` must be an official dump import (`mirror_wiki.py --from-dump`). A snapshot materialized from a dev living wiki is never treated as official.
2. Set:
   - `GTNH_SEARCH_DATA=/app/data/corpus` and `GTNH_SEARCH_INDEX_DIR=/app/data/index`;
   - `GTNH_SEARCH_STATE=/var/lib/dave/search` (a volume; the living wiki lives at `<state>/wiki-git`);
   - `OPENROUTER_API_KEY_FILE=/run/secrets/openrouter`;
   - `CLAUDE_CODE_OAUTH_TOKEN`, or its docker secret, for the Sonnet merges.
3. Entrypoint:
   1. `python3 -I /app/tools/gtnh-search/index.py --seed` (it also creates the living wiki when the volume has none);
   2. once, optionally, `python3 -I /app/tools/gtnh-search/update_wiki.py` (merges a newer dump baked into the image);
   3. start [supercronic](https://github.com/aptible/supercronic) in the background with [`crontab`](crontab) (`supercronic /app/tools/gtnh-search/crontab &`);
   4. start Dave.
   
   supercronic passes the container environment to the job and logs its output to stdout. Both MCP servers (`gtnh-search` and `living-wiki`) need the same `GTNH_SEARCH_STATE`.

The MCP config is the same as above, with the `/app` path; the server inherits the environment:

```json
{
  "mcpServers": {
    "gtnh-search": {"command": "python3", "args": ["-I", "/app/tools/gtnh-search/server.py"]}
  }
}
```

## Tools exposed to Dave

| Tool | What it does |
|---|---|
| `gtnh_search` | Takes `query` (natural language), plus optional `k` (1–25, default 8) and `kind` (`any`, `quest`, `guide`, `wiki`, `item`, `lang`, `playbook`, `memory`). Each hit shows `[n] kind · title · score`, its source (`quest:<id>`, `guide:<ns>/<page>.md:<lines>`, `lang:<mod>:<lines>`, …), any IDs (`quest_id`, `quest_ids`, `item_ids`, `page`) and a snippet of up to 1,500 characters. |
| `gtnh_search_status` | Chunk counts per kind, the model, when and from which pack it was built, and whether a refresh is running or disabled. |
| `gtnh_reindex` | Refreshes now and waits for it, for example right after a playbook answer is saved. |

## Command line

```sh
python3 -I tools/gtnh-search/index.py --extract        # re-read the pack into data/corpus/ (no API calls; waits for a running build)
python3 -I tools/gtnh-search/index.py --stats          # chunks and characters per kind, estimated cost (no API calls)
python3 -I tools/gtnh-search/index.py                  # incremental build
python3 -I tools/gtnh-search/index.py --query "best nitrogen source at HV" -k 5 --kind quest
python3 -I tools/gtnh-search/eval.py --check           # every expected eval hit exists in the corpus (no API calls)
python3 -I tools/gtnh-search/eval.py --dry-run         # per-model eval cost (no API calls)
python3 -I tools/gtnh-search/eval.py --models voyageai/voyage-4,openai/text-embedding-3-small,qwen/qwen3-embedding-8b
python3 -I tools/gtnh-search/index.py --seed           # container start-up: fill GTNH_SEARCH_STATE from the baked seed
python3 -I tools/gtnh-search/update_wiki.py --check    # is there a newer wiki dump? (one request)
python3 -I tools/gtnh-search/mirror_wiki.py --from-dump .work/wiki-dump/gtnhwiki-20260904.xml.gz
python3 -I tools/gtnh-search/test_semsearch.py         # offline tests (no API calls)
```

## Eval

`eval/questions.jsonl` holds 32 player questions, each with the sources that should come back, for example `{"question": "which quest unlocks the EBF", "expect": ["quest:AAAAAAAAAAAAAAAAAAAATQ=="]}`. Every expected source was checked against the extracted corpus; `--check` re-checks after a pack update. There are no wiki expectations yet; the wiki was imported after the set was written.

`eval.py --models a,b,c` embeds the whole prose corpus once per model (cached under `data/index/eval/`), then reports recall@1/3/5/10, MRR and coverage@10 (the share of each question's expected sources found in the top 10), ranking one slot per document. Results are written to `data/index/eval/results-<time>.json`; `-v` prints each question's rank and top three hits. `--sample N` embeds only the expected sources plus N random distractors.

Candidate prices are in `MODEL_PRICES` in `eval.py`. With the wiki imported, the prose corpus is 9,603 chunks and about 15 M characters, so a full embed costs about $0.25 with `voyageai/voyage-4`; the first full build cost $0.246.

## The wiki

The wiki (CC BY-SA 4.0) is hosted on Miraheze. Miraheze's `robots.txt` has `Disallow: /w/` for every user agent, which covers `/w/api.php`, so the wiki isn't crawled. Instead, the corpus comes from the XML backups Miraheze publishes to archive.org: items `miraheze-wiki-gtnhwiki-YYYYMMDD`, each with `gtnhwiki-YYYYMMDD.xml.gz` (about 35 MB, full history; the images tarball is skipped).

`mirror_wiki.py --from-dump <file.xml[.gz]>` imports a dump:

- every non-redirect page in the main namespace, at its newest revision;
- raw wikitext in `raw/`, plain text in `text/` (headings as Markdown, infobox fields as `key: value` lines);
- `manifest.json`, with each page's revid, timestamp, URL and categories, the dump it came from (`source`) and the license.

It writes to a staging directory and swaps it in whole, so a crash never leaves a half-updated wiki. The 2026-09-04 dump gives 638 pages. Once a living wiki exists, dumps go through `update_wiki.py` instead, which imports them onto the `official` branch; `mirror_wiki.py` then refuses to write the corpus wiki. Page file names keep at most 100 bytes of the title plus a hash.

### The living wiki and the weekly refresh

The wiki corpus is a **living document**: Dave corrects it with evidence as he learns what is true on our pack, and official dumps are merged in without wiping those edits. The full design is in [`docs/plans/living-wiki.md`](../../docs/plans/living-wiki.md); the code is in [`tools/living-wiki/`](../living-wiki/).

- **Repo.** `<state>/wiki-git` (`data/wiki-git` in dev) is a git repo with two branches:
  - `official`: one commit per imported dump;
  - `living`: official plus Dave's edits and merges.
- **Search corpus.** `corpus/wiki` is a snapshot materialized from `living`. Chunks from text Dave changed carry `edited_by_dave` metadata, and their hits show "locally edited <date>" in the header.
- **Content rule.** Page text states what is true now. History, reasons and evidence go in commit trailers.
- **Dave's tools.** The `living-wiki` MCP server (`tools/living-wiki/server.py`): `wiki_get`, `wiki_search_titles`, `wiki_edit`, `wiki_create`, `wiki_history` and `wiki_revert`. Each edit is a commit with `Reason`, `Evidence` and `Asked-by` trailers, followed by a background incremental reindex.

[`crontab`](crontab) runs `update_wiki.py` every Monday at 05:17. Each run:

1. Asks the archive.org search API for the newest `miraheze-wiki-gtnhwiki-*` item. Dumps arrive irregularly, so the run checks weekly instead of on a fixed date.
2. Compares it with the newest dump on `official`, and with the dump baked into the image. If the living wiki is current, it stops there.
3. Downloads only the `.xml.gz` and checks its md5 against `archive.org/metadata/<item>/files`. A dump baked into the image needs no download.
4. Imports it as a new `official` commit. A dump with under half the current pages is refused as broken.
5. Merges `official` into `living` (`git merge-tree`, no worktree):
   - untouched pages update cleanly, and non-overlapping hunks merge automatically;
   - only conflicted pages go to the merger: Sonnet through `claude -p` on the owner's subscription, or `--merger stub`;
   - output that fails validation falls back to a lossless section merge;
   - contradictions and pages deleted upstream but edited by Dave are flagged into `<state>/wiki-review.jsonl`.
6. Builds the next index from the merged snapshot (incremental: only changed chunks are embedded, cents).
7. Holding the index's build lock, moves both branches, swaps in the new `corpus/wiki`, and replaces the index file. The server picks the index up by mtime. The merge report goes into the merge commit and `<state>/wiki-reports/`.

Any failure before step 7 leaves the branches, corpus and index untouched and cleans up the staging files, and the summary says so. A failure after the branches moved says that the living wiki holds the new dump while the corpus or index may lag until the next refresh or `living_wiki.py sync`.

It is safe for cron:

- `jobs.lock` stops overlapping runs; a second run prints `skipped` and exits 0;
- it prints one summary line on stdout, with details on stderr;
- `--check` and read-only mode write nothing: no seeding, no living wiki, no lock file;
- exit codes: 0 updated, up to date or skipped; 1 failure; 2 no key.

The job needs `OPENROUTER_API_KEY` (or `OPENROUTER_API_KEY_FILE`) for embeddings and `CLAUDE_CODE_OAUTH_TOKEN` for the Sonnet merges. Without the token, conflicted pages take the flagged fallback.

```sh
python3 -I tools/gtnh-search/update_wiki.py --check     # report only: one search request, no download
python3 -I tools/gtnh-search/update_wiki.py             # update if a newer dump exists (merger: claude)
python3 -I tools/gtnh-search/update_wiki.py --merger stub --force miraheze-wiki-gtnhwiki-20260904
python3 -I tools/living-wiki/living_wiki.py status      # branches, Dave edits, open reviews
python3 -I tools/living-wiki/living_wiki.py export      # git bundle of the living wiki, for backup
```

### Live API mirror (not used)

`mirror_wiki.py` without `--from-dump` mirrors through the MediaWiki API instead: one request at a time, about one per second, `maxlag=5`, back-off on errors, and the User-Agent `Dave-Agent offline mirror (private, non-commercial)`. It checks `robots.txt` first and stops, because the API is disallowed. Use it only with the wiki admins' permission (`--ignore-robots`). `--check` reports robots.txt and the license.

## Limits

- Quests and guide pages can lag behind the pack. Check numbers against the recipe tools before quoting them.
- About a third of quest task items show a raw ID until `data/corpus/names/items.tsv` exists.
- Scores compare well within one kind; across kinds they are only a rough guide.
- Changing a profile's model starts a new index file and a full re-embed.
- After changing an extractor, bump `EXTRACT_VERSION` in `semsearch.py` or run `index.py --extract`, so the cached documents are rebuilt.
