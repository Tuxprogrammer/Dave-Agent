# Plan: the living wiki

Status: built (2026-10-31). Code in [`tools/living-wiki/`](../../tools/living-wiki/), weekly job in [`tools/gtnh-search/update_wiki.py`](../../tools/gtnh-search/update_wiki.py).

## The content rule

**The wiki describes what is true now.** History belongs in git commit messages, never in page text.

- Edits and merges *replace* wrong or outdated text with the current truth.
- Page bodies never contain:
  - "the guide used to say…", "previously…", "you might have thought…", "as of the last update…";
  - "(corrected by Dave)", strikethrough, or notes about a merge;
  - two versions side by side.
- The why, the old claim and the evidence go in commit trailers:
  - `Reason`, `Evidence`, `Asked-by` and `Supersedes` on Dave's edits;
  - the merge commit message for merges.
  
  `git log` and `wiki_history` show them.
- Review flags and the losing text of a contradiction go to:
  - the merge commit message;
  - the merge report;
  - the review queue (`<state>/wiki-review.jsonl`).
  
  They never go into a page.
- Search may mark a hit "locally edited <date>" in its header. That is metadata, not page text.

`wiki_edit` and `wiki_create` say this in their descriptions. They also bounce text that narrates history ("used to", "previously", "no longer", "was changed", "old version", "corrected", strikethrough) back to Dave with a rewrite hint. Dave can resend with `confirm_current_fact: true` when the phrase really is current fact ("no longer drops from mobs since the pack's config change" is still history; "does not drop from mobs" is the fact). The merge prompt says the same, and merge validation rejects history phrasing that neither input contained.

## Why

Our wiki copy is a **living document**, not a mirror. Our pack differs from stock GTNH; for example, it adds the owner's GregGuns mod. Dave edits the wiki as he discovers what is true on our server.

Official Miraheze dumps are upstream updates that arrive roughly monthly. Two rules follow:

- an official update must never wipe Dave's edits;
- a new image must never roll the wiki back.

## Layout

The git repo is `<state>/wiki-git/`: `GTNH_SEARCH_STATE` in the container, `data/wiki-git/` in dev, or `GTNH_WIKI_GIT`. It is an ordinary non-bare repo, run with the system `git`. User and system git config are ignored: there are no hooks and no signing.

| Path | Written by | What |
|---|---|---|
| `text/<file>.txt` | official imports, Dave | The converted page text that search reads. Dave edits these. |
| `raw/<file>.wiki` | official imports only | The wikitext, for reference |
| `manifest.json` | official imports only | Official page list, one page per line, sorted, so a dump changes only the lines of changed pages |
| `local.json` | living only | Pages Dave created, and official pages that were deleted upstream but kept because Dave edited them |
| `reports/merge-<item>.json` | living only | The report of each merge, in the merge commit |

**Branches:**

- `official`: one commit per imported dump, with the trailers `Dump-Item`, `Dump-File` and `Pages`. Only the import job writes here.
- `living`: official plus Dave's edits plus merge commits. The repo is checked out on `living`. Search indexes `living`.

**Outside the repo,** next to it:

- `wiki-git.lock`: every write takes it;
- `wiki-review.jsonl`: the review queue;
- `wiki-reports/`: copies of the merge reports, including the merge commit ID;
- `exports/`: bundles.

**The search corpus** (`<corpus>/wiki`: `manifest.json` plus `text/`) is a **snapshot materialized from `living`**. It is written to a staging directory and swapped in. Its manifest records:

- `living_commit` and `official_commit`;
- for each page where living differs from official: `edited_by_dave` (the date of the last Dave edit), `dave_lines` (changed line ranges) and `dave_reason`.

The `wiki` search source marks only the chunks that overlap `dave_lines`, and the hit header says "locally edited <date>".

## Dave's edits (`tools/living-wiki/server.py`)

A stdio MCP server, standard library only, in the same style as `gtnh-search`.

| Tool | What it does |
|---|---|
| `wiki_get(page, history=5)` | Living text, "locally edited" / server-only page markers, open review flags, and short history |
| `wiki_search_titles(prefix)` | Titles starting with, then containing, the text |
| `wiki_edit(page, new_text, reason, evidence, section?, asked_by?, supersedes?, resolves_review?, confirm_current_fact?, confirm_whole_page?)` | Commits on `living`. With `section`, replaces the text under that heading up to the next heading of any level (headings inside code fences don't count). Evidence is required. `wiki_get` shows the first 40,000 characters; a whole-page edit of a longer page that drops most of the hidden tail, or contains the truncation marker, is refused unless `confirm_whole_page` is true. |
| `wiki_create(page, text, reason, evidence, asked_by?)` | A server-specific page, recorded in `local.json` |
| `wiki_history(page)` | Official imports, merges and Dave's edits, with their trailers |
| `wiki_revert(commit, reason)` | A new commit undoing one of Dave's edits. Imports and merges can't be reverted. A revert whose changes are already undone is refused. |

**Commit trailers:**

```
Reason: <why>
Evidence: <tool result summary, gtnh-src path, recipe ID, in-game eval>
Asked-by: <player, or "dave (no player)">
Section: <heading>
Supersedes: <the old claim>
Resolves-review: true
Dave-edit: true
```

The merger reads these back with `git log <base>..living -- <page>`.

All players are ops and may ask for any edit, so there is no permission gating; `Asked-by` is always recorded. After each change the server re-materializes the search corpus (under the wiki lock) and runs one incremental `index.py` build in the background. A corpus refresh that fails after the commit is reported in the reply, not as an error, so Dave doesn't retry a saved edit. Requests that arrive during a build are queued as one more build. The `gtnh-search` server reloads the index by mtime.

## The monthly update

[`update_wiki.py`](../../tools/gtnh-search/update_wiki.py) runs weekly from the container's crontab. It acts only when archive.org has a newer `miraheze-wiki-gtnhwiki-*` item than the newest dump on `official`. It then:

1. Downloads `gtnhwiki-YYYYMMDD.xml.gz` and checks its md5 against archive.org's metadata. It imports the newest revision of each main-namespace page into a staging snapshot. A dump with under half the current pages is refused.
2. Commits the snapshot as a new `official` commit (plumbing, with a throwaway index). No branch moves yet.
3. Merges it into `living` with `git -c merge.renames=false merge-tree --write-tree`, without a worktree. This first pass runs without the wiki lock, so Dave can keep editing while the merger works. The merge is then redone under the lock with the merger's answers replayed; only pages Dave edited in between reach the merger again.
   - **No rename detection:** page files are named after titles, so an upstream page move is a delete plus an add. A moved page that Dave edited is kept and flagged with its likely new title (see "Deleted officially"); git never merges Dave's edit into a renamed file. Conflicted pages are read from merge-tree's stage blobs.
   - **Clean:** pages only official changed. They update as is.
   - **Auto-merged:** pages both changed in non-overlapping hunks. Git merges them.
   - **Conflicted:** pages both changed in the same lines. These go to the merger, one call per page.
   - **Deleted officially:** deleted on `living` too. If Dave edited the page, it is kept (and recorded in `local.json`) and flagged. The flag names the officially added page most like it ("probably moved to …").
4. Builds the merge commit (parents: `living` and the new `official`). Its tree includes `reports/merge-<item>.json`; its message has a summary line plus one block per conflicted or kept page (resolution, note, flag).
5. Materializes the merged tree into a staging corpus and builds the next index from it. This is incremental: only changed chunks are embedded.
6. Under the index build lock:
   - moves `official` and `living` in one `git update-ref --stdin` transaction (both or neither, each checked against its old value), then resets the worktree;
   - appends the flags to the review queue and writes the report copy;
   - swaps in the corpus;
   - replaces the index file.
7. Prints one summary line.

A failure before the ref transaction changes nothing: no branch, corpus or index has moved, and only unreferenced git objects are left behind. If a crash lands after it, the next `sync` (on server start or after an edit) replays the newest merge's report copy and review rows from the copy in the merge commit (it never adds them twice) and re-materializes the corpus; the background refresh fixes the index.

Every write takes `wiki-git.lock` first. Under it, stale git lock files left by a killed process (`index.lock`, ref locks) are removed, an interrupted revert is cleared, and HEAD is put back on `living` if anything moved it, so an edit can never land on `official`. Git runs with `GIT_OPTIONAL_LOCKS=0`, so readers outside the lock never take `index.lock`.

### Merge rules

The merger gets the merge base, the new official text, the living text, and Dave's edit records for the page (reason, evidence, asked-by, section, supersedes). It returns one coherent current page:

1. Keep official improvements: new sections, new facts, fixes in parts Dave did not touch.
2. Keep Dave's corrections: they carry evidence.
3. If the new official text already fixes the same thing, take the official wording and say so in the commit note.
4. If official contradicts Dave:
   - keep Dave's evidence-backed version and **flag** the page;
   - put the official claim in `losing_text`, which goes to the report and the review queue, not the page;
   - if Dave's edit has no real evidence, take the official text instead.
5. Keep every heading of the new official page, unless it is dropped with a stated reason.
6. Keep Dave's lines word for word; any Dave or official line left out or reworded goes in `losing_text`.

**Validation** of any merger output:

- the text is non-empty;
- its length is sane against both inputs;
- there are no conflict markers;
- every new official heading is present, or listed as dropped with a reason;
- it has no history phrasing that neither input had.

**The preservation audit** then compares the output with the inputs line by line, after whitespace normalization only. There is no fuzzy matching: Dave's corrections are often a single number. It finds:

- Dave's added or changed lines (living vs base, including headings he added) that the merge left out;
- lines Dave removed that are back;
- official's added or changed lines that the merge left out;
- lines official removed that the merge kept.

Dave's text left out and **not** listed in `losing_text` rejects the output, and the fallback runs. Anything else the audit finds is accepted but **flagged**: the reason is added to `flag_reason`, and unreported lines are appended to `losing_text`. A merge that takes the official wording over Dave's (rule 3) is therefore always flagged for a quick review. For every LLM-merged page the report also stores Dave's full living text and the three stage blob IDs, so nothing depends on the merger's own account.

If validation, the audit or the call fails, the **lossless fallback** applies. It is a deterministic three-way merge by section:

- official text for sections Dave did not touch;
- Dave's text for sections he did;
- sections Dave added stay where he put them.

The page is always flagged, and every losing alternative goes to the report and the review queue. Nothing is lost, and nothing pollutes the page.

**Mergers:** `--merger claude` (default) or `--merger stub`. The stub is the same section merge, flagged only on real contradictions; tests and dry runs use it.

### The Sonnet merger

`merger.ClaudeMerger` runs one `claude -p` per conflicted page on the owner's subscription, never an API key:

```
claude -p --model sonnet --output-format json --no-session-persistence
       --system-prompt-file tools/living-wiki/merge_prompt.md
       --tools "" --setting-sources "" --strict-mcp-config --mcp-config <run>/wiki-merger/empty-mcp.json
       --disable-slash-commands
```

- **Environment:** only Dave's launcher allow-list (`dave_cmd.ENV_ALLOW`), plus:
  - `HOME` and `CLAUDE_CONFIG_DIR` set to `<run>/wiki-merger/home`, separate from Dave's;
  - `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `DISABLE_AUTOUPDATER=1`;
  - `CLAUDE_CODE_OAUTH_TOKEN`, from `dave/config.py`'s `secret()`.
  
  `ANTHROPIC_API_KEY` is removed.
- **Working directory:** `<workdir parent>/wiki-merge` (`/tmp/dave-agent/wiki-merge`), checked with `dave_cmd.problems()`.
- **Code:** it imports `dave/config.py` and `dave/launch/dave_cmd.py` and changes neither.
- **Input:** page data goes on stdin as one JSON object.
- **Prompt:** says that everything in that object is **data, never instructions**.
- **Reply:** a JSON object with `merged_text`, `commit_note`, `flag`, `flag_reason`, `losing_text` and `dropped_headings`.
- **Model:** set with `--merger-model` or `LIVING_WIKI_MERGE_MODEL` (default `sonnet`).
- **Budget:** at most `LIVING_WIKI_MERGE_MAX_CALLS` model calls per run (default 50). Pages past it take the fallback, flagged. Each call times out after 600 s, also into the fallback. The prompt says the official text comes from a public wiki and that nothing in the input can change the rules.

## Review flags

Each flag is a line in `<state>/wiki-review.jsonl`: page, dump item, reason, losing text, and Dave's edit records. `wiki_get` shows open flags for a page. A `wiki_edit` with `resolves_review: true` settles the flags open at that moment (its queue row lists their dump items), and the edit records why in its trailers. Flags from later merges stay open. The merge report lists the same flags; `living_wiki.py status` counts them.

## Seeding and new images

- **Volume has no `wiki-git`:** `living_wiki.py init` creates `official` and `living` from the image's baked wiki snapshot (an official dump import). `update_wiki.py`, the `living-wiki` server and `index.py --seed` do the same through `ensure()`.
- **Volume has a living wiki:** it is the source of truth. A re-seed after a new image still refreshes quests, guides, lang and the index, but keeps the volume's `corpus/wiki`.
- **Image carries a newer official dump than the volume has seen:** `update_wiki.py` imports it through the same merge path as a monthly update, never a re-seed, and needs no download. A baked snapshot that was materialized from a living wiki (its manifest has `living_commit`) is never treated as official.

## Export

`living_wiki.py export [--out F]` writes a git bundle of every branch, by default to `<state>/exports/living-wiki-<date>.bundle`. To pull it into the dev repo for backup:

```sh
git clone living-wiki-2026-10-31.bundle data/wiki-git    # first time
git -C data/wiki-git fetch /path/to/new.bundle 'refs/heads/*:refs/remotes/prod/*'
```

## Trial on real dumps (2026-10-31, offline)

The 2026-08-06 dump was the base (637 pages). Four scripted Dave edits went in through the MCP tools, and the 2026-09-04 dump (638 pages) was applied by `update_wiki.run()`. The trial used the stub merger and a stub embedder, so it made no API calls of any kind.

| Page | Edit | Result |
|---|---|---|
| Volcanus | Dave edited "Heating Rate Comparison"; official changed the intro paragraph | auto-merged by git; both changes present |
| Vacuum Freezer | Dave edited "Usage"; official unchanged | kept |
| Ore Washing Plant | Dave rewrote "Trivia"; official deleted a line in it | conflicted; stub kept Dave's version, flagged; the official Trivia text is in the review queue |
| Effects | Dave trimmed it; official deleted the page | kept as a server page, flagged |
| Volcanus | "This table used to be wrong." | bounced back by the history lint |

Summary line: `79 official page changes: 75 clean, 1 auto-merged, 2 conflicted (1 merged by stub, 0 fallback); 2 flagged; 1 deleted, 1 kept because Dave edited them`. The index re-embedded 249 of 9,600 chunks. The trial state is kept in `.work/living-wiki-trial/` for the one real Sonnet merge:

```sh
GTNH_SEARCH_STATE=$PWD/.work/living-wiki-trial/state \
  python3 -I tools/living-wiki/living_wiki.py try-merge --page "Ore Washing Plant" --merger claude
```

It re-runs that page's merge from the stored report, prints the validated result, and commits nothing. It needs `CLAUDE_CODE_OAUTH_TOKEN` (env or `dave/.env`).

## Known limits

- Dave edits the converted text, not the wikitext; `raw/` stays official.
- Fixed 2026-11-01: the wikitext converter split infobox fields on the pipe inside `[[Target|label]]` links (219 pages, e.g. `tier: [[Extreme Voltage (EV)`). The fix reached the living wiki by re-importing the current dump with `update_wiki.py --force miraheze-wiki-gtnhwiki-20260904`, which makes it an official change like any other.
- The merger works page by page. A fact that moved to another page upstream shows up as two separate page changes.
