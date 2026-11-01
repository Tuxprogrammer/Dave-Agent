# Plan: guided demonstrations ("Show me")

Status: idea, planned after M2 (live eval). Added 2026-10-31.

## The idea

Some answers are hard to give in chat: "where does the muffler hatch go", "which side does the input bus face", "how do I route this pipe". For those, Dave can **show** the player instead of telling them.

A ghost Dave appears in the player's own world, **visible only to them**. He walks the route slowly, looks at and points to the right blocks, and shows ghost blocks where things go. Floating labels give the step text ("Input bus here, facing the chest"). Then the demonstration loops, like a game tutorial, until the player stops it.

Only the player sees it, and nothing in the real world changes.

## How it flows

1. **The player asks**, or Dave offers: "{send:dave, show me|Show me}".
2. **Dave inspects the world on the server** through DaveBridge eval: blocks, tile entities, the multiblock's structure definition and its facing.
3. **Dave writes a lesson.** It's a short, declarative step list, not code.
4. **DaveBridge validates it on the server.** Coordinates must be near the player and in loaded chunks. Block and item IDs must exist, the number of steps and the duration are capped, and unknown steps are dropped. It then sends the lesson to that player's client half (chunked packets).
5. **The client half plays it,** looping until the player stops it with a chat button, a keybind, `/dave stop`, or by walking far away. A new lesson replaces the old one.

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
