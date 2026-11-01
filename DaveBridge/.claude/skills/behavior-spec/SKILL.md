---
name: behavior-spec
description: Use when documenting how an existing mod behaves so it can be rebuilt (a behavior spec), when adding or reviewing a spec sheet, when building a feature from a spec, or when maintaining the register of the original's bugs that must not be reproduced and the record of deliberate deviations.
---

# Writing and using a behavior spec

A behavior spec is the contract between the people who read the original and the people who build the new mod. It must be complete enough that a builder never needs to open the original.

## Layout

```
docs/original-spec/
  README.md            how to read the spec, coverage summary
  CONVENTIONS.md       the rules below, adapted
  BUGS.md              merged register of suspected bugs in the original
  ASSET-FACTS.md       measured asset footprints (sizes, frames, colors, sound lengths)
  01-core/index.md     one folder per area, each with an index
  02-.../
docs/new-spec/         same areas: what the new mod changes, and how it plugs into the pack
```

Pick areas by subsystem, not by source package: core (lifecycle, config, packets, keybinds, HUD), each major content family, visuals and audio, projectiles or effects, items, blocks, machines, entities, worldgen. Aim for 8–12 areas. Each area gets an index; see [docs/templates/spec-area-index.md](../../../docs/templates/spec-area-index.md).

Keep two parallel trees: the *original* spec describes what exists; the *new* spec per area says what changes (tier gates, energy model, replaced machines, bug fixes) and how it integrates with the pack. Builders read both.

## Rules for writing

- **Describe, don't copy.** Prose, tables, ordered steps and your own pseudocode. No pasted or closely paraphrased source (see `clean-room-reimplementation`).
- **Facts are welcome:** registry and lang names, IDs, metadata values, constants, recipe grids, NBT keys, packet fields, config keys with defaults, asset paths and sizes.
- **Say "none" explicitly.** "Sounds: none" tells the reader it was checked; a missing field could mean either.
- **Document unreachable content** too, marked *unregistered*, *dead code* or *unobtainable*, so the builder can choose to build or drop it.
- **Label sides.** Every behavior step says client, server or both.
- **Only add.** Expanding one area never trims another. Correct only what is wrong, and note corrections in the area's coverage section.
- **Inferred is not observed.** If you cannot run, hear or see something (audio, a render), say the description is inferred from names and code paths.
- **Coverage and limits.** Each index states files read out of files in scope, and what could not be verified and why.

## Entity sheets

Every documented thing (item, block family, machine, entity, projectile, structure, packet, keybind) gets a sheet with these fields in this order: identity, obtaining, numbers, behavior, persistence and sync, UI, visuals, audio, relationships, bugs. The template is [docs/templates/spec-sheet.md](../../../docs/templates/spec-sheet.md). Catalog tables are a quick reference *in addition to* sheets, never instead of them.

## The bugs-not-to-reproduce register

The original almost certainly has hundreds of bugs. Rebuilding faithfully means rebuilding *without* them.

- While writing each area, log every suspicious thing inline with an ID: `<AREA>-<n>` (e.g. `CORE-12`). Columns: ID, title, location, what looks wrong, severity (crash, gameplay, visual, cosmetic).
- Merge all areas into one `BUGS.md`, deduplicate, and list aliases ("also reported as ITEM-07").
- These are *suspected* bugs. Do not design fixes in the spec; the builder decides.
- Typical high-value finds: unvalidated packets, client classes referenced from common code, world mutation off the main thread, unchecked casts and array indices from network or NBT data, divide-by-zero in falloff formulas, config lists whose length is assumed, registration that depends on optional mods without declaring them.
- Template: [docs/templates/bug-register.md](../../../docs/templates/bug-register.md).

## Building from the spec

1. Read the sheet and the matching new-spec area.
2. Read the feature's rows in `BUGS.md`. Each bug the feature could reproduce gets a regression test named after it, for example `doesNotReproduceCORE12_shiftClickKeepsStack`.
3. Cite the sheet at the top of the implementing class: `// Spec: docs/original-spec/02-items/tools.md#drill`.
4. Mark deliberate differences where they happen: `// Deviation: energy is EU, the original used RF (decision 0003).` A large deviation gets a decision record (see `port-workflow`).
5. In the PR, list deviations and the bug IDs avoided, each with its proving test.
6. When behavior changes later, update the new-spec deviation notes in the same PR.

## Pitfalls

- Specs written from memory or from a wiki. Wikis are often wrong or describe another version; pin the version you document and say so in the README.
- Numbers without units. Always say ticks, blocks, EU, hearts or half-hearts.
- Treating the original's quirks as design. If it smells like a bug, register it and let a decision record keep it on purpose.
