# Pack-side changes

<!-- docs/PACK-CHANGES.md. Every change this mod needs outside its own jar.
     Paths are relative to the pack's .minecraft/ folder; take them from the real pack's config/, not the other mod's defaults.
     This mod never writes another mod's config at runtime. -->

Target pack version: <x.y.z>

| File | Change | Why | Delivery | Spec sheet |
|---|---|---|---|---|
| `config/<mod>/<file>` | Add `<modid>:<item>` to `<list>` | Without it, ... | in jar / optional server-owner step / pack PR | link |

## Pack-wide issues found

Shipped values that break something for everyone, not just this mod. Report separately.

| File | Value | Effect |
|---|---|---|
