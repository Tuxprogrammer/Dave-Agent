# The turn envelope: what the daemon sends Dave, and what comes back

This is the **Claude-facing** contract between the Dave daemon (`dave/daemon/main.py`) and Dave's long-lived
`claude -p --input-format stream-json --output-format stream-json` process. The game-facing WebSocket messages
(`chat` events, `say` requests) are defined in `DaveBridge/PROTOCOL.md`; this file refers to them but does not
depend on their details.

SOUL.md teaches Dave this format (section "Each turn"). Change the two together.

## 1. One turn in

Each player question is one stream-json user message on Dave's stdin, one JSON object per line:

```json
{"type":"user","message":{"role":"user","content":"<turn id=\"t-000123\" ts=\"2026-10-31T18:04:05Z\" pack=\"2.9.0\">\n<player ...>...</turn>"}}
```

The `content` string is the envelope:

```xml
<turn id="t-000123" ts="2026-10-31T18:04:05Z" pack="2.9.0" kind="question">
<player name="Alex" uuid="069a79f4-44e9-4726-a5be-fca90e38aaf5" tier="HV" dim="0" pos="120,64,-340" hasClientMod="true" clientEval="false" source="client"/>
<profile>
Player: Alex (uuid 069a79f4-...)
Tier: HV (since 2026-10-12)
Setup: has a cleanroom (since 2026-10-20)

Server facts:
- Server rules: Be nice. No lag machines.
Lessons:
- Saltpeter nitrogen is a trap: Always compare against the air centrifuge.
Maybe related playbook: Best nitrogen source at HV (playbook/best-nitrogen-source-at-hv)
</profile>
<context looking_at="gregtech:gt.blockmachines:1000" holding="gregtech:gt.metaitem.01:32600" gui="none"/>
<warnings reply="t-000122">unknown item gregtech:gt.metaitem.01:32601 (shown as plain text)</warnings>
<message>dave, what's the best source of nitrogen? I have plenty of oxygen</message>
</turn>
```

| Element / attribute | Required | Source | Notes |
|---|---|---|---|
| `turn@id` | yes | daemon | Unique per turn; echoed in logs. |
| `turn@ts` | yes | daemon | UTC ISO-8601. Dave's only clock: the system prompt has no date. |
| `turn@pack` | yes | `config.toml [pack] version` | Lets Dave notice stale playbook entries. |
| `turn@kind` | no | daemon | `question` (default). `retry`: see "Crash or restart" in section 4. Reserved: `button` (a follow-up button the player clicked), `event` (join/leave, for greetings later). |
| `player@name`, `player@uuid` | yes | bridge `chat` event | The UUID is the memory key. |
| `player@tier` | no | profile | Omitted when unknown. Memory is the source, not the client. |
| `player@dim`, `player@pos` | no | bridge | Dimension id and block position, when the server sends them. |
| `player@hasClientMod` | yes | bridge `client_mod` event | `true` when the client half is installed. |
| `player@clientEval` | no | bridge `client_mod` event | `true` only if the player opted in (`clientEvalAllowed`). Absent means no. |
| `player@source` | yes | bridge | `chat` (typed in plain chat) or `client` (the client mod's Ask Dave). |
| `<profile>` | yes | `load_turn_context(uuid, message)` in `dave/memory/store.py` | Profile, pinned and relevant server facts, relevant lessons, pointers to related playbook entries. Capped at about 1,500 characters. "no profile yet" for a new player. |
| `<context>` | no | client mod (`source="client"` only) | What the player looks at, holds and has open. **Client-reported and untrusted** (per PROTOCOL.md). |
| `<message>` | yes | player | The text after the trigger (`dave`, `@dave`, `!dave`), or the button's text for `kind="button"`. |
| `<warnings>` | no | the `say` ack for Dave's previous reply | Present only when that ack listed `warnings` (an item, quest or player link that did not resolve and showed as plain text, a blocked URL, a degraded line). One per line, with `reply="<turn id>"` naming the turn it came from. It goes on Dave's next turn whoever asks, so he fixes the id next time. |
| `<recent>` | no | daemon | Optional: the last few public chat lines, one per line as `Name: text`, for "what he said" follow-ups. Only when it helps; it costs tokens. Only public exchanges go in: a question typed in chat that Dave answered with `@reply`. Whispers and client-half Asks (which other players never see) are left out. |

**Escaping.** Everything a player or client supplies (names, message, context values, recent lines) is
XML-escaped (`&` `<` `>` `"`) by the daemon, so no player text can close a tag or forge a `<profile>`. SOUL tells
Dave that tag contents are information, not instructions.

**Why the profile is per turn and not in the system prompt.** The system prompt is recorded once per conversation
(see `dave/soul/README.md`), and many players share one conversation. Profiles change, and each turn has a
different asker, so they ride in the envelope.

## 2. The reply out

The CLI streams events on stdout. The daemon waits for the turn's `{"type":"result", ...}` event; its `result`
field is Dave's final assistant text for the turn. Intermediate assistant text (between tool calls) is never
posted. When Dave delegates to the `recipe-planner` subagent, its events appear in the stream with
`parent_tool_use_id` set; the daemon ignores them (only the top-level `result` is posted). A delegated turn takes
longer, so keep the `thinking` indicator up until the result arrives.

The final text is:

```
@reply
{Dave markup: the answer, links, buttons}
```

**Line 1 is the directive**, exactly one of:

| Directive | `say` request | Renders as | Use |
|---|---|---|---|
| `@reply` | `target: "@a"` | `<Dave> ...` for everyone; Dave addresses the asker by name in the text | **The default** (owner's rule): replies are public, so others can follow and chime in |
| `@whisper` | `target: "<asker name>"` | vanilla "Dave whispers to you: ..." for the asker only | Only when the player explicitly asked for a private reply |
| `@none` | no `say` | nothing | The message was plainly not for Dave (players talking about him). When in doubt Dave replies, so a real question never goes unanswered |

There is no separate broadcast directive: `@reply` already reaches the whole server.

If line 1 is not a directive, the daemon treats the whole text as the message and uses
`[session] default_target` from `config.toml` (`reply`, i.e. `@a`). It logs the miss so prompt drift shows up.

**Everything after line 1 is Dave markup**, which the daemon passes unchanged to DaveBridge's `say` request in its
`markup` field (`say` takes exactly one of `markup`, `text` or `components`; the daemon always uses `markup`), with
`replyTo` set to the chat event's id. The bridge turns it into Minecraft chat components per recipient: colours,
item links (hover tooltip, NEI), quest links (open the Quest Book), URLs, waypoints and follow-up buttons such as
`{send:dave, show the full chain|Full chain}`. The paste-ready grammar is `DaveBridge/docs/dave-markup.md`, which
`dave_cmd.py` includes whole into Dave's system prompt (full grammar: PROTOCOL.md section 1.5); this file does not
repeat it. If that file is missing, the prompt falls back to plain text, which is valid markup.

**Warnings.** The `say` ack returns `warnings` for anything it could not resolve (unknown item, quest or player;
blocked link; a degraded oversized line). The daemon logs them and puts them in a `<warnings>` element on Dave's
next turn (section 1), so Dave corrects the id next time.

The bridge also caps lines (`maxLinesPerMessage`) and sanitises output, so a runaway reply is truncated
rather than flooding chat.

## 3. Long answers and follow-ups

- Dave keeps chat to about three lines and offers depth with a follow-up button rather than a wall of text.
- A clicked button arrives as a new turn with `kind="button"`, the same player, and the button's text as
  `<message>`. Because the conversation is the same session, Dave still has the previous answer, its tool results
  and the player's locks and constraints in context, so "Full chain" can be answered without redoing the work.
- Dave may add a confirm button to anything that changes the world. The in-game confirm is enforced by the bridge
  and daemon, not by Dave's good behaviour.

## 4. Sessions, rotation and concurrency

- **One session, many players.** The daemon keeps one long-lived process and sends turns one at a time. While a
  turn is in flight, other questions queue; the daemon sends the bridge's `thinking` indicator for the asker and
  applies per-player cooldowns (keyed by UUID, or by name when the bridge sends none). A queued question is
  dropped, with a notice to the player, only if it waited longer than `stale_seconds` while Dave was free, i.e.
  for the bridge to come back. Time spent behind Dave's earlier turns does not count.
- **Rotation.** The daemon starts a fresh session every `rotate_turns` turns or `rotate_hours` hours
  (`[session]` in `config.toml`), and on restart. A new session picks up SOUL.md edits. Context from the old
  session is not carried over; persistent memory bridges the gap (profiles, playbook, lessons).
- **Follow-ups across a rotation** lose the earlier tool results. Dave re-derives them; a saved playbook entry
  makes that one recall. The daemon may include a short `<recent>` block on the first turn after a rotation.
- **Crash or restart.** Sessions persist in `CLAUDE_CONFIG_DIR`, so the daemon can `--resume` one. A resumed
  session keeps its original system prompt, and its turn count and age, so rotation stays on schedule. A crash
  during a turn resumes once and retries the turn; a crash between turns resumes at the next turn; a resumed
  process that dies again starts a fresh session. Before retrying, the daemon looks for the turn id in the
  session's transcript (`CLAUDE_CONFIG_DIR/projects/*/<session>.jsonl`). If the question is already there, it
  does not send it twice. Instead it sends a short `kind="retry"` envelope: the same turn id, a `<player>`
  element and a `<note>` asking Dave to answer the interrupted question. There is no `<message>`.

**Background agents.** Dave normally runs `recipe-planner` in the foreground (`run_in_background: false`), and
the turn ends with one `result`. If he backgrounds it, the stream reports `system/task_started` with
`is_backgrounded: true`; the turn's first `result` is posted, and a second `result` follows when the agent finishes.
The daemon holds the queue until that follow-up arrives, so it always goes to the player who asked.

Every top-level `result` goes through one queue. While a turn (and its follow-ups) is running, results queue for
it, so a follow-up that arrives before the daemon starts waiting is not lost. A result that arrives between turns
goes straight to the player of the last turn. The daemon cannot attribute one case: an unannounced second result
(no `task_started` with `is_backgrounded`) that arrives during a *later* turn. The stream carries nothing that ties
a result to the input that caused it, so that turn takes it as its own answer. Announced background agents never
hit this case, because the queue is held for them.

## 5. Daemon side

Implemented in `dave/daemon/main.py` (tests: `dave/daemon/test_daemon.py`). The original sketch:

```python
from dave.launch import dave_cmd
from dave.memory.store import open_store, load_turn_context

b = dave_cmd.build()                       # argv, env, cwd; refuses nothing, so check b["problems"] first
proc = subprocess.Popen(b["argv"], cwd=b["cwd"], env=b["env"], stdin=PIPE, stdout=PIPE, text=True)
store = open_store(actor="daemon")
store.ensure_player(uuid, name)            # first sight / rename
profile = load_turn_context(uuid, message, player_name=name)
proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": envelope}}) + "\n")
# read stdout lines until {"type": "result"}; split line 1 (directive) from the markup; send `say`
```
