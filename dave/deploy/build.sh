#!/bin/sh
# Builds Dave's image from this repo and, with --ship, copies it to the game server's Docker over SSH.
#
#   dave/deploy/build.sh                      build dave:<git rev> and tag it dave:current
#   dave/deploy/build.sh --ship HOST          build, then load it into HOST's docker and tag it dave:current there
#
# The image holds code and read-only data only (see .dockerignore); secrets come from the compose stack at runtime.
# The build refuses pack-derived data (gtnh-src, recipes, search corpus and embeddings) that was built from another
# pack than the current GTNH + tuxmine packs: run tools/refresh-pack-data.sh first. DAVE_ALLOW_STALE=1 overrides.
# Applying it on the server is a separate, owner-approved step: `docker compose up -d dave` in /opt/gtnh.
set -eu
cd "$(dirname "$0")/../.."

SHIP=""
case "${1:-}" in
    --ship) SHIP="${2:?usage: build.sh [--ship HOST]}" ;;
    "") ;;
    *) echo "usage: build.sh [--ship HOST]" >&2; exit 2 ;;
esac

mkdir -p data/packstate
if ! python3 -I tools/packstate.py check; then
    if [ "${DAVE_ALLOW_STALE:-0}" = 1 ]; then
        echo "build.sh: WARNING: building with stale pack data (DAVE_ALLOW_STALE=1)" >&2
    else
        echo "build.sh: pack-derived data is stale; run tools/refresh-pack-data.sh (or set DAVE_ALLOW_STALE=1)" >&2
        exit 1
    fi
fi

REV="$(git describe --always --dirty 2>/dev/null || echo local)"
docker build -f dave/deploy/Dockerfile -t "dave:$REV" -t dave:current .
docker image ls "dave:$REV" --format 'built dave:{{.Tag}} ({{.Size}})'

if [ -n "$SHIP" ]; then
    docker save "dave:$REV" | gzip -1 | ssh "$SHIP" "gunzip | sudo docker load && sudo docker tag dave:$REV dave:current"
    echo "shipped dave:$REV to $SHIP as dave:current"
fi
