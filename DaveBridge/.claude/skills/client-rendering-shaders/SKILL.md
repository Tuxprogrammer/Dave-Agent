---
name: client-rendering-shaders
description: Use when writing or debugging any 1.7.10 client rendering - item, block, entity and tile renderers, particles and effects, HUD overlays, box models - especially when something looks wrong only with a shader pack or Angelica, when water, clouds or the hand vanish, when the screen washes out, or when faces flicker.
---

# Client rendering under shaders and Angelica

GTNH players run Angelica, often with a shader pack. The fixed-function GL state your renderer leaves behind, and the state it draws with, decide whether a shader pipeline treats your geometry as an entity, a translucent effect, or garbage. Code that looks fine in a plain dev client can break the whole frame.

## GL state hygiene

- Every renderer saves the state it changes and restores it **from the saved values**, not to assumed defaults (cull was not necessarily on; blend was not necessarily off). A small guard helper that records and restores blend, depth mask, depth test, cull, alpha test, lighting, texture and color is worth writing once and using everywhere.
- Prefer `GL11.glPushAttrib`/`glPopAttrib` around self-contained effect draws where the state set is broad.
- Reset the color to opaque white after tinted draws.

## Translucent effects

- **Translucent effects never write depth:** `glDepthMask(false)` while drawing them. An effect quad that writes depth makes everything translucent drawn after it (water, clouds, stained glass) fail the depth test: a screen-aligned hole appears around the effect.
- Enable alpha test so fully transparent texels are discarded instead of drawn invisibly.
- **Additive blend scales by alpha:** `glBlendFunc(GL_SRC_ALPHA, GL_ONE)`, not `GL_ONE, GL_ONE`. Unscaled additive light blows out under HDR and bloom and washes the screen white.
- **Set vertex normals** on every quad (`tessellator.setNormal`). Shader packs light geometry by normal; missing normals produce black or blown-out faces.
- **Don't disable `GL_TEXTURE_2D`** to draw flat color. Shader pipelines pick their program from that state and may draw your quad with the wrong one. Bind a 1×1 white texture instead.

## Captured tessellators (Angelica)

Angelica can capture tessellator output and replay it later, sampling GL state at capture (around the first vertex), not at your later state changes. Set blend, depth mask, texture and color **before** `startDrawingQuads()`, and don't change them between vertices of one draw.

## Effects and the camera

- **Never spawn effects at the camera.** A first-person effect positioned at the player's eye renders inside the near plane and fills the screen, worse under shaders. Spawn first-person effects at the visible emitter (the held item's muzzle, nozzle or tip in first-person space) and third-person ones at the model's emitter.
- Cull particles within about half a block of the camera.
- Beams and trails drawn in first person start at the emitter, not at the eye.

## Box models

- **Z-fighting:** two boxes with coplanar faces flicker. Inset one by 0.001–0.002 block (e.g. a lid inside its body), or merge the faces. Add a unit test over the model's box data that fails on coplanar overlapping faces.
- Watch for models authored facing the opposite axis from your renderer's convention; check orientation before tuning dimensions.

## Attribute side effects

- Vanilla computes FOV from the movement-speed attribute. A movement-speed modifier used for anything else (a swim or sprint boost, a slowdown while charging) zooms the player's view. Use motion changes for movement effects, or correct the FOV in `FOVUpdateEvent`, and clamp it.
- Night-vision or other potion-like effects you toggle must not remove the same effect granted by a real potion.

## Testing visual bugs

- Reproduce shader bugs with the **same shader pack and settings** the reporter uses. A different pack and a casual look will miss them. Shader runs are expensive; reserve them for shader tests and keep normal client tests on plain rendering.
- Compare your screenshot side by side with the reporter's for the same situation, and look for the *specific* signature (a rectangle of missing water, a white wash, a light pillar), not general haze the pack adds by itself.
- Capture first person, third person, inventory, dropped item and GUI views for visual PRs.
