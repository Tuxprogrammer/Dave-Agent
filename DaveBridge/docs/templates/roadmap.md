# Roadmap

<!-- docs/ROADMAP.md. Milestones are delivered in order. Tick a box only in the PR that completes it. -->

## How to read this roadmap

- **Milestones (M0…)** each have an **entry gate** (true before work starts) and an **exit gate** (the definition of done).
- **Decision gates (D1…)** are design questions settled, as records in `docs/design/`, before the milestones they block.
- Each milestone's content ships behind a module toggle that changes behavior only, never registration.
- Every change also meets the definition of done in CLAUDE.md.

```
M0 Foundation ──► D1–Dn ──► M1 Core mechanic ──► M2 … ──► Review gate ──► Polish
```

## M0 · Foundation

**Entry gate:** the repo builds from the template; CI is green.

**Scope:** dependencies pinned to the target pack; package skeleton; per-module registries; config with module flags; network channel with validated packet base classes; creative tab and lang file; unit-test harness; in-world scenario command; dev self-check.

**Exit gate:**
- [ ] `./gradlew spotlessApply build` passes, with at least one real unit test.
- [ ] `./gradlew runServer` boots with the pack's core dependencies and no errors from this mod.
- [ ] `./gradlew runClient` reaches the main menu.
- [ ] Module flags load, save, sync from the server, and are documented.
- [ ] Packet base classes reject out-of-range, wrong-dimension and unauthorized requests, with tests.

## Decision gates

### D1 · Tier map. *Blocks M1 and later.*
Every item gets one voltage tier and a gating material. Record: `docs/design/0001-tier-map.md`.

### D2 · Deconfliction. *Blocks the machine milestones.*
Keep, replace or drop each system of the original against what GT and the pack provide.

### D3 · Energy model.
EU only; electric-item API; charging rules per tier.

<!-- Add the gates your port needs: combat or damage model, world presence, art direction, end goal (standalone or pack inclusion) ... -->

## M1 · <Core mechanic>

**Entry gate:** M0 done; D1 accepted.

**Scope:** ...

**Exit gate:**
- [ ] ...
- [ ] Scenario tests for every world-touching feature.
- [ ] Regression tests for the original's bugs this milestone could reproduce.

## Review gate

**Entry gate:** all content milestones done.

**Exit gate:**
- [ ] Each milestone audited against its exit gate.
- [ ] Release jar tested on a dedicated server of the exact target pack.
- [ ] Multiplayer and client pass, batched into one session.
