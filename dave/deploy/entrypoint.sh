#!/bin/sh
# Container start: prepare the data volume, start the scheduled jobs, then run the daemon in the foreground.
set -eu
APP=/dave/app

mkdir -p /dave/data/memory /dave/data/logs /dave/data/state /dave/data/exports

# Dave's memory: seeded from the image's copy of data/memory only when the volume has none. After that the
# volume is the source of truth; a new image never overwrites it.
if [ ! -e /dave/data/memory/INDEX.md ]; then
    cp -a /dave/seed/memory/. /dave/data/memory/
    echo "entrypoint: seeded memory from the image"
fi

# Search corpus and index: copied into the state volume when it lacks them or holds an older seed. The living
# wiki in the volume is never replaced (see docs/plans/living-wiki.md).
python3 -I "$APP/tools/gtnh-search/index.py" --seed || echo "entrypoint: search seed failed; search may be stale"

# Refuses to start with a missing secret or a bad isolation setup, so the problem shows in `docker logs`.
python3 -I "$APP/dave/daemon/main.py" --check

supercronic -passthrough-logs "$APP/dave/deploy/crontab" &

exec python3 -I "$APP/dave/daemon/main.py"
