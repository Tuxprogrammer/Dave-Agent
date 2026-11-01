---
name: pack-contribution-policy
description: Use before planning, drafting or promising any pull request, submission or pitch to a modpack (GTNH or another) or to another mod's repository, and at project start when choosing how code and assets will be produced. Checks contribution, AI and content policies so a project is not built into a dead end.
---

# Check the pack's contribution policies first

A mod can be technically perfect and still be unacceptable to the pack it targets. Find out at the start, not after the work is done.

## What to read

For the target pack's organization, read the current versions of:
- the contribution guide and code of conduct;
- any **AI policy** (rules on AI-generated code, commits co-authored by AI, generated textures, audio or text, PR descriptions written by AI);
- the vision or roadmap document (what content they want, at which tiers, and what they discourage);
- requirements for new mods: whether a team member must champion it, whether it must live as a fork under their organization, whether major content must be discussed first and where;
- closed or rejected requests for similar mods, and the reasons given. A prior "doesn't fit thematically" is strong evidence.

Record what you found, with links and the date read, in a decision record. Policies change; re-check before any submission.

## Assess honestly

For each rule, say whether the project as built **meets, fails or is unclear** on it. Common hard conflicts:
- generated assets where the pack bans generated media;
- AI co-authored commits where the pack bans them;
- "a human must fully understand all code" against a codebase written mostly by agents;
- new content in tiers or themes the pack discourages.

## What not to do

- **Never strip `Co-Authored-By` lines, rewrite history to hide how work was made, or relabel generated assets as hand-made** to pass a policy.
- Never submit to the pack, or contact its maintainers, without the owner's explicit go-ahead.
- Never post on the owner's behalf; draft and let the owner post.

## Options to put to the owner

- **Standalone release**: one self-contained jar players add themselves (see `in-pack-content-delivery`). Always available.
- **Pitch first** in the pack's development channel, describing the mod and how it was made, before any PR.
- **Adopter handoff**: document the project (`HANDOFF.md`) for a maintainer who could bring it into compliance; keep the description honest about provenance and leave the path open-ended rather than prescribing a full rework.
- **Plan for compliance from day one**, if inclusion is the goal: human-made assets, human-authored commits, early discussion with the team.

Decide early which path the project is on, and write it into the roadmap's end goal.
