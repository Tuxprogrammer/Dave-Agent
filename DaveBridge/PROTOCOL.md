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

`accepts` lists the inbound message types this server handles. Servers from 0.2.0 add `lesson` and `lesson_stop`. Later milestones add types here, so the
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
Messages cancelled by other mods (mutes, chat filters) are not forwarded. `source:"client"` asks are shown to
every player as ordinary `<Player> text` chat, like typed chat (section 2.3). Reply publicly (`@a`) by default, or
privately (`target` = the player) when asked.

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

#### `lesson_status`

A lesson (section 1.4 `lesson`) ended on the player's client. Relayed from the client half (untrusted, validated:
unknown states are dropped, unknown reasons become `other`, `id` is cut to 64 characters, at most one per 200 ms).

```json
{"type":"lesson_status","ts":...,"id":"ebf-muffler","state":"stopped","reason":"walked_away",
 "player":"Steve","playerUuid":"...","dim":0,"x":...,"y":...,"z":...,"hasClientMod":true}
```

`state` is `finished` (a non-looping lesson played to the end; `reason` `done`) or `stopped`, with `reason` one of
`player` (chat button, stop key or `/davebridge stop`), `walked_away`, `dimension`, `replaced` (a newer lesson),
`agent` (`lesson_stop`), `timeout` (10 minutes of play), `rejected` (the client could not play it) or `other`.

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
- Blank lines are dropped. Lines wider than the chat box (`chatWidth` pixels, measured with the default font) are
  cut at spaces into a `<Dave>` line plus continuation lines indented by two spaces, without splitting a word or a
  link, so the client never wraps them. Only a word wider than a whole line is cut.
- A message stops after `maxLinesPerMessage` lines with `... (truncated)` (for `markup` and `text` alike, with a
  warning). Markup longer than one character per pixel of output (`maxLinesPerMessage` x line width in pixels) is
  cut before it is parsed, with a warning.
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
- A named `target` who is not online gets nothing: the ack says `recipients: 0` with the warning
  `player 'X' is not online; the whisper was dropped` (since 0.2.0; earlier versions answered `not_found`). The
  asker may have left, or be a `/dave ask` test name (section 5).
- Errors: `bad_request` for an empty message.

#### `thinking`

```json
{"type":"thinking","target":"Steve","reqId":8}
```

Shows a short gray italic "Dave is thinking..." line. With the client half the line replaces any earlier
thinking line and disappears when the answer arrives (or after 60 s). Reply: `ack` (with `recipients`, 0 when the
player is not online) / `error` as for `say`.

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

#### `lesson`

Shows one player a guided demonstration ("show me"): a ghost Dave, visible only to that player, walks a route,
looks and points at blocks, holds items, shows ghost blocks and highlighted blocks with labels, then loops until the
player stops it. Nothing in the world changes. Design: `docs/plans/guided-demos.md` (repository root).

```json
{"type":"lesson","player":"Steve","reqId":12,"lesson":{
  "id":"ebf-muffler","title":"EBF muffler hatch","loop":true,"speed":0.6,"steps":[
    {"walkTo":[102,64,-18]},
    {"lookAt":[104.5,65,-18.5]},
    {"hold":"gregtech:gt.metatool.01:22"},
    {"highlight":{"pos":[104,64,-19],"color":"gold","label":"Controller goes here"}},
    {"ghost":{"pos":[104,65,-19],"block":"gregtech:gt.blockmachines","meta":1000,"facing":"north"}},
    {"swing":true},
    {"say":"Right-click with a screwdriver to set the output side"},
    {"wait":40}]}}
```

| Field | Meaning |
|---|---|
| `player` | One online player (case-insensitive). `@a` is refused. |
| `lesson.id` | Optional, 1-64 of `A-Z a-z 0-9 _ . : -`; made up otherwise. Echoed in the ack and in `lesson_status`. |
| `lesson.title` | Optional, cut to 64 characters; shown in chat and on the HUD. |
| `lesson.loop` | Default `true`: replay after a 2 s pause until the player stops it. `false`: play once, keep the last frame 5 s. |
| `lesson.speed` | Walking speed as a multiple of vanilla walking (4.3 blocks/s). Default 0.6, clamped to 0.1..2. |
| `lesson.steps` | Played in order. Each step is an object with exactly one of the keys below. |

| Step | Argument | Does | Ticks |
|---|---|---|---|
| `walkTo` | `[x,y,z]` (feet position) | Walks there from where he is. The server replaces the walk with the route a mob would walk (a `walkTo` per turn); the client interpolates between them. | distance / speed |
| `lookAt` | `[x,y,z]` | Turns head and body to the point and points at it with his right arm. | 15 |
| `hold` | `"modid:name[:meta]"` (also `@meta`), or `""` / `null` for empty hands | Holds the item. Until the first `hold`, Dave holds GregGuns' Golden Revolver if the player has GregGuns. | 10 |
| `highlight` | `{"pos":[x,y,z],"color":..,"label":..}` or just `[x,y,z]` | Pulsing colored box on the block (outline visible through walls), label above it; Dave looks and points. `color`: a chat color name (`gold` default, `red`, `green`, `aqua`, ... plus `orange`, `pink`, `cyan`, `lime`, `purple`) or `#rrggbb`. `label` up to 80 characters. | 25 |
| `ghost` | `{"pos":[x,y,z],"block":"modid:name","meta":0,"facing":"north"}` | Translucent block, drawn by the block's own inventory renderer (for GT machines `meta` is the meta tile entity id, as on the item). `facing` (`north`/`south`/`east`/`west`/`up`/`down`) turns the block's inventory front (south) that way. | 25 |
| `swing` | `true` | Swings his arm. | 10 |
| `say` | text, up to 200 characters | Floating line over Dave's head until the next `say` or the end of the pass. | 40..200 (by length) |
| `wait` | ticks, 1..400 | Pause. | as given |

Highlights and ghost blocks stay up for the rest of the pass and are cleared when it restarts.

Validation (on the server thread):
- Every position must be within **256 blocks** of where the player stands (**32** for clients before 0.2.4, which
  drop farther points), in **y 0..255**, in a **loaded chunk**. The client stops the lesson when the player is 320
  blocks from that spot.
  Highlight and ghost positions are floored to block positions.
- Items and blocks must exist in the server's registries. `ore:` and numeric ids are not accepted.
- At most **64 steps**; one pass at most **180 s** (3600 ticks).
- An invalid or unknown step (or extra keys) is dropped (or ignored) with a warning; the rest still plays. Text loses
  `§` codes and control characters.
- Dave appears with the player, two blocks in front of them (the closest spot a mob can walk to when that is inside a
  wall), so every walk, even the first, starts from the player.
- When the walks would make a pass longer than 180 s, the server raises `speed` (up to 2) so the pass fits, with a
  warning.

Reply:

```json
{"type":"ack","ok":true,"for":"lesson","id":"ebf-muffler","steps":8,"dropped":1,"passTicks":216,
 "warnings":["step 9: unknown step teleport, dropped"],"reqId":12}
```

Errors:
- `no_client_mod`: the player has no DaveBridge client half that plays lessons (no client half, a client half older
  than 0.2.0, or another packet protocol). Answer in chat instead. Lessons do **not** need `clientEvalAllowed`:
  they are data the client draws, never code.
- `not_found`: the player is offline. `bad_request`: `player` or `lesson` missing, or no step left after
  validation (the message lists the warnings).

A new lesson replaces the one playing (that one reports `lesson_status` `replaced`). The player stops a lesson with
the `[Stop]` chat button, the stop key (unbound by default), `/davebridge stop`, by walking more than 320 blocks from
where the lesson was made, by changing dimension, or after 10 minutes of play; `/davebridge pause` (or `[Pause]`)
toggles pause.

#### `lesson_stop`

```json
{"type":"lesson_stop","player":"Steve","id":"ebf-muffler","reqId":13}
```

Stops the lesson `id` on that player's client (or whatever is playing, without `id`). Reply: `ack`. Errors as for
`lesson`. The client answers with `lesson_status` (`stopped`, `agent`) if something was playing.

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
- **Highlights:** `{m:name}` colors a machine name aqua and `{i:name}` an item or fluid name green (a `|label`
  replaces the name). Common-rarity `{item:}` links and `{fluid:}` links use the same green. In text without a
  color of its own, the renderer colors voltage tiers in GregTech's tier colors and numbers with units
  (`480 EU/t`, `45s`, `x16`) in yellow.
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
| `no_client_mod` | `lesson` / `lesson_stop`: the player has no client half that plays lessons. |
| `queue_full` | The main-thread queue is at `maxQueueDepth`. Retry later. |
| `cancelled` | The server is stopping: queued actions that had not run yet, and any message received while it stops. Sent before `server_stopping` and the close. |
| `internal` | A handler threw. Logged on the server; the server itself is unaffected. |
| `disabled` | The feature is turned off in the server config (`eval.evalEnabled`, `eval.clientEvalRelay`). |
| `not_opted_in` | `client_eval` for a player whose client half has not opted in (or has no client half). |
| `unsupported` | `client_eval` for a client half too old to run scripts (no `eval` capability). |

Errors never close an authenticated connection.

### 1.8 Live eval (milestone 2)

Groovy scripts from the agent, run inside the server JVM (or, for opted-in players, their own client). The trust
model is the README's: trusted players only, so arbitrary code is accepted on purpose. The safeguards below prevent
accidents (a frozen tick, a crashed server, a world change nobody saw), not attacks. Servers that support this list
`eval`, `describe` and `client_eval` in `hello.accepts`.

#### `eval`

```json
{"type":"eval","id":"e1","script":"world.getBlock(0,64,0).getLocalizedName()","mode":"read",
 "player":"Steve","params":{"item":"gregtech:gt.metaitem.01:32600"},"timeoutMs":1000,"reqId":11}
```

| Field | Required | Meaning |
|---|---|---|
| `script` | yes | Groovy source, at most 64 KiB. Its last expression is the result. |
| `id` | no | Echoed in the result and in `eval_pending`. |
| `mode` | no | `"read"` (default) runs at once. `"write"` waits for the asking player's Confirm click (below). |
| `player` | for `write` | The asking player (the daemon fills it in from the turn). Bound as `player` when online. |
| `summary` | for `write` | One line shown to the player: what will change. |
| `params` | no | JSON object, bound as `params` (numbers arrive as doubles: use `params.n as int`). |
| `timeoutMs` | no | Time limit, default `evalTimeoutMillis` (500), at most `evalMaxTimeoutMillis` (5000). |
| `confirmTimeoutSeconds` | no | `write` only: how long to wait for the click (default 120, at most 600). |

**What a script sees.** `server` (MinecraftServer), `player` (the asker's EntityPlayerMP, or null), `asker` (name),
`world` (the asker's world, else the overworld), `params`, `log`, `out` (`println` goes to the result's `output`), and
`dave`, a helper object:

- reflection that speaks MCP names: `dave.fields(obj)`, `dave.methods(obj, "filter")`, `dave.get(obj, "name")`,
  `dave.call(obj, "name", args...)`, `dave.cls("full.ClassName")`, `dave.mcp("field_71071_by")`, `dave.srg("inventory")`;
- lookups (loaded state only; nothing loads a chunk): `dave.players()`, `dave.player(name)`, `dave.world(dim)`,
  `dave.worlds()`, `dave.te(dim,x,y,z)`, `dave.tiles(world)` / `dave.tiles()` (loaded tile entities),
  `dave.describe(dim,x,y,z)`, `dave.describe(stack)`, `dave.looking(player)`;
- formatting: `dave.item(stack)` (`id, meta, count, name, ore, nbt`), `dave.fluid(fluidStack)`, `dave.markupId(stack)`
  (for `{item:...}`), `dave.waypoint(x,y,z,dim,label)` (a `{waypoint:...}` markup link), `dave.dump(obj)`.

Common packages are imported (`net.minecraft.{block,entity,entity.player,init,inventory,item,nbt,server,tileentity,
util,world}`, `net.minecraftforge.{common.util,fluids,oredict}`); other classes need their full name or an import.

**MCP names work at runtime.** Outside the dev environment vanilla members only exist under SRG names
(`field_71071_by`). When a property or method of a Minecraft-hierarchy class is missing, it is retried under each
SRG name of that MCP name (table generated at build time from Forge's own mapping, the names mod source uses,
plus MCP stable_12, the names in the decompiled vanilla source), so `player.inventory`, `entity.getHealth()`,
`entity.health`, `stack.getItemDamage()` / `stack.getMetadata()` and `Blocks.stone` all work. Mod classes keep their
real names. On a dedicated server some mod classes declare client-only signatures without `@SideOnly`, so Java cannot
list their members; Groovy then dispatches through their nearest listable superclass (overrides still run), and
methods only that class declares are out of reach.

`dave.items(spec)` (a fast stack matcher) and `dave.gtRecipes(item, fluid, uses, map, limit)` (every GregTech
recipe map scanned in Java, tens to a few hundred milliseconds) keep heavy lookups off Groovy's dynamic dispatch.

**Safeguards.**
- Compiled off the server thread, then run on it through the main-thread queue (section 3).
- Time limit: a check compiled into every loop, method and closure stops the script with `errorType:"timeout"`.
  Java code it calls is not interrupted, so a long call inside another mod finishes first.
- Refused at compile time (`errorType:"blocked"`): `System.exit`, `Runtime.halt`, `initiateShutdown`, `stopServer`,
  `sleep`, `wait`, thread `stop`, and `executeCommand` with a stop or restart command.
- `mode:"read"` scripts that call obvious world changers (`setBlock`, `setInventorySlotContents`, `setDead`,
  `spawnEntityInWorld`, `executeCommand`, `stackSize =`, ...) are refused with `errorType:"needs_confirm"`: resend
  as `write` with a summary. A read script that changes the world some other way runs anyway (trusted players).
- Results are converted to JSON with caps (depth 8, 500 items per collection, 8000 characters per string,
  `evalMaxResultChars` overall); anything cut sets `truncated:true`. Items, fluids, tile entities, entities and
  worlds have compact shapes; other objects become `{"$class":..., "$str": toString()}`.
- Exceptions are caught and returned; they never reach the server.

Reply:

```json
{"type":"eval_result","id":"e1","mode":"read","side":"server","ok":true,"result":"Stone","output":"",
 "ms":0.42,"reqId":11}
{"type":"eval_result","id":"e1","mode":"read","side":"server","ok":false,"errorType":"exception",
 "error":"java.lang.NullPointerException","line":3,"stack":["DaveScript7.run(DaveScript7.groovy:3)", "..."],"reqId":11}
```

`errorType` is one of `compile`, `blocked`, `needs_confirm`, `timeout`, `exception`, and for `write`: `cancelled`,
`expired`, `too_many_pending`. Optional fields: `truncated`, `outputTruncated`, `warnings`, `confirmed`,
`confirmedBy`. Request errors (`bad_request`, `disabled`, `queue_full`, `cancelled`) come as `error` messages.

**World changes need the asking player's confirm (`mode:"write"`).** An accident guard against the agent's mistakes:
1. The script is compiled. The asking player sees `[Dave] wants to change the world: <summary>` (hover: the script)
   and `[Confirm] [Cancel] (expires in 2 min)`. The buttons run `/dave confirm <id>` and `/dave cancel <id>`.
2. The agent at once gets an event without `reqId`:
   `{"type":"eval_pending","id":"e1","player":"Steve","playerOnline":true,"confirmId":"3fa9c0d1e2","summary":"...","expiresInSeconds":120}`.
3. The request's reply is the `eval_result` after the click (`confirmed:true`, with the run's outcome), or
   `ok:false` with `cancelled` or `expired`. So the agent's request waits up to `confirmTimeoutSeconds`.
- Only the asking player's click counts; another player's click is refused. Each confirm runs at most once. A
  player may have 5 waiting. The server console (or RCON) may answer any confirm, which is how an asker who is not
  online (a `/dave ask` test name) is confirmed.
- If `backupCommand` is set, it runs right before the confirmed script.

#### `describe`

```json
{"type":"describe","target":"looking","player":"Steve","reqId":12}
{"type":"describe","target":"block","dim":0,"x":10,"y":64,"z":-4,"reqId":13}
```

`target`: `looking` (the block the player looks at, ray-traced on the server, `reach` default 64), `held`,
`player`, `block` (`x`,`y`,`z`, `dim` default the player's or 0), `entity` (`entityId`, `dim`). Reply:

```json
{"type":"description","target":"block","description":{"kind":"block","dim":0,"x":10,"y":64,"z":-4,
 "id":"gregtech:gt.blockmachines","meta":0,"blockClass":"...","name":"Electric Blast Furnace",
 "tile":{"class":"gregtech.api.metatileentity.BaseMetaTileEntity","gregtech":{"metaTileId":1000,"owner":"Steve",
 "mteClass":"...MTEElectricBlastFurnace","metaName":"multimachine.blastfurnace","localName":"Electric Blast Furnace",
 "description":["..."],"recipeMap":"gt.recipe.blastfurnace"},"inventory":{"size":2,"slots":[]}}},"reqId":13}
```

GregTech machines add `gregtech` (MetaTileEntity id, class, names, tooltip description lines, recipe map, owner);
a held GT machine item names its machine. Item tooltips are client-side in 1.7.10 and do not exist on a dedicated
server: use `client_eval` for a player's real tooltip. An unloaded position answers `"loaded":false` (never loads
the chunk). Errors: `not_found` (player offline, dimension not loaded, no such entity), `bad_request`.

#### `client_eval`

```json
{"type":"client_eval","player":"Steve","id":"c1","script":"mc.thePlayer.getHeldItem()?.getTooltip(mc.thePlayer, false)",
 "params":{},"timeoutMs":500,"reqId":14}
```

Runs a script on one player's own client. **Only for a player who opted in** (`clientEvalAllowed`, client config or
`/davebridge optin`), because the code runs on their machine. The server checks the player's current opt-in at send
time (the latest `client_hello` / `client_settings`) and refuses otherwise (`not_opted_in`); a client half without
the `eval` capability gets `unsupported`. The client re-checks its own setting before running it. It runs on the
client thread with the same time limit and caps (`timeoutMs` at most 2000 there), with `mc` (Minecraft), `player`
(`mc.thePlayer`), `world` (`mc.theWorld`), `params`, `out` and `dave` (the common helpers plus
`dave.tooltip(stack)`). No confirm step: it changes nothing on the server.

Reply (the client's result relayed):

```json
{"type":"client_eval_result","id":"c1","player":"Steve","side":"client","ok":true,"result":["Iron Pickaxe","..."],
 "ms":0.8,"reqId":14}
```

If the client does not answer within `clientEvalTimeoutSeconds` (or logs out first) the result is `ok:false`
with `errorType:"timeout"` or `"disconnected"`.

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
| `client_hello` | C->S | `modVersion`, `protocol`, `capabilities` (string[], e.g. `render`, `ask`, `context`, `nei`, and `eval` from 0.2.0: can run `client_eval_request`), `clientEvalAllowed` (bool) |
| `ask` | C->S | `text` (string), `context` (object) |
| `client_settings` | C->S | `clientEvalAllowed` (bool): the player changed their opt-in mid-session |
| `client_eval_result` | C->S | `id`, `ok`, `result` (any JSON), `error`, `errorType`, `output`, `ms`, `truncated`: the outcome of a `client_eval_request` (section 1.8). Results the server did not ask for are dropped. |
| `server_hello` | S->C | `modVersion`, `protocol`, `botName`, `triggerPrefixes` (string[]), `maxAskLength` (int; 0 or missing from older servers) |
| `dave_message` | S->C | **Unused since rich chat.** `botName`, `text`, `replyTo`. Dave's replies now arrive as normal chat for everyone; clients still render it if received. |
| `thinking` | S->C | `botName`, `clear` (bool): show the indicator, or remove it because the answer arrived |
| `client_eval_request` | S->C | `id`, `script`, `mode` (`"groovy"`), `timeoutMs`, `params` (JSON object). Sent only to players whose client reported `clientEvalAllowed` and the `eval` capability; the client re-checks its own opt-in before running it (section 1.8). |
| `lesson` | S->C | A validated lesson (section 2.6): `id`, `title`, `loop`, `speed`, `dim`, `anchor` (x,y,z), `start` (x,y,z), `steps` |
| `lesson_stop` | S->C | `id` (null or empty: whatever is playing) |
| `lesson_status` | C->S | `id`, `state` (`finished`/`stopped`), `reason` (see `lesson_status` in 1.3) |

Server-side validation of client packets:

- `lesson_status`: only from players whose client half said hello; relayed as described in 1.3.
- `client_hello`: only the first one per login counts; version and capability strings are clipped to 64
  characters, at most 32 capabilities. Chat lines use client-command links (`/davebridge nei ...`) only for players
  whose client reported the `nei` capability; everyone else gets the plain-chat formats.
- `client_settings`: only accepted after `client_hello`; a value that did not change is dropped, a change is
  announced to the agent as a fresh `client_mod` event. Servers older than 0.1.2 log it as an unknown kind and
  ignore it (the opt-in then reaches them on the next login).
- `ask`: only accepted after `client_hello`; `text` must be 1..`maxAskLength` characters and must contain a question
  after its trigger prefix (a bare `dave` or `dave,` is refused); at most one per `askCooldownMillis` per player. Refused asks
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

### 2.6 Lessons on the client half

Client halves from 0.2.0 report the `lesson` capability in `client_hello`; the server sends lessons only to them.

The `lesson` packet carries the steps in normalized form, one object per step: `op` (the step name), `pos`
(x,y,z), `id` (item or block), `meta`, `facing`, `color` (0xRRGGBB int), `text` (label or line) and `ticks` (the
step's duration, computed by the server). The client still checks everything again (client-bound packets are decoded
defensively): unknown ops, positions that are not finite or more than 34 blocks from `anchor`, and steps past
64 or past a 3600-tick pass are dropped; a lesson with nothing left, or for another dimension, is answered with
`lesson_status` `rejected`.

The ghost Dave is a client-only object, never an entity in the world: nothing is synced and no other player can see
it. Labels, the HUD bar (`Title · Step 3/7 · [K] stop`) and the chat line with `[Pause]` / `[Stop]` buttons come from
the client's lang file, never from the server.

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
| chat | `triggerPrefixes` | `dave` `@dave` `!dave` | Case-insensitive prefixes that address Dave. A prefix ending in a letter must be followed by a space or punctuation (`Dave how…`, `dave, …`), never another letter or an apostrophe (`davey`, `dave's`). Plain chat also counts with a greeting first (`hey dave, …`) or the name last (`how do I make steel, dave?`); clickable `{send:}` text must still start with a prefix. |
| chat | `forwardAllChat` | `false` | Forward every chat message (`triggered:false` for the rest). |
| chat | `botName` | `Dave` | Name in `<Dave>`. |
| chat | `botNameColor` | `aqua` | Minecraft color name for the plain-chat name. |
| chat | `chatWidth` | `320` | Players' chat box width in pixels (vanilla default at 100%). Replies are cut into lines this wide. |
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
| eval | `evalEnabled` | `true` | Accept `eval` and `describe`. |
| eval | `evalTimeoutMillis` | `500` | Default time limit of a script (it holds the server tick while it runs). |
| eval | `evalMaxTimeoutMillis` | `5000` | Largest `timeoutMs` a request may ask for. |
| eval | `evalMaxResultChars` | `65536` | Approximate cap on a result's JSON size. |
| eval | `evalMaxOutputChars` | `16384` | Printed output kept per script. |
| eval | `confirmTimeoutSeconds` | `120` | Default wait for a Confirm click. |
| eval | `confirmMaxTimeoutSeconds` | `600` | Longest `confirmTimeoutSeconds` a request may ask for. |
| eval | `backupCommand` | (empty) | Server command run right before a confirmed write, e.g. `backup start` (ServerUtilities; it copies in the background, so the backup may finish after the change). |
| eval | `clientEvalRelay` | `true` | Relay `client_eval` to opted-in players at all. |
| eval | `clientEvalTimeoutSeconds` | `30` | How long to wait for a client's result. |

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
authenticated agents, queue depth and timing, how many online players have the client half, and how many changes
wait for a confirm.

**Confirms (any player, or the console).**

- `/dave confirm <id>` / `/dave cancel <id>`: what the `[Confirm]` and `[Cancel]` buttons of a world-changing
  script run (section 1.8). A player may answer only their own confirm; the console (or RCON) may answer any.

**Test hooks (ops and the console).** These exist so the whole Dave loop can be exercised from `rcon-cli` with nobody
online:

- `/dave ask <asName> [@x,y,z[,dim]] <question...>`: sends the agent a `chat` event exactly like a triggered chat
  line from `asName`: `triggered:true`, `prompt` = the question without a trigger prefix (if it has one),
  `source:"console"`, `hasClientMod:false`. `playerUuid` is the online player's, else the one Forge's username cache
  remembers for that name, else the offline-mode UUID derived from the name (stable). The position defaults to the
  online player's, else the overworld spawn (dim 0). Replies need no player online: a public reply is broadcast as
  usual, a whisper to an absent name is dropped with a warning in the `say` ack.
- `/dave pending`: lists the changes waiting for a confirm (`id`, asking player, seconds left, summary).

`DaveBridge/tools/eval_check.py` runs these against a test server (agent socket plus RCON: reads, timeouts, blocked
calls, describe, a confirmed and a cancelled write, an expiry, `/dave ask`, the starter queries; `--gt` adds the
GregTech checks). It places one glass block 40 above spawn and removes it again. `dave/daemon/e2e_bridge_check.py`
does the same through the real daemon and the `bridge` MCP server, with a fake Claude (no model calls).

Client half only:

- `/davebridge nei <recipe|uses> <modid:name[:meta]>` (section 2.5), the target of Dave's recipe and usage links.
- `/davebridge stop`, `/davebridge pause`: stop or pause/resume the lesson playing (section 2.6), the targets of the
  lesson's chat buttons. The **Stop Dave's demonstration** key (Controls, unbound by default) also stops it.
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
