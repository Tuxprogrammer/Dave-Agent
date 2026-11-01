# Plan: Dave core (soul, memory, launch)

Status: skeleton built 2026-10-31; the daemon (`dave/daemon/`) was added 2026-11-01. Claude Code 2.1.316. Packaging comes later; this is what
they plug into.

| Part | Where | State |
|---|---|---|
| Soul: identity and system prompt | `dave/soul/SOUL.md`, `dave/soul/README.md` | First draft for the owner to edit |
| Memory: store and MCP server `dave-memory` | `dave/memory/`, data in `data/memory/` | Built, 13 offline tests |
| Launch: command, env, permissions, MCP config | `dave/launch/`, `dave/config.toml`, `dave/config.py` | Built, verified offline |
| Turn envelope | `dave/ENVELOPE.md` | Spec for the daemon |
| Tool inventory | `dave/TOOLS.md` | Live and planned |

## 1. Decisions

### 1.1 SOUL replaces the default system prompt (`--system-prompt-file`)

Chosen: **replace**, not `--append-system-prompt-file`.

The default Claude Code prompt is a coding-agent prompt: a software-engineering persona, GitHub-flavoured
Markdown, file editing, git and commit workflows, todo lists, and per-machine sections (cwd, platform, git
status). For Dave almost all of it is wrong or noise. Markdown fights a chat voice that needs Dave markup. The
edit and git guidance concerns tools he doesn't have. The persona competes with his. It also adds thousands of
tokens to every request on a latency-sensitive chat path.

What replacing loses, and how that is handled:

| Lost with the default prompt | Handled by |
|---|---|
| General tool-use habits (parallel calls, read before quoting, prefer the dedicated search tool) | Restated in SOUL "Using your tools", tailored to gtnh-src |
| Tool documentation | Unaffected: built-in and MCP tool schemas and descriptions are sent as tool definitions, not system prompt |
| MCP server `instructions` | Unaffected: the CLI delivers them as an `mcp_instructions_delta` attachment, not inside the system prompt (seen in the 2.1.316 binary) |
| Today's date and environment info | The envelope's `turn@ts` and `turn@pack`; Dave needs no cwd or OS |
| Safety and refusal guidance | Built into the model; SOUL adds Dave's own boundaries |
| Output-tone guidance ("be concise") | SOUL "Voice in chat" with examples |

Risk: Claude Code features that assume the default prompt (plan mode, todo tools, subagents) degrade, but
Dave uses none of them. If tool use turns out sloppy in practice, the fallback is
`--append-system-prompt-file` with the same file, a one-line change in `dave_cmd.py`.

### 1.2 Prompt snapshot

The CLI default `--system-prompt-snapshot on` (passed explicitly) records the prompt once per conversation and
replays it on every request and resume. Consequences, documented in `dave/soul/README.md`:

- a SOUL edit takes effect at the next session or rotation;
- per-turn context (who is asking, their profile, relevant memories) goes in the envelope, never in the prompt;
- a resumed session keeps its old prompt.

### 1.3 Memory is Markdown files, not a database

The owner wants memories auditable and versioned, and Claude Code's own memory files set the precedent. So
memory is one Markdown file per memory with a small frontmatter block, which is easy to read, diff in git,
hand-fix, and index with the gtnh-search corpus (which already reads `data/memory/playbook/` as kind
`playbook`). Hundreds to low thousands of files are scanned per call in milliseconds; past that, add a cached
index behind the same `Store` API.

Rules:

- Nothing is hard-deleted.
- Every write goes to `.log.jsonl` with before and after hashes.
- Every version is kept under `.objects/` by hash, so `store.py restore` can undo any edit.
- Writes are atomic (temp file plus rename) under an fcntl lock.
- Playbook entries carry the pack version and read as `stale` when it differs. This is a check on read, not a
  migration; `memory_update(reverify=true)` re-stamps an entry after Dave re-checks it.
- Corrections supersede playbook entries and are credited to the player.

Recall is BM25 for now. `Store.ranker` is the hook for semantic or hybrid ranking through gtnh-search's
`playbook` kind.

### 1.4 Player identity

Profiles are keyed by UUID (`players/<uuid>.md`), with the current name and former names in frontmatter.
`ensure_player` (called by the daemon) creates a profile on first sight and records renames. Dave can look a
player up by name, former name or UUID.

### 1.5 One config file, env overrides, no dev paths

`dave/config.toml` holds every location and setting. Every key has a `DAVE_*` env override (see the comments in
the file). Data paths resolve against `DAVE_ROOT` (default: the repo). Prompt files resolve against the app
directory. Defaults work in this repo; the container sets env vars (section 4).

### 1.6 Model

`[model] name = "sonnet"` (`DAVE_MODEL`). This is a Sonnet-class model for chat latency. In the probe it
resolved to `claude-sonnet-5-5`. Switch with one line or one env var to `opus` or a full model id. `fallback`
(e.g. `haiku`) and `effort` are optional.

### 1.7 An Opus "recipe-planner" subagent (owner's decision)

Dave stays on Sonnet and delegates long recipe-chain and factory-design work to exactly one custom agent,
`recipe-planner`.

- **Model:** `[model] planner = "opus"` (`DAVE_PLANNER_MODEL`).
- **Prompt:** `dave/soul/recipe-planner.md`, focused on chain planning with `plan_chain` and the recipe tools.
  It returns a compact checked result (ANSWER / CHAIN / TOTALS / RUNNER-UP / ASSUMPTIONS / UNVERIFIED /
  SOURCES) that Dave turns into chat markup.
- **Definition:** a Claude Code custom agent, passed with `--agents <file>`. In `-p` mode the flag takes a
  file path. The 2.1.316 schema has `description`, `prompt`, `model`, `tools`, `disallowedTools`, `maxTurns`,
  `omitClaudeMd`, `effort` and `permissionMode`, among others.
- **Tools:** Read, Grep, Glob, `gtnh_search`, read-only memory (`memory_recall`, `memory_get`, `player_get`),
  and the planned recipe tools. Tools of MCP servers that aren't registered yet are dropped when rendering.
- **Limits:** `maxTurns` 40; `omitClaudeMd` true.

SOUL's "Using your tools" says when to delegate (multi-step chains, factory designs, comparing routes under
constraints) and when not to (single lookups).

**Opus usage counts more heavily against the subscription's 5-hour and weekly limits than Sonnet**, so delegation
is reserved for real planning work. If limits bite, set `planner = "sonnet"`; no other change is needed.

**Restricting the Agent tool to this one agent.** `Agent` is added to `--tools`. The CLI has no main-session
option to allowlist agent types: `allowedAgentTypes` exists in 2.1.316, but it comes only from an agent
definition's `tools` list (`Agent(type,...)` beside `*`), not from a flag or setting for the main session. So the
restriction uses the mechanism that is checked at spawn time, permission rules on the agent type:

- `allow`: `Agent(recipe-planner)`;
- `deny`: `Agent(claude)`, `Agent(general-purpose)`, `Agent(Explore)`, `Agent(Plan)` and
  `Agent(statusline-setup)`, each also as `Task(...)`. The debug log shows the CLI normalizing `Task(x)` to
  `Agent(x)`. Rule content is matched against `subagent_type`;
- `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1` removes Explore and Plan altogether.

The init event's `agents` list is not permission-filtered: it still shows claude, general-purpose and
statusline-setup. So `dave_cmd.py --probe` checks that every listed type other than recipe-planner has a deny
rule, and fails otherwise. That catches a new built-in agent in a future CLI version. A spawn of a denied type
should be refused; confirming that against the live model is part of the smoke-test follow-up.

### 1.8 Replies are public by default (owner's decision)

`@reply` posts to the whole server (`say` target `@a`, rendered `<Dave> ...`), with the asker addressed by name,
because players often discuss a problem together and others may chime in. `@whisper` (`say` target = the
asker, rendered as vanilla's "Dave whispers to you:") is used only when the player explicitly asks for privacy.
`@none` posts nothing. A missing directive falls back to public. There is no broadcast directive, because
`@reply` already reaches everyone.

### 1.9 Players are trusted ops (owner's decision)

All players are ops and have the owner's standing permission to ask Dave for anything, including what he knows
about them, editing any memory, and having him forget something. The memory tools have no per-player gating.
Every write tool takes `asked_by`, which `.log.jsonl` records next to `by`, the writing process.

Two safeguards stay, because they guard against something other than players:
- The in-game confirm for world-changing code guards against Dave's mistakes.
- Client-side code needs that player's own opt-in, because it runs on their machine.

### 1.10 Persona (owner's decisions)

- The chat name is plain `<Dave>`.
- Dictator Dave flavour is light: a friendly guide who works within the player's design (the keystone
  approach), gives no homework, and makes decrees, if any, only in the player's favour.
- The beret stays as a quiet nod to the origin.
- The Golden Revolver comes up rarely: a personal favourite in boss fights, with the honest caveat that another
  weapon may suit better.
- SOUL carries good and bad example replies for each of these.

## 2. The launch command

`python3 -I dave/launch/dave_cmd.py --print` shows the exact command. As built (dev paths shortened):

```
claude -p
  --input-format stream-json --output-format stream-json --verbose     # long-lived stream (smoke: text in, no persistence)
  --model sonnet
  --system-prompt-file <run>/system-prompt.md --system-prompt-snapshot on
  --settings <run>/settings.json --setting-sources ""
  --mcp-config <run>/mcp.json --strict-mcp-config
  --tools Read,Grep,Glob,WebFetch,Agent --agents <run>/agents.json
  --permission-mode dontAsk --permission-prompts none
  --restricted --disable-slash-commands
  --add-dir <gtnh-src> --add-dir <data/corpus>
cwd = /tmp/dave-agent/work (empty, private, outside the repo and the owner's home)
```

Every flag was checked in `claude --help` (2.1.316), except two. `--system-prompt-file` and
`--append-system-prompt-file` are not listed in `--help`, but they are referenced by `--bare`'s help text and
present in the binary's option table, and a probe run accepted them.

| Flag | Why |
|---|---|
| `--verbose` | Required by the CLI for `--output-format stream-json` with `-p` |
| `--settings` | The only settings file Dave reads: `launch/settings.json`, rendered with absolute paths |
| `--setting-sources ""` | Load no user, project or local settings files. Parsed as an empty list in 2.1.316. It also gates project and local CLAUDE.md loading |
| `--strict-mcp-config` | No MCP servers except `launch/mcp.json`: no user, project or claude.ai connectors |
| `--tools` | The built-in set is only Read, Grep, Glob, WebFetch, and Agent (for recipe-planner only, section 1.7) |
| `--agents <file>` | The recipe-planner definition, rendered from `launch/agents.json` with its prompt and model filled in |
| `--permission-mode dontAsk` + `--permission-prompts none` | Anything not allowed in settings is refused silently; nobody is at a terminal |
| `--restricted` | Defence in depth: strips code-running tools, ignores user, project and local settings, confines file tools to the working dirs, refuses bypass mode. `--settings` and `--mcp-config` still apply |
| `--disable-slash-commands` | No skills or commands |
| `--add-dir` | Read access to the source tree and corpus. Added only if the directory exists |

Not used: `--bare`, which forces API-key auth. `--safe-mode` disables MCP servers. `--no-session-persistence` is
used only for the smoke test, so the daemon can `--resume` after a crash.

**Environment.** Built from an allowlist (`PATH`, locale, `TZ`, `USER`, `TMPDIR`, CA and proxy variables).
Nothing else from the caller is inherited, so `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, the bridge token and
cloud credentials can't leak in. Then it sets:

| Var | Purpose |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Subscription auth (from `claude setup-token`); the only Anthropic credential |
| `CLAUDE_CONFIG_DIR`, `HOME` | `dave/.claude-home/` (git-ignored): Dave's own sessions and state, none of the owner's |
| `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` | Turns off every CLAUDE.md loader (managed, user, project, nested-on-read) |
| `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` | Claude Code's own auto-memory is off; Dave's memory is `dave-memory` |
| `ENABLE_TOOL_SEARCH=false` | Load all MCP tools up front. ToolSearch is not in `--tools`, and the tool set is small |
| `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1` | Removes the built-in Explore and Plan agents (also denied in settings) |
| `DISABLE_AUTOUPDATER=1` | The binary changes only when the image is rebuilt |

**Rendered files.** `settings.json`, `mcp.json` and `agents.json` in `dave/launch/` are templates with
`${NAME}` placeholders. `dave_cmd.py` fills them in for this machine or container (paths, the planner's prompt
and model) and writes them to `<run>/` with the assembled prompt. It also drops MCP servers whose script doesn't
exist yet, and agent tools from those servers.

## 3. Isolation: what was found and how it was checked

Dave must not load the developer `CLAUDE.md` at the repo root, the owner's personal `~/.claude` (skills, plugins,
hooks, CLAUDE.md, MCP servers), or agent files inside upstream source trees.

**Layers, each sufficient on its own for CLAUDE.md:**

1. `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`. In the 2.1.316 binary, every CLAUDE.md loader returns early when this
   is set: managed, user, project, `.claude/rules` and the nested on-read loader.
2. `--setting-sources ""`. The project and local CLAUDE.md loaders also require the `projectSettings` and
   `localSettings` sources, and user CLAUDE.md requires `userSettings`.
3. `pluginConfigs["agents-md@builtin"].options.instructionFiles = "managed-only"` in `launch/settings.json`.
   AGENTS.md support is the builtin `cc-plugin-agents-md` plugin, whose default loads AGENTS.md "exactly where
   and how CLAUDE.md would be". `managed-only` makes it filter out every project and user instruction file,
   CLAUDE.md included. Its debug line confirms it reads the option from `--settings`.
4. The cwd is outside the repo and the owner's home: `/tmp/dave-agent/work`, empty, 0700. `dave_cmd.py` refuses
   to smoke-test, and `--print` exits 1, if any `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` or `.claude/`
   exists in the workdir or any parent, if it sits inside the repo, if it or its parent is owned by someone
   else, or if an `--add-dir` root has a `.claude/` (Claude Code reads `<add-dir>/.claude/settings*.json`, as
   the debug log showed).

**Why layer 4 matters (found by probing).** The first probe ran with an isolated `CLAUDE_CONFIG_DIR` but cwd
inside the repo. Its debug log said `Loaded 2 unique skills (... project: 2 ...)`. Those were the owner's
personal `~/.claude/skills/gtnh-update` and `reverse-engineer-anything`, picked up as project skills because the
ancestor walk passes through the owner's home. An isolated config dir alone is not enough: the cwd must not be
under the owner's home. The original default (`~/.local/state/...`) was changed to `/tmp/dave-agent/work`.

**Nested agent files in gtnh-src.** A full scan of `gtnh-src/` found no `CLAUDE.md`, `CLAUDE.local.md`,
`AGENTS.md`, `.claude/`, `.cursorrules` or Copilot instructions today. Even if a future regeneration brings one:

- nested CLAUDE.md files in `--add-dir` trees load only with
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`, which is never set;
- layer 1 disables the nested loader entirely;
- layer 3 covers AGENTS.md.

Re-run the scan after each regeneration:
`find gtnh-src \( -iname CLAUDE.md -o -iname AGENTS.md -o -name .claude \)`.

**Offline verification: `dave_cmd.py --probe`** (no token, no model call). With no credentials the CLI still
emits its `system/init` event before failing with "Not logged in". `--probe` runs the exact configured command
with every credential stripped, prints that event, and fails on any deviation. The latest run showed:

- `tools`: Task (the Agent tool's legacy name), Glob, Grep, Read, WebFetch, the nine `mcp__dave-memory__*`
  tools and three `mcp__gtnh-search__*` tools. No Bash, Edit, Write or WebSearch.
- `mcp_servers`: dave-memory connected, gtnh-search connected.
- `agents`: claude, general-purpose, recipe-planner and statusline-setup. Explore and Plan are gone; the other
  three built-ins are denied by rule (section 1.7).
- `skills: []`, `slash_commands: []`, `permissionMode: dontAsk`, `cwd: /tmp/dave-agent/work`,
  `apiKeySource: none`, model `claude-sonnet-5-5`.
- In the debug log: "Adding 9 allow rule(s)" and "Adding 16 deny rule(s)", so the settings file validated and
  loaded (an invalid one would be silently ignored in `-p` mode). `Task(x)` rules appear normalized to
  `Agent(x)`. The agents-md plugin registers only `session.start` and `prompt.context`, its `managed-only` path.

`--probe` PASSED.

The init event doesn't list memory files. Proof that no CLAUDE.md text reaches the model is the smoke test
(below), plus layers 1 to 3 read from the binary.

**Smoke test** (`dave_cmd.py --smoke`). It runs only if `CLAUDE_CODE_OAUTH_TOKEN` is found (env, `_FILE`,
docker secret, or `dave/.env` in dev), and makes exactly one short call through the configured process. It
prints the init event (tools, MCP servers, `apiKeySource`, model) and asks the model to list its tools and say
whether it saw two canaries: the root CLAUDE.md's "re-litigate" and the owner's global CLAUDE.md's "local copy
of artifacts". It fails on an unexpected built-in tool, a disconnected server or a "yes". Not run yet: no token
was available.

## 4. Production: Docker on the game server's stack

**Status: live since 2026-11-01** as the `dave` service in `/opt/gtnh/docker-compose.yaml` on game-host.
Files: [`dave/deploy/`](../../dave/deploy/) (Dockerfile, entrypoint, crontab, `build.sh`, compose snippet) and the
repo-root `.dockerignore`.

**Layout in the container:**

| Path | What | Lifetime | Env |
|---|---|---|---|
| `/dave/app` | Code: `dave/`, `tools/`, `DaveBridge/PROTOCOL.md` and `DaveBridge/docs/dave-markup.md` (the markup include) | Image | (derived from code location) |
| `/dave/ro/gtnh-src` | Source tree, without `_decompiled/` and the checkouts' `.git` | Image, read-only | `DAVE_GTNH_SRC` |
| `/dave/ro/corpus`, `/dave/ro/index` | Search seed (corpus, embeddings) | Image, read-only | `DAVE_CORPUS_DIR`, `DAVE_INDEX_DIR`, `GTNH_SEARCH_DATA`, `GTNH_SEARCH_INDEX_DIR` |
| `/dave/seed/memory` | A blank memory (the README), used only when the volume is empty and there is no history | Image | |
| `/dave/data` | **Volume `dave-data`**: `memory/`, `logs/`, `state/` (search corpus, index and the living wiki `wiki-git`), `exports/` | Volume: a rebuild never touches it | `DAVE_ROOT`, `DAVE_MEMORY_DIR`, `DAVE_LOG_DIR`, `DAVE_SEARCH_STATE`, `GTNH_SEARCH_STATE` |
| `/dave/history` | **Volume `dave-memory-history`**: `memory.git`, the long-term memory history (bare git repo) | Volume, kept apart from `dave-data` | `DAVE_MEMORY_HISTORY` |
| `/dave/home` | **Volume `dave-home`**: `CLAUDE_CONFIG_DIR` and `HOME` (sessions, CLI state) | Volume, so `--resume` survives restarts | `DAVE_CLAUDE_HOME` |
| `/dave/run` | Rendered prompt, settings, mcp.json, runtime secret file | tmpfs (uid 10001, 0700) | `DAVE_RUN_DIR` |
| `/dave/work` | Dave's empty cwd | Image (empty dir) | `DAVE_WORKDIR` |

The read-only data sits outside `/dave/data` on purpose: a named volume mounted over image content would keep
serving the first image's copy after every rebuild.

`DAVE_BRIDGE_URL=ws://gtnh_2:25580` (the server's compose service name on the stack network; the port is not
published) and `DAVE_CONTAINER=1`. The image runs as `dave` (uid 10001) with all capabilities dropped and
`no-new-privileges`; tini (`init: true`) reaps the claude, MCP and supercronic children.

**Start-up** (`entrypoint.sh`): seed the memory volume if it has no `INDEX.md`; `index.py --seed` (search state and,
first time only, the living wiki); `main.py --check` (refuses to start with a missing secret or bad isolation);
supercronic in the background; then the daemon in the foreground.

**Scheduled jobs** (`dave/deploy/crontab`, UTC): the weekly wiki refresh (Monday 05:17) and a nightly memory export
(04:43).

**Image contents:** python 3.13-slim (pinned by digest), Claude Code 2.1.316 from the official installer (pinned;
`DISABLE_AUTOUPDATER`, so a new CLI means a rebuild), supercronic (pinned with sha256), git, and the pip
requirements of `tools/*/requirements.txt` (numpy for gtnh-search). About 2.7 GB, mostly `gtnh-src` and the index.

**Build and ship:** `dave/deploy/build.sh --ship game-host.example.net` builds `dave:<git rev>`, pipes
`docker save` over SSH into the server's docker and tags it `dave:current` there. Then, on the server:
`cd /opt/gtnh && sudo docker compose up -d dave`. The compose service has `pull_policy: never`.

**Secrets are runtime-only.** `CLAUDE_CODE_OAUTH_TOKEN`, `OPENROUTER_API_KEY` and the bridge token are never in
the image or in `config.toml`. On the server they are files in `/opt/gtnh/secrets/` (owner uid 10001, mode 0400;
the directory is root 0700), mounted as compose secrets at `/run/secrets/{claude_oauth_token,openrouter_api_key,
dave_token}`. `dave_token` holds the same value as `authToken` in gtnh_2's `config/davebridge.cfg`. `config.secret()`
looks in order at:

1. the env var;
2. the file named by `NAME_FILE`;
3. `/run/secrets/<name>`;
4. outside a container only, the dev `.env` files (`dave/.env`; root `.env` for OpenRouter).

Inside a container the dev fallback is disabled. The OpenRouter key reaches only gtnh-search, as a file path
(`OPENROUTER_API_KEY_FILE`), never as a value in Claude's environment.

**DaveBridge side:** `S:bindAddress=0.0.0.0` in gtnh_2's `config/davebridge.cfg` (applied with `/dave reload`, no
restart). Checked 2026-11-01: port 25580 refuses connections from the host and the LAN; only containers on the
stack network reach it.

**Container gives isolation for free, but the dev measures stay.** We also run Dave locally for testing.

| Measure | Needed in dev | Needed in container |
|---|---|---|
| `CLAUDE_CONFIG_DIR` and `HOME` override | Yes: the owner's `~/.claude` is right there | Redundant (own HOME), kept for explicitness |
| Workdir outside the repo and the owner's home | Yes (see the skills finding) | Redundant (no owner home, no repo CLAUDE.md unless copied in) |
| Env allowlist | Yes | Yes: the daemon's env holds the bridge token and OpenRouter key |
| `CLAUDE_CODE_DISABLE_CLAUDE_MDS`, `--setting-sources ""`, agents-md `managed-only` | Yes | Cheap insurance against a stray CLAUDE.md in the image (`.dockerignore` also drops the upstream checkouts' CLAUDE.md, AGENTS.md and `.claude/`) |
| `--strict-mcp-config`, `--tools`, `dontAsk`, `--restricted` | Yes | Yes: this is the permission model, not isolation |
| Dev `.env` fallback | Yes | Disabled automatically |

**Memory history and backups.** Production memories live on the `dave-data` volume. Memories hold player data
and the Dave-Agent repo is public, so they never come back into it; their long-term record is a git repository on a
volume of its own, `dave-memory-history` (`/dave/history/memory.git`), managed by `dave/memory/history.py`:

- `snapshot` commits the memory folder (memories, `INDEX.md`, `.log.jsonl`, saved queries; not `.objects/`, `.lock`
  or temp files) under the store lock. The commit message lists the memory writes since the last snapshot, from
  `.log.jsonl`. The entrypoint runs it at start and supercronic every 10 minutes; nothing is committed when nothing
  changed.
- `log [id] [N]` and `show <rev> [id]` browse it; `restore <id> <rev>` writes an old version back through the store
  (logged and indexed like any write).
- `recover`: the entrypoint fills an empty memory folder from the newest snapshot before falling back to a blank
  seed, so a lost or reset `dave-data` volume comes back from the history.
- `bundle <file>` writes the whole history to one file (`git clone <file>` reads it) for a backup off the host:
  `sudo docker exec gtnh-dave-1 python3 -I /dave/app/dave/memory/history.py bundle /dave/history/memory.bundle`,
  then copy it from the volume to a private place.
- The nightly `store.py export <dir> [keep]` tarball (newest 14, in `/dave/data/exports`) stays as a quick restore
  point next to the history. Exports stay on the server or in a private backup, never in this repo.
- Host snapshots (ZFS) cover both volumes.

**Living wiki backup:** `living_wiki.py export` inside the container writes a git bundle to
`/dave/data/state/exports/` (see living-wiki.md).

## 5. Open questions for the owner

Answered and applied: reply target (public by default, section 1.8), rotation (keep 40 turns or 6 hours), model
(Sonnet plus an Opus recipe-planner, section 1.7), player permissions (section 1.9), persona (section 1.10).

Still open:

1. **Prompt size.** SOUL's own text is about 1,650 words after the persona additions, plus about 450 for the
   included markup spec: about 2,100 in all, against a 1,500 target. Trim the examples, or accept it? It is
   cached, so the cost is mostly first-request latency after a rotation.
2. **Search index in production.** The image's index is read-only, but playbook entries are created at runtime.
   gtnh-search needs a writable spot for the `playbook` and `memory` kinds, or Dave relies on `memory_recall`
   for those. Coordinate with the gtnh-search agent, along with `OPENROUTER_API_KEY_FILE` support.
3. **Session store as a volume.** Keeping `/dave/home` on a volume enables `--resume` after a crash, but
   accumulates transcripts (`cleanupPeriodDays: 30` in settings). Alternatively, tmpfs, and always start fresh.
4. **Planner limits.** `maxTurns` 40 is a guess. Should the daemon also cap delegations per player or per hour,
   given Opus's weight against the subscription?
