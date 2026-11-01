# Dave's memories

This folder is Dave's long-term memory. It is written by the `dave-memory` MCP server (`dave/memory/server.py`)
and, later, the daemon, both through `dave/memory/store.py`. Memories are valuable and hold player data, so
they are **versioned, but not in this repo** (it is public; only this README is tracked). Their history is a git
repository of its own (`dave/memory/history.py`): `data/memory-history.git` in dev, the `dave-memory-history`
volume in production. See `docs/plans/dave-core.md`.

| Path | Holds |
|---|---|
| `players/<uuid>.md` | One profile per player, keyed by UUID, with the name (and former names) in frontmatter: tier, base, setup, preferences, client-eval opt-in as reported. Each fact carries a `since` date |
| `playbook/<slug>.md` | Solved answers: question, constraints and locks, answer, chain, pack version, who asked, status (`active` / `superseded` / `archived`; reads as `stale` when its pack version is not the current one), `supersedes` / `superseded_by`, corrections |
| `server/<slug>.md` | Server-wide facts: rules, shared infrastructure, landmarks, conventions. Tag one `pinned` to show it on every turn |
| `lessons/<slug>.md` | Dave's notes to himself about mistakes and gotchas |
| `INDEX.md` | Generated on every write: one line per active memory. Don't edit |
| `.log.jsonl` | Every write: when, who, what (`op`), the id, and before/after content hashes |
| `.objects/` | Every version ever written, by content hash. `restore` reads from here |
| `.lock` | fcntl lock file taken around writes |

A memory's id is its path without `.md`, e.g. `playbook/best-nitrogen-source-at-hv`.

## Rules

- **Nothing is hard-deleted.** Forgetting sets `status: archived` with a reason; a correction supersedes.
- Writes are atomic (temp file + rename) under the lock, so Dave's process and the daemon can both write.
- Hand edits are fine (it's Markdown), but prefer the CLI so the change is logged. A hand edit is picked up
  as-is; the next tool write records the hand-edited version as its "before".

## Owner CLI

```sh
python3 -I dave/memory/store.py index                 # regenerate INDEX.md
python3 -I dave/memory/store.py log 50                # last 50 writes
python3 -I dave/memory/store.py restore <id> <sha>    # put back an earlier version (sha from the log)
```

`DAVE_MEMORY_DIR` points the tools at another folder (e.g. a copy pulled from the server).
