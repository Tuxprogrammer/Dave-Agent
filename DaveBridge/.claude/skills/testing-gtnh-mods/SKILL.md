---
name: testing-gtnh-mods
description: Use when writing or running tests for a 1.7.10 GTNH mod - unit tests, static checks, headless server boots, in-world scenario tests, multiplayer and client checks, worldgen tests, tests inside the real pack - or when a test is flaky, hangs, or passes in dev but fails in the pack.
---

# Testing a GTNH mod

Each layer catches bugs the others miss. A feature needs every layer that applies to it.

## Layer 1: pure-logic unit tests (always)

- Put formulas, state machines and tables (damage, falloff, timings, tier checks, spawn weights, NBT round-trips, recipe tables) in plain Java classes **with no Minecraft types in their signatures**. Items, entities and tiles stay thin and call into them.
- JUnit 5 in `src/test/java`, mirroring the main packages, run by `./gradlew test`.
- Deterministic: seeded randomness, no wall clock, no sleeps.
- Each bug from the original that a feature could reproduce gets a regression test named after its ID (see `behavior-spec`).
- Return explicit results from logic you test, not sentinel values. A `NaN` meaning "never hit" will be misread as a math bug in a failure report.

## Layer 2: static checks over compiled classes

Cheap tests that read `.class` files with ASM (nothing loaded) catch whole bug families that compile, pass headless runs, and crash a player:
- Every `@SubscribeEvent` method **and its declaring class** must be `public`. FML generates the event handler in another package; a package-private handler throws `IllegalAccessError` on first fire.
- No class outside the client package references a client-only class (see `networking-side-safety`).
- No lang key, texture path or sound event referenced in code is missing from resources.

## Layer 3: headless server boot

- `./gradlew runServer` with the pack's core dependencies loaded must reach "Done" with no errors or warnings from your mod. The GTNH CI workflow runs this on every push; keep it green.
- Boot with every module off and every module on (see `config-safe-registration`).
- A dev-only `postInit` self-check (recipes resolve, tier map holds, every item has a lang key and texture) fails the boot loudly.

## Layer 4: in-world scenarios

A scenario is a reproducible situation with a checked outcome, run in a live server: `/<modid> test <name|all|list>` (op only).

- **Isolation.** Each scenario gets its own arena offset from the others, loads its own chunks, and cleans up. Count only entities and items *inside its own arena*, tagged as its own.
- **Spawn inside the arena.** Position entities before spawning them, and keep them inside loaded chunks: `origin + i` crosses a chunk edge sooner than you think, and a mob's path cache can reach unloaded terrain.
- **Ticks, not wall clock.** Wait in server ticks with a hard timeout; under load, ticks slow down. Confirm each step from the server's side before the next.
- **One greppable summary.** Print `PASS <name>` / `FAIL <name>` with reasons, and a final `Scenarios: N passed, M failed` only after every async scenario finishes. Automation waits for that line and treats `M > 0` as failure.
- **Opt-in slow scenarios** (soaks, long performance runs) are excluded from `all` and run by name before a release gate.
- **Full suite before landing.** A scenario that passes alone can fail in the full suite because of state leaked from earlier ones. Run everything after merging the main branch in.
- Fake players need a stub network handler, or the entity tracker crashes when it tries to send to them.

## Layer 5: the real pack

Dev environments load a handful of mods. Players load hundreds. Test the release jar in the real pack's dedicated server before every release.

- **Opt-in test hooks in release jars.** Gate scenario commands and debug hooks behind a system property (e.g. `-D<modid>.testHooks=true`) so they can run in the real pack. Hooks that change the registry or rely on deobfuscated names stay dev-only.
- **Pack mods act on your test subjects.** Expect mob-variant mods to replace spawned vanilla mobs, scaling mods to rescale or heal them on the next tick, join protection to make a new player untargetable for a while, claim and protection mods to block explosions, elite-mob mods to add modifiers, and balance mods to retune tool levels. Have the scenario context opt test mobs out (persistence, the mods' own opt-out tags), clear join protection, and probe and skip, with a reason, when a protection mod blocks a test.
- Record each interaction you find in the spec, so builders design for it.
- Count dev-only skips separately from failures in the summary.

## Worldgen tests

- The pack's ore generator replaces stone. Build test fixtures out of something else.
- **No cascading worldgen.** During your populate, record every chunk load; a non-zero count fails. Clip writes to the populate window and log any write outside it. Test on fresh chunk squares far from spawn, with a control run that has your generator off.
- `provideChunk` may return an empty placeholder chunk instead of generating; force real loads in the harness.
- Map data and some pack saves are written asynchronously; wait for them before asserting.
- Generation layouts are pure data: unit-test layout, rotation and placement plans without a world, then add one scenario per structure.

## Multiplayer and client checks

- **Two clients on a dedicated server** for anything synced: others see animations, sounds and effects; inventories and NBT match; nothing desyncs after a relog. Give items server-side, not through `/give` timing races.
- **Client runs are expensive.** Batch them: gate each branch on unit, static and headless layers, then run one client session after a group of merges. Cap concurrent Minecraft JVMs by RAM (a GT dev server is around 4 GB, a client around 6 GB) with a shared lock.
- **Watchdog every client and server you launch:**
  - tight timeouts: everything is local, a join takes seconds once at the menu;
  - scan logs for failure signatures, not just the success line: `Exception`, `Crash Report`, `A fatal error has occured`, `Mod rejections`, `Connection Lost`, `Disconnected`;
  - when state is unclear, screenshot the *game window* and look at it; never wait blind;
  - stop only the processes you started.
- **Drive clients from inside the game.** Add dev-only autotest signals (look, use, take a screenshot) that the mod reads from a file or command, rather than moving the OS pointer or capturing a user's desktop.
- Shader-specific checks have their own rules (see `client-rendering-shaders`).

## Flaky tests

- Assume the test is wrong before the code: lag, ambient spawns, neighboring terrain, leaked state, or a pack mod.
- Make the failure message say what was observed ("expected 3 flags in arena, found 2; nearest other flag 40 blocks away"), so the next run diagnoses it.
- Fix the cause; never add retries that hide it.
