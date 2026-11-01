<!-- Copy to .github/pull_request_template.md in your mod. -->

## What and why

<!-- One or two sentences. -->

**Roadmap item:**
**Spec sheets:**
**Decision records:**

## Deviations from the original

<!-- What behaves differently and why (tier gate, EU, replaced machine, bug fix). "None" if none. -->

## Inherited bugs avoided

<!-- Bug-register IDs this change avoids, and the test that proves each. -->

## External behavior relied on

<!-- `// Source:` permalinks pinned to the pack's tag; any `// Decompiled:` hedges added. -->

## Definition of done

- [ ] Implements the spec sheet, deviations recorded
- [ ] `./gradlew spotlessApply build` passes; unit tests cover the new logic and the relevant bug regressions
- [ ] `runServer` boots cleanly; dev self-check passes
- [ ] Scenario exists (world-touching features); multiplayer checked (synced features)
- [ ] Content registered regardless of config; config gates behavior only
- [ ] Recipes tier-gated, no clash with the pack's recipe set, visible in NEI; no duplicated GT materials
- [ ] Every string is a lang key; assets are original with provenance recorded
- [ ] Javadoc and `// Spec:` comments in place; no commented-out code
- [ ] No hostnames, usernames, local paths or secrets in the diff
- [ ] Roadmap box ticked; docs and changelog updated

## Test evidence

<!-- Test output, scenario summary line, screenshots for visual work. -->
