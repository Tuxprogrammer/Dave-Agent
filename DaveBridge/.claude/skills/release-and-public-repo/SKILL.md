---
name: release-and-public-repo
description: Use when cutting a release, writing a changelog or upgrade notes, tagging a version, making a repository public, or committing anything that might contain machine-specific details (hosts, usernames, paths, IPs, emails, tokens).
---

# Releases and public-repo hygiene

## Versions come from tags

- The GTNH buildscript derives the version from the latest git tag; `.github/workflows/release-tags.yml` builds the jar and creates the GitHub release when a tag is pushed. Don't hand-edit version strings.
- Use semantic versions with a stage suffix while unstable: `0.1.0-alpha`, `0.2.0-beta`, `1.0.0`.
- The shared GTNH release workflow (`GTNewHorizons/GTNH-Actions-Workflows`, `release-tags.yml`) uses `.changelogs/<tag>.md` as the release body when that file exists, and GitHub's generated notes otherwise. Keep an `unreleased.md` there that every PR appends to, and rename it to the tag at release time. Re-read the workflow's source before relying on this; it changes.
- That workflow deletes and recreates a release whose tag already exists. Treat pushed tags as immutable; fix forward with a new patch version.
- It marks a GitHub release as pre-release only for `-snapshot` tags, and skips Modrinth and CurseForge publishing for `-snapshot` and `-pre` tags. For alpha or beta builds, set the flag yourself afterwards (`gh release edit <tag> --prerelease`).

## Before tagging

1. `./gradlew spotlessApply build` is green, and CI is green on the commit you tag.
2. The **release jar** (not the dev run) boots on a dedicated server of the exact target pack version with default config, then with every module on (see `testing-gtnh-mods`).
3. One client joins that server and does the feature's basic loop.
4. The changelog is complete.

## What a changelog says

- **Added / Changed / Fixed / Removed**, in player terms, not commit subjects.
- **Upgrade notes** whenever saves or configs are affected: renamed or removed config keys and their replacements, retired content and its placeholder behavior (see `config-safe-registration`), required pack or dependency versions, steps a server owner must take.
- **Known issues** found in testing, with workarounds. Honest caveats for alpha and beta builds.
- **Provenance** where it matters: how the code and assets were made (including AI assistance), and the licenses of anything third-party.

## Public-repo hygiene

Once a repo is public, everything in its history is public.
- **Never commit** hostnames, SSH users, IPs, local absolute paths, personal emails, tokens or machine names. Read them from environment variables or an untracked local config, and write placeholders like `<user>@<test-host>` in docs.
- Grep staged changes for these patterns before every commit in tool or script folders, where they creep in most.
- **Before changing visibility** to public, audit the full history (`git log -p`, plus a secret scanner). A leak in an old commit needs a history rewrite, done in a mirror clone, with a backup bundle kept outside the repo, and only with the owner's approval. Afterwards, old commit hashes are stale: never merge or push work based on them.
- Protect the default branch (no force pushes, no deletion) once others depend on it.
- Keep reference packs, decompiled output, clones of other mods and large generated media out of git (see `gtnh-integration-research`).
