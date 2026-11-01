---
name: clean-room-reimplementation
description: Use when rebuilding, cloning or "porting" the behavior or look of an existing mod whose code or assets you may not copy (All Rights Reserved, unlicensed, or GPL into a permissively licensed project), or when deciding whether a piece of someone else's code or art may enter this repo at all. Covers license triage, the dirty-room/clean-room split, fresh assets and ported-code quality.
---

# Clean-room reimplementation

Reproduce what a mod *does* and how it *reads* to a player, never how it is *written*. The deliverable is your own code and your own assets, built from a written description.

## 1. Triage the license first

Look at the original's license file, the jar's `mcmod.info`, the mod page, and every branch you might read. Record the result in a design record before anyone opens the source.

| License of the original | What you may do |
|---|---|
| No license file, or "All Rights Reserved" | Clean room only. No code, no assets, no close paraphrase. Facts are usable (see below). |
| GPL / LGPL, and your project is MIT or similar | Treat as clean room unless you are willing to relicense. Calling its public API is integration, not copying. |
| MIT / BSD / Apache | Porting is possible, but only for named components, with the notice kept (section 5). |
| Different license per branch or version | Each branch is judged alone. An unlicensed branch is All Rights Reserved even if a later one is MIT. |

Facts are generally usable: names, numbers, formulas, recipe grids, IDs, config keys, lang text, asset sizes and frame counts. Expression is not: source text, its structure line by line, textures, models, sounds, structure files. If a call is unclear, stop and record it as an open question for the human owner; this skill is not legal advice.

## 2. Split the work into two rooms

- **Dirty room (notes author).** May read the original source, assets and renders. Writes a behavior spec (see the `behavior-spec` skill) or design notes in prose: sizes, angles, timings, hex colors, ordered logic, state machines, pseudocode in its own words. **No code, no UV coordinates, no copied images, no transcribed coordinate lists.**
- **Clean room (builder).** A *fresh* person or agent session that has never seen the original. Builds only from the notes. Never opens the source, the original assets, or the dirty room's comparison renders.
- **Comparator.** Compares the builder's output with the original and turns differences into *more notes*, never into code or pixels.

Give the builder a checklist of 10–15 verifiable items at the end of each notes page, so it can self-check before handing back.

## 3. Iterate with measured corrections

- Vague corrections ("make the handle longer") overshoot and regress. Write corrections as measured facts: "the front section is 9/16 of total length, top edge 2 px below the rear section".
- Add each round as a new dated section ("Round N corrections") in the notes; a fresh builder rebuilds from the improved notes.
- Use an objective metric where you can (silhouette overlap from several fixed camera angles, color distance per region). **Keep a round only if it scores better than the previous one**: score the old version too, from git.
- Check the comparator's own inputs before trusting a score (stale textures, flipped axes, wrong scale).
- Land the best passing round as it stands rather than holding a whole batch for one laggard.

## 4. Assets are made fresh

- Design geometry first, then paint textures for *that* model's UV layout. Painting textures from generic archetypes and fitting models to them produces things that look nothing like the target.
- Match the original's *footprint* (texture size, frame count, sound length, GUI slot positions) so it fits the same role. Do not trace, recolor, resample or edit original assets.
- Record provenance for every asset (author or tool, date, license) in a credits file. Label generated or AI-assisted assets honestly; never relabel them later to pass a policy.

## 5. Ported permissive code still meets the bar

When a license allows a port (MIT and similar):
- Port only components named in a design record, from the exact license-compatible branch or tag. Keep the copyright notice in a third-party notices file and at the top of the ported class.
- Treat the port as a rewrite that happens to start from someone else's logic: restructure it to project idioms, add Javadoc, unit-test it against the spec's numbers, and fix every known upstream bug before commit.
- "Copy for speed" is how bad code ships. Review gates are identical to native code.

## 6. Keep reference material out of the repo

- Clone the original outside the repo or in a git-ignored folder. Never commit it, its decompiled output, or its renders.
- When the source settles a question the spec did not answer, write the answer back into the spec in your own words.
- If the repo is or will be public, keep licensing research that names third parties outside it unless the owner wants it published.

## Pitfalls

- Letting one session both read the source and write the code. Even with good intent, structure leaks. Use a fresh session.
- "Originality by being different": the aim is faithfulness to the experience, achieved independently, not a deliberately worse imitation.
- Copying a "small helper" from the original or from decompiled output. There is no size threshold.

Templates: [notes-template.md](notes-template.md) for dirty-room notes.
