---
name: gtnh-integration-research
description: Use before writing any code that calls, extends, registers with or reacts to GregTech, GTNHLib, IC2, NEI, BetterQuesting or any other mod in the GT New Horizons pack, and when adding or bumping a dependency. Source first at the exact tag the pack ships; decompile only as a fallback; cite what you relied on.
---

# GTNH integration research: source first

Guessing how another mod behaves is the most common cause of integration bugs. Find out from its source, at the version the players actually run.

## 0. Have the target pack on disk

- Download the exact pack release you target (GTNH publishes MultiMC zips per version, betas and RCs included) and extract it into a **git-ignored** `reference/` folder. Never commit anything from it.
- Its `mods/` folder is the ground truth for versions; its `config/` folder shows how the pack configures each mod, which often differs from that mod's defaults.
- The pack's release manifest (GTNH's DreamAssemblerXXL repo, `releases/manifests/`) maps each mod to its version and repo. A small script that joins manifest, jar names, mod IDs and source repos into one index pays for itself in a day.
- Search tools skip git-ignored folders by default; point them at `reference/` explicitly (`rg --no-ignore`).
- Treat the downloaded pack as untrusted: run helper scripts from outside it, with `python -I`.

## 1. Order of evidence

Use the first that answers the question:

1. **The mod's source on GitHub at the tag the pack ships.** Most GTNH mods live under `GTNewHorizons/` and are tagged with the pack's version string.
2. **The shipped jar's signatures** (`javap -p -cp <jar> <fqcn>`): confirms a class or method exists in the pack's build.
3. **Decompiled bytecode**, only when no source exists for that version. Prefer a `-dev` (deobfuscated) jar from the mod's maven over the obfuscated pack jar.

Prefer documented API (an `api` package, events, IMC, registries) over internals. Before inventing an integration, look for a precedent in other GTNH mods: a pattern the pack already uses is the strongest evidence of intended use.

## 2. Commands

```sh
# Where is a symbol defined or used? (code search covers the default branch only)
gh search code 'GTOreDictUnificator' --repo GTNewHorizons/GT5-Unofficial --language java
# Precedent across the org
gh search code 'IElectricItem' --owner GTNewHorizons --language java
# Read a file at the pinned tag
gh api 'repos/OWNER/REPO/contents/PATH?ref=TAG' -H 'Accept: application/vnd.github.raw'
# List files at the tag
gh api 'repos/OWNER/REPO/git/trees/TAG?recursive=1' --jq '.tree[].path'
# Why does it work this way?
gh api 'repos/OWNER/REPO/commits?path=PATH&sha=TAG' --jq '.[].commit.message'
# Which maven coordinate do GTNH devs compile against?
gh search code '<mod>' --owner GTNewHorizons --filename dependencies.gradle
```

For heavy research on one mod (GT5-Unofficial especially), shallow-clone it at the tag into `reference/src/` and search locally.

**Always re-read at the pinned tag** anything found by code search; the default branch may be ahead of the pack.

## 3. When there is no source

Look harder first: the author's other repos and forks, archive orgs, GTNH's nexus (`-sources.jar`, `-dev.jar`), the mod author's own maven, `.java` files or API packages shipped inside the jar. Many old mods publish their API as source even when internals are closed.

If you must decompile:
- **Never paste decompiled code**, not even a helper. Learn the contract (names, signatures, constants, call order) and write your own code against it.
- Never commit decompiled output.
- Decompiled APIs are guesses: parameter names are lost, constants are inlined, control flow can be wrong.

## 4. Cite what you relied on

One comment per external contract, on the class Javadoc or directly above the call site:

```java
// Source: https://github.com/GTNewHorizons/<Repo>/blob/<pack-tag>/src/main/java/.../Thing.java#L120-L131
// addTo() registers with every given map, so one builder can feed several maps.
```

```java
// Decompiled: <jar name> (<pack version>), <fqcn>#<member>. No source exists for this version;
// inferred from decompiled bytecode and may be wrong. Re-check when the pack updates this mod.
```

Permalinks are pinned to a tag or commit, never `master`/`HEAD`.

## 5. Dependencies

- Pin every dependency in `dependencies.gradle` to the version the pack ships, using GTNH maven coordinates with the `:dev` classifier.
- `compileOnly` for optional integrations; `devOnlyNonPublishable` for things needed only to run the dev client/server. Never shade another mod.
- Obfuscated jars from CurseForge maven need `rfg.deobf(...)`.
- Guard optional mods with `Loader.isModLoaded("<modid>")` or `@Optional`, and keep that code in a `compat` package. Declare hard dependencies in `@Mod(dependencies = ...)`.
- GT5-Unofficial renamed its API classes in 2024 (`GT_Values` → `GTValues` and so on). Old snippets online use the old names; check against your pinned version.

## 6. When the pack version changes

1. Fetch the new pack into `reference/`, rebuild the index.
2. Re-pin `dependencies.gradle`.
3. Update the tag in every `// Source:` link for mods whose version changed, and re-check every `// Decompiled:` hedge for them.
4. Boot the real pack with your jar (see `testing-gtnh-mods`) before calling it done.

## Licenses

Reading any mod's source or bytecode to interoperate is fine. Copying implementation is not: most pack mods are LGPL/GPL and some are All Rights Reserved; check each mod's license before borrowing even a pattern verbatim. Calling public API, implementing its interfaces and reading its constants is integration.
