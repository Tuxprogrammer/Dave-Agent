# DaveBridge

A Forge mod for Minecraft 1.7.10 / GT New Horizons that connects the server to an external AI agent ("Dave").

- **Server half (required on the server):** a local WebSocket the agent connects to, chat triggers
  (`dave,` `@dave` `!dave`), player join/leave events, Dave's replies as rich chat (item tooltips, NEI bookmark
  and quest links, buttons, rendered per recipient), `/dave status|reload`, and a
  main-thread task queue that later milestones (Groovy eval, introspection, SRG/MCP mapping) build on.
- **Client half (optional on clients):** a thinking indicator, links that open NEI recipe/usage pages, and an
  "Ask Dave" key that sends the question with what you are looking at and holding. Clients never talk to the agent; everything goes through
  the server. Players without the mod use Dave through plain chat.

One jar for both sides (`acceptableRemoteVersions = "*"`). Built for the GTNH 2.9.x dedicated server on modern
Java (17+ via lwjgl3ify); the code also runs on Java 8.

See [PROTOCOL.md](PROTOCOL.md) for the WebSocket and packet protocol and every config key,
[docs/dave-markup.md](docs/dave-markup.md) for the chat markup Dave writes (prompt-ready), and
[docs/chat-integration.md](docs/chat-integration.md) for how it maps onto the pack's native chat features
(BetterQuesting quest links, NEI bookmark links, GTNHLib item names, sharewhereiam waypoints).

## Install

1. Put `build/libs/davebridge-<version>.jar` into the server's `mods/` folder (and optionally clients').
2. Start the server once. It writes `config/davebridge.cfg` with a random `authToken`.
3. Point the agent at `ws://127.0.0.1:25580` and send `{"type":"auth","token":"<authToken>"}` first.

In Docker (Dave in his own container on the same stack network), set `bindAddress=0.0.0.0`, don't publish
port 25580, and pass the token to Dave's container as a secret. See "Docker deployment" in
[PROTOCOL.md](PROTOCOL.md).

## Package layout

| Package | Loaded on | Contents |
|---|---|---|
| `com.tuxprogrammer.davebridge` | both | `@Mod` class |
| `...common` | both | proxy base, server config, packet DTOs, packet channel and chunking, main-thread queue |
| `...server` | both (logical server) | agent WebSocket, chat hooks and relay, `/dave` command, client-mod tracking |
| `...client` | client only | `ClientProxy`, rendering, Ask key, context capture, client config |

Nothing outside `client` references client classes; `SideSafetyTest` checks the compiled classes.

## Build and test

```sh
./gradlew spotlessApply build    # format, compile, unit + side-safety tests
./gradlew runServer21            # dev dedicated server on Java 21 with lwjgl3ify
uv run tools/dave_client.py --config run/server/config/davebridge.cfg selftest
uv run tools/e2e_chat_test.py --mc-port <server-port> --commands --stop
```

The e2e test needs `online-mode=false` on the dev server and, for `--commands`/`--stop`, the test player
`PlainBot` in `run/server/ops.json`. Dev runs load NEI, CodeChickenCore and BetterQuesting (pinned to the pack's
versions); for the quest-link checks, copy the pack's `config/betterquesting/DefaultQuests` into
`run/server/config/betterquesting/` so BetterQuesting loads the real quest database.

`tools/` scripts are for local dev servers only.

The version comes from git tags (GTNH buildscript). The clone still carries the template's tags, so tag
DaveBridge's first release (or build with `VERSION=0.1.0 ./gradlew build`).

## Template

Built on the GTNH ExampleMod buildscript (RetroFuturaGradle). Do not edit `build.gradle.kts` or
`settings.gradle.kts`; use `gradle.properties`, `dependencies.gradle` and `repositories.gradle`. Buildscript
help: [docs/FAQ.md](docs/FAQ.md). Agent guidance: [CLAUDE.md](CLAUDE.md) and `.claude/skills/`.

## License

MIT, Copyright (c) 2026 Spencer Callicott. See [LICENSE](LICENSE). Notices for the template and the shaded libraries are in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md); both files also ship inside the jar.
