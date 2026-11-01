---
name: networking-side-safety
description: Use when writing packets, packet handlers, synced state, GUIs with buttons, keybind actions, tooltips, or any code that might load on a dedicated server - and whenever a crash says ClassNotFound, NoClassDefFoundError or NoSuchMethodError for a client class on a server, or a client asks the server to do something.
---

# Networking and side safety

Two rules: a dedicated server never loads a client class, and the server never trusts the client.

## Side split

- All client-only code (renderers, models, HUD, effects, sounds, keybinds, GUIs' screens) lives in one `client` package. Common code never references it, not even through an import in a code path the server loads.
- Reach the client through the proxy or `@SideOnly(Side.CLIENT)` methods. `@SideOnly` strips the member; any common code that calls it still fails on the server.
- Code that runs on both sides can still touch client APIs by accident. Tooltip and description builders are the classic case: calling `Keyboard.isKeyDown` (LWJGL) or `Minecraft.getMinecraft()` from shared tooltip code crashes a server that builds the same tooltip (e.g. for a command, a scenario or a GT multiblock description).
- Prove it: boot `runServer` for every feature, and add a static test that no class outside `client` references `net.minecraft.client`, `org.lwjgl` or your client package.
- Client and server effects are separate: the server says *what happened*, the client decides *how it looks and sounds*.

## Server authority

- The server decides hits, damage, item or charge consumption, inventory changes, block changes and progression.
- The client may *predict* for responsiveness (animations, sounds, use effects) but never mutates authoritative state. When the server disagrees, the server wins and the client corrects.
- Gameplay gates (module enabled, tier allowed, permission) are evaluated on the server with the server's config, and the effective values are synced to clients at login (see `config-safe-registration`).

## Validate every client packet

For every client-to-server message, check before acting:
1. The player is alive, in the same dimension as the target, and within reach (use the server's reach, not a client-sent distance).
2. The target block, tile entity or entity exists **and is the expected type** before casting.
3. The player has permission: op level where needed, protection or claim mods respected, GUI actually open for GUI actions.
4. Every index, enum ordinal, slot number and array length is within bounds.
5. Strings have a maximum length; decode defensively and reject malformed data.
6. A GUI-open request may only open GUIs valid for that context, never "any ID the client sends".

Reject silently or with a debug log; never crash or kick on bad input. Put the checks in packet base classes so every packet gets them, and unit-test each base class with out-of-range, wrong-dimension and unauthorized requests.

Client-bound packets get the same defensive decoding: unchecked casts and enum indices from the network crash clients.

## Threads

- Know which thread your network stack calls handlers on in this Forge version (read the FML source at the version you pin). Any world, entity or inventory change from a non-main thread must be queued to the next server or client tick.
- Never load chunks from a packet handler, entity tick or tile entity tick.

## Synced state

- Prefer vanilla mechanisms: tile entity description packets, `DataWatcher`, container progress bars, extended entity properties synced on login, respawn and dimension change.
- Persist per-player and per-entity state in NBT or extended properties, not static maps.
- Test sync with two clients on a dedicated server, including after a relog and a dimension change (see `testing-gtnh-mods`).

## Pitfalls

- A packet carrying an entity ID that the server then casts and uses without checking type or distance.
- An entity ID stored in NBT and resolved later: the ID may now belong to a different entity. Store UUIDs.
- A keybind action that toggles state client-side and only tells the server afterwards.
