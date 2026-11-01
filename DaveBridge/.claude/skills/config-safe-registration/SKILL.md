---
name: config-safe-registration
description: Use when adding module or feature toggles, registering items, blocks, entities, tile entities or GT MetaTileEntities, renaming or retiring content, or changing NBT formats. Keeps worlds loadable and clients joinable whatever the config says, across upgrades.
---

# Config-safe registration

In 1.7.10, the registry is the contract between a server, its clients and every saved world. If config can change what is registered, a client and server with different configs fail to join, and a flipped flag deletes items from saves.

## Rule 1: register always, gate behavior

- **Every** item, block, entity, tile entity, MTE and sound is registered regardless of config. Config never changes *what exists*.
- Config changes only *behavior*: recipes, spawning, worldgen, ticking, use actions, NEI and creative-tab visibility.
- A disabled feature's content: does nothing when used, has no recipes, is hidden from NEI and the creative tab, and shows a tooltip line saying it is disabled.
- Ask one runtime authority, `ModuleState.isActive(id)`, for behavior. Never read raw config flags at use sites.

Lifecycle split that makes this work:

| Phase | Runs for | Does |
|---|---|---|
| `preInit` | all modules | config, items, blocks, entities, network channels |
| content init (GT machines, renderers, GUI handlers) | all modules | registration that must exist on both sides |
| `init` / `postInit` | active modules only | recipes, event handlers, spawning, worldgen, cross-mod hooks |

## Rule 2: the server is authoritative

- On login, the server sends its effective module mask; the client applies it until disconnect, then falls back to local config.
- Warn the player on login if the client's local config differs from the server's, but do not kick.
- Unit-test the mask round-trip and the dependency rules ("module B requires A").

## Rule 3: IDs are forever

- Registry names, entity IDs, MetaTileEntity IDs, metadata values and NBT keys are **never renamed or reused** once a release ships. Keep them as constants.
- **Retired content keeps an inert placeholder.** An item stack whose metadata no longer maps to anything can crash the item renderer or tooltip code on the first frame it is in a hotbar. Register a placeholder at every retired ID (both sides) that renders as a generic "removed" icon and does nothing. Record retired ranges as reserved forever.
- Register placeholders at every *free* ID in your reserved MTE block too, if a client with a different module set could otherwise see an unknown ID.
- Note every retirement in the release notes with what players should do.

## Rule 4: NBT tolerates the past

- Readers handle missing keys with sensible defaults; old saves must load.
- Write a round-trip unit test per NBT format and one per historic format you still read.
- Never store per-player or per-entity state in static maps; use NBT or extended entity properties.

## Rule 5: resources load at the right time

- Register icons and textures during the registration or texture-stitch phase. Anything built lazily inside a render or `getTexture` call after the atlas is stitched stays null and throws later.
- Lang keys exist for every registered thing, including placeholders and disabled content.

## Checks to automate

- A dev self-check (postInit) that every registered item has a lang key, a texture, and a creative-tab entry or an explicit hidden flag.
- A test that flips each module flag and asserts the registered set is identical.
- A headless server boot with every module off and with every module on.
- A two-client join test where the clients' configs differ from the server's.

## Pitfalls

- `if (config.featureEnabled) registerItem(...)`. This is the bug this skill exists to prevent.
- Renumbering MTE IDs to "tidy up" a range.
- Removing a placeholder because "nobody has that item any more". Somebody's chest does.
