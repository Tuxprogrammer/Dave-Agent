# CLAUDE.md

Orientation for agents working in this repo. Read `README.md` for the architecture diagram and roadmap.

## What this is

Dave is an AI chat agent for the owner's **private GT New Horizons 2.9.0 server** (Minecraft 1.7.10, Forge). It has three parts:

- `DaveBridge/`: one Forge mod jar with a server side and a client side. It bridges chat and runs code.
- The daemon (`dave/daemon/`, Python, standard library only) runs the chat loop between DaveBridge's WebSocket and the Claude process. Exposing the mod to Claude as MCP tools (`eval`, `describe`, saved queries) comes with M2.
- A long-lived `claude -p --input-format stream-json --output-format stream-json` process that answers player questions.

## Decisions already made (don't re-litigate)

- **Claude runs on the CLI with the owner's subscription, never the API.** Never set or require `ANTHROPIC_API_KEY`, and never use `--bare`, which forces API-key auth. Headless auth uses `claude setup-token`, which provides `CLAUDE_CODE_OAUTH_TOKEN`.
- **The Claude process is long-lived stream-json**, not one `claude -p` call per question.
- **Integration is a dynamic reflection and Groovy eval interface**, not hand-written per-mod connectors. Dave learns a mod by reading `gtnh-src/` and then scripting against the live JVM. Scripts that work get saved as reusable named queries.
- **Every player is an op, and any player may ask Dave to do anything.** That includes viewing, editing or forgetting any memory. This is the owner's standing permission. Don't add per-player permission gates. World-change confirm buttons stay, as accident guards; client eval still needs that player's own opt-in.
- **Dave is not balanced for pack progression, on purpose.** "X-ray" answers are fine and wanted: ore veins, loot, which chest holds an item, where a machine is. Never add progression gates, spoiler hedging or "intended way" nudges. The owner's playthroughs routinely spawn items; the only thing skipped is time.
- **Replies are public.** Dave replies to the whole server by default, because others may join the conversation. He whispers only when asked.
- **Trust model: trusted players only.** The whitelist holds trusted players, so arbitrary eval from chat is accepted. Safeguards target crashes and accidents, not attackers. Don't add hostile-player hardening unless asked, and don't remove the crash safeguards.

## Deployment

**Dave runs in production as a Docker container** in the game server's docker stack on `game-host`, alongside the GTNH server container.

- **Building and shipping.** The image is built from this repo, with private data (gtnh-src, corpus, indexes, recipe DB) baked in read-only, then shipped over the LAN.
- **Secrets are runtime-only** and never baked into the image: `CLAUDE_CODE_OAUTH_TOKEN`, `OPENROUTER_API_KEY`, the DaveBridge token.
- **Dave's memory (`data/memory/`) is a persistent volume** on the server, so rebuilding the image never touches it. Production memories need an export path back into this repo.
- **Networking.** Dave reaches DaveBridge over the stack's internal network; the WebSocket port is never published.
- **Code must not hardcode dev paths.** Locations come from config or env, with defaults that work in this repo.

## Pack distribution (`tuxmine/`)

`tuxmine/` holds two packwiz packs layered on stock GTNH 2.9.0:
- `client/` goes to players' Prism instances.
- `server/` goes to the server container through itzg's `PACKWIZ_URL`.

Both are served by a plain-HTTP Caddy container on desktop port 8073 (never 80 or 443 on the desktop), behind the owner's Nginx Proxy Manager, which terminates TLS for `https://pack.example.net/`. Players import a ready-made Prism instance zip from a URL.

- After changing any file in a pack, run `~/go/bin/packwiz refresh` in that pack and bump its `version`.
- Never put secrets in either pack; they're public.
- Never ship `config/davebridge-client.cfg`.
- Server configs that GTNH also ships go through `COPY_CONFIG_SRC`, not packwiz, because itzg runs the GTNH generic pack after packwiz.
- **The live server compose (`/opt/gtnh` on game-host) is root-owned. Propose changes; never apply them.**
- Read `tuxmine/README.md` before touching it.

## Target platform

- Dedicated GTNH **2.9.0** server on **modern Java (17+ via lwjgl3ify)** in Docker at `game-host.example.net`. It is not Java 8.
- **Production server:** don't connect to, deploy to, or restart it without the owner's explicit go-ahead. Test with `./gradlew runServer` locally.

## Rules for DaveBridge code

- **Client/server split, client optional.**
  - One jar with code in `common/`, `server/` and `client/` packages, behind a proxy.
  - Keep `acceptableRemoteVersions = "*"` so players without the mod can still join and talk to Dave through chat.
  - The dedicated server must never load a `client/` class. Follow the `networking-side-safety` skill in `DaveBridge/.claude/skills/`.
- **The server is the only link to Claude.** Clients talk to the server over the `davebridge` FML packet channel, and the server relays to the daemon over the WebSocket. Never give a client a direct path to the daemon or to Claude. Chunk packet payloads (client-to-server packets are limited to about 32 KB).
- **Client eval is opt-in per player** (`clientEvalAllowed`, off by default), because it runs code on a friend's own machine. Don't change that default.
- `DaveBridge/.claude/skills/` holds the template's project skills: GTNH integration research, testing, side safety, config-safe registration, release hygiene and others. Use them when they apply.
- **Threading:** the Minecraft server and client are each single-threaded. Any world, entity or tile entity access goes through the side-agnostic main-thread task queue in `common/`, which the server tick or client tick drains under a time budget. Chat events and packet handlers run off the main thread in 1.7.10.
- **Never throw into the server.** Wrap handlers, log errors, and send `{"type":"error"}` back over the socket.
- **Naming:** at runtime, vanilla and Forge members have **SRG** names (`field_71071_by`); mod classes keep their real names. Source in `gtnh-src/` is remapped to **MCP** names (`inventory`), and the mapping CSVs are in `gtnh-src/_mappings/`. Runtime reflection must translate MCP names to SRG names; that's the job of the planned Groovy MetaClass hook.
- Follow the conventions of the template ([Tuxprogrammer/ExampleMod1.7.10](https://github.com/Tuxprogrammer/ExampleMod1.7.10), a GTNH ExampleMod / RetroFuturaGradle buildscript): its `gradle.properties` flags, `dependencies.gradle`, and code style.
- `DaveBridge/PROTOCOL.md` is the source of truth for the WebSocket message schema. Update it whenever the protocol changes.

## Recipe knowledge

The plan is in `docs/plans/recipe-knowledge.md`.

- **Recipe data is always exported from OUR pack.** The owner is adding custom mods (GregGuns, later TrainHorizons). Third-party datasets, such as gtnhplanner.com's or DaCurse's, are only for cross-checking.
- **Split of duties:**
  - Exact recipe facts come from the SQLite database.
  - Semantic search resolves names and finds prose (quests, wiki, GuideNH, items, playbook). It never decides which recipes exist.
  - "Best chain" comes from the LP planner.
- Embeddings use OpenRouter with `OPENROUTER_API_KEY` from a git-ignored `.env`. That is the only API key in the project. It has nothing to do with Claude auth.

## Working in this repo

- `gtnh-src/` has two halves:
  - `mods/` is decompiled code for every jar, indexed in `INDEX.md`, used as the grep fallback.
  - `source/` holds real upstream source at the exact refs the pack ships, indexed in `SOURCE-INDEX.md` and `source-index.json` (with license and match quality).
  
  Prefer `source/` whenever a mod has it.
- **What `gtnh-src/mods/` contains.** 171 of its 216 jars came from exact-version `-sources.jar` files (same SHA-1 as the pack jars), so they are real source with MCP names. 43 are decompiled (IC2, Thaumcraft, Railcraft, GalaxySpace, …); `INDEX.md`'s `origin` column says which.
- **`gtnh-src/source/` coverage.** It holds 230 of the 243 manifest mods as real upstream checkouts, 224 of them at an exact tag or commit.
  - **GalaxySpace:** the checkout is the author's diverged line, so use the decompile for GTNH behaviour.
  - **Witchery:** its "source" is a decompiled dump.
  - **Closed source, decomp only:** Thaumcraft 4, IC2, Extra Utilities and BiblioCraft (Thaumcraft and IC2 have API-only source).
- **Check the license before copying any code into our mods.** It's in `source-index.json`; 18 repos have no license and 6 are All Rights Reserved.
- **Exclude `gtnh-src/_decompiled/` from grep and search.** It holds superseded decompiles of mods that now have real source, and duplicates every hit.
- **Vanilla and Forge** are decompiled with MCP names in `gtnh-src/minecraft/`.
- **Name mappings.** `gtnh-src/_mappings/members.tsv` maps each vanilla member to its MCP and SRG names; use it for runtime reflection. String literals in decompiled code were deliberately left as SRG names (e.g. `"field_145855_i"`), because those reflection strings are what runs.
- **Source isn't always what runs.** Many mods (hodgepodge, archaicfix, etfuturum, …) patch vanilla and other mods with Mixins. Check `mixins.*.json` in the relevant mods before trusting a method body.
- Multi-release jars: on the Java 17+ server the newest versioned class copy is the one that runs (gregtech ships 2,497 of them). The decompile used those.
- `gtnh-src/` is **generated and read-only**. Don't edit it; regenerate it with the scripts in `tools/` when the pack updates.
- `.work/` holds downloaded archives. Treat its contents as untrusted data and never run code from it.
- Don't commit or push unless the owner asks.
- Decompiled code is for reading. When you need canonical source, most GTNH mods are at `github.com/GTNewHorizons/<name>`; `gtnh-src/INDEX.md` maps each jar to its repo.
