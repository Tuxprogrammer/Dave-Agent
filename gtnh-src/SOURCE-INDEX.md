# GTNH 2.9.0 upstream source index

Real upstream source for every mod in GT New Horizons **2.9.0** (Minecraft 1.7.10), checked out at the version the pack ships. Prefer this over the decompiles in `gtnh-src/mods/` (see `INDEX.md`) when it exists: it has comments, javadoc and real local names. Machine-readable copy: `gtnh-src/source-index.json`.

## Summary

| | |
|---|---|
| Pack | GTNH 2.9.0, 243 mods in the release manifest (27 client-only, 1 server-only, the rest both) |
| Manifest | [DreamAssemblerXXL `releases/manifests/2.9.0.json`](https://raw.githubusercontent.com/GTNewHorizons/DreamAssemblerXXL/1b62ef00ad679c51ab0ec67f8a8e42778a059ce6/releases/manifests/2.9.0.json) (DreamAssemblerXXL commit `1b62ef00ad679c51ab0ec67f8a8e42778a059ce6`, "update 2.9.0 final", byte-identical to `.work/gtnh-2.9.0/meta/manifest-2.9.0.json`) |
| **exact** | 224: a tag equal to the pack version, or a commit that sets that version |
| **sources-jar** | 1: no public repo, but the exact-version `-sources.jar` exists (extracted by the sibling into `gtnh-src/mods/`) |
| **nearest** | 0 |
| **branch-head** | 5: no matching tag; the release branch head was used (see notes per mod) |
| **decomp-only** (`none`) | 13: no public source found; use `gtnh-src/mods/` (some have an API-only `apiSource`) |
| Checkouts | 233 directories in `gtnh-src/source/` (49,118 .java/.scala/.kt files), **814M** disk usage (`du -sh`; 488 MB apparent size), including the shallow `.git` dirs |
| Built | 2026-10-31 |

### How the checkouts were made

- `git clone --depth 1 --single-branch --branch <tag|branch> --filter=blob:none --no-checkout`, then a non-cone sparse checkout that skips binary assets (`*.png *.jpg *.gif *.ogg *.wav *.mp3 *.psd *.xcf *.blend *.jar *.zip *.ttf *.obj *.b3d *.tcn` and similar). Java/Scala/Kotlin, lang files, JSON, mcmod.info, mixin configs, docs and build files are all there. Textures, sounds and models are not.
- Each checkout is a shallow, detached, partial clone. Treat it as read-only data: **no build scripts or gradle wrappers were run** and none should be.
- `.git/CLONE_OK` marks a completed checkout. `git -C <path> rev-parse HEAD` equals the `commit` field.
- 208 of the 212 GTNH-hosted mods are public GTNewHorizons repos with a tag exactly equal to the manifest version. The other 4 (Catwalks-2, Galaxy-Space-GTNH, harvestcraft, Automagy-GTNH) are private repos.
- `GT5-Unofficial` is the GregTech jar, and it also contains the merged addons (bartworks, GT++, TecTech, GoodGenerator, KekzTech, KubaTech, GGFab, ...).

### JSON schema (`source-index.json`)

An array with one object per manifest mod, plus one extra row for CoFHLib, which ships inside the CoFH Core jar. Keys:

- `modId` (first mod id in the jar), `modIds`, `name` (mcmod.info name when known), `manifestName`, `jar`, `packVersion`, `side` (BOTH/CLIENT/SERVER)
- `repoUrl`, `ref`, `refKind` (`tag`|`commit`|`branch`, or `maven` for jar sources), `commit` (checked-out SHA), `commitDate`
- `match`: `exact`|`nearest`|`branch-head`|`sources-jar`|`none`
- `sourceKind`: `original`, `upstream-divergent` (a related but different code line than the shipped fork), `decompiled-reference` (someone else's decompile), or null for `none`
- `license` (SPDX id, `LicenseRef-*` for custom texts, `none` = no license file or no public source, `unknown`), `licenseNote`, and `manifestLicense` (what the GTNH manifest claims; unverified)
- `path`: where to read the source (relative to the project root). For `sources-jar` this is the sibling's `gtnh-src/mods/<dir>/`
- `decompPath` / `decompOrigin`: the sibling's output for the same jar (null for client-only jars, which are not in the server pack)
- `sourcesJar`: the URL when `match` = `sources-jar`
- `apiSource`: `{repoUrl, ref, refKind, path, commit, license, notes}` when only an official API is public (IC2, Thaumcraft, Automagy)
- `notes`, `searched` (where we looked; filled in for every non-exact row)

## Licenses

From each checkout's root `LICENSE`/`COPYING` file. The manifest's own license field is often wrong. Where the license text only names a family, ids are given without `-only`/`-or-later`. **Before copying any code into our own mods, check the license.** ARR, `none`, `LicenseRef-*` and CC-NC/ND licenses mean "read, don't copy". GPL and LGPL code may only be copied into a mod that is compatibly licensed. `none` below means the repo has no license file, so treat it as All Rights Reserved. Decomp-only mods are not counted.

| license | mods with source |
|---|---|
| LGPL-3.0 | 69 |
| MIT | 57 |
| GPL-3.0 | 25 |
| none | 18 |
| CC-BY-NC-SA-4.0 | 7 |
| WTFPL | 6 |
| LicenseRef-ARR | 6 |
| LicenseRef-MMPL-1.0 | 5 |
| LGPL-2.1 | 4 |
| Unlicense | 4 |
| GPL-2.0 | 3 |
| CC0-1.0 | 3 |
| MPL-2.0 | 2 |
| CC-BY-4.0 | 2 |
| CC-BY-SA-4.0 | 2 |
| CC-BY-NC-SA-3.0 | 2 |
| AGPL-3.0 | 2 |
| CC-BY-NC-3.0 | 1 |
| unknown | 1 |
| LGPL-3.0-or-later AND Unlicense | 1 |
| LGPL-2.1-or-later | 1 |
| LicenseRef-Galacticraft | 1 |
| LicenseRef-AtomicStryker | 1 |
| BSD-3-Clause | 1 |
| LicenseRef-Permissive-Custom | 1 |
| LicenseRef-Railcraft | 1 |
| LicenseRef-Vswe-Permissive | 1 |
| CC-BY-NC-ND-4.0 | 1 |
| LicenseRef-Calclavia-Educational | 1 |
| LicenseRef-CC-unknown | 1 |

## Mods

Sorted by name. `path` is relative to the project root. Source of truth: `source-index.json`.

| mod | jar | pack version | match | repo | ref | license | path |
|---|---|---|---|---|---|---|---|
| Advanced Solar Panels 1.7.10 Edition | `AdvancedSolarPanel-1.7.10-3.5.1.jar` | 1.7.10 Edition | **none** |  |  | none |  |
| Adventure Backpack | `adventurebackpack-1.4.28-GTNH.jar` | 1.4.28-GTNH | exact | [GTNewHorizons/AdventureBackpack2](https://github.com/GTNewHorizons/AdventureBackpack2) | `1.4.28-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/AdventureBackpack2/` |
| AE2 Fluid Crafting | `ae2fc-1.5.116-gtnh.jar` | 1.5.116-gtnh | exact | [GTNewHorizons/AE2FluidCraft-Rework](https://github.com/GTNewHorizons/AE2FluidCraft-Rework) | `1.5.116-gtnh` (tag) | LGPL-3.0 | `gtnh-src/source/AE2FluidCraft-Rework/` |
| AE2 Wireless Crafting Terminal | `WirelessCraftingTerminal-1.12.17.jar` | 1.12.17 | exact | [GTNewHorizons/WirelessCraftingTerminal](https://github.com/GTNewHorizons/WirelessCraftingTerminal) | `1.12.17` (tag) | GPL-3.0 | `gtnh-src/source/WirelessCraftingTerminal/` |
| AFSU Mod | `AFSU-1.3.2-GTNH.jar` | 1.3.2-GTNH | exact | [GTNewHorizons/AFSU](https://github.com/GTNewHorizons/AFSU) | `1.3.2-GTNH` (tag) | MIT | `gtnh-src/source/AFSU/` |
| Akashic Tome | `akashictome-1.2.7.jar` | 1.2.7 | exact | [GTNewHorizons/AkashicTome](https://github.com/GTNewHorizons/AkashicTome) | `1.2.7` (tag) | CC-BY-NC-3.0 | `gtnh-src/source/AkashicTome/` |
| Alchemical Grate | `alchgrate-1.3.2-GTNH.jar` | 1.3.2-GTNH | exact | [GTNewHorizons/AlchemyGrate](https://github.com/GTNewHorizons/AlchemyGrate) | `1.3.2-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/AlchemyGrate/` |
| Amazing Trophies | `amazingtrophies-1.4.10.jar` | 1.4.10 | exact | [GTNewHorizons/Amazing-Trophies](https://github.com/GTNewHorizons/Amazing-Trophies) | `1.4.10` (tag) | LGPL-3.0 | `gtnh-src/source/Amazing-Trophies/` |
| Amun-Ra | `AmunRa-GC-0.8.14.jar` | 0.8.14 | exact | [GTNewHorizons/amunra](https://github.com/GTNewHorizons/amunra) | `0.8.14` (tag) | MIT | `gtnh-src/source/amunra/` |
| Angelica | `angelica-2.2.43.jar` | 2.2.43 | exact | [GTNewHorizons/Angelica](https://github.com/GTNewHorizons/Angelica) | `2.2.43` (tag) | LGPL-3.0 | `gtnh-src/source/Angelica/` |
| AngerMod. Makes your Mobs angry! | `AngerMod-1.0.7.jar` | 1.0.7 | exact | [GTNewHorizons/AngerMod](https://github.com/GTNewHorizons/AngerMod) | `1.0.7` (tag) | WTFPL | `gtnh-src/source/AngerMod/` |
| AppleCore | `AppleCore-3.3.13.jar` | 3.3.13 | exact | [GTNewHorizons/AppleCore](https://github.com/GTNewHorizons/AppleCore) | `3.3.13` (tag) | LGPL-3.0 | `gtnh-src/source/AppleCore/` |
| Applied Energistics 2 | `appliedenergistics2-rv3-beta-1095-GTNH.jar` | rv3-beta-1095-GTNH | exact | [GTNewHorizons/Applied-Energistics-2-Unofficial](https://github.com/GTNewHorizons/Applied-Energistics-2-Unofficial) | `rv3-beta-1095-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/Applied-Energistics-2-Unofficial/` |
| ArchaicFix | `archaicfix-0.8.2.jar` | 0.8.2 | exact | [embeddedt/ArchaicFix](https://github.com/embeddedt/ArchaicFix) | `0.8.2` (tag) | LGPL-3.0 | `gtnh-src/source/ArchaicFix/` |
| ArchitectureCraft | `ArchitectureCraft-1.12.19.jar` | 1.12.19 | exact | [GTNewHorizons/ArchitectureCraft](https://github.com/GTNewHorizons/ArchitectureCraft) | `1.12.19` (tag) | MIT | `gtnh-src/source/ArchitectureCraft/` |
| AsieLib | `AsieLib-0.7.2.jar` | 0.7.2 | exact | [GTNewHorizons/AsieLib](https://github.com/GTNewHorizons/AsieLib) | `0.7.2` (tag) | MIT | `gtnh-src/source/AsieLib/` |
| Aspect Recipe Index | `aspectrecipeindex-1.1.6.jar` | 1.1.6 | exact | [GTNewHorizons/AspectRecipeIndex](https://github.com/GTNewHorizons/AspectRecipeIndex) | `1.1.6` (tag) | GPL-3.0 | `gtnh-src/source/AspectRecipeIndex/` |
| Automagy | `Automagy-0.29.8-GTNH.jar` | 0.29.8-GTNH | **none** |  |  | none |  API: `gtnh-src/source/Automagy/` |
| Avaritia | `Avaritia-1.100.jar` | 1.100 | exact | [GTNewHorizons/Avaritia](https://github.com/GTNewHorizons/Avaritia) | `1.100` (tag) | MIT | `gtnh-src/source/Avaritia/` |
| Avaritiaddons | `Avaritiaddons-1.9.6-GTNH.jar` | 1.9.6-GTNH | exact | [GTNewHorizons/Avaritiaddons](https://github.com/GTNewHorizons/Avaritiaddons) | `1.9.6-GTNH` (tag) | MPL-2.0 | `gtnh-src/source/Avaritiaddons/` |
| Backhand | `backhand-1.8.18.jar` | 1.8.18 | exact | [GTNewHorizons/Backhand](https://github.com/GTNewHorizons/Backhand) | `1.8.18` (tag) | MIT | `gtnh-src/source/Backhand/` |
| Backpack Edited for ModdedNetwork | `backpack-2.6.18-GTNH.jar` | 2.6.18-GTNH | exact | [GTNewHorizons/Minecraft-Backpack-Mod](https://github.com/GTNewHorizons/Minecraft-Backpack-Mod) | `2.6.18-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/Minecraft-Backpack-Mod/` |
| BD lib | `bdlib-1.11.1-GTNH.jar` | 1.11.1-GTNH | exact | [GTNewHorizons/bdlib](https://github.com/GTNewHorizons/bdlib) | `1.11.1-GTNH` (tag) | none | `gtnh-src/source/bdlib/` |
| BeeBetterAtBees-GTNH | `beebetteratbees-0.4.8-GTNH.jar` | 0.4.8-GTNH | exact | [GTNewHorizons/BeeBetterAtBees-GTNH](https://github.com/GTNewHorizons/BeeBetterAtBees-GTNH) | `0.4.8-GTNH` (tag) | none | `gtnh-src/source/BeeBetterAtBees-GTNH/` |
| BetterAchievements | `BetterAchievements-0.3.3.jar` | 0.3.3 | exact | [GTNewHorizons/BetterAchievements](https://github.com/GTNewHorizons/BetterAchievements) | `0.3.3` (tag) | LicenseRef-ARR | `gtnh-src/source/BetterAchievements/` |
| BetterBuildersWands | `BetterBuildersWands-0.13.12-GTNH.jar` | 0.13.12-GTNH | exact | [GTNewHorizons/BetterBuildersWands](https://github.com/GTNewHorizons/BetterBuildersWands) | `0.13.12-GTNH` (tag) | none | `gtnh-src/source/BetterBuildersWands/` |
| BetterCrashes | `bettercrashes-1.4.7-GTNH.jar` | 1.4.7-GTNH | exact | [GTNewHorizons/BetterCrashes](https://github.com/GTNewHorizons/BetterCrashes) | `1.4.7-GTNH` (tag) | MIT | `gtnh-src/source/BetterCrashes/` |
| BetterLoadingScreen | `betterloadingscreen-1.7.19-GTNH.jar` | 1.7.19-GTNH | exact | [GTNewHorizons/BetterLoadingScreen](https://github.com/GTNewHorizons/BetterLoadingScreen) | `1.7.19-GTNH` (tag) | GPL-2.0 | `gtnh-src/source/BetterLoadingScreen/` |
| BetterP2P | `betterp2p-1.4.8.jar` | 1.4.8 | exact | [GTNewHorizons/BetterP2P](https://github.com/GTNewHorizons/BetterP2P) | `1.4.8` (tag) | GPL-3.0 | `gtnh-src/source/BetterP2P/` |
| BetterQuesting | `BetterQuesting-3.8.92-GTNH.jar` | 3.8.92-GTNH | exact | [GTNewHorizons/BetterQuesting](https://github.com/GTNewHorizons/BetterQuesting) | `3.8.92-GTNH` (tag) | MIT | `gtnh-src/source/BetterQuesting/` |
| BiblioCraft | `BiblioCraft[v1.11.7][MC1.7.10].jar` | 1.11.7 | **none** |  |  | none |  |
| BiblioWoods Biomes O'Plenty Edition | `BiblioWoods[BiomesOPlenty][v1.9].jar` | 1.9 | **none** |  |  | none |  |
| BiblioWoods Forestry Edition | `BiblioWoods[Forestry][v1.7].jar` | 1.7 | **none** |  |  | none |  |
| BiblioWoods Natura Edition | `BiblioWoods[Natura][v1.5].jar` | 1.5 | **none** |  |  | none |  |
| Binnie Core | `binnie-mods-2.6.51.jar` | 2.6.51 | exact | [GTNewHorizons/Binnie](https://github.com/GTNewHorizons/Binnie) | `2.6.51` (tag) | LGPL-3.0 | `gtnh-src/source/Binnie/` |
| Biomes O' Plenty | `BiomesOPlenty-1.7.10-2.1.0.2308-universal.jar` | 2.1.0.2308 | branch-head | [Glitchfiend/BiomesOPlenty](https://github.com/Glitchfiend/BiomesOPlenty) | `BOP-1.7.10-2.1.x` (branch) | none | `gtnh-src/source/BiomesOPlenty/` |
| BlockLimiter. Restrict your Blocks | `BlockLimiter-0.7.0.jar` | 0.7.0 | exact | [GTNewHorizons/BlockLimiter](https://github.com/GTNewHorizons/BlockLimiter) | `0.7.0` (tag) | WTFPL | `gtnh-src/source/BlockLimiter/` |
| BlockRenderer6343 | `blockrenderer6343-1.4.25.jar` | 1.4.25 | exact | [GTNewHorizons/BlockRenderer6343](https://github.com/GTNewHorizons/BlockRenderer6343) | `1.4.25` (tag) | LGPL-3.0 | `gtnh-src/source/BlockRenderer6343/` |
| Blood Arsenal | `BloodArsenal-1.5.12.jar` | 1.5.12 | exact | [GTNewHorizons/BloodArsenal](https://github.com/GTNewHorizons/BloodArsenal) | `1.5.12` (tag) | CC-BY-4.0 | `gtnh-src/source/BloodArsenal/` |
| Blood Magic: Alchemical Wizardry | `BloodMagic-1.9.16.jar` | 1.9.16 | exact | [GTNewHorizons/BloodMagic](https://github.com/GTNewHorizons/BloodMagic) | `1.9.16` (tag) | CC-BY-4.0 | `gtnh-src/source/BloodMagic/` |
| Botania | `Botania-1.13.42-GTNH.jar` | 1.13.42-GTNH | exact | [GTNewHorizons/Botania](https://github.com/GTNewHorizons/Botania) | `1.13.42-GTNH` (tag) | none | `gtnh-src/source/Botania/` |
| botanichorizons | `BotanicHorizons-1.12.10-GTNH.jar` | 1.12.10-GTNH | exact | [GTNewHorizons/Botanic-horizons](https://github.com/GTNewHorizons/Botanic-horizons) | `1.12.10-GTNH` (tag) | CC-BY-NC-SA-4.0 | `gtnh-src/source/Botanic-horizons/` |
| Botany, NEIAddons\ | `NEIAddons-1.18.8.jar` | 1.18.8 | exact | [GTNewHorizons/neiaddons](https://github.com/GTNewHorizons/neiaddons) | `1.18.8` (tag) | LicenseRef-MMPL-1.0 | `gtnh-src/source/neiaddons/` |
| BugTorch | `bugtorch-1.3.1.jar` | 1.3.1 | exact | [jss2a98aj/BugTorch](https://github.com/jss2a98aj/BugTorch) | `1.3.1` (tag) | MIT | `gtnh-src/source/BugTorch/` |
| BuildCraft Oil Tweak | `BuildCraftOilTweak-1.1.3.jar` | 1.1.3 | exact | [GTNewHorizons/BuildCraftOilTweak](https://github.com/GTNewHorizons/BuildCraftOilTweak) | `1.1.3` (tag) | MIT | `gtnh-src/source/BuildCraftOilTweak/` |
| Carpenter's Blocks | `CarpentersBlocks-3.7.3-GTNH.jar` | 3.7.3-GTNH | exact | [GTNewHorizons/CarpentersBlocks](https://github.com/GTNewHorizons/CarpentersBlocks) | `3.7.3-GTNH` (tag) | LGPL-2.1 | `gtnh-src/source/CarpentersBlocks/` |
| Catwalks Mod | `catwalks-2.4.2-GTNH.jar` | 2.4.2-GTNH | sources-jar | [sources jar](https://nexus.gtnewhorizons.com/repository/public/com/github/GTNewHorizons/Catwalks-2/2.4.2-GTNH/Catwalks-2-2.4.2-GTNH-sources.jar) |  | unknown | `gtnh-src/mods/catwalks/` |
| Chisel | `chisel-2.17.34-GTNH.jar` | 2.17.34-GTNH | exact | [GTNewHorizons/Chisel](https://github.com/GTNewHorizons/Chisel) | `2.17.34-GTNH` (tag) | GPL-2.0 | `gtnh-src/source/Chisel/` |
| Chisel Tones | `chiseltones-1.2.0-GTNH.jar` | 1.2.0-GTNH | exact | [GTNewHorizons/ChiselTones](https://github.com/GTNewHorizons/ChiselTones) | `1.2.0-GTNH` (tag) | LicenseRef-MMPL-1.0 | `gtnh-src/source/ChiselTones/` |
| ChromaticTooltips | `chromatictooltips-1.0.36-GTNH.jar` | 1.0.36-GTNH | exact | [GTNewHorizons/ChromaticTooltips](https://github.com/GTNewHorizons/ChromaticTooltips) | `1.0.36-GTNH` (tag) | GPL-3.0 | `gtnh-src/source/ChromaticTooltips/` |
| ChromaticTooltipsCompat | `chromatictooltipscompat-1.0.40-GTNH.jar` | 1.0.40-GTNH | exact | [GTNewHorizons/ChromaticTooltipsCompat](https://github.com/GTNewHorizons/ChromaticTooltipsCompat) | `1.0.40-GTNH` (tag) | GPL-3.0 | `gtnh-src/source/ChromaticTooltipsCompat/` |
| ChunkAPI | `chunkapi-mc1.7.10-0.8.4.jar` | 0.8.4 | exact | [LegacyModdingMC/ChunkAPI](https://github.com/LegacyModdingMC/ChunkAPI) | `0.8.4` (tag) | LGPL-3.0 | `gtnh-src/source/ChunkAPI/` |
| CodeChicken Core | `CodeChickenCore-1.4.22.jar` | 1.4.22 | exact | [GTNewHorizons/CodeChickenCore](https://github.com/GTNewHorizons/CodeChickenCore) | `1.4.22` (tag) | MIT | `gtnh-src/source/CodeChickenCore/` |
| CoFH Core | `CoFHCore-[1.7.10]3.1.4-329.jar` | 3.1.4-329 | exact | [CoFH/CoFHCore-1.12-Legacy](https://github.com/CoFH/CoFHCore-1.12-Legacy) | `4be193afe6` (commit) | LicenseRef-ARR | `gtnh-src/source/CoFHCore-1.12-Legacy/` |
| CoFHLib (bundled in CoFH Core) | `CoFHCore-[1.7.10]3.1.4-329.jar` | 3.1.4-329 | exact | [CoFH/CoFHLib](https://github.com/CoFH/CoFHLib) | `6b24c7dc3b` (commit) | LGPL-3.0 | `gtnh-src/source/CoFHLib/` |
| Compact Kinetic Wind and Water Generators | `CompactKineticGenerators-1.7.10-1.0.jar` | 1.0 | branch-head | [PinkaLulan/CompactKineticGenerators](https://github.com/PinkaLulan/CompactKineticGenerators) | `master` (branch) | MIT | `gtnh-src/source/CompactKineticGenerators/` |
| Compat | `buildcraft-compat-7.1.22.jar` | 7.1.22 | exact | [GTNewHorizons/BuildCraftCompat](https://github.com/GTNewHorizons/BuildCraftCompat) | `7.1.22` (tag) | none | `gtnh-src/source/BuildCraftCompat/` |
| Computronics | `Computronics-1.9.13-GTNH.jar` | 1.9.13-GTNH | exact | [GTNewHorizons/Computronics](https://github.com/GTNewHorizons/Computronics) | `1.9.13-GTNH` (tag) | MIT | `gtnh-src/source/Computronics/` |
| Controlling | `controlling-2.1.10.jar` | 2.1.10 | exact | [GTNewHorizons/Controlling](https://github.com/GTNewHorizons/Controlling) | `2.1.10` (tag) | MIT | `gtnh-src/source/Controlling/` |
| Cooking For Blockheads | `CookingForBlockheads-1.4.14-GTNH.jar` | 1.4.14-GTNH | exact | [GTNewHorizons/CookingForBlockheads](https://github.com/GTNewHorizons/CookingForBlockheads) | `1.4.14-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/CookingForBlockheads/` |
| Core, BuildCraft\ | `buildcraft-7.1.65.jar` | 7.1.65 | exact | [GTNewHorizons/BuildCraft](https://github.com/GTNewHorizons/BuildCraft) | `7.1.65` (tag) | LicenseRef-MMPL-1.0 | `gtnh-src/source/BuildCraft/` |
| Core, ProjRed\ | `ProjRed-4.12.50-GTNH.jar` | 4.12.50-GTNH | exact | [GTNewHorizons/ProjectRed](https://github.com/GTNewHorizons/ProjectRed) | `4.12.50-GTNH` (tag) | MIT | `gtnh-src/source/ProjectRed/` |
| Core, WR-CBE\ | `WR-CBE-1.7.12.jar` | 1.7.12 | exact | [GTNewHorizons/WirelessRedstone-CBE](https://github.com/GTNewHorizons/WirelessRedstone-CBE) | `1.7.12` (tag) | MIT | `gtnh-src/source/WirelessRedstone-CBE/` |
| CoreTweaks | `coretweaks-0.3.4.7-GTNH.jar` | 0.3.4.7-GTNH | exact | [GTNewHorizons/CoreTweaks](https://github.com/GTNewHorizons/CoreTweaks) | `0.3.4.7-GTNH` (tag) | MIT | `gtnh-src/source/CoreTweaks/` |
| CosmeticArmorReworked | `cosmeticarmorreworked-1.0.7-GTNH.jar` | 1.0.7-GTNH | exact | [GTNewHorizons/CosmeticArmorReworked](https://github.com/GTNewHorizons/CosmeticArmorReworked) | `1.0.7-GTNH` (tag) | LicenseRef-MMPL-1.0 | `gtnh-src/source/CosmeticArmorReworked/` |
| Craft-Presence | `CraftPresence-2.7.1+1.7.10-forge.jar` | 2.7.1 | exact | [CDAGaming/CraftPresence](https://gitlab.com/CDAGaming/CraftPresence) | `f625d0e7a5` (commit) | MIT | `gtnh-src/source/CraftPresence/` |
| Crops NH | `cropsnh-2.0.140.jar` | 2.0.140 | exact | [GTNewHorizons/CropsNH](https://github.com/GTNewHorizons/CropsNH) | `2.0.140` (tag) | LGPL-3.0 | `gtnh-src/source/CropsNH/` |
| Custom-Main-Menu | `custommainmenu-1.14.1.jar` | 1.14.1 | exact | [GTNewHorizons/Custom-Main-Menu](https://github.com/GTNewHorizons/Custom-Main-Menu) | `1.14.1` (tag) | MIT | `gtnh-src/source/Custom-Main-Menu/` |
| Darkerer | `darkerer-1.1.0.jar` | 1.1.0 | exact | [GTNewHorizons/Darkerer](https://github.com/GTNewHorizons/Darkerer) | `1.1.0` (tag) | LGPL-3.0 | `gtnh-src/source/Darkerer/` |
| Default-Configs | `defaultkeys-1.3.4.jar` | 1.3.4 | exact | [GTNewHorizons/Default-Configs](https://github.com/GTNewHorizons/Default-Configs) | `1.3.4` (tag) | MIT | `gtnh-src/source/Default-Configs/` |
| DefaultServerList | `defaultserverlist-1.7.4.jar` | 1.7.4 | exact | [GTNewHorizons/DefaultServerList](https://github.com/GTNewHorizons/DefaultServerList) | `1.7.4` (tag) | LGPL-3.0 | `gtnh-src/source/DefaultServerList/` |
| DefaultWorldGenerator | `defaultworldgenerator-0.5.0.jar` | 0.5.0 | exact | [GTNewHorizons/DefaultWorldGenerator](https://github.com/GTNewHorizons/DefaultWorldGenerator) | `0.5.0` (tag) | MIT | `gtnh-src/source/DefaultWorldGenerator/` |
| Draconic Evolution | `Draconic-Evolution-1.5.35-GTNH.jar` | 1.5.35-GTNH | exact | [GTNewHorizons/Draconic-Evolution](https://github.com/GTNewHorizons/Draconic-Evolution) | `1.5.35-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/Draconic-Evolution/` |
| DummyCore | `DummyCore-1.21.0.jar` | 1.21.0 | exact | [GTNewHorizons/DummyCore](https://github.com/GTNewHorizons/DummyCore) | `1.21.0` (tag) | CC-BY-SA-4.0 | `gtnh-src/source/DummyCore/` |
| DuraDisplay | `duradisplay-1.4.7.jar` | 1.4.7 | exact | [GTNewHorizons/DuraDisplay](https://github.com/GTNewHorizons/DuraDisplay) | `1.4.7` (tag) | MIT | `gtnh-src/source/DuraDisplay/` |
| Electro-Magic Tools | `EMT-1.7.25.jar` | 1.7.25 | exact | [GTNewHorizons/Electro-Magic-Tools](https://github.com/GTNewHorizons/Electro-Magic-Tools) | `1.7.25` (tag) | GPL-3.0 | `gtnh-src/source/Electro-Magic-Tools/` |
| Ender IO | `EnderIO-2.10.51.jar` | 2.10.51 | exact | [GTNewHorizons/EnderIO](https://github.com/GTNewHorizons/EnderIO) | `2.10.51` (tag) | LGPL-3.0-or-later AND Unlicense | `gtnh-src/source/EnderIO/` |
| Ender Zoo | `EnderZoo-1.3.6.jar` | 1.3.6 | exact | [GTNewHorizons/EnderZoo](https://github.com/GTNewHorizons/EnderZoo) | `1.3.6` (tag) | CC0-1.0 | `gtnh-src/source/EnderZoo/` |
| EnderCore | `endercore-0.5.15.jar` | 0.5.15 | exact | [GTNewHorizons/EnderCore](https://github.com/GTNewHorizons/EnderCore) | `0.5.15` (tag) | CC0-1.0 | `gtnh-src/source/EnderCore/` |
| EnderStorage | `EnderStorage-1.8.9.jar` | 1.8.9 | exact | [GTNewHorizons/EnderStorage](https://github.com/GTNewHorizons/EnderStorage) | `1.8.9` (tag) | MIT | `gtnh-src/source/EnderStorage/` |
| EndlessIDs | `endlessids-mc1.7.10-1.7.4.jar` | 1.7.4 | exact | [GTMEGA/EndlessIDs](https://github.com/GTMEGA/EndlessIDs) | `1.7.4` (tag) | LGPL-3.0 | `gtnh-src/source/EndlessIDs/` |
| Enhanced LootBags | `EnhancedLootBags-1.3.5.jar` | 1.3.5 | exact | [GTNewHorizons/EnhancedLootBags](https://github.com/GTNewHorizons/EnhancedLootBags) | `1.3.5` (tag) | GPL-3.0 | `gtnh-src/source/EnhancedLootBags/` |
| Et Futurum Requiem | `etfuturum-2.6.65-GTNH.jar` | 2.6.65-GTNH | exact | [GTNewHorizons/Et-Futurum-Requiem](https://github.com/GTNewHorizons/Et-Futurum-Requiem) | `2.6.65-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/Et-Futurum-Requiem/` |
| Eternal Singularity | `eternalsingularity-1.4.3.jar` | 1.4.3 | exact | [GTNewHorizons/Eternal-Singularity](https://github.com/GTNewHorizons/Eternal-Singularity) | `1.4.3` (tag) | none | `gtnh-src/source/Eternal-Singularity/` |
| Expanded | `BaublesExpanded-2.2.27-GTNH.jar` | 2.2.27-GTNH | exact | [GTNewHorizons/Baubles-Expanded](https://github.com/GTNewHorizons/Baubles-Expanded) | `2.2.27-GTNH` (tag) | CC-BY-NC-SA-3.0 | `gtnh-src/source/Baubles-Expanded/` |
| Extra Utilities | `extrautilities-1.2.12.jar` | 1.2.12 | **none** |  |  | none |  |
| Extreme Sound Muffler | `esm-legacy-1.7.10-1.1.1.jar` | 1.1.1 | exact | [Lyfts/ExtremeSoundMuffler-Legacy](https://github.com/Lyfts/ExtremeSoundMuffler-Legacy) | `1.1.1` (tag) | LGPL-3.0 | `gtnh-src/source/ExtremeSoundMuffler-Legacy/` |
| FalsePatternLib | `falsepatternlib-mc1.7.10-1.12.2.jar` | 1.12.2 | exact | [FalsePattern/FalsePatternLib](https://github.com/FalsePattern/FalsePatternLib) | `1.12.2` (tag) | LGPL-3.0 | `gtnh-src/source/FalsePatternLib/` |
| Fether | `fether-2.0.9.jar` | 2.0.9 | exact | [GTNewHorizons/Fether](https://github.com/GTNewHorizons/Fether) | `2.0.9` (tag) | LGPL-3.0 | `gtnh-src/source/Fether/` |
| FindIt | `findit-1.4.8.jar` | 1.4.8 | exact | [GTNewHorizons/FindIt](https://github.com/GTNewHorizons/FindIt) | `1.4.8` (tag) | MIT | `gtnh-src/source/FindIt/` |
| Flood Lights | `FloodLights-1.5.6.jar` | 1.5.6 | exact | [GTNewHorizons/FloodLights](https://github.com/GTNewHorizons/FloodLights) | `1.5.6` (tag) | LGPL-3.0 | `gtnh-src/source/FloodLights/` |
| Forbidden Magic | `Forbidden.Magic-0.9.18-GTNH.jar` | 0.9.18-GTNH | exact | [GTNewHorizons/ForbiddenMagic](https://github.com/GTNewHorizons/ForbiddenMagic) | `0.9.18-GTNH` (tag) | WTFPL | `gtnh-src/source/ForbiddenMagic/` |
| Forestry | `Forestry-4.11.40.jar` | 4.11.40 | exact | [GTNewHorizons/ForestryMC](https://github.com/GTNewHorizons/ForestryMC) | `4.11.40` (tag) | LGPL-3.0 | `gtnh-src/source/ForestryMC/` |
| Forge Multipart | `ForgeMultipart-1.7.18.jar` | 1.7.18 | exact | [GTNewHorizons/ForgeMultipart](https://github.com/GTNewHorizons/ForgeMultipart) | `1.7.18` (tag) | LGPL-2.1-or-later | `gtnh-src/source/ForgeMultipart/` |
| Forgelin | `forgelin-2.0.3-GTNH.jar` | 2.0.3-GTNH | exact | [GTNewHorizons/Forgelin](https://github.com/GTNewHorizons/Forgelin) | `2.0.3-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/Forgelin/` |
| ForgeRelocation | `ForgeRelocation-0.3.7.jar` | 0.3.7 | exact | [GTNewHorizons/ForgeRelocation](https://github.com/GTNewHorizons/ForgeRelocation) | `0.3.7` (tag) | GPL-3.0 | `gtnh-src/source/ForgeRelocation/` |
| Freecam | `freecam-gtnh-1.0.12.jar` | 1.0.12 | exact | [GTNewHorizons/Freecam](https://github.com/GTNewHorizons/Freecam) | `1.0.12` (tag) | LGPL-3.0 | `gtnh-src/source/Freecam/` |
| Gadomancy | `gadomancy-1.5.17.jar` | 1.5.17 | exact | [GTNewHorizons/Gadomancy](https://github.com/GTNewHorizons/Gadomancy) | `1.5.17` (tag) | LGPL-3.0 | `gtnh-src/source/Gadomancy/` |
| Galacticraft Core | `Galacticraft-3.4.37-GTNH.jar` | 3.4.37-GTNH | exact | [GTNewHorizons/Galacticraft](https://github.com/GTNewHorizons/Galacticraft) | `3.4.37-GTNH` (tag) | LicenseRef-Galacticraft | `gtnh-src/source/Galacticraft/` |
| GalaxySpace | `GalaxySpace-1.1.144-GTNH.jar` | 1.1.144-GTNH | branch-head (upstream-divergent) | [BlesseNtumble/GalaxySpace](https://github.com/BlesseNtumble/GalaxySpace) | `dev_1.7.10` (branch) | none | `gtnh-src/source/GalaxySpace/` |
| Gendustry | `gendustry-1.9.13-GTNH.jar` | 1.9.13-GTNH | exact | [GTNewHorizons/gendustry](https://github.com/GTNewHorizons/gendustry) | `1.9.13-GTNH` (tag) | none | `gtnh-src/source/gendustry/` |
| Graviation Suite | `GraviSuite-1.7.10-2.0.3.jar` | 2.0.3 | **none** |  |  | none |  |
| Gravitation Suite Neo | `gravisuiteneo-1.3.16.jar` | 1.3.16 | exact | [GTNewHorizons/Gravitation-Suite-Neo](https://github.com/GTNewHorizons/Gravitation-Suite-Neo) | `1.3.16` (tag) | LGPL-3.0 | `gtnh-src/source/Gravitation-Suite-Neo/` |
| Gregory Tweaks For Crafting | `craftingtweaks-1.0.3.jar` | 1.0.3 | exact | [GTNewHorizons/GregoryTweaksForCrafting](https://github.com/GTNewHorizons/GregoryTweaksForCrafting) | `1.0.3` (tag) | LGPL-3.0 | `gtnh-src/source/GregoryTweaksForCrafting/` |
| GregTech | `gregtech-5.09.54.265.jar` | 5.09.54.265 | exact | [GTNewHorizons/GT5-Unofficial](https://github.com/GTNewHorizons/GT5-Unofficial) | `5.09.54.265` (tag) | LGPL-3.0 | `gtnh-src/source/GT5-Unofficial/` |
| GT: New Horizons | `GTNewHorizonsCoreMod-2.9.99.jar` | 2.9.99 | exact | [GTNewHorizons/NewHorizonsCoreMod](https://github.com/GTNewHorizons/NewHorizonsCoreMod) | `2.9.99` (tag) | GPL-3.0 | `gtnh-src/source/NewHorizonsCoreMod/` |
| GTNH Lib | `gtnhlib-0.11.54.jar` | 0.11.54 | exact | [GTNewHorizons/GTNHLib](https://github.com/GTNewHorizons/GTNHLib) | `0.11.54` (tag) | LGPL-3.0 | `gtnh-src/source/GTNHLib/` |
| GTNH-Credits | `gtnhcredits-1.4.0.jar` | 1.4.0 | exact | [GTNewHorizons/GTNH-Credits](https://github.com/GTNewHorizons/GTNH-Credits) | `1.4.0` (tag) | MIT | `gtnh-src/source/GTNH-Credits/` |
| GTNH-TC-Wands | `GTNH-TC-Wands-1.4.14.jar` | 1.4.14 | exact | [GTNewHorizons/GTNH-TC-Wands](https://github.com/GTNewHorizons/GTNH-TC-Wands) | `1.4.14` (tag) | WTFPL | `gtnh-src/source/GTNH-TC-Wands/` |
| GTNHExtLib | `gtnhextlib-1.0.5.jar` | 1.0.5 | exact | [GTNewHorizons/GTNHExtLib](https://github.com/GTNewHorizons/GTNHExtLib) | `1.0.5` (tag) | LGPL-3.0 | `gtnh-src/source/GTNHExtLib/` |
| GTTweaker | `GTTweaker-2.3.4.jar` | 2.3.4 | exact | [GTNewHorizons/Minetweaker-Gregtech-5-Addon](https://github.com/GTNewHorizons/Minetweaker-Gregtech-5-Addon) | `2.3.4` (tag) | GPL-3.0 | `gtnh-src/source/Minetweaker-Gregtech-5-Addon/` |
| GuideNH | `guidenh-1.3.55.jar` | 1.3.55 | exact | [GTNewHorizons/GuideNH](https://github.com/GTNewHorizons/GuideNH) | `1.3.55` (tag) | LGPL-3.0 | `gtnh-src/source/GuideNH/` |
| Hardcore Ender Expansion | `HardcoreEnderExpansion-1.12.29-GTNH.jar` | 1.12.29-GTNH | exact | [GTNewHorizons/Hardcore-Ender-Expansion](https://github.com/GTNewHorizons/Hardcore-Ender-Expansion) | `1.12.29-GTNH` (tag) | none | `gtnh-src/source/Hardcore-Ender-Expansion/` |
| Healer | `Healer-1.2.1.jar` | 1.2.1 | exact | [Glease/Healer](https://github.com/Glease/Healer) | `1.2.1` (tag) | MIT | `gtnh-src/source/Healer/` |
| HelpFixer | `HelpFixer-1.3.2.jar` | 1.3.2 | exact | [GTNewHorizons/HelpFixer](https://github.com/GTNewHorizons/HelpFixer) | `1.3.2` (tag) | WTFPL | `gtnh-src/source/HelpFixer/` |
| Hodgepodge | `hodgepodge-2.7.221.jar` | 2.7.221 | exact | [GTNewHorizons/Hodgepodge](https://github.com/GTNewHorizons/Hodgepodge) | `2.7.221` (tag) | LGPL-3.0 | `gtnh-src/source/Hodgepodge/` |
| Holo Inventory | `holoinventory-2.5.18-GTNH.jar` | 2.5.18-GTNH | exact | [GTNewHorizons/HoloInventory](https://github.com/GTNewHorizons/HoloInventory) | `2.5.18-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/HoloInventory/` |
| Hunger Overhaul | `HungerOverhaul-1.7.10-1.0.0.jenkins104.jar` | 1.0.0.104 | branch-head | [progwml6/HungerOverhaul](https://github.com/progwml6/HungerOverhaul) | `master` (branch) | none | `gtnh-src/source/HungerOverhaul/` |
| HydroEnergy | `hydroenergy-1.4.26.jar` | 1.4.26 | exact | [GTNewHorizons/HydroEnergy](https://github.com/GTNewHorizons/HydroEnergy) | `1.4.26` (tag) | MIT | `gtnh-src/source/HydroEnergy/` |
| I Will Find You | `ifu-1.12.4.jar` | 1.12.4 | exact | [GTNewHorizons/IFU](https://github.com/GTNewHorizons/IFU) | `1.12.4` (tag) | LGPL-3.0 | `gtnh-src/source/IFU/` |
| Iguana Tinker Tweaks | `IguanaTweaksTConstruct-2.7.15.jar` | 2.7.15 | exact | [GTNewHorizons/IguanaTweaksTConstruct](https://github.com/GTNewHorizons/IguanaTweaksTConstruct) | `2.7.15` (tag) | CC-BY-SA-4.0 | `gtnh-src/source/IguanaTweaksTConstruct/` |
| IndustrialCraft 2 | `industrialcraft-2-2.2.828-experimental.jar` | 2.2.2.828 | **none** |  |  | none |  API: `gtnh-src/source/IC2-API/` |
| Infernal Mobs | `InfernalMobs-1.10.7-GTNH.jar` | 1.10.7-GTNH | exact | [GTNewHorizons/Infernal-Mobs](https://github.com/GTNewHorizons/Infernal-Mobs) | `1.10.7-GTNH` (tag) | LicenseRef-AtomicStryker | `gtnh-src/source/Infernal-Mobs/` |
| InGame Info XML | `InGameInfoXML-2.9.8.jar` | 2.9.8 | exact | [GTNewHorizons/InGame-Info-XML](https://github.com/GTNewHorizons/InGame-Info-XML) | `2.9.8` (tag) | MIT | `gtnh-src/source/InGame-Info-XML/` |
| Inventory Bogo Sorter | `bogosorter-1.3.55-GTNH.jar` | 1.3.55-GTNH | exact | [GTNewHorizons/InventoryBogoSorter](https://github.com/GTNewHorizons/InventoryBogoSorter) | `1.3.55-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/InventoryBogoSorter/` |
| Iron Chest Minecarts | `IronChestMinecarts-1.2.1.jar` | 1.2.1 | exact | [GTNewHorizons/IronChestMinecarts](https://github.com/GTNewHorizons/IronChestMinecarts) | `1.2.1` (tag) | none | `gtnh-src/source/IronChestMinecarts/` |
| Iron Chests | `IronChest-6.1.13.jar` | 6.1.13 | exact | [GTNewHorizons/ironchest](https://github.com/GTNewHorizons/ironchest) | `6.1.13` (tag) | GPL-3.0 | `gtnh-src/source/ironchest/` |
| Iron Tank Minecarts | `irontankminecarts-1.0.12.jar` | 1.0.12 | exact | [GTNewHorizons/IronTankMinecarts](https://github.com/GTNewHorizons/IronTankMinecarts) | `1.0.12` (tag) | MIT | `gtnh-src/source/IronTankMinecarts/` |
| Iron Tanks | `irontanks-1.4.7.jar` | 1.4.7 | exact | [GTNewHorizons/Irontanks](https://github.com/GTNewHorizons/Irontanks) | `1.4.7` (tag) | MIT | `gtnh-src/source/Irontanks/` |
| JABBA | `JABBA-1.5.24.jar` | 1.5.24 | exact | [GTNewHorizons/Jabba](https://github.com/GTNewHorizons/Jabba) | `1.5.24` (tag) | CC-BY-NC-SA-4.0 | `gtnh-src/source/Jabba/` |
| JarJar | `jarjar-0.3.7-beta.jar` | 0.3.7-beta | exact | [GTNewHorizons/JarJar](https://github.com/GTNewHorizons/JarJar) | `0.3.7-beta` (tag) | LGPL-3.0 | `gtnh-src/source/JarJar/` |
| JourneyMap | `journeymap-1.7.10-5.2.23-fairplay.jar` | 5.2.23-fairplay | exact | [TeamJM/journeymap-legacy](https://github.com/TeamJM/journeymap-legacy) | `5.2.23` (tag) | LGPL-2.1 | `gtnh-src/source/journeymap-legacy/` |
| JourneyMapServer | `JourneyMapServer1.0.5_MC1.7.10.jar` | 1.0.5 | **none** |  |  | none |  |
| LittleTiles | `littletiles-1.6.63.jar` | 1.6.63 | exact | [GTNewHorizons/LittleTiles](https://github.com/GTNewHorizons/LittleTiles) | `1.6.63` (tag) | GPL-3.0 | `gtnh-src/source/LittleTiles/` |
| Logistics Pipes | `logisticspipes-1.5.39-GTNH.jar` | 1.5.39-GTNH | exact | [GTNewHorizons/LogisticsPipes](https://github.com/GTNewHorizons/LogisticsPipes) | `1.5.39-GTNH` (tag) | LicenseRef-MMPL-1.0 | `gtnh-src/source/LogisticsPipes/` |
| LootGames | `lootgames-2.2.14.jar` | 2.2.14 | exact | [GTNewHorizons/LootGames](https://github.com/GTNewHorizons/LootGames) | `2.2.14` (tag) | LicenseRef-ARR | `gtnh-src/source/LootGames/` |
| LunatriusCore | `LunatriusCore-1.2.1-GTNH.jar` | 1.2.1-GTNH | exact | [GTNewHorizons/LunatriusCore](https://github.com/GTNewHorizons/LunatriusCore) | `1.2.1-GTNH` (tag) | MIT | `gtnh-src/source/LunatriusCore/` |
| lwjgl3ify | `lwjgl3ify-3.0.42.jar` | 3.0.42 | exact | [GTNewHorizons/lwjgl3ify](https://github.com/GTNewHorizons/lwjgl3ify) | `3.0.42` (tag) | LGPL-3.0 | `gtnh-src/source/lwjgl3ify/` |
| Magic Bees | `magicbees-2.10.13-GTNH.jar` | 2.10.13-GTNH | exact | [GTNewHorizons/MagicBees](https://github.com/GTNewHorizons/MagicBees) | `2.10.13-GTNH` (tag) | WTFPL | `gtnh-src/source/MagicBees/` |
| Malisis' Doors | `malisisdoors-1.19.13-GTNH.jar` | 1.19.13-GTNH | exact | [GTNewHorizons/MalisisDoors](https://github.com/GTNewHorizons/MalisisDoors) | `1.19.13-GTNH` (tag) | MIT | `gtnh-src/source/MalisisDoors/` |
| Mantle | `Mantle-0.5.4.jar` | 0.5.4 | exact | [GTNewHorizons/Mantle](https://github.com/GTNewHorizons/Mantle) | `0.5.4` (tag) | none | `gtnh-src/source/Mantle/` |
| Matter Manipulator | `matter-manipulator-0.1.75-GTNH.jar` | 0.1.75-GTNH | exact | [GTNewHorizons/MatterManipulator](https://github.com/GTNewHorizons/MatterManipulator) | `0.1.75-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/MatterManipulator/` |
| Mine & Blade Battlegear 2 | `battlegear2-1.6.8-backhand.jar` | 1.6.8-backhand | exact | [GTNewHorizons/Battlegear2-for-Backhand](https://github.com/GTNewHorizons/Battlegear2-for-Backhand) | `1.6.8-backhand` (tag) | GPL-3.0 | `gtnh-src/source/Battlegear2-for-Backhand/` |
| MineTweaker 3 | `CraftTweaker-3.4.8.jar` | 3.4.8 | exact | [GTNewHorizons/CraftTweaker](https://github.com/GTNewHorizons/CraftTweaker) | `3.4.8` (tag) | none | `gtnh-src/source/CraftTweaker/` |
| MobsInfo | `mobsinfo-0.6.2.jar` | 0.6.2 | exact | [kuba6000/Mobs-Info](https://github.com/kuba6000/Mobs-Info) | `0.6.2` (tag) | LGPL-3.0 | `gtnh-src/source/Mobs-Info/` |
| Mod Tweaker 2 | `ModTweaker2-0.14.0.jar` | 0.14.0 | exact | [GTNewHorizons/ModTweaker](https://github.com/GTNewHorizons/ModTweaker) | `0.14.0` (tag) | MIT | `gtnh-src/source/ModTweaker/` |
| ModernMarkings | `modernmarkings-0.3.13-1.7.10.jar` | 0.3.13-1.7.10 | exact | [GTNewHorizons/ModernMarkings](https://github.com/GTNewHorizons/ModernMarkings) | `0.3.13-1.7.10` (tag) | GPL-3.0 | `gtnh-src/source/ModernMarkings/` |
| Modular UI 2 | `modularui2-2.3.94-1.7.10.jar` | 2.3.94-1.7.10 | exact | [GTNewHorizons/ModularUI2](https://github.com/GTNewHorizons/ModularUI2) | `2.3.94-1.7.10` (tag) | LGPL-3.0 | `gtnh-src/source/ModularUI2/` |
| ModularUI | `modularui-1.3.4.jar` | 1.3.4 | exact | [GTNewHorizons/ModularUI](https://github.com/GTNewHorizons/ModularUI) | `1.3.4` (tag) | LGPL-3.0 | `gtnh-src/source/ModularUI/` |
| MouseTweaks | `MouseTweaks-2.5.4-GTNH.jar` | 2.5.4-GTNH | exact | [GTNewHorizons/MouseTweaks](https://github.com/GTNewHorizons/MouseTweaks) | `2.5.4-GTNH` (tag) | BSD-3-Clause | `gtnh-src/source/MouseTweaks/` |
| MrTJPCore | `MrTJPCore-1.3.7.jar` | 1.3.7 | exact | [GTNewHorizons/MrTJPCore](https://github.com/GTNewHorizons/MrTJPCore) | `1.3.7` (tag) | LGPL-3.0 | `gtnh-src/source/MrTJPCore/` |
| Natura | `Natura-2.8.24.jar` | 2.8.24 | exact | [GTNewHorizons/Natura](https://github.com/GTNewHorizons/Natura) | `2.8.24` (tag) | LGPL-3.0 | `gtnh-src/source/Natura/` |
| Nature's Compass | `naturescompass-1.5.2-GTNH.jar` | 1.5.2-GTNH | exact | [GTNewHorizons/NaturesCompass](https://github.com/GTNewHorizons/NaturesCompass) | `1.5.2-GTNH` (tag) | CC-BY-NC-SA-4.0 | `gtnh-src/source/NaturesCompass/` |
| Navigator | `navigator-1.1.10.jar` | 1.1.10 | exact | [GTNewHorizons/Navigator](https://github.com/GTNewHorizons/Navigator) | `1.1.10` (tag) | LGPL-3.0 | `gtnh-src/source/Navigator/` |
| NEI Custom Diagram | `NEICustomDiagram-1.8.36.jar` | 1.8.36 | exact | [GTNewHorizons/nei-custom-diagram](https://github.com/GTNewHorizons/nei-custom-diagram) | `1.8.36` (tag) | LGPL-3.0 | `gtnh-src/source/nei-custom-diagram/` |
| NEIIntegration | `NEIIntegration-1.5.3.jar` | 1.5.3 | exact | [GTNewHorizons/NEI-Integration](https://github.com/GTNewHorizons/NEI-Integration) | `1.5.3` (tag) | LGPL-3.0 | `gtnh-src/source/NEI-Integration/` |
| Nether Portal Fix | `netherportalfix-1.4.0.jar` | 1.4.0 | exact | [GTNewHorizons/NetherPortalFix](https://github.com/GTNewHorizons/NetherPortalFix) | `1.4.0` (tag) | MIT | `gtnh-src/source/NetherPortalFix/` |
| NodalMechanics | `NodalMechanics-1.3.4-GTNH.jar` | 1.3.4-GTNH | exact | [GTNewHorizons/Nodal-Mechanics](https://github.com/GTNewHorizons/Nodal-Mechanics) | `1.3.4-GTNH` (tag) | none | `gtnh-src/source/Nodal-Mechanics/` |
| NoHotbarNeeded | `nohotbarneeded-0.0.6.jar` | 0.0.6 | exact | [GTNewHorizons/NoHotbarNeeded](https://github.com/GTNewHorizons/NoHotbarNeeded) | `0.0.6` (tag) | MIT | `gtnh-src/source/NoHotbarNeeded/` |
| NotEnoughEnergistics | `NotEnoughEnergistics-1.7.50.jar` | 1.7.50 | exact | [GTNewHorizons/NotEnoughEnergistics](https://github.com/GTNewHorizons/NotEnoughEnergistics) | `1.7.50` (tag) | MIT | `gtnh-src/source/NotEnoughEnergistics/` |
| NotEnoughItems | `NotEnoughItems-2.8.171-GTNH.jar` | 2.8.171-GTNH | exact | [GTNewHorizons/NotEnoughItems](https://github.com/GTNewHorizons/NotEnoughItems) | `2.8.171-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/NotEnoughItems/` |
| Nuclear Control 2 | `IC2NuclearControl-2.7.17.jar` | 2.7.17 | exact | [GTNewHorizons/Nuclear-Control](https://github.com/GTNewHorizons/Nuclear-Control) | `2.7.17` (tag) | LGPL-3.0 | `gtnh-src/source/Nuclear-Control/` |
| Nutrition | `nutrition-1.0.1.jar` | 1.0.1 | exact | [GTNewHorizons/Nutrition](https://github.com/GTNewHorizons/Nutrition) | `1.0.1` (tag) | LGPL-3.0 | `gtnh-src/source/Nutrition/` |
| oauth | `oauth-1.3.4-GTNH.jar` | 1.3.4-GTNH | exact | [GTNewHorizons/oauth](https://github.com/GTNewHorizons/oauth) | `1.3.4-GTNH` (tag) | GPL-3.0 | `gtnh-src/source/oauth/` |
| OC Glasses | `OpenGlasses-1.6.9-GTNH.jar` | 1.6.9-GTNH | exact | [GTNewHorizons/OCGlasses](https://github.com/GTNewHorizons/OCGlasses) | `1.6.9-GTNH` (tag) | MIT | `gtnh-src/source/OCGlasses/` |
| Open Modular Turrets | `OpenModularTurrets-2.4.8.jar` | 2.4.8 | exact | [GTNewHorizons/OpenModularTurrets](https://github.com/GTNewHorizons/OpenModularTurrets) | `2.4.8` (tag) | GPL-3.0 | `gtnh-src/source/OpenModularTurrets/` |
| OpenBlocks | `OpenBlocks-1.12.22-GTNH.jar` | 1.12.22-GTNH | exact | [GTNewHorizons/OpenBlocks](https://github.com/GTNewHorizons/OpenBlocks) | `1.12.22-GTNH` (tag) | MIT | `gtnh-src/source/OpenBlocks/` |
| OpenComputers | `OpenComputers-1.12.68-GTNH.jar` | 1.12.68-GTNH | exact | [GTNewHorizons/OpenComputers](https://github.com/GTNewHorizons/OpenComputers) | `1.12.68-GTNH` (tag) | MIT | `gtnh-src/source/OpenComputers/` |
| OpenMods | `OpenModsLibs-0.10.15.jar` | 0.10.15 | exact | [GTNewHorizons/OpenModsLib](https://github.com/GTNewHorizons/OpenModsLib) | `0.10.15` (tag) | MIT | `gtnh-src/source/OpenModsLib/` |
| OpenPrinter | `openprinter-0.3.1-GTNH.jar` | 0.3.1-GTNH | exact | [GTNewHorizons/OpenPrinter](https://github.com/GTNewHorizons/OpenPrinter) | `0.3.1-GTNH` (tag) | MIT | `gtnh-src/source/OpenPrinter/` |
| OpenSecurity | `opensecurity-1.2.2-GTNH.jar` | 1.2.2-GTNH | exact | [GTNewHorizons/OpenSecurity](https://github.com/GTNewHorizons/OpenSecurity) | `1.2.2-GTNH` (tag) | MIT | `gtnh-src/source/OpenSecurity/` |
| Opis | `Opis-1.4.12-mapless.jar` | 1.4.12-mapless | exact | [GTNewHorizons/Opis](https://github.com/GTNewHorizons/Opis) | `1.4.12-mapless` (tag) | CC-BY-NC-SA-4.0 | `gtnh-src/source/Opis/` |
| OverloadedArmorBar | `overloadedarmorbar-1.1.1.jar` | 1.1.1 | exact | [GTNewHorizons/OverloadedArmorBar](https://github.com/GTNewHorizons/OverloadedArmorBar) | `1.1.1` (tag) | MIT | `gtnh-src/source/OverloadedArmorBar/` |
| Pam's HarvestCraft | `harvestcraft-1.3.15-GTNH.jar` | 1.3.15-GTNH | **none** |  |  | none |  |
| PersonalSpace | `personalspace-1.0.41.jar` | 1.0.41 | exact | [GTNewHorizons/PersonalSpace](https://github.com/GTNewHorizons/PersonalSpace) | `1.0.41` (tag) | LGPL-3.0 | `gtnh-src/source/PersonalSpace/` |
| Player API | `PlayerAPI-1.5.0.jar` | 1.5.0 | exact | [GTNewHorizons/Player-API](https://github.com/GTNewHorizons/Player-API) | `1.5.0` (tag) | LGPL-3.0 | `gtnh-src/source/Player-API/` |
| Postea | `postea-1.2.7.jar` | 1.2.7 | exact | [GTNewHorizons/Postea](https://github.com/GTNewHorizons/Postea) | `1.2.7` (tag) | MIT | `gtnh-src/source/Postea/` |
| Project Blue | `ProjectBlue-1.2.11-GTNH.jar` | 1.2.11-GTNH | exact | [GTNewHorizons/ProjectBlue](https://github.com/GTNewHorizons/ProjectBlue) | `1.2.11-GTNH` (tag) | LicenseRef-Permissive-Custom | `gtnh-src/source/ProjectBlue/` |
| Railcraft | `Railcraft-9.17.36.jar` | 9.17.36 | exact | [GTNewHorizons/Railcraft](https://github.com/GTNewHorizons/Railcraft) | `9.17.36` (tag) | LicenseRef-Railcraft | `gtnh-src/source/Railcraft/` |
| Random Boubles | `randomboubles-1.1.7.jar` | 1.1.7 | exact | [GTNewHorizons/RandomBoubles](https://github.com/GTNewHorizons/RandomBoubles) | `1.1.7` (tag) | LGPL-3.0 | `gtnh-src/source/RandomBoubles/` |
| RandomThings | `RandomThings-2.7.13.jar` | 2.7.13 | exact | [GTNewHorizons/Random-Things](https://github.com/GTNewHorizons/Random-Things) | `2.7.13` (tag) | LGPL-3.0 | `gtnh-src/source/Random-Things/` |
| Realistic World Gen Alpha | `RWG-alpha-1.5.3.jar` | alpha-1.5.3 | exact | [GTNewHorizons/Realistic-World-Gen](https://github.com/GTNewHorizons/Realistic-World-Gen) | `alpha-1.5.3` (tag) | GPL-3.0 | `gtnh-src/source/Realistic-World-Gen/` |
| Realistic World Gen RC1 | `rwg2-2.0.6.jar` | 2.0.6 | exact | [GTNewHorizons/Realistic-World-Gen-2](https://github.com/GTNewHorizons/Realistic-World-Gen-2) | `2.0.6` (tag) | GPL-3.0 | `gtnh-src/source/Realistic-World-Gen-2/` |
| RelocationFMP | `ForgeRelocationFMP-0.2.0.jar` | 0.2.0 | exact | [GTNewHorizons/ForgeRelocationFMP](https://github.com/GTNewHorizons/ForgeRelocationFMP) | `0.2.0` (tag) | GPL-3.0 | `gtnh-src/source/ForgeRelocationFMP/` |
| RemoteIO | `RemoteIO-2.7.11.jar` | 2.7.11 | exact | [GTNewHorizons/RemoteIO](https://github.com/GTNewHorizons/RemoteIO) | `2.7.11` (tag) | MIT | `gtnh-src/source/RemoteIO/` |
| Roguelike Dungeons | `roguelike-1.6.6-GTNH.jar` | 1.6.6-GTNH | exact | [GTNewHorizons/Roguelike-Dungeons](https://github.com/GTNewHorizons/Roguelike-Dungeons) | `1.6.6-GTNH` (tag) | GPL-3.0 | `gtnh-src/source/Roguelike-Dungeons/` |
| Salis Arcana | `salisarcana-v2.7.0.jar` | 2.7.0 | exact | [rndmorris/Salis-Arcana](https://github.com/rndmorris/Salis-Arcana) | `v2.7.0` (tag) | LGPL-3.0 | `gtnh-src/source/Salis-Arcana/` |
| Schematica | `Schematica-1.12.6-GTNH.jar` | 1.12.6-GTNH | exact | [GTNewHorizons/Schematica](https://github.com/GTNewHorizons/Schematica) | `1.12.6-GTNH` (tag) | MIT | `gtnh-src/source/Schematica/` |
| ServerUtilities | `ServerUtilities-2.4.22.jar` | 2.4.22 | exact | [GTNewHorizons/ServerUtilities](https://github.com/GTNewHorizons/ServerUtilities) | `2.4.22` (tag) | LGPL-3.0 | `gtnh-src/source/ServerUtilities/` |
| SG Craft | `SGCraft-1.4.14-GTNH.jar` | 1.4.14-GTNH | exact | [GTNewHorizons/SGCraft](https://github.com/GTNewHorizons/SGCraft) | `1.4.14-GTNH` (tag) | MIT | `gtnh-src/source/SGCraft/` |
| Share Where I am | `sharewhereiam-2.1.11.jar` | 2.1.11 | exact | [GTNewHorizons/Share-Where-I-am](https://github.com/GTNewHorizons/Share-Where-I-am) | `2.1.11` (tag) | MIT | `gtnh-src/source/Share-Where-I-am/` |
| SimpleSkinBackport | `simpleskinbackport-1.0.5-GTNH.jar` | 1.0.5-GTNH | exact | [GTNewHorizons/SimpleSkinBackport](https://github.com/GTNewHorizons/SimpleSkinBackport) | `1.0.5-GTNH` (tag) | MIT | `gtnh-src/source/SimpleSkinBackport/` |
| Sleeping Bag | `sleepingbag-0.3.1.jar` | 0.3.1 | exact | [GTNewHorizons/SleepingBags](https://github.com/GTNewHorizons/SleepingBags) | `0.3.1` (tag) | LGPL-3.0 | `gtnh-src/source/SleepingBags/` |
| Special Mobs | `SpecialMobs-3.7.10.jar` | 3.7.10 | exact | [GTNewHorizons/SpecialMobs](https://github.com/GTNewHorizons/SpecialMobs) | `3.7.10` (tag) | LicenseRef-ARR | `gtnh-src/source/SpecialMobs/` |
| Steve's Addons | `StevesAddons-0.15.5.jar` | 0.15.5 | exact | [GTNewHorizons/StevesAddons](https://github.com/GTNewHorizons/StevesAddons) | `0.15.5` (tag) | LicenseRef-ARR | `gtnh-src/source/StevesAddons/` |
| Steve's Carts 2 | `StevesCarts-2.3.15.jar` | 2.3.15 | exact | [GTNewHorizons/SC2](https://github.com/GTNewHorizons/SC2) | `2.3.15` (tag) | MIT | `gtnh-src/source/SC2/` |
| Steve's Factory Manager | `StevesFactoryManager-1.3.13-GTNH.jar` | 1.3.13-GTNH | exact | [GTNewHorizons/Steve-s-Factory-Manager](https://github.com/GTNewHorizons/Steve-s-Factory-Manager) | `1.3.13-GTNH` (tag) | LicenseRef-Vswe-Permissive | `gtnh-src/source/Steve-s-Factory-Manager/` |
| Storage Drawers | `StorageDrawers-2.2.31-GTNH.jar` | 2.2.31-GTNH | exact | [GTNewHorizons/StorageDrawers](https://github.com/GTNewHorizons/StorageDrawers) | `2.2.31-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/StorageDrawers/` |
| StructureCompat | `structurecompat-0.7.5.jar` | 0.7.5 | exact | [GTNewHorizons/StructureCompat](https://github.com/GTNewHorizons/StructureCompat) | `0.7.5` (tag) | AGPL-3.0 | `gtnh-src/source/StructureCompat/` |
| StructureLib | `structurelib-1.4.47.jar` | 1.4.47 | exact | [GTNewHorizons/StructureLib](https://github.com/GTNewHorizons/StructureLib) | `1.4.47` (tag) | LGPL-3.0 | `gtnh-src/source/StructureLib/` |
| Super Solar Panel | `supersolarpanel-1.1.5.jar` | 1.1.5 | exact | [GTNewHorizons/supersolarpanels](https://github.com/GTNewHorizons/supersolarpanels) | `1.1.5` (tag) | none | `gtnh-src/source/supersolarpanels/` |
| SuperTic | `SuperTic-1.5.6.jar` | 1.5.6 | exact | [GTNewHorizons/Super-TiC](https://github.com/GTNewHorizons/Super-TiC) | `1.5.6` (tag) | LGPL-3.0 | `gtnh-src/source/Super-TiC/` |
| Tainted Magic | `Tainted-Magic-7.7.8-GTNH.jar` | 7.7.8-GTNH | exact | [GTNewHorizons/Tainted-Magic](https://github.com/GTNewHorizons/Tainted-Magic) | `7.7.8-GTNH` (tag) | CC-BY-NC-ND-4.0 | `gtnh-src/source/Tainted-Magic/` |
| TC4 Tweak | `Thaumcraft4Tweaks-1.5.48.jar` | 1.5.48 | exact | [Glease/TC4Tweaks](https://github.com/Glease/TC4Tweaks) | `1.5.48` (tag) | AGPL-3.0 | `gtnh-src/source/TC4Tweaks/` |
| TCNodeTracker | `tcnodetracker-1.4.6.jar` | 1.4.6 | exact | [GTNewHorizons/TCNodeTracker](https://github.com/GTNewHorizons/TCNodeTracker) | `1.4.6` (tag) | CC-BY-NC-SA-4.0 | `gtnh-src/source/TCNodeTracker/` |
| Thaumcraft | `Thaumcraft-1.7.10-4.2.3.5.jar` | 4.2.3.5 | **none** |  |  | none |  API: `gtnh-src/source/thaumcraft-api/` |
| Thaumcraft Mob Aspects | `ThaumcraftMobAspects-1.2.1-GTNH.jar` | 1.2.1-GTNH | exact | [GTNewHorizons/ThaumcraftMobAspects](https://github.com/GTNewHorizons/ThaumcraftMobAspects) | `1.2.1-GTNH` (tag) | Unlicense | `gtnh-src/source/ThaumcraftMobAspects/` |
| Thaumcraft Research Tweaks | `ThaumcraftResearchTweaks-1.4.1.jar` | 1.4.1 | exact | [GTNewHorizons/thaumcraft-research-tweaks](https://github.com/GTNewHorizons/thaumcraft-research-tweaks) | `1.4.1` (tag) | MIT | `gtnh-src/source/thaumcraft-research-tweaks/` |
| Thaumic Bases | `Thaumic-Based-1.9.22.jar` | 1.9.22 | exact | [GTNewHorizons/ThaumicBases](https://github.com/GTNewHorizons/ThaumicBases) | `1.9.22` (tag) | CC0-1.0 | `gtnh-src/source/ThaumicBases/` |
| Thaumic Boots | `thaumicboots-1.5.13.jar` | 1.5.13 | exact | [GTNewHorizons/ThaumicBoots](https://github.com/GTNewHorizons/ThaumicBoots) | `1.5.13` (tag) | MIT | `gtnh-src/source/ThaumicBoots/` |
| Thaumic Energistics | `thaumicenergistics-1.7.68-GTNH.jar` | 1.7.68-GTNH | exact | [GTNewHorizons/ThaumicEnergistics](https://github.com/GTNewHorizons/ThaumicEnergistics) | `1.7.68-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/ThaumicEnergistics/` |
| Thaumic Exploration | `Thaumic-Exploration-1.5.29-GTNH.jar` | 1.5.29-GTNH | exact | [GTNewHorizons/Thaumic_Exploration](https://github.com/GTNewHorizons/Thaumic_Exploration) | `1.5.29-GTNH` (tag) | CC-BY-NC-SA-4.0 | `gtnh-src/source/Thaumic_Exploration/` |
| Thaumic Insurgence | `thaumicinsurgence-0.4.1.jar` | 0.4.1 | exact | [GTNewHorizons/thaumicinsurgence](https://github.com/GTNewHorizons/thaumicinsurgence) | `0.4.1` (tag) | GPL-3.0 | `gtnh-src/source/thaumicinsurgence/` |
| Thaumic Machina | `ThaumicMachina-0.2.6-GTNH.jar` | 0.2.6-GTNH | exact | [GTNewHorizons/ThaumicMachina](https://github.com/GTNewHorizons/ThaumicMachina) | `0.2.6-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/ThaumicMachina/` |
| Thaumic Tinkerer | `ThaumicTinkerer-2.12.34.jar` | 2.12.34 | exact | [GTNewHorizons/ThaumicTinkerer](https://github.com/GTNewHorizons/ThaumicTinkerer) | `2.12.34` (tag) | CC-BY-NC-SA-3.0 | `gtnh-src/source/ThaumicTinkerer/` |
| ThaumicHorizons | `ThaumicHorizons-1.8.28.jar` | 1.8.28 | exact | [GTNewHorizons/ThaumicHorizons](https://github.com/GTNewHorizons/ThaumicHorizons) | `1.8.28` (tag) | LGPL-3.0 | `gtnh-src/source/ThaumicHorizons/` |
| The Spice of Life - Carrot Edition | `SpiceOfLife-2.2.12-carrot.jar` | 2.2.12-carrot | exact | [GTNewHorizons/SpiceOfLife](https://github.com/GTNewHorizons/SpiceOfLife) | `2.2.12-carrot` (tag) | LGPL-3.0 | `gtnh-src/source/SpiceOfLife/` |
| The Twilight Forest | `TwilightForest-2.7.45.jar` | 2.7.45 | exact | [GTNewHorizons/twilightforest](https://github.com/GTNewHorizons/twilightforest) | `2.7.45` (tag) | LGPL-2.1 | `gtnh-src/source/twilightforest/` |
| TiC-Tooltips | `TiCTooltips-1.4.2.jar` | 1.4.2 | exact | [GTNewHorizons/TiC-Tooltips](https://github.com/GTNewHorizons/TiC-Tooltips) | `1.4.2` (tag) | Unlicense | `gtnh-src/source/TiC-Tooltips/` |
| Tinkers Defense | `tinkersdefense-1.3.4.jar` | 1.3.4 | exact | [GTNewHorizons/Tinkers-Defense](https://github.com/GTNewHorizons/Tinkers-Defense) | `1.3.4` (tag) | GPL-3.0 | `gtnh-src/source/Tinkers-Defense/` |
| Tinkers Mechworks | `TMechworks-0.4.2.jar` | 0.4.2 | exact | [GTNewHorizons/TinkersMechworks](https://github.com/GTNewHorizons/TinkersMechworks) | `0.4.2` (tag) | MIT | `gtnh-src/source/TinkersMechworks/` |
| Tinkers' Construct | `TConstruct-1.14.123-GTNH.jar` | 1.14.123-GTNH | exact | [GTNewHorizons/TinkersConstruct](https://github.com/GTNewHorizons/TinkersConstruct) | `1.14.123-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/TinkersConstruct/` |
| Tinkers' Gregworks | `TGregworks-1.7.10-GTNH-1.0.34.jar` | 1.0.34 | exact | [GTNewHorizons/TinkersGregworks](https://github.com/GTNewHorizons/TinkersGregworks) | `GTNH-1.0.34` (tag) | LicenseRef-Calclavia-Educational | `gtnh-src/source/TinkersGregworks/` |
| TooMuchLoot | `TooMuchLoot-4.3.0-GTNH.jar` | 4.3.0-GTNH | exact | [GTNewHorizons/TooMuchLoot](https://github.com/GTNewHorizons/TooMuchLoot) | `4.3.0-GTNH` (tag) | MIT | `gtnh-src/source/TooMuchLoot/` |
| ToroHealth | `torohealth-1.2.4.jar` | 1.2.4 | exact | [GTNewHorizons/ToroHealth](https://github.com/GTNewHorizons/ToroHealth) | `1.2.4` (tag) | GPL-3.0 | `gtnh-src/source/ToroHealth/` |
| Translocator | `Translocator-1.4.5.jar` | 1.4.5 | exact | [GTNewHorizons/Translocators](https://github.com/GTNewHorizons/Translocators) | `1.4.5` (tag) | LGPL-3.0 | `gtnh-src/source/Translocators/` |
| TX-Loader | `txloader-1.9.1.jar` | 1.9.1 | exact | [GTNewHorizons/TX-Loader](https://github.com/GTNewHorizons/TX-Loader) | `1.9.1` (tag) | LGPL-3.0 | `gtnh-src/source/TX-Loader/` |
| UniLib | `UniLib-1.2.1+1.7.10-forge.jar` | 1.2.1 | exact | [CDAGaming/UniLib](https://gitlab.com/CDAGaming/UniLib) | `be764a9afa` (commit) | MIT | `gtnh-src/source/UniLib/` |
| UniMixins | `+unimixins-all-1.7.10-0.3.1.jar` | 0.3.1 | exact | [LegacyModdingMC/UniMixins](https://github.com/LegacyModdingMC/UniMixins) | `0.3.1` (tag) | Unlicense | `gtnh-src/source/UniMixins/` |
| UniversalSingularities | `Universal-Singularities-8.15.4.jar` | 8.15.4 | exact | [GTNewHorizons/Universal-Singularities](https://github.com/GTNewHorizons/Universal-Singularities) | `8.15.4` (tag) | none | `gtnh-src/source/Universal-Singularities/` |
| Vending Machine | `vendingmachine-0.4.103.jar` | 0.4.103 | exact | [GTNewHorizons/VendingMachine](https://github.com/GTNewHorizons/VendingMachine) | `0.4.103` (tag) | MIT | `gtnh-src/source/VendingMachine/` |
| Village Names | `VillageNames-4.5.21-GTNH.jar` | 4.5.21-GTNH | exact | [GTNewHorizons/VillageNames](https://github.com/GTNewHorizons/VillageNames) | `4.5.21-GTNH` (tag) | GPL-3.0 | `gtnh-src/source/VillageNames/` |
| VisualProspecting | `visualprospecting-1.5.42.jar` | 1.5.42 | exact | [GTNewHorizons/VisualProspecting](https://github.com/GTNewHorizons/VisualProspecting) | `1.5.42` (tag) | MIT | `gtnh-src/source/VisualProspecting/` |
| Waila | `Waila-1.19.34.jar` | 1.19.34 | exact | [GTNewHorizons/waila](https://github.com/GTNewHorizons/waila) | `1.19.34` (tag) | CC-BY-NC-SA-4.0 | `gtnh-src/source/waila/` |
| Waila Harvestability | `WailaHarvestability-1.3.6-GTNH.jar` | 1.3.6-GTNH | exact | [GTNewHorizons/WailaHarvestability](https://github.com/GTNewHorizons/WailaHarvestability) | `1.3.6-GTNH` (tag) | Unlicense | `gtnh-src/source/WailaHarvestability/` |
| WAILA Plugins | `WAILAPlugins-0.7.2.jar` | 0.7.2 | exact | [GTNewHorizons/WAILAPlugins](https://github.com/GTNewHorizons/WAILAPlugins) | `0.7.2` (tag) | LicenseRef-CC-unknown | `gtnh-src/source/WAILAPlugins/` |
| WanionLib | `WanionLib-1.10.1.jar` | 1.10.1 | exact | [GTNewHorizons/WanionLib](https://github.com/GTNewHorizons/WanionLib) | `1.10.1` (tag) | MPL-2.0 | `gtnh-src/source/WanionLib/` |
| WarpTheory | `WarpTheory-1.5.8-GTNH.jar` | 1.5.8-GTNH | exact | [GTNewHorizons/WarpTheory](https://github.com/GTNewHorizons/WarpTheory) | `1.5.8-GTNH` (tag) | none | `gtnh-src/source/WarpTheory/` |
| What Are We Looking At | `Wawla-1.3.4-GTNH.jar` | 1.3.4-GTNH | exact | [GTNewHorizons/WAWLA](https://github.com/GTNewHorizons/WAWLA) | `1.3.4-GTNH` (tag) | LGPL-2.1 | `gtnh-src/source/WAWLA/` |
| Witchery | `witchery-1.7.10-0.24.1.jar` | 0.24.1 | branch-head (decompiled-reference) | [GTNewHorizons/witchery](https://github.com/GTNewHorizons/witchery) | `master` (branch) | LicenseRef-ARR | `gtnh-src/source/witchery/` |
| Witchery++ | `WitcheryExtras-1.4.20.jar` | 1.4.20 | exact | [GTNewHorizons/WitcheryExtras](https://github.com/GTNewHorizons/WitcheryExtras) | `1.4.20` (tag) | GPL-3.0 | `gtnh-src/source/WitcheryExtras/` |
| Witching Gadgets | `WitchingGadgets-1.8.53-GTNH.jar` | 1.8.53-GTNH | exact | [GTNewHorizons/WitchingGadgets](https://github.com/GTNewHorizons/WitchingGadgets) | `1.8.53-GTNH` (tag) | LGPL-3.0 | `gtnh-src/source/WitchingGadgets/` |
| YAMCore | `YAMCore-0.7.5.jar` | 0.7.5 | exact | [GTNewHorizons/Yamcl](https://github.com/GTNewHorizons/Yamcl) | `0.7.5` (tag) | GPL-2.0 | `gtnh-src/source/Yamcl/` |
| Ztones | `Ztones-1.7.10-2.2.2.jar` | 2.2.2 | **none** |  |  | none |  |

## Notes: non-exact matches and special cases

- **Biomes O' Plenty** (`BiomesOPlenty-1.7.10-2.1.0.2308-universal.jar`, branch-head): No tag for 2.1.0.2308 ("2308" is a CI build number). Branch BOP-1.7.10-2.1.x is the 1.7.10 line (build.properties mod_version=2.1.0, last commit 2017-11-13); the jar's entry timestamps are stripped, so the exact build commit cannot be pinned. Probably at or near the release.
- **Catwalks Mod** (`catwalks-2.4.2-GTNH.jar`, sources-jar): GTNH repo github.com/GTNewHorizons/Catwalks-2 is private, but the exact-version -sources.jar is on the GTNH Nexus. The sibling extracted it into gtnh-src/mods/catwalks/ (origin sources-jar).
- **CoFH Core** (`CoFHCore-[1.7.10]3.1.4-329.jar`, exact): Branch 1.7.10 head commit "Update to final 1.7.10 release." (2017-03-04) sets CoFHCore.version = "1.7.10R3.1.4"; the pack jar entries are timestamped 2017-03-04. "-329" is the CI build number. The jar also bundles CoFHLib (see the separate CoFHLib entry).
- **CoFHLib (bundled in CoFH Core)** (`CoFHCore-[1.7.10]3.1.4-329.jar`, exact): Library packages cofh.lib.* shipped inside the CoFH Core jar. Branch 1.7.10 head commit "Update to final 1.7.10 release." (2017-03-04), same day as the CoFH Core 3.1.4 release commit.
- **Compact Kinetic Wind and Water Generators** (`CompactKineticGenerators-1.7.10-1.0.jar`, branch-head): No tags or version info in the repo; 1.0 is the only release, and the 35 source files match the jar's 36 classes. README: "reference only - do not build or distribute".
- **Craft-Presence** (`CraftPresence-2.7.1+1.7.10-forge.jar`, exact): GitLab is canonical (GitHub mirror is README only). Tag release/v2.7.1 points at the 1.12.2 master; the 1.7.10 build comes from branch 1.7.10, whose head commit "[Port] Update to 1.7.10 (v2.7.1)" has versionId=2.7.1, mc_version=1.7.10. Client-only: jar not in the server pack, so no decompile exists.
- **Extreme Sound Muffler** (`esm-legacy-1.7.10-1.1.1.jar`, exact): Repo found via the Modrinth project source_url. Client-only: jar not in the server pack, so no decompile exists.
- **GalaxySpace** (`GalaxySpace-1.1.144-GTNH.jar`, branch-head): DIVERGENT: GTNH ships its own fork (github.com/GTNewHorizons/Galaxy-Space-GTNH, private; Nexus has only -dev.jar and the plain jar for 1.1.144-GTNH, no -sources.jar). This checkout is the original author's 1.7.10 line, developed separately since the fork (package layout differs: upstream galaxyspace/systems/SolarSystem vs shipped galaxyspace/SolarSystem). Useful for names and comments only; for GTNH behaviour use the decompile in gtnh-src/mods/GalaxySpace/.
- **GregTech** (`gregtech-5.09.54.265.jar`, exact): GregTech 5 Unofficial. Also contains the merged former addons: bartworks/bwcrossmod, GT++ (gtPlusPlus), TecTech, GoodGenerator, KekzTech, KubaTech, GGFab, GalacticGreg, Detrav scanner, gtnhlanth, gtnhintergalactic, gtneioreplugin, toxiceverglades.
- **Hunger Overhaul** (`HungerOverhaul-1.7.10-1.0.0.jenkins104.jar`, branch-head): Pack ships the original 1.0.0.jenkins104 build, not GTNH's fork (GTNewHorizons/HungerOverhaul, tags up to 1.1.0-GTNH). There is no build-104 tag. The jar contains the enableRightClickHarvesting option and the de_DE/zh_CN/pack.mcmeta changes, which only reached master in the final merge f099fe8 (2016-08-04), so master head is almost certainly the build source. Tag 1.0.0 (2015-05) is older than the jar.
- **JourneyMap** (`journeymap-1.7.10-5.2.23-fairplay.jar`, exact): "fairplay" is a build flavour of the same source (project.properties fairPlay=FairPlay). Client-only: jar not in the server pack, so no decompile exists.
- **Salis Arcana** (`salisarcana-v2.7.0.jar`, exact): Pack version 2.7.0; repo tag is v2.7.0.
- **Tinkers' Gregworks** (`TGregworks-1.7.10-GTNH-1.0.34.jar`, exact): The manifest points at Vexatos/TinkersGregworks (GT-NH branch, no release tags); the GTNH fork has tag GTNH-1.0.34 matching jar TGregworks-1.7.10-GTNH-1.0.34.
- **UniLib** (`UniLib-1.2.1+1.7.10-forge.jar`, exact): Branch 1.7.10 head commit "[Port] Update to 1.7.10 (v1.2.1)" has versionId=1.2.1, mc_version=1.7.10. Client-only: jar not in the server pack, so no decompile exists.
- **UniMixins** (`+unimixins-all-1.7.10-0.3.1.jar`, exact): The -all jar also bundles UniMix (LegacyModdingMC/UniMix, 0.15.6 = Mixin 0.8.7) and MixinExtras 0.5.0; those were not cloned.
- **Witchery** (`witchery-1.7.10-0.24.1.jar`, branch-head): NOT original source: GTNH's "reference only - do not build or distribute" decompile of Witchery with MCP names (Witchery.java declares version 0.24.1, matching the pack). No original comments. Original is closed (Emoniph, ARR). Roughly equivalent to gtnh-src/mods/witchery/.

## Decomp only

No public source at any version close to the shipped one. Use the decompile in `gtnh-src/mods/` (the `decompPath` column in the JSON). Where an official API is public it was checked out as `apiSource`, and the API is the best place to look up interfaces and javadoc.

### Advanced Solar Panels 1.7.10 Edition (`AdvancedSolarPanel-1.7.10-3.5.1.jar`)

- Reason: Closed source (SeNtiMeL, ARR). No public repo or sources jar.
- Decompile: `gtnh-src/mods/AdvancedSolarPanel/`
- Searched: CurseForge (ARR); forum.industrial-craft.net thread (binary only); github.com/GTNewHorizons/AdvancedSolarPanel (not found); GitHub repo search "AdvancedSolarPanel 1.7.10" (nothing); Modrinth (nothing relevant)

### Automagy (`Automagy-0.29.8-GTNH.jar`)

- Reason: Closed: GTNH fork github.com/GTNewHorizons/Automagy-GTNH is private; no Nexus artifacts. Only the upstream API package is public (cloned as apiSource).
- API source: https://github.com/Tuhljin/Automagy @ `master` -> `gtnh-src/source/Automagy/` (Original author's repo holds only the public API package (tuhljin/automagy/api, 15 files) from the pre-fork 0.28.x line. Not the GTNH 0.29.8 code.)
- Decompile: `gtnh-src/mods/Automagy/`
- Searched: git ls-remote github.com/GTNewHorizons/Automagy-GTNH (private); github.com/GTNewHorizons/Automagy (not found); GTNH Nexus Automagy-GTNH / Automagy (no artifacts); github.com/Tuhljin/Automagy (API only; cloned as apiSource); github.com/vvmax/Automagy (third-party 0.28.6 reconstruction/audit, not GTNH 0.29.8; not cloned); GitHub repo search "Automagy"

### BiblioCraft (`BiblioCraft[v1.11.7][MC1.7.10].jar`)

- Reason: Closed source (Nuchaz, All Rights Reserved). No public repo or sources jar.
- Decompile: `gtnh-src/mods/BiblioCraft/`
- Searched: CurseForge project page (ARR, no source link); bibliocraftmod.com (no source); github.com/GTNewHorizons/BiblioCraft (not found); GitHub repo search "BiblioCraft 1.7.10" (nothing); Modrinth (only unrelated modern "Bibliocraft Legacy" remakes); GTNH Nexus search (nothing)

### BiblioWoods Biomes O'Plenty Edition (`BiblioWoods[BiomesOPlenty][v1.9].jar`)

- Reason: Closed source (Nuchaz, All Rights Reserved). No public repo or sources jar.
- Decompile: `gtnh-src/mods/BiblioWoods_BiomesOPlenty/`
- Searched: CurseForge project page (ARR, no source link); bibliocraftmod.com (no source); github.com/GTNewHorizons/BiblioCraft (not found); GitHub repo search "BiblioCraft 1.7.10" (nothing); Modrinth (only unrelated modern "Bibliocraft Legacy" remakes); GTNH Nexus search (nothing)

### BiblioWoods Forestry Edition (`BiblioWoods[Forestry][v1.7].jar`)

- Reason: Closed source (Nuchaz, All Rights Reserved). No public repo or sources jar.
- Decompile: `gtnh-src/mods/BiblioWoods_Forestry/`
- Searched: CurseForge project page (ARR, no source link); bibliocraftmod.com (no source); github.com/GTNewHorizons/BiblioCraft (not found); GitHub repo search "BiblioCraft 1.7.10" (nothing); Modrinth (only unrelated modern "Bibliocraft Legacy" remakes); GTNH Nexus search (nothing)

### BiblioWoods Natura Edition (`BiblioWoods[Natura][v1.5].jar`)

- Reason: Closed source (Nuchaz, All Rights Reserved). No public repo or sources jar.
- Decompile: `gtnh-src/mods/BiblioWoods_Natura/`
- Searched: CurseForge project page (ARR, no source link); bibliocraftmod.com (no source); github.com/GTNewHorizons/BiblioCraft (not found); GitHub repo search "BiblioCraft 1.7.10" (nothing); Modrinth (only unrelated modern "Bibliocraft Legacy" remakes); GTNH Nexus search (nothing)

### Extra Utilities (`extrautilities-1.2.12.jar`)

- Reason: Closed source (RWTema, ARR). github.com/rwtema/extrautilities holds only a README (2014).
- Decompile: `gtnh-src/mods/extrautilities/`
- Searched: CurseForge (ARR); github.com/rwtema/extrautilities (README only); github.com/GTNewHorizons/ExtraUtilities, Extra-Utilities (not found); GitHub repo search "extrautilities 1.7.10" (nothing); Modrinth (only later remakes)

### Graviation Suite (`GraviSuite-1.7.10-2.0.3.jar`)

- Reason: Closed source (SeNtiMeL, ARR). Not to be confused with gravisuiteneo (GTNH, has source).
- Decompile: `gtnh-src/mods/GraviSuite/`
- Searched: forum.industrial-craft.net thread (binary only); github.com/GTNewHorizons/GraviSuite (not found); GitHub repo search "GraviSuite": cropinghigh/gravisuite-1710-204 (a 2.0.4 rework, apparently decompile-derived, not the shipped 2.0.3; not cloned), RevivalHyperborea/gravisuite (empty), others are ports to other MC versions

### IndustrialCraft 2 (`industrialcraft-2-2.2.828-experimental.jar`)

- Reason: Closed source (IC2 team, ARR). The IC2 maven publishes only -api.jar (with .java) and a deobfuscated -dev.jar (bytecode, no comments) for 2.2.828-experimental; no -sources.jar. Internals: gtnh-src/mods/industrialcraft-2/.
- API source: https://maven.ic2.player.to/net/industrial-craft/industrialcraft-2/2.2.828-experimental/industrialcraft-2-2.2.828-experimental-api.jar @ `net.industrial-craft:industrialcraft-2:2.2.828-experimental:api` -> `gtnh-src/source/IC2-API/` (Exact-version official API jar (SHA-1 6132eb4f... matches the maven .sha1); its 91 .java files (ic2.api.*) were extracted, javadoc included. API only.)
- Decompile: `gtnh-src/mods/industrialcraft-2/`
- Searched: maven.ic2.player.to 2.2.828-experimental (api + dev jars only; api extracted); GTNH Nexus net.industrial-craft (nothing); CurseForge (ARR); Modrinth (IC2 Classic only, different mod)

### JourneyMapServer (`JourneyMapServer1.0.5_MC1.7.10.jar`)

- Reason: Closed source (techbrew/mysticdrew, ARR). TeamJM/journeymap-legacy has the client and a later journeymap.server package, but not this separate net.techbrew.journeymapserver 1.0.5 mod.
- Decompile: `gtnh-src/mods/JourneyMapServer/`
- Searched: CurseForge (ARR); github.com/TeamJM/journeymap-legacy (no net.techbrew.journeymapserver package); github.com/TeamJM/journeymap (README only); github.com/techbrew/journeymap (not found); GitHub repo search "JourneyMapServer" (nothing)

### Pam's HarvestCraft (`harvestcraft-1.3.15-GTNH.jar`)

- Reason: Closed: GTNH fork github.com/GTNewHorizons/harvestcraft is private and Nexus has no -sources.jar (a deobfuscated -dev.jar exists at https://nexus.gtnewhorizons.com/repository/public/com/github/GTNewHorizons/harvestcraft/1.3.15-GTNH/harvestcraft-1.3.15-GTNH-dev.jar). Pam's public repo is 1.12.2 only.
- Decompile: `gtnh-src/mods/harvestcraft/`
- Searched: git ls-remote github.com/GTNewHorizons/harvestcraft (private); GTNH Nexus com.github.GTNewHorizons:harvestcraft:1.3.15-GTNH (dev + plain jar, no sources); github.com/MatrexsVigil/harvestcraft (1.12.2 only: ForgeGradle 2.3, minecraft 1.12.2); github.com/MatrexsVigil/pamsharvestcraft (not found); GitHub repo search "harvestcraft 1.7.10" (nothing); Modrinth (only HarvestCraft 2 for modern MC)

### Thaumcraft (`Thaumcraft-1.7.10-4.2.3.5.jar`)

- Reason: Closed source (Azanor, All Rights Reserved). Only the official API is public (cloned as apiSource). For internals use gtnh-src/mods/Thaumcraft/; GTNH patches TC4 heavily through TC4Tweaks, Salis Arcana and hodgepodge mixins.
- API source: https://github.com/Azanor/thaumcraft-api @ `1.7.10` -> `gtnh-src/source/thaumcraft-api/` (Official Thaumcraft 4 API (thaumcraft.api.*), branch 1.7.10 head (2015-12). Has javadoc. API only.)
- Decompile: `gtnh-src/mods/Thaumcraft/`
- Searched: CurseForge (ARR); github.com/Azanor (only thaumcraft-api); github.com/GTNewHorizons/Thaumcraft (not found); GTNH Nexus thaumcraft group (no artifacts); Modrinth (only addons)

### Ztones (`Ztones-1.7.10-2.2.2.jar`)

- Reason: Closed source (riciJak). github.com/ricijak/Ztones has only an initial commit. GTNewHorizons/Ztones-Unofficial is a from-scratch rewrite that is NOT the jar shipped in 2.9.0 (pack ships Ztones-1.7.10-2.2.2 from CurseForge).
- Decompile: `gtnh-src/mods/Ztones/`
- Searched: CurseForge (ARR, modpack permission only); github.com/ricijak/Ztones (initial commit only); github.com/RevivalHyperborea/ztones (empty); github.com/GTNewHorizons/Ztones (not found); github.com/GTNewHorizons/Ztones-Unofficial (rewrite, not shipped); github.com/TehNut/Xtones (clone for later MC)

## Our own mods

These are not copied here. Record them so the future code index can include them:

- **GregGuns**: `/path/to/GregGuns`
- **TrainHorizons**: coming; not yet available. Add its path here and in the code index when it exists.
