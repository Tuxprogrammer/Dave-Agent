# DaveBridge protocol

DaveBridge connects a Minecraft 1.7.10 (GT New Horizons) server to an external AI agent ("Dave").

```
 player client ──(plain chat)───────────────┐
 player client ──(davebridge packet channel)─┤   Minecraft server   ──(WebSocket, JSON)──  agent daemon
   (optional DaveBridge client half)         │   (DaveBridge server half)
```

- The **server** is the only proxy. Clients never talk to the agent or the daemon directly.
- The **agent WebSocket** (section 1) carries JSON between the server and the daemon.
- The **packet channel** (section 2) carries JSON packets between the server and clients that have the
  optional client half. Players without it use Dave through plain chat; everything degrades to chat lines.

Protocol versions: WebSocket `protocol: 1`, packet channel `protocol: 1`.

---

## 1. Agent WebSocket

`ws://<bindAddress>:<port>` (default `ws://127.0.0.1:25580`). Text frames only, one JSON object per frame.
Binary frames get an `error`.

### 1.1 Authentication

Every connection must authenticate with the `authToken` from `config/davebridge.cfg`, in one of two ways:

1. **First message:** `{"type":"auth","token":"<token>"}`. Anything else first (including malformed JSON or a
   binary frame), a wrong token, or no auth within `authTimeoutSeconds` gets
   `{"type":"error","code":"unauthorized",...}` and the connection is closed (close code 1008).
2. **Handshake header:** `Authorization: Bearer <token>` or `X-Dave-Token: <token>`. A wrong header token
   fails the handshake. A correct one authenticates immediately.

On success the server sends:

```json
{"type":"hello","ts":1730000000000,"protocol":1,"mod":"davebridge","version":"0.1.0",
 "session":3,"botName":"Dave","accepts":["list_players","ping","say","thinking"]}
```

`accepts` lists the inbound message types this server handles. Later milestones add types here, so the
daemon can feature-detect.

Connections beyond `maxClients` are refused at the handshake.

### 1.2 Common fields

- Every server message has `type` and `ts` (epoch milliseconds).
- Any inbound message may carry `reqId` (any JSON value except `null`, which counts as absent). Replies to that
  message (`ack`, `error`, `pong`, `players`, ...) echo it back unchanged. That includes a `bad_json` error for an
  object without a string `type`; only a frame that is not a JSON object at all gets an error without `reqId`.
- Unknown fields are ignored in both directions.

### 1.3 Server to agent: events

#### `chat`

A player addressed Dave (or `forwardAllChat` is on).

```json
{"type":"chat","ts":1730000000000,"id":"8d7c...-uuid",
 "player":"Steve","playerUuid":"069a79f4-...","dim":0,"x":12.5,"y":64.0,"z":-3.25,
 "hasClientMod":false,
 "message":"dave, how do I make steel?","triggered":true,"prompt":"how do I make steel?",
 "source":"chat"}
```

| Field | Meaning |
|---|---|
| `id` | Random UUID for this event. Pass it back as `replyTo`. |
| `player`, `playerUuid`, `dim`, `x`, `y`, `z` | Sender and position (rounded to 0.01) when the message was handled. |
| `hasClientMod` | The sender runs the DaveBridge client half. |
| `message` | The chat text as the server received it. |
| `triggered` | The message starts with a trigger prefix (or came from the client half's Ask). |
| `prompt` | Only when triggered: the message without the prefix and the `,`/`:` after it. |
| `source` | `"chat"` for normal chat. `"client"` for an Ask from the client half (section 2). |
| `context` | Only for `source:"client"`: what the player was looking at and holding (see `Ask`). **Client-reported and untrusted.** |

Triggered chat is matched case-insensitively against `triggerPrefixes` at the start of the message. A prefix
ending in a letter must be followed by a non-word character, so `@dave hi` matches and `@davey hi` does not.
Messages cancelled by other mods (mutes, chat filters) are not forwarded. `source:"client"` asks are not shown
to other players; the asker sees a gray `You -> Dave: ...` echo. Reply privately (`target` = the player) or
publicly (`@a`) as you see fit.

If no agent is connected, a triggered sender gets a private "Dave is not connected right now." notice
(`notifyWhenOffline`).

#### `player_join` / `player_leave`

```json
{"type":"player_join","ts":...,"player":"Steve","playerUuid":"...","dim":0,"x":...,"y":...,"z":...,"hasClientMod":false}
```

`hasClientMod` is always `false` in `player_join`, because the client half says hello a moment after login.
Watch for `client_mod`.

#### `client_mod`

A player's client half said hello. Sent once per login, shortly after `player_join`, and again (same shape) whenever
that player changes their opt-in mid-session (`client_settings`, section 2.3). Treat the latest one as current.

```json
{"type":"client_mod","ts":...,"player":"Steve","playerUuid":"...","dim":0,"x":...,"y":...,"z":...,
 "hasClientMod":true,"modVersion":"0.1.0","protocol":1,
 "capabilities":["render","ask","context"],"clientEvalAllowed":false}
```

`clientEvalAllowed` is the player's opt-in (client config, `/davebridge optin|optout`) for milestone 2 client-side
eval.

#### `server_stopping`

Sent to authenticated agents just before the server closes the socket (close code 1001).

### 1.4 Agent to server: requests

All game actions run on the server thread through the main-thread task queue (section 3), so a reply comes
on a later server tick, not immediately.

#### `say`

```json
{"type":"say","target":"@a","markup":"Smelt {item:minecraft:iron_ingot}\n{send:dave, more|More}","replyTo":"8d7c...","reqId":7}
```

| Field | Required | Meaning |
|---|---|---|
| `markup` | one of the three | Dave markup (section 1.5): styles, item/quest/NEI links, buttons. **The normal way to talk.** |
| `text` | one of the three | Plain text. Newlines split lines; URLs become clickable; `§` codes pass through. |
| `components` | one of the three | Escape hatch: raw 1.7.10 chat JSON, one component per line (an array) or a single component. |
| `target` | no (default `@a`) | `"@a"` for everyone, or a player name (case-insensitive). A named player gets a **whisper**. |
| `replyTo` | no | The `id` of the `chat` event being answered (logged). |

Exactly one of `markup`, `text` and `components` must be present (`bad_request` otherwise).

Every message is delivered as ordinary chat lines, rendered **per recipient** (section 1.6):
- Public messages start each line with `<Dave> ` (name in `botNameColor`).
- Whispers use vanilla's translated "Dave whispers to you: " prefix (gray italic); the body keeps its own style.
- Blank lines are dropped and long lines wrap at spaces (`maxLineLength`) without splitting a link.
- A message stops after `maxLinesPerMessage` lines with `... (truncated)` (for `markup` and `text` alike, with a
  warning). Markup longer than 4 characters per visible character (`maxLinesPerMessage` x line width) is cut before
  it is parsed, with a warning.
- A line whose JSON would exceed 30000 bytes is degraded: item hovers become text hovers, then hovers are
  removed, then it becomes plain text, each with a warning.
- Each recipient hears `replySound` (only they do). Players with the client half get `thinking{clear:true}`, which
  removes their thinking indicator.

`components` are checked like markup:
- `open_url` must be http/https (and in `urlAllowlist`).
- `run_command` must be an allowlisted command, or chat text starting with a trigger prefix.
- `open_file`, `twitch_user_info` and unknown click actions are removed (vanilla drops them when parsing; DaveBridge
  still reports each one).
- Every removal is a warning; JSON that does not parse is `bad_request`.

Reply (only when `reqId` was given):

```json
{"type":"ack","ok":true,"for":"say","recipients":1,"warnings":["{item:nope:x}: unknown item nope:x:0"],"reqId":7}
```

- `recipients` is how many players got the message (0 for `@a` on an empty server).
- `warnings` lists everything that was degraded: unknown items, fluids, quests or players; blocked links or
  commands; markup that was not understood (kept as text); truncation. Read them to correct the next message.
  Warnings are also logged on the server.
- Errors: `not_found` if the target player is offline, `bad_request` for an empty message.

#### `thinking`

```json
{"type":"thinking","target":"Steve","reqId":8}
```

Shows a short gray italic "Dave is thinking..." line. With the client half the line replaces any earlier
thinking line and disappears when the answer arrives (or after 60 s). Reply: `ack` (with `recipients`) /
`error` as for `say`.

#### `list_players`

```json
{"type":"list_players","reqId":9}
```

Reply:

```json
{"type":"players","ts":...,"reqId":9,"players":[{"player":"Steve","playerUuid":"...","dim":0,"x":...,"y":...,"z":...,"hasClientMod":true}]}
```

#### `ping`

```json
{"type":"ping","reqId":10}
```

Answered immediately on the socket thread (not via the queue):
`{"type":"pong","ts":...,"tick":123456,"queueDepth":0,"reqId":10}`. `tick` is the server tick counter at the
last tick; if it stops advancing between pings, the server thread is stuck.

### 1.5 Dave markup

The full, prompt-ready spec is [docs/dave-markup.md](docs/dave-markup.md). In short:

- **Lines and text:** one chat line per line of markup; blank lines dropped. `# Heading` lines are bold;
  `- item` / `* item` become bullets. `\` escapes the next character.
- **Markdown spans** (inside one line): `**bold**`, `*italic*`, `__underline__`, `~~strike~~`, `` `code` ``
  (gray). A delimiter only counts with a partner later on the same line and no space inside it, so `2 * 3`
  stays literal.
- **Tag spans** (may cross lines):
  - colors: `{gold}...{/gold}`, `{color:red}`; any vanilla color name, plus aliases orange, grey, pink,
    purple, cyan, lime, magenta;
  - styles: `{b}` `{i}` `{u}` `{s}` `{obf}`;
  - closing: `{/}` closes the innermost span, `{/name}` closes that one and anything opened after it, `{/color}`
    closes the innermost color;
  - `{br}` is a line break.
- **Tokens:** `{kind:argument|label}`. The label is optional and split off at the **last** unescaped `|`. In a
  hover text, `\n` is a newline; in other token arguments and labels it is a space.

| Token | Argument |
|---|---|
| `item`, `recipe`, `uses` | `modid:name`, `modid:name:meta`, `modid:name@meta`, `name` (minecraft), `ore:<oredict name>` (an unknown ore name is never created), numeric `id[:meta]` |
| `fluid` | fluid registry name |
| `chain` | comma-separated items, each with an optional `*amount` |
| `quest` | quest UUID, BQ's 22/24-character id, or exact quest name (case-insensitive; first match, with a warning if several; an id that names no quest is tried as a name) |
| `url` (alias `link`) | http(s) URL |
| `player` | online player name |
| `waypoint` | `x,y,z` or `x,y,z,dim` |
| `guide` | GuideNH guide id `modid:path` |
| `send` | chat text the player will say; must start with a trigger prefix, at most 100 characters, no `§` |
| `suggest` | text put into the player's chat line (cut to 100) |
| `cmd` | `/command ...` in `commandAllowlist`, at most 100 characters |
| `hover` | hover text; markdown spans and one level of tags and tokens are allowed (`{hover:{red}Hot{/}\nmelts tin\|lava}`); the label is what is shown |

Anything not understood (unknown tag or token kind, unmatched `{`, stray `{/}`, unknown `{/name}`) stays literal
text and adds a warning. Unresolved tokens (including one whose lookup fails with an error) show their label (or argument) as plain text, keeping the surrounding style. A
`{send:}` that breaks its rules becomes a `{suggest:}` with a warning.

### 1.6 Per-recipient rendering and native formats

Each token compiles to the pack's own chat format where one exists, so links work for every GTNH player without
the client half. Research and sources: [docs/chat-integration.md](docs/chat-integration.md).

- **Items** (`item`, `recipe`, `uses`):
  - Shown as the item's own chat component (`ItemStack.func_151000_E()`; GTNHLib localizes it on each client),
    with the **show_item** hover.
  - The click is **NEI's native bookmark link**: the server first sends NEI's `CACHE_BOOKMARK_DATA` packet
    (channel `NEI`, id 25) to that recipient only, then the click runs NEI's client command
    `/nei_bookmark <payloadId>`.
  - For players **with the client half**, `recipe` / `uses` instead run `/davebridge nei recipe|uses
    <modid:name:meta>`, which opens the NEI page (NEI has no native command for that).
- **Chains:** NEI bookmark **group** payload (TODO-list view, items with amounts, no recipe ids), clicked via
  `/nei_bookmark`.
- **Quests:**
  - BetterQuesting's share token `betterquesting.msg.sharequest:<24-char id>` as one unstyled run. The BQ client
    rewrites the line into `[Quest: #id - name]` and the click `/bq_client show <id>`.
  - Because BQ replaces the whole line, a quest link never shares a line with another link.
  - The quest is validated against BQ's server-side database first.
- **Fluids:** GTNHLib's client-localized fluid name with a hover (id, temperature); no click.
- **Waypoints:** sharewhereiam's share format, clicked via `/savewaypoint <base64>` (opens JourneyMap's editor).
- **Guides:** `/guidenhc open <id>` (GuideNH).
- **Everything else** is vanilla chat: `open_url`, `run_command`, `suggest_command`, `show_text`.

If NEI or BQ is not on the server, item links keep their hover (and the client-half click), quests become plain
text, and chains become a hover list, all with warnings.

### 1.7 Errors

```json
{"type":"error","ts":...,"code":"bad_json","message":"malformed JSON: ...","reqId":7}
```

| Code | When |
|---|---|
| `bad_json` | The frame is not a JSON object, or has no string `type`. |
| `bad_request` | A field is missing or has the wrong type; binary frame; second `auth`. |
| `unknown_type` | No handler for `type`. |
| `unauthorized` | Not authenticated (the connection is then closed). |
| `not_found` | Target player is not online. |
| `queue_full` | The main-thread queue is at `maxQueueDepth`. Retry later. |
| `cancelled` | The server is stopping: queued actions that had not run yet, and any message received while it stops. Sent before `server_stopping` and the close. |
| `internal` | A handler threw. Logged on the server; the server itself is unaffected. |

Errors never close an authenticated connection.

### 1.8 Planned (not implemented yet)

These names are reserved; servers that support them list them in `hello.accepts`.

- **`client_eval`** (agent to server): run a script on one player's client.
  `{"type":"client_eval","player":"Steve","id":"e1","script":"...","mode":"groovy","reqId":...}`.
  The server only forwards it if that player's `client_mod` event reported `clientEvalAllowed: true`, sends a
  `ClientEvalRequest` packet and relays the `ClientEvalResult` back as
  `{"type":"client_eval_result","id":"e1","player":"Steve","ok":true,"result":...}` or with `"ok":false,"error":"..."`.
- **Server-side `eval`** (Groovy on the server thread via the same task queue), **introspection**
  (reflection over loaded classes and objects) and **SRG/MCP name mapping** will be further request types.

---

## 2. Packet channel `davebridge` (server <-> client half)

An FML `SimpleNetworkWrapper` channel named `davebridge`. Only clients with the DaveBridge client half use it.

### 2.1 Framing and chunking

1.7.10 rejects client-to-server custom payloads of 32767 bytes or more, so every packet is serialized to
UTF-8 JSON (vanilla Gson) and sent as one or more **frames** of at most 30000 data bytes:

| Discriminator | Direction | Frame |
|---|---|---|
| 0 | client to server | `Frame.ToServer` |
| 1 | server to client | `Frame.ToClient` |

Frame layout: `byte version (1)`, `utf8 kind`, `varint streamId`, `varint index`, `varint total`,
`varint length`, `length bytes`. The receiver reassembles a stream when all `total` chunks have arrived (in any
order), then decodes the JSON as the packet class registered for `kind`.

Limits on the receiving side (clients are untrusted): a reassembled client packet is at most 256 KiB (so at
most 9 chunks may be announced), a client may have 4 streams open at once and an unfinished stream expires
after 30 s. Server packets are capped at 8 MiB on the client. Malformed frames, unknown
kinds and kinds sent in the wrong direction are logged and dropped, never kick or crash anyone.

### 2.2 Handshake

1. After joining (once the player entity exists), the client half sends **`client_hello`**.
2. On its main thread the server replies with **`server_hello`**. If the hello's `protocol` equals the server's, it
   then records the player as having the client mod and tells the agent (`client_mod` event). A client with a
   different `protocol` is not recorded: the server treats it as a plain client.
3. Until `server_hello` arrives the client assumes the server does **not** run DaveBridge and falls back to
   plain chat. It also stays on plain chat (and says so in one chat line) when `server_hello.protocol` differs from
   its own. So both sides agree: either both use the packet channel or neither does. If the server cannot answer (its
   task queue is full), it records nothing and both sides stay on plain chat.

The client says hello again on every new connection. The server forgets a player on logout.

### 2.3 Packets

| Kind | Direction | Fields |
|---|---|---|
| `client_hello` | C->S | `modVersion`, `protocol`, `capabilities` (string[], e.g. `render`, `ask`, `context`, `nei`), `clientEvalAllowed` (bool) |
| `ask` | C->S | `text` (string), `context` (object) |
| `client_settings` | C->S | `clientEvalAllowed` (bool): the player changed their opt-in mid-session |
| `client_eval_result` | C->S | **Reserved (M2).** `id`, `ok`, `result` (any JSON), `error`. Ignored by the server today. |
| `server_hello` | S->C | `modVersion`, `protocol`, `botName`, `triggerPrefixes` (string[]), `maxAskLength` (int; 0 or missing from older servers) |
| `dave_message` | S->C | **Unused since rich chat.** `botName`, `text`, `replyTo`. Dave's replies now arrive as normal chat for everyone; clients still render it if received. |
| `thinking` | S->C | `botName`, `clear` (bool): show the indicator, or remove it because the answer arrived |
| `client_eval_request` | S->C | **Reserved (M2).** `id`, `script`, `mode`. Never sent today; the client logs and ignores it. |

Server-side validation of client packets:

- `client_hello`: only the first one per login counts; version and capability strings are clipped to 64
  characters, at most 32 capabilities. Chat lines use client-command links (`/davebridge nei ...`) only for players
  whose client reported the `nei` capability; everyone else gets the plain-chat formats.
- `client_settings`: only accepted after `client_hello`; a value that did not change is dropped, a change is
  announced to the agent as a fresh `client_mod` event. Servers older than 0.1.2 log it as an unknown kind and
  ignore it (the opt-in then reaches them on the next login).
- `ask`: only accepted after `client_hello`; `text` must be 1..`maxAskLength` characters and must contain a question
  after its trigger prefix (a bare `dave,` is refused); at most one per `askCooldownMillis` per player. Refused asks
  get a gray notice saying why (empty, too long, or "slow down"). `context` is dropped unless it is a JSON object of at
  most 16 KiB. An accepted ask is shown to **every player** as an ordinary chat line, `<Player> text`, exactly like
  vanilla chat and with the trigger prefix kept, because Dave's replies are public and others may join in. It is
  not posted as a `ServerChatEvent` (that would relay it twice), so other chat mods do not see it. It is relayed to the
  agent as a `chat` event with `source:"client"`, `triggered:true` and `prompt` = text without a trigger prefix
  (if it had one).

### 2.4 Ask context

The client half captures context when the player presses the **Ask Dave** key (unbound by default; set it in
Controls). The key opens a chat line pre-filled with `askPrefix` (default `dave, `). On a DaveBridge server
the line is sent as an `ask` packet, up to the server's `maxAskLength` (1000 if the server does not say), and everyone
sees the question as normal chat (see 2.3); on any other server it is sent as ordinary chat. A `/command` typed
into that line still goes through the normal command path; one longer than vanilla's 100 characters is refused with
a message (unless it is a client command), since the chat packet would cut it short.

```json
{"dim":0,"biome":"Plains",
 "heldItem":{"id":"minecraft:iron_pickaxe","meta":0,"count":1,"hasNbt":false,"name":"Iron Pickaxe"},
 "lookingAt":{"kind":"block","x":10,"y":64,"z":-4,"side":1,"id":"gregtech:gt.blockmachines","meta":0,
              "name":"Basic Macerator","tileEntity":"gregtech.api.metatileentity.BaseMetaTileEntity"}}
```

`lookingAt` is either `{"kind":"block",...}` as above or
`{"kind":"entity","entityId":..,"class":"...","type":"Zombie","name":"...","uuid":"..."}`.
If a lookup throws, the field is left out (or `captureError` is set). Not captured yet: NEI's hovered item, and
context from inside GUIs (keys pressed in a GUI do not reach the keybind in 1.7.10, so the key only works
in-world). An `openGui` field (screen class name) is reserved for that.

### 2.5 What the client half adds to chat

- **Thinking indicator.** `thinking` shows one gray italic line that replaces itself on repeat; `thinking` with
  `clear:true` (sent right after Dave's reply) removes it. It also expires after 60 s.
- **Client command `/davebridge nei <recipe|uses> <modid:name[:meta]>`.** Registered with `ClientCommandHandler`,
  so a `run_command` click reaches it. On the next client tick it closes chat and opens NEI's recipe or usage page
  (deferred so a typed command is not closed again by the chat screen). The client reports it as the `nei`
  capability when NEI is installed. It only opens GUIs and
  never changes game or client state. Server-rendered links use it for players with the client half (see 1.6).
- Everything else (styles, NEI bookmarks, quest links, buttons) is plain chat that every client renders.

---

## 3. Main-thread task queue

All world and player actions from the agent run on the server thread, during `ServerTickEvent` (END phase).
Socket threads submit `Callable`s to a bounded queue (`maxQueueDepth`) and get a `CompletableFuture`; each
tick the queue runs tasks until `tickBudgetMillis` is used up, always at least one. Exceptions complete the
future and become `error` replies; they never reach the tick loop. The same queue class is drained on the client
tick by the client half. Later milestones (Groovy eval, introspection) submit their work to the same queue.

---

## 4. Configuration

### `config/davebridge.cfg` (server, also used by singleplayer)

| Category | Key | Default | Meaning |
|---|---|---|---|
| network | `enabled` | `true` | Start the WebSocket at all. |
| network | `startOnIntegratedServer` | `false` | Also open the socket for singleplayer/LAN worlds. |
| network | `bindAddress` | `127.0.0.1` | Address to bind. `127.0.0.1` for dev; `0.0.0.0` in Docker (see section 6). |
| network | `port` | `25580` | TCP port. |
| network | `authToken` | random | Shared secret. Generated (48 hex chars) on first run if empty. |
| network | `authTimeoutSeconds` | `10` | Drop connections that have not authenticated by then. |
| network | `maxClients` | `4` | Maximum simultaneous WebSocket connections. |
| network | `maxMessageBytes` | `1048576` | Largest inbound WebSocket frame. |
| chat | `triggerPrefixes` | `dave,` `@dave` `!dave` | Case-insensitive prefixes that address Dave. |
| chat | `forwardAllChat` | `false` | Forward every chat message (`triggered:false` for the rest). |
| chat | `botName` | `Dave` | Name in `<Dave>`. |
| chat | `botNameColor` | `aqua` | Minecraft color name for the plain-chat name. |
| chat | `maxLineLength` | `200` | Plain-chat wrap width. |
| chat | `maxLinesPerMessage` | `40` | Plain-chat lines per `say` before truncation. |
| chat | `notifyWhenOffline` | `true` | Tell a player when they address Dave and no agent is connected. |
| chat | `askCooldownMillis` | `1000` | Minimum time between asks from one client. |
| chat | `maxAskLength` | `2000` | Longest ask text accepted. |
| chat | `urlAllowlist` | (empty) | Hosts `{url:}` may link to, matched as domain suffixes; empty allows any http/https host. |
| chat | `commandAllowlist` | `/dave` `/davebridge` `/bq_client` `/nei_bookmark` `/savewaypoint` `/guidenhc` | Commands a `{cmd:}` button or a raw `run_command` may run. |
| chat | `replySound` | `random.orb` | Sound each recipient hears when Dave replies; empty disables. |
| chat | `replySoundVolume` | `0.5` | 0 to 1. |
| chat | `replySoundPitch` | `1.4` | 0.5 to 2. |
| queue | `tickBudgetMillis` | `5` | Time per tick for queued tasks. |
| queue | `maxQueueDepth` | `1000` | Further tasks are rejected (`queue_full`). |

`/dave reload` re-reads the file. The socket restarts only if `bindAddress`, `port`, `authToken`,
`maxClients` or `maxMessageBytes` changed (which also drops connected agents), or if `enabled` changed.

### `config/davebridge-client.cfg` (client half only)

| Category | Key | Default | Meaning |
|---|---|---|---|
| client | `clientEvalAllowed` | `false` | Opt in to letting Dave run code on this computer (milestone 2). Only reported to the server today. Same as `/davebridge optin` / `optout`. |
| client | `optInReminder` | `true` | Show the opt-in nudge when joining a DaveBridge server while not opted in. `/davebridge optout` turns it off. |
| client | `askPrefix` | `dave, ` | Text pre-filled by the Ask Dave key. |

## 5. Commands

`/dave status` and `/dave reload`, permission level 3 (ops). Status shows the socket state, connected and
authenticated agents, queue depth and timing, and how many online players have the client half.

Client half only:

- `/davebridge nei <recipe|uses> <modid:name[:meta]>` (section 2.5), the target of Dave's recipe and usage links.
- `/davebridge optin`, `/davebridge optout`, `/davebridge status` (also bare `/davebridge`): the client-eval opt-in.
  Saved to `davebridge-client.cfg` and sent to the server at once (`client_settings`). Opting out also turns off
  the reminder.

The client options are also editable in game: Mods > DaveBridge > Config.

**Opt-in nudge.** About five seconds after joining a server that answers `server_hello`, a client that is not opted
in (and has `optInReminder` on) shows one `[Dave]` line explaining what opting in gives, with clickable
`[Opt in]` (`/davebridge optin`) and `[No thanks]` (`/davebridge optout`) buttons. The text is in the client's
lang file (`davebridge.optin.*`), so it never comes from the server.

## 6. Docker deployment

Dave runs as his own container in the same Docker stack as the GTNH server and connects over the stack's
internal network, e.g. `ws://gtnh:25580` (the server's service name).

- **Server container:** set `bindAddress=0.0.0.0` in `config/davebridge.cfg`. Loopback (`127.0.0.1`) is not
  reachable from other containers.
- **Do not publish the port.** Leave 25580 out of the server's `ports:` (publish only the Minecraft port), and
  don't use `network_mode: host`. The bridge is then reachable only from containers on the stack network, never
  from the host or the LAN.
- **Token as a secret.** The server generates `authToken` into `config/davebridge.cfg` on first start (or set
  your own value there before starting). Give the same value to Dave's container as a Docker secret (e.g.
  mounted at `/run/secrets/dave_token`), not as a plain environment variable in the compose file or image. Dave
  sends it in the `auth` message or the `Authorization: Bearer` header. Changing it takes `/dave reload` (which
  drops connected agents) and a matching secret update.
- Check with `/dave status`: it should say `listening on 0.0.0.0:25580`.

```yaml
services:
  gtnh:
    # ... GTNH server image; config/davebridge.cfg has bindAddress=0.0.0.0
    ports:
      - "25565:25565"        # Minecraft only; 25580 stays internal
  dave:
    # ... agent image; connects to ws://gtnh:25580
    secrets:
      - dave_token
secrets:
  dave_token:
    file: ./secrets/dave_token   # same value as authToken in davebridge.cfg
```
