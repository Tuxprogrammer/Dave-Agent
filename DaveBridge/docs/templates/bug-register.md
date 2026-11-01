# Suspected bugs in the original mod

<!-- docs/original-spec/BUGS.md. Bugs in the ORIGINAL, listed so the rewrite does not reproduce them.
     Suspected, not confirmed at runtime; no fixes designed here. Merged from every area index. -->

N raw findings merge into **M unique bugs**: a crash, b gameplay, c visual, d cosmetic.

The ID is the first area's ID; **Also** lists the same bug as reported by other areas.

## Crash

| ID | Also | Area(s) | Title | Location |
|---|---|---|---|---|
| CORE-01 | ITEM-03 | 01-core, 06-items | Item registered twice | `path/Main.java:120` |

## Gameplay

| ID | Also | Area(s) | Title | Location |
|---|---|---|---|---|

## Visual

| ID | Also | Area(s) | Title | Location |
|---|---|---|---|---|

## Cosmetic

| ID | Also | Area(s) | Title | Location |
|---|---|---|---|---|

<!-- In the new mod: a regression test per reproducible bug, named doesNotReproduce<ID>_<what>,
     and the PR's "Inherited bugs avoided" section lists the IDs. -->
