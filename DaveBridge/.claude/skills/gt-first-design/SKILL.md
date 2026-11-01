---
name: gt-first-design
description: Use when deciding what content a GTNH mod adds and how it is crafted, powered and gated - materials, recipes, voltage tiers, energy, machines and multiblocks, key bindings - and whenever an original mod's own ore, machine, energy system or progression would otherwise be carried over. GT and the pack come first; never duplicate what they provide.
---

# GT-first design

A mod feels native to GTNH when it *consumes* the pack's progression instead of running a parallel one. Every item you port gets re-homed onto GregTech materials, recipe maps, voltage tiers and EU.

## Deconflict before you build

For every system in the original mod, decide **keep, replace or drop**, and write the table into a decision record:

| Original system | Typical decision |
|---|---|
| Its own ores, ingots, plates, wires, circuits, fluids | **Drop.** Use GT materials and parts through ore-dict unification. |
| Its own energy (RF or custom) | **Drop.** EU only. |
| Machines that duplicate a GT or pack process (press, grinder, chemical mixer, charger, miner) | **Replace** with recipes in the existing GT or pack recipe maps. |
| Machines that are distinctive *and* have no pack equivalent | **Keep**, rebuilt as GT MetaTileEntities. |
| Ore generation | **Drop.** The pack's ore system owns ores. |

Check every pack mod, not just GT: a chemistry, biology or magic mod in the pack may already make your intermediate. A machine that duplicates what the pack does counts against you with players and pack maintainers. Before adding any mechanic, search the pack for it.

## Materials and parts

- Never register an ingot, plate, rod, screw, wire, circuit, ore or fluid that GT provides. Get them by ore dictionary:
  ```java
  GTOreDictUnificator.get(OrePrefixes.plate, Materials.Steel, 1)
  ```
- Mod-specific components are your own items, but they are *made from* GT parts.

## Recipes

- Machine processing goes through GT recipe maps with the builder, at the EU/t of the item's tier:
  ```java
  GTValues.RA.stdBuilder()
      .itemInputs(...).itemOutputs(...)
      .duration(10 * SECONDS).eut(TierEU.RECIPE_MV)
      .addTo(RecipeMaps.assemblerRecipes);
  ```
  Verify class and method names against the GT version you pin (see `gtnh-integration-research`).
- Crafting-table recipes follow pack conventions: GT tools in the grid, GT parts as ingredients.
- **Recipe clashes.** GT maps look recipes up by inputs. Two recipes in one map with the same item inputs and the same programmed circuit conflict, and a recipe whose inputs are a subset of another's can *shadow* it. Give each of yours a free circuit number, and test against the **pack's full recipe set** (dump recipes from a real-pack boot), not just GT's defaults.
- No recipe may let an item be obtained before its tier.

## Tier map

Every item has exactly one GT voltage tier, gated by **both**:
1. the minimum machine voltage of its final recipe, and
2. at least one input material unobtainable before that tier (for example steel at LV, aluminum at MV, stainless steel at HV, titanium at EV, tungstensteel at IV; confirm each against the current pack's progression).

Write the map as a decision record (template: [docs/templates/decision-record.md](../../../docs/templates/decision-record.md)). If an item's recipe cannot meet its tier, move its tier with a new record; never weaken the recipe to fit. Items made by combining other items carry their inputs' tier; say so in the record.

Enforce the map in code: a dev-only `postInit` self-check that walks your recipes and fails if any uses an input or machine above its output's tier, or if any recipe input fails to resolve.

## Energy

- EU only. Electric items implement the IC2 electric-item API the way GT's do, so GT chargers and battery buffers work with them.
- Decide charging rules per tier in a record (for example: an item charges only in a machine of exactly its tier or above).
- Fuel-using items take GT fluids.

## Machines

- Kept machines are GT MetaTileEntities (single blocks or StructureLib multiblocks) using GT's GUI framework, not custom tile entities with their own energy code. New non-GT GUIs use ModularUI2.
- **MetaTileEntity IDs are a shared, global space.** Reserve a block with the GTNH team (or document the range you claim), record it, and **never renumber or reuse an ID**, even after retiring a machine (see `config-safe-registration`).
- **Multiblocks for scale.** GTNH players scale everything. Every machine players use regularly, and at minimum every bottleneck, gets a multiblock that shares the single block's recipe map and adds parallels. Do a bottleneck analysis per machine.
- **Distinctive shapes.** No plain 3×3×3 cubes; a multiblock's silhouette should say what it does. Cite a GT multiblock as precedent for hatch and casing rules.
- Use the pack's own multiblocks to scale the GT maps you rely on, and list which one covers each.

## Other pack-fit rules

- **Default key bindings** clash easily in a pack with hundreds of mods. Read the pack's shipped `options.txt` and key configs, pick free keys, and add a test that checks your defaults against that list.
- Tooltips, names, sounds and textures follow the pack's style. Add an "Added by: <mod>" line where GT conventions show one.
- NEI shows GT recipe maps automatically; add handlers only for non-GT logic. Hide unobtainable and technical items. NEI's default sort follows numeric item IDs, which vary per world in 1.7.10; if your items' order matters, supply an explicit order.
- Quest content, loot tables and other pack data are a separate delivery problem (see `in-pack-content-delivery`).

## Pitfalls

- Porting the original's progression wholesale and "adding GT recipes later". Tiers drive every recipe; set them first.
- Registering a material GT already has under a slightly different name. Players get two incompatible plates.
- Assuming a GT recipe map's behavior from memory. Read it at the pinned tag.
