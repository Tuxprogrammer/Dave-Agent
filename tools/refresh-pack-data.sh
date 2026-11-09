#!/usr/bin/env bash
# Rebuild every piece of Dave's pack-derived data that no longer matches the current packs, in dependency order.
#
#   tools/refresh-pack-data.sh            rebuild what tools/packstate.py check reports stale
#   tools/refresh-pack-data.sh --force    rebuild everything
#   tools/refresh-pack-data.sh --dry-run  only show what is stale
#
# Run it after any change to the GTNH base pack (.work/gtnh-<ver>/pack) or to tuxmine/server or tuxmine/client
# (a new GregGuns jar, a config change, a new mod). dave/deploy/build.sh refuses to build an image until it passes.
#
#   gtnh-src  tools/decomp/tuxmine_extras.py           source for the tuxmine extras (stock GTNH is regenerated
#                                                       with tools/decomp/ when GTNH itself updates)
#   recipes   tools/recipe-export/run.sh <pack>         headless export + data/recipes.sqlite (a few minutes, ~6 GB heap)
#   corpus    tools/gtnh-search/index.py --extract      quest/guide/lang text from GTNH + tuxmine jars (no API calls)
#   index     tools/gtnh-search/index.py                embeddings of changed chunks (OpenRouter, OPENROUTER_API_KEY)
#
# Each step stamps its component (data/packstate/<component>.json) only when it succeeds; a failure stops the run.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
export DAVE_AGENT_ROOT="${DAVE_AGENT_ROOT:-$repo}"

force=0 dry=0
for a in "$@"; do
  case "$a" in
    --force) force=1 ;;
    --dry-run) dry=1 ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

log() { printf '[refresh %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
stale() { [[ $force == 1 ]] || ! python3 -I tools/packstate.py check "$1" >/dev/null 2>&1; }

python3 -I tools/packstate.py check || true
if [[ $dry == 1 ]]; then exit 0; fi

log "fetching tuxmine jars (sha256-verified)"
python3 -I tools/packstate.py jars --fetch >/dev/null

pack="$(python3 -I -c 'import json,sys; sys.path.insert(0,"tools"); import packstate; print(packstate.gtnh_pack_dir() or "")')"
[[ -n "$pack" ]] || { echo "no extracted GTNH pack (.work/gtnh-*/pack or GTNH_PACK_DIR)" >&2; exit 1; }

if stale gtnh-src; then
  log "gtnh-src: tuxmine extras"
  python3 -I tools/decomp/tuxmine_extras.py
fi

if stale recipes; then
  log "recipes: export from $pack"
  tools/recipe-export/run.sh "$pack"
fi

reembed=0
if stale corpus; then
  log "corpus: extract"
  python3 -I tools/gtnh-search/index.py --extract
  reembed=1
fi

if [[ $reembed == 1 ]] || stale index; then
  log "index: embed changed chunks"
  python3 -I tools/gtnh-search/index.py
fi

python3 -I tools/packstate.py check
log "done"
