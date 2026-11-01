---
name: in-pack-content-delivery
description: Use when a mod needs something outside its own code to change in the GTNH pack - quests, loot tables, mob or item blacklists, NEI groups, key defaults, other mods' configs - or when deciding whether to ship such content inside the jar or ask the pack for it. Covers the pack-changes list, in-jar delivery, and safe questbook installation.
---

# Delivering content into the pack

A mod that works only after a pack PR is a mod nobody can try. Aim for one portable jar a server owner drops into the pack, and treat every pack-side change as either done from the jar or documented as an optional step.

## 1. Keep a pack-changes list

Maintain `docs/PACK-CHANGES.md`: every change the pack would need, as rows of *file, change, why, which spec sheet*. Paths are relative to the pack's `.minecraft/`. Find them by reading the pack's real `config/` folder, not the other mod's defaults. Typical rows in a large pack:

- loot configs (many pack loot files run in an override mode that **wipes entries added from code**; a missing or misspelled mode attribute can default to override);
- elite or infernal mob item lists, which are global and apply to vanilla mobs too;
- mob blacklists in info or scanning mods (or your technical entities show up empty);
- offhand mods' stop lists and blacklists, so one click doesn't also use the offhand item;
- NEI collapsible groups and handler ordering (some are file-only);
- explosion or "creeper-like" behavior lists that trigger on tools from unlisted mods.

Note pack-wide bugs you find (a shipped value that breaks a feature for everyone) as such, separate from your own needs.

## 2. Prefer in-jar delivery

For each row, in order of preference:
1. **Make it unnecessary**: change your design so the pack needs nothing (register your mob through the normal spawn lists behind a spawn event gate, rather than a swap trick that other mods' lists can't see).
2. **Do it from the jar** with a public API, an event, IMC, a bundled resource or a sensible config default of your own.
3. **Document it** as an optional server-owner step with the exact lines to add.

**Never write another mod's config file at runtime.** It surprises pack maintainers, breaks their updates, and is overwritten on the next pack update anyway.

## 3. Questbook lines from the jar (BetterQuesting)

GTNH quests live in the pack's quest database. To ship a quest line without a pack PR:

- Store the quests in the jar as resources in the quest mod's own on-disk format, generated from one source file by a script, and validated by a unit test.
- **Install only behind a hidden config key**, off by default and absent from the in-game config GUI. With it off, the quest mod is never touched.
- **Stable IDs.** Derive every quest and line ID deterministically from a stable key, e.g. `uuid5(<your fixed namespace UUID>, "<modid>.<quest key>")`, encoded the way the quest mod encodes IDs (read its source; see `gtnh-integration-research`). Never rename a key after release; a retired quest is removed and its key never reused.
- **Idempotent upsert.** Installing twice, or after an update, replaces exactly your quests and line, never duplicates them, and never touches anyone else's. A later uninstall can remove exactly them.
- **Let the owning mod save.** Mark its database dirty and let it write on its own schedule. Writing the file yourself can stamp your version or timestamp into it and make the quest mod think the database changed, triggering backups or resets.
- **Respect the pack's reset hooks.** Packs often reset or reload default quests on a pack update; check what the pack does on update and make sure an install survives it or is re-applied by the same key.
- Cross-links from the pack's own lines are an optional pack-side step; list them in PACK-CHANGES.
- Test on a real server of the target pack: install, restart, install again, update the jar, and confirm no duplicates and no backup churn.

## 4. Other data the same way

Guide-book pages, NEI groups that have an API, default key bindings and loot your own structures place can usually ship in the jar. Anything that can only be a pack file stays a documented optional step.

## Pitfalls

- Depending on a pack PR for something players need on day one.
- Using random UUIDs for generated content, so every install adds a copy.
- Assuming a config file is additive because the mod's default is; the pack may ship it in override mode.
