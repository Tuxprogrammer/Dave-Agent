# Agent guide

A Forge 1.7.10 mod built on the GT New Horizons buildscript, meant to live inside the GTNH pack. This file is a map: load the skill or document you need, not everything up front.

Skills live in [.claude/skills/](.claude/skills/). Claude Code loads one automatically when its description matches the task; you can also ask for one by name.

## Non-negotiables

1. **Never copy code or assets you have no license for.** Rebuild from a written behavior spec in a clean room. → `clean-room-reimplementation`
2. **GT and the pack first.** Use GT materials, recipe maps, voltage tiers and EU; never duplicate what the pack provides. → `gt-first-design`
3. **Source before guesses.** Read another mod's source at the tag the pack ships before integrating with it; cite it. → `gtnh-integration-research`
4. **Config never changes what is registered.** Register everything; gate behavior; IDs are forever. → `config-safe-registration`
5. **Servers never load client classes, and never trust clients.** → `networking-side-safety`
6. **Java 8 API.** `enableModernJavaSyntax = jabel` allows modern syntax, but the runtime is Java 8: no records, no `List.of`, no `String.isBlank`.
7. **Tests and comments ship with the code.** → `testing-gtnh-mods`
8. **Never edit `build.gradle.kts` or `settings.gradle.kts`.** They come from the GTNH buildscript. Use `dependencies.gradle`, `repositories.gradle`, `gradle.properties`.
9. **Nothing machine-specific in git:** no hostnames, usernames, local paths, IPs or secrets. → `release-and-public-repo`

## Skills

| Skill | Use it when |
|---|---|
| [clean-room-reimplementation](.claude/skills/clean-room-reimplementation/SKILL.md) | Rebuilding another mod's behavior or look; license triage; ported code |
| [behavior-spec](.claude/skills/behavior-spec/SKILL.md) | Documenting the original; bug register; deviations |
| [gtnh-integration-research](.claude/skills/gtnh-integration-research/SKILL.md) | Any code touching GT or another pack mod; dependency bumps |
| [gt-first-design](.claude/skills/gt-first-design/SKILL.md) | Materials, recipes, tiers, energy, machines, multiblocks, key defaults |
| [config-safe-registration](.claude/skills/config-safe-registration/SKILL.md) | Module toggles, registration, retiring content, NBT formats |
| [testing-gtnh-mods](.claude/skills/testing-gtnh-mods/SKILL.md) | Unit, static, headless, scenario, real-pack, worldgen and client tests |
| [client-rendering-shaders](.claude/skills/client-rendering-shaders/SKILL.md) | Renderers, effects, models; anything that breaks under shaders |
| [networking-side-safety](.claude/skills/networking-side-safety/SKILL.md) | Packets, sync, GUIs, tooltips, server crashes on client classes |
| [in-pack-content-delivery](.claude/skills/in-pack-content-delivery/SKILL.md) | Quests, loot, pack configs; shipping from the jar |
| [release-and-public-repo](.claude/skills/release-and-public-repo/SKILL.md) | Tags, changelogs, upgrade notes, going public |
| [port-workflow](.claude/skills/port-workflow/SKILL.md) | Roadmap and gates, decision records, branches, landing, long jobs, agents |
| [pack-contribution-policy](.claude/skills/pack-contribution-policy/SKILL.md) | Before planning any submission to a pack or another mod |

## Where to look

| You need… | Read |
|---|---|
| What to build next, and its gates | `docs/ROADMAP.md` (start from [docs/templates/roadmap.md](docs/templates/roadmap.md)) |
| Accepted design decisions | `docs/design/` (template: [decision-record.md](docs/templates/decision-record.md)) |
| How the original behaves | `docs/original-spec/` (templates: [spec-area-index.md](docs/templates/spec-area-index.md), [spec-sheet.md](docs/templates/spec-sheet.md), [bug-register.md](docs/templates/bug-register.md)) |
| Changes the pack would need | `docs/PACK-CHANGES.md` (template: [pack-changes.md](docs/templates/pack-changes.md)) |
| PR checklist | [docs/templates/pull_request_template.md](docs/templates/pull_request_template.md) |
| Build settings, mod ID, package | [gradle.properties](gradle.properties) |
| Dependencies and repositories | [dependencies.gradle](dependencies.gradle), [repositories.gradle](repositories.gradle) |
| Buildscript FAQ, migrating or porting a build | [docs/FAQ.md](docs/FAQ.md), [docs/migration.md](docs/migration.md), [docs/porting.md](docs/porting.md) |

## Commands

```sh
./gradlew spotlessApply build   # format, compile, test: run before every commit
./gradlew test                  # unit tests
./gradlew runServer             # headless boot smoke test (side safety)
./gradlew runClient             # visual checks
```

## Housekeeping

- One change per branch; never commit to the default branch directly.
- When behavior changes, update the spec deviation notes or design records in the same PR.
- Keep reference packs, other mods' clones and decompiled output in a git-ignored `reference/` folder.
- American English in code, docs and lang (`color`, `armor`, `gray`); keep external API identifiers as they are.
