# <Thing name>

<!-- One sheet per documented thing: item, block family, machine, tile entity, entity, projectile, structure, packet, keybind.
     Describe behavior in your own words. No pasted or closely paraphrased source. Write "none" for fields that do not apply. -->

| # | Field | Contents |
|---|---|---|
| 1 | **Identity** | Classes; registry name; unlocalized name; metadata; English name and lang key; creative tab; ore-dict names |
| 2 | **Obtaining** | Crafting grid, machine recipe, loot, drop, worldgen, or *unobtainable* with the reason |
| 3 | **Numbers** | Every stat, constant and default, with units (ticks, blocks, EU, half-hearts), and each config key that changes one |
| 4 | **Behavior** | Ordered logic, each step labeled client / server / both: ticking, use, sneak-use, left-click, automation (sided slots), redstone, edge cases |
| 5 | **Persistence and sync** | NBT keys with type and meaning; packets; DataWatcher indices; GUI progress fields |
| 6 | **UI** | GUI layout with pixel coordinates for slots, bars, tanks, buttons; exact tooltip lines and when each appears; chat messages |
| 7 | **Visuals** | Renderer and model, transforms, textures (paths, sizes, frames), animations, particles and effects |
| 8 | **Audio** | Sound events, exact trigger, volume and pitch passed; any description of how it sounds is marked *inferred* unless heard |
| 9 | **Relationships** | What uses it and what it uses, linked across areas |
| 10 | **Bugs** | Inline bug IDs (`AREA-12`) for everything suspicious |

## Behavior detail

1. (server) ...
2. (client) ...

## Deviations in the new mod

Link the new-spec area and any decision record. "None" if none.
