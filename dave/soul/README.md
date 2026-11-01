# Dave's soul: how the system prompt is built

`SOUL.md` is the core of Dave's system prompt: who he is, how he talks in chat, how he works a question, his
memory policy and his boundaries. Edit it freely; it's meant to be owned by the server owner.

## Assembly

`dave/launch/dave_cmd.py` builds the prompt on every launch (`assemble_prompt()`):

1. Read `SOUL.md` (path: `[prompt] soul` in `dave/config.toml`, env `DAVE_SOUL`).
2. Replace each `<!-- include: NAME -->` with the named text. Today there is one:
   - `DaveBridge markup spec`: the whole of `DaveBridge/docs/dave-markup.md`, the bridge's paste-ready spec
     (`[prompt] markup_spec`, env `DAVE_MARKUP_SPEC`), minus its `# ` title. If the file ever carries
     `<!-- dave-prompt:begin -->` / `<!-- dave-prompt:end -->` markers, only the text between them is used. If
     the file is missing, a short plain-text fallback is inserted ("reply in plain text, offer follow-ups as a
     question") and `--print` shows a note.
3. Strip every other HTML comment (editor notes like the one at the top of SOUL.md never reach Dave).
4. Write the result to `<run>/system-prompt.md` (`dave/.run/` in dev) and pass it with `--system-prompt-file`.

Check the assembled prompt any time with:

```sh
python3 -I dave/launch/dave_cmd.py --print     # writes dave/.run/system-prompt.md and shows notes
```

**Replace, not append.** SOUL replaces Claude Code's default system prompt rather than being appended to it.
The default prompt is a coding-agent prompt (markdown formatting, git and file-editing workflows, a software
engineering persona) that fights a short in-chat voice. The few useful bits it carried, such as tool-use
habits, are restated in SOUL's "Using your tools". Tool definitions and MCP server instructions are not part of the
system prompt and still reach Dave. The reasoning is in `docs/plans/dave-core.md`.

## The recipe-planner prompt

`recipe-planner.md` in this folder is the system prompt of Dave's one subagent (`[prompt] planner`, model
`[model] planner`, default Opus). `dave_cmd.py` strips its comments and puts it in the rendered `agents.json`
(`--agents`). It is focused on chain planning and returns a compact checked result, never chat markup. The same
"next session" rule applies to edits.

## What goes where

| Content | Where | Why |
|---|---|---|
| Identity, voice, procedure, memory policy, boundaries | `SOUL.md` | Stable; same for every player |
| Tool specifics (names, arguments, what is live) | MCP tool descriptions and `dave/TOOLS.md` | Change with the tools; SOUL names capabilities generically so it never tells Dave to call a tool that does not exist |
| Chat markup grammar | `DaveBridge/PROTOCOL.md`, included | Owned by the bridge, still changing |
| Who is asking, their profile, relevant server facts and lessons | The per-turn envelope (`dave/ENVELOPE.md`) | Changes every turn |

## When edits take effect

The CLI records the system prompt **once per conversation** (`--system-prompt-snapshot on`, the default, which
`dave_cmd.py` also passes explicitly). It is rendered on the conversation's first request and replayed verbatim on
every later request and on resume, even if a later launch passes different text, until the conversation is
compacted.

So:

- **A SOUL edit takes effect at the next session**: when the daemon rotates sessions (every N turns or hours,
  `[session]` in `config.toml`) or restarts Dave. Not mid-conversation. A resumed session keeps its old prompt.
- To try an edit right away, start a new session (restart the daemon).
- Per-turn facts (the player's profile, memories) must never go in SOUL. They go in the envelope, which is fresh
  on every turn.
- Persistent memory is what carries knowledge across rotations, so nothing is lost when a session ends.

## Editing tips

- Keep SOUL's own text near 1,500 words (it is about 1,650 now, plus about 450 for the included markup spec); it
  is sent with every request, and chat latency matters. `--print` writes the file;
  `wc -w dave/.run/system-prompt.md` counts it.
- Name capabilities, not tools ("check memory", "use the chain planner"). If you add a section that depends on a
  new tool, make sure the tool exists first, or phrase it as "if available".
- Examples teach tone better than adjectives. The good/bad pairs in "Voice in chat" are the strongest lever on
  how Dave sounds.
