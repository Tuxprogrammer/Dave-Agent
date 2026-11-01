# Plan: guided demonstrations ("Show me")

Status: **first version built** (non-interactive mode), 2026-11-01. Wire format: `DaveBridge/PROTOCOL.md` (`lesson`, `lesson_stop`, `lesson_status`, section 2.6). Interactive mode is still later. Added 2026-10-31.

## The idea

Some answers are hard to give in chat: "where does the muffler hatch go", "which side does the input bus face", "how do I route this pipe". For those, Dave can **show** the player instead of telling them.

A ghost Dave appears in the player's own world, **visible only to them**. He walks the route slowly, looks at and points to the right blocks, and shows ghost blocks where things go. Floating labels give the step text ("Input bus here, facing the chest"). Then the demonstration loops, like a game tutorial, until the player stops it.

Only the player sees it, and nothing in the real world changes.

## How it flows

1. **The player asks**, or Dave offers: "{send:dave, show me|Show me}".
2. **Dave inspects the world on the server** through DaveBridge eval: blocks, tile entities, the multiblock's structure definition and its facing.
3. **Dave writes a lesson.** It's a short, declarative step list, not code.
4. **DaveBridge validates it on the server.** Coordinates must be near the player and in loaded chunks. Block and item IDs must exist, the number of steps and the duration are capped, and unknown steps are dropped. It then sends the lesson to that player's client half (chunked packets).
5. **The client half plays it,** looping until the player stops it with a chat button, a keybind, `/davebridge stop` (the client command; there is no client `/dave`), or by walking far away. A new lesson replaces the old one.

Lessons are data that the client renders; they never run code. So unlike client eval, lessons **don't need `clientEvalAllowed`**. They do need DaveBridge's client half. Players without it get the chat answer plus static hints, if StructureLib can show them (see below).

## Lesson steps (first draft)

```json
{"id": "...", "loop": true, "speed": 0.6, "steps": [
  {"walkTo": [x, y, z]},
  {"lookAt": [x, y, z]},
  {"hold": "gregtech:gt.metatool.01:22"},
  {"highlight": {"pos": [x, y, z], "color": "gold", "label": "Controller goes here"}},
  {"ghost": {"pos": [x, y, z], "block": "gregtech:gt.blockmachines", "meta": 1000, "facing": "north"}},
  {"swing": true},
  {"say": "Right-click with a screwdriver to set the output side"},
  {"wait": 40}
]}
```

## Build on what the pack already has (native first)

- **StructureLib** (`StructureLibAPI.hintParticle*`) is the hologram hint system GTNH players already know from building multiblocks. Use it for ghost blocks and per-block tint, including the red error tint for wrong blocks.
  - On top of that, Dave can trigger a multiblock's own structure definition, so "show me the EBF layout" draws GT's real structure.
  - Check whether StructureLib hints can be sent server-side to players who don't have DaveBridge's client half.
- **BlockRenderer6343** renders multiblock previews in NEI. Look at it for showing a structure off to the side.
- **Waila / WAWLA** already label what the player is looking at. Don't duplicate their labels.
- Check Navigator and VisualProspecting for path, overlay and waypoint rendering before writing our own. JourneyMap 1.7.10 has no chat waypoint format (checked: `ChatEventHandler` only handles control codes).

## What we build ourselves (the gaps)

- **The ghost Dave avatar** is **Dictator Dave**: black hair, sunglasses, moustache and beard, grey shirt with a black belt.
  - **Skin:** GregGuns' own MIT skin, copied to `DaveBridge/src/main/resources/assets/davebridge/textures/entity/dave.png`, with provenance in DaveBridge's `THIRD-PARTY-NOTICES.md`. It's a 64x64 old-layout biped skin (top half used), so it renders on a plain `ModelBiped` with a 64-pixel texture height.
  - **Rendering:** client-only, translucent, with a walking animation, head and arm pointing, and holding the step's item.
  - **Golden Revolver (optional).** If GregGuns is installed, Dave idles with his Golden Revolver. This must be a soft dependency: DaveBridge never requires GregGuns.
  - It is never a real server entity, so there's nothing to sync and nothing else can see it.
- **Path playback.** The server sends waypoints, computed with vanilla's pathfinder through eval, and the client interpolates them so the ghost follows the ground smoothly.
- **Floating step labels** and a small "Step 3/7 · [Stop]" bar on the HUD.
- **Loop, pause and stop controls.**

## Later: interactive mode

The lesson advances only when the player actually completes a step. The server sees the block placed, the item crafted or the GUI opened, and tells the client to move on, turning a highlight green on success. This is where it becomes a real tutorial rather than a replay.

## Risks

- **Rendering on GTNH clients** goes through Angelica and often a shader pack. Follow DaveBridge's `client-rendering-shaders` skill, and test with and without shaders. This is the part most likely to look wrong.
- **Hard to test.** Lessons need a real client to check visually. Packets and validation can be tested headlessly; the visuals can't.
- **Lesson quality depends on Dave's world inspection,** which needs M2 eval plus a few reusable inspection queries (multiblock structure, facing, nearby inventories).

## What was built (first version)

Code: `DaveBridge/src/main/java/.../server/lesson/` (validation, requests), `common/protocol/Lesson*.java` and
`common/lesson/LessonLimits.java` (packets, caps, timings), `client/lesson/` (playback, ghost Dave, rendering, HUD,
controls). Daemon: `Bridge.lesson()` / `Bridge.lesson_stop()` in `dave/daemon/main.py`; the MCP tool shape is in
`dave/TOOLS.md` (the `bridge` MCP server is being built on the M2 branch).

Decisions made while building, checked against the source the pack ships:

- **StructureLib hints are not used for lesson ghost blocks.** At the shipped tag (1.4.47), `StructureLibAPI.hintParticle*`
  works only on the client (`CommonProxy` is a no-op on the server, so a server can't send hints to players without
  DaveBridge's client half; only `markHintParticleError` / `updateHintParticleTint` reach a client, and only for hints
  that already exist there). Hints can't be removed on demand: they expire after the `hintLifespan` config (400 ticks).
  And with the default `maxCoexisting = 1` a lesson's hint group would erase the hologram the player is building
  from. So ghost blocks are drawn by DaveBridge itself, with the block's own inventory renderer (GT machines render
  from their meta tile entity id, so `"meta":1000` works). "Show me the EBF layout" through GT's real structure
  definition is still a good later step, as a separate request that triggers StructureLib's own hologram.
- **Navigator, VisualProspecting and BlockRenderer6343** draw map layers (JourneyMap, Xaero, VoxelMap) and NEI GUI
  previews; none renders in the world, so there was nothing to reuse for the ghost or labels.
- **Ghost Dave** is a client-side `EntityLiving` object that is never spawned: it exists only so vanilla's biped
  renderer can animate it (walk cycle, head turn, swing) and draw its held item, including other mods' held-item
  renderers. Skin: GregGuns' MIT Dictator Dave skin, already in the repo; provenance re-verified (byte-identical to
  GregGuns commit a1d6097b, MIT, same copyright holder), see `DaveBridge/THIRD-PARTY-NOTICES.md`.
- **Golden Revolver** is a soft dependency: the client looks up `gregguns:golden_revolver` by name when GregGuns is
  loaded and uses it as Dave's idle item until the lesson's first `hold`.
- **Walking** is straight-line interpolation between the agent's waypoints; no ground snapping yet. Dave should send
  waypoints from vanilla's pathfinder (via eval) for routes that aren't straight.
- **Highlights and ghost blocks accumulate** through a pass and clear when it loops.
- **Limits:** 64 steps, 180 s per pass, positions within 256 blocks of the player (32 for clients before 0.2.4) and in
  loaded chunks, auto-stop at 320 blocks or after 10 minutes, a 2 s pause between passes.

## Testing

- Unit tests (`./gradlew test`): `LessonParserTest` (validation, dropping, caps, timings, colors, text cleaning),
  `LessonServiceTest` (capability gate, status relay), `LessonPlaybackTest` (timeline, interpolation, loop, pause,
  timeout, client-side sanitizing), `LessonPacketRoundTripTest` (encode, chunk, reassemble, decode; direction),
  `LessonLimitsTest`. `SideSafetyTest` covers the new server and common classes.
- Headless (`tools/e2e_lesson_test.py` against `./gradlew runServer`, scripted clients): a player without the client
  half and an old client half get `no_client_mod`; a lesson-capable client gets the validated lesson and nobody else
  does; `lesson_stop` is delivered; `lesson_status` is relayed.
- **Visuals can't be checked headlessly.** They need a real client: run the checklist below with
  `./gradlew runClient` (plain rendering) and once in the real pack with Angelica and a shader pack.

### Manual test checklist (real client)

Send lessons from the agent socket (e.g. `DaveBridge/tools/dave_client.py`, or the daemon) to the player.

1. **Arrival.** The chat line "[Dave] Dave is showing you: <title>. Only you can see it. [Pause] [Stop]" appears and
   the HUD bar "<title> · Step 1/N · /davebridge stop" shows at the top center (lower when a boss bar is up).
2. **Ghost Dave.** Translucent, correct skin (black hair, sunglasses, beard, grey shirt, black belt), not stretched
   (a 64-high texture), walking animation while moving, standing still otherwise, slightly lit at night. A second
   player standing next to you sees nothing.
3. **Walking.** Moves smoothly between waypoints at about 60% walking speed; faces the way he walks; teleports back
   to the start (no slide) when the lesson loops.
4. **Look and point.** On `lookAt`, `highlight` and `ghost` he turns to the target, head pitched toward it, right arm
   pointing at it; the arm drops when he walks again.
5. **Hold.** Holds the `hold` item (try a GT tool, a block, `""` for empty hands). With GregGuns installed and no
   `hold` yet, he holds the Golden Revolver; without GregGuns, empty hands and no errors in the log.
6. **Swing.** The arm swings once on `swing`.
7. **Ghost blocks.** A vanilla block (chest, furnace with `facing`) and a GT machine (`gregtech:gt.blockmachines`,
   meta = the machine's id) appear translucent, fade in, face the given direction, don't z-fight with neighbors, and
   don't hide water, clouds or stained glass behind them.
8. **Highlights.** A pulsing colored box with an outline that shows faintly through walls; the label floats above
   and faces the camera; colors match (`gold`, `red`, `#12abef`).
9. **Labels.** `say` text over Dave's head, wrapped, readable at day and night, through blocks.
10. **Controls.** `[Pause]` / `/davebridge pause` freezes and resumes (HUD says Paused); `[Stop]`,
    `/davebridge stop` and the "Stop Dave's demonstration" key (bind it in Controls; unbound by default) stop it and
    print a gray line; the agent gets `lesson_status` `stopped`/`player`.
11. **Auto-stop.** Walking more than 320 blocks away, changing dimension, or relogging stops it (`walked_away` /
    `dimension`); a non-looping lesson clears itself 5 s after the end (`finished`).
12. **Replace.** Sending a second lesson replaces the first (`replaced` for the old id).
13. **Shaders.** Repeat 2, 7, 8 and 9 with Angelica and the shader pack players use: no white wash, no black faces,
    no holes in water or clouds around the ghost or boxes, the hand and HUD still render. Ghost blocks use a constant
    blend alpha (`GL_CONSTANT_ALPHA`); if a shader pack ignores it they show opaque, so note which pack.
14. **Log.** No repeated "Lesson render failed" or "Ghost Dave render failed" warnings.
