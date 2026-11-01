# Dave

Dave is an AI agent that lives in the chat of a private GT New Horizons server. Players ask him questions in game ("dave, what's the EU/t of the EBF steel recipe?"), and he answers in chat. To do that, he reads the pack's source code and runs small scripts against the live server.

Dave runs on the **Claude Code CLI** with a Claude subscription, not with API tokens.

## How it works

```
┌───────────────────────┐  FML packets  ┌──────────────────────────────┐  WebSocket (token)  ┌──────────────────────┐
│ Player client         │ ◀───────────▶ │ GTNH 2.9.0 server (Docker)   │ ◀─────────────────▶ │ Dave daemon          │
│  └─ DaveBridge (opt.) │  ask/context  │  └─ DaveBridge (server side) │  chat / say / eval  │ (MCP server + bridge)│
│      • context capture│  messages     │      • chat hooks + relay    │                     └──────────┬───────────┘
│      • client eval    │  client eval  │      • main-thread queue     │                                │ stream-json
│        (opt-in, M2)   │               │      • Groovy eval (M2)      │                     ┌──────────▼───────────┐
└───────────────────────┘               └──────────────────────────────┘                     │ claude -p (long-lived)│
  vanilla-chat players work too                                                              │ reads gtnh-src/, wiki │
                                                                                             └──────────────────────┘
```

1. **DaveBridge** is one Forge mod jar with a server side and a client side.
   - **Server side (required).** It forwards chat that starts with a trigger (`dave,`, `@dave`, `!dave`) over a WebSocket that requires a token. Replies are queued and shown as `<Dave>` on the server thread. It is the **only** link to Claude, and it relays traffic for clients.
   - **Client side (optional).** Players without it still use Dave through plain chat. With it, questions carry context (what the player is looking at or holding, which GUI is open), and Dave's replies render more nicely. Later, Dave can run code on that player's client, but only if the player opts in with `clientEvalAllowed`, which is off by default.
2. **The Dave daemon** holds the socket and exposes the server to Claude as MCP tools: `say`, `eval`, `describe`, and the saved-query library.
3. **Claude** runs as one long-lived `claude -p --input-format stream-json --output-format stream-json` process. To answer a question about any mod, it greps the decompiled pack in `gtnh-src/`, then writes a Groovy script and runs it in the live server. No mod needs a hand-written connector.

## Layout

| Path | What |
|---|---|
| `DaveBridge/` | The Forge mod, built from [Tuxprogrammer/ExampleMod1.7.10](https://github.com/Tuxprogrammer/ExampleMod1.7.10). The wire format is in `DaveBridge/PROTOCOL.md` |
| `gtnh-src/` | Decompiled GTNH 2.9.0 mods, remapped to MCP names, plus the pack's `config/` and the MCP mapping CSVs. `gtnh-src/INDEX.md` lists every jar. This folder is generated; don't edit it |
| `.work/` | Downloaded pack archives and other scratch files |
| `tools/` | Helper scripts, such as the decompile pipeline |
| `tuxmine/` | The packwiz pack layered on top of stock GTNH 2.9.0: our mods and server-specific configs, synced to every client and the server. See `tuxmine/README.md` |

## Roadmap

- [ ] **M1: Chat bridge.** Mod skeleton with the client/server split, WebSocket, chat in and out, the `davebridge` packet channel (client hello, ask with context, Dave messages), `/dave status` and `/dave reload`. *(in progress)*
- [ ] **M1: Source tree.** GTNH 2.9.0 decompiled into `gtnh-src/`. *(in progress)*
- [ ] **M2: Live eval.** Groovy engine on the main-thread queue with a per-tick time budget, MCP to SRG name mapping, a capped JSON serializer, and the introspection API. Eval works on the server, and on opted-in clients by way of the server relay. It ships with a starter set of saved **world lookups**, each answered with a `{waypoint:}` link:
- **Where is my machine:** found by type or name.
- **Which chest, drawer or AE network holds an item.**
- **Where is the nearest ore vein of X:** from GregTech's ore-vein data and generated chunks; also check what VisualProspecting already stores before writing our own.
- **Where is loot or a structure.**
- [x] **M3: Daemon (chat loop).** `dave/daemon/`: the DaveBridge WebSocket, the long-lived Claude process, the turn envelope with memory, the reply directives, per-player cooldowns and queue caps, session rotation, crash resume and reconnects. Tested against a fake bridge and live with Dave on 2026-11-01. The bridge MCP tools (`eval`, `describe`, saved queries) come with M2.
- [x] **Recipe knowledge.** Our own recipe export (`tools/recipe-export/run.sh`, headless on a throwaway server) into `data/recipes.sqlite`, the `recipes` MCP server (`recipe_producers`, `recipe_uses`, `recipe_get`, `item_find`, and the `plan_chain` LP optimizer), and `gtnh_search` semantic search over the quest book, wiki, GuideNH and item cards. Still to come: the item-cost pass and plan JSON export. See [docs/plans/recipe-knowledge.md](docs/plans/recipe-knowledge.md).
- [ ] **Guided demonstrations ("Show me").** A client-only ghost Dave walks the player through a task in their world, with ghost blocks and labels, looping until they stop it. See [docs/plans/guided-demos.md](docs/plans/guided-demos.md).
- [x] **Distribution: the `tuxmine` packwiz packs.** packwiz-installer runs as a Prism pre-launch command and keeps DaveBridge, GregGuns and the other extra mods up to date on every client and on the server. Live at `https://pack.example.net/<token>/` since 2026-11-01; see `tuxmine/README.md`.
- [x] **Production container.** Dave runs as the `dave` service in the GTNH stack on game-host, connected to DaveBridge over the stack network, with his memory, logs and living wiki on a volume and a nightly memory export. Live since 2026-11-01; see `dave/deploy/` and `docs/plans/dave-core.md` section 4.
- [ ] **M4: Polish.** Clickable confirm buttons for scripts that change the world, a backup before writes, the saved-query library, and event-hook subscriptions.

## Running Dave on a subscription

- Log in with `claude login`. On a headless box, use `claude setup-token` and set `CLAUDE_CODE_OAUTH_TOKEN`.
- `ANTHROPIC_API_KEY` must **not** be set in the daemon's environment. If it is, the CLI bills the API instead of the subscription.
- Don't pass `--bare`. It only accepts API-key auth.
- Dave's usage counts against the same 5-hour and weekly limits as the owner's own Claude use. The daemon will rate-limit players.

## Trust model

The server is private, and its whitelist holds only trusted players. Dave can run arbitrary code inside the server JVM **on purpose**. The safeguards are there to prevent accidents, not attacks:

- Payloads run on the main thread under a per-tick time budget, with interrupt checks compiled into their loops and calls.
- Exceptions are caught and sent back to Dave, so they never reach the server.
- Result sizes are capped.
- A blocklist catches obvious footguns such as `System.exit` and server shutdown.
- Scripts that change the world need the player to confirm them in chat.
- Dave runs code on a player's own client only if that player turns on `clientEvalAllowed` in their client config. It is off by default, because that code runs on their machine, not the server.

If the server is ever opened to untrusted players, this whole design has to be rethought.
