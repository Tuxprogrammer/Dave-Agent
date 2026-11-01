#!/usr/bin/env bash
# Export every recipe of OUR pack with the GTNH calculation oracle, headless, on a throwaway server copy.
#
#   tools/recipe-export/run.sh <pack-dir>
#
# <pack-dir> is a stock GTNH server directory (the extracted GT_New_Horizons_<ver>_Server zip, e.g.
# .work/gtnh-2.9.0/pack). It is only read: the run copies it to $RECIPE_EXPORT_WORK/server, adds our server
# pack's mods from tuxmine/server/ and the oracle jar, starts it with -Dgtnh.oracle.autorun=true, and collects
# the JSON the oracle writes on FMLServerStarted before it exits the JVM. Nothing connects to the production
# server; the copy listens on 127.0.0.1 only, on a spare port, with online-mode off.
#
# Then it builds the recipe database (tools/recipes/build_db.py) unless RECIPE_EXPORT_NO_DB=1.
#
# Environment (all optional):
#   RECIPE_EXPORT_WORK   scratch dir            default <repo>/.work/recipe-export
#   RECIPE_EXPORT_OUT    where the JSON lands    default <repo>/data/exports/recipes
#   DAVE_RECIPES_DB      the database to build   default <repo>/data/recipes.sqlite
#   JAVA                 java binary (17+)       default /usr/lib/jvm/java-25-openjdk/bin/java, else `java`
#   JAVA_HOME_BUILD      JDK for the Gradle build (default: the JDK of $JAVA if it has javac, else java-25)
#   RECIPE_EXPORT_MEM    max heap                default 6G (GTNH 2.9.0 needs about 5-6 GB)
#   RECIPE_EXPORT_LOCK   lock file; only one heavy JVM at a time across agents  default /tmp/dave-agent-heavy-jvm.lock
#   RECIPE_EXPORT_TIMEOUT seconds                default 3600
#   RECIPE_EXPORT_PORT   server port             default 25599
#   RECIPE_EXPORT_SKIP   space-separated jar-name prefixes from tuxmine/server/mods to leave out
#                        default "davebridge DiscordIntegration journeymap" (no recipes; DaveBridge opens a
#                        WebSocket listener and DiscordIntegration logs in to Discord)
#   ORACLE_JAR           use this oracle jar instead of building tools/recipe-export/oracle
#   RECIPE_EXPORT_HOST   run the server on this ssh host instead (e.g. a big build box). The oracle jar is built
#                        here; run.sh, tuxmine/server/ (public pack files only) and the pack are rsynced to
#                        RECIPE_EXPORT_REMOTE_DIR (required with HOST), the export runs there with
#                        RECIPE_EXPORT_REMOTE_JAVA (default `java`), and the JSON is rsynced back to RECIPE_EXPORT_OUT.
#                        The database is always built here. Nothing is left running on the host.
set -euo pipefail

usage() { sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[[ $# -eq 1 && "$1" != -h && "$1" != --help ]] || usage

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
pack_dir="$(cd "$1" && pwd)"
work="${RECIPE_EXPORT_WORK:-$repo/.work/recipe-export}"
out="${RECIPE_EXPORT_OUT:-$repo/data/exports/recipes}"
db="${DAVE_RECIPES_DB:-$repo/data/recipes.sqlite}"
mem="${RECIPE_EXPORT_MEM:-6G}"
lock="${RECIPE_EXPORT_LOCK:-/tmp/dave-agent-heavy-jvm.lock}"
timeout_s="${RECIPE_EXPORT_TIMEOUT:-3600}"
port="${RECIPE_EXPORT_PORT:-25599}"
skip="${RECIPE_EXPORT_SKIP:-davebridge DiscordIntegration journeymap}"
server_pack="$repo/tuxmine/server"

if [[ -n "${JAVA:-}" ]]; then java_bin="$JAVA"
elif [[ -x /usr/lib/jvm/java-25-openjdk/bin/java ]]; then java_bin=/usr/lib/jvm/java-25-openjdk/bin/java
else java_bin="$(command -v java)"; fi

log() { printf '[recipe-export %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

for f in lwjgl3ify-forgePatches.jar java9args.txt mods config; do
  [[ -e "$pack_dir/$f" ]] || die "$pack_dir is not a GTNH Java 17+ server directory (no $f)"
done
[[ -d "$server_pack/mods" ]] || die "no $server_pack/mods"
case "$work" in ""|/|"$HOME"|"$repo") die "refusing RECIPE_EXPORT_WORK=$work";; esac

log "pack: $pack_dir"

# ---------------------------------------------------------------- 1. the oracle jar
if [[ -n "${ORACLE_JAR:-}" ]]; then
  oracle_jar="$ORACLE_JAR"
else
  build_home="${JAVA_HOME_BUILD:-}"
  if [[ -z "$build_home" && -n "${RECIPE_EXPORT_HOST:-}" ]]; then build_home=/usr/lib/jvm/java-25-openjdk; fi
  if [[ -z "$build_home" ]]; then
    jh="$(dirname "$(dirname "$(readlink -f "$java_bin")")")"
    if [[ -x "$jh/bin/javac" ]]; then build_home="$jh"; else build_home=/usr/lib/jvm/java-25-openjdk; fi
  fi
  log "building the oracle (JAVA_HOME=$build_home)"
  (cd "$here/oracle" && JAVA_HOME="$build_home" flock "$lock" ./gradlew --no-daemon -q build) 2>&1 \
    | grep -v '^INFO: merging' || true
  oracle_jar="$(ls -t "$here"/oracle/build/libs/*.jar 2>/dev/null | grep -v -e '-dev' -e 'sources' | head -n 1 || true)"
fi
[[ -f "$oracle_jar" ]] || die "no oracle jar (build failed?)"
log "oracle: $oracle_jar"

# ---------------------------------------------------------------- 1b. or run it on another host
if [[ -n "${RECIPE_EXPORT_HOST:-}" ]]; then
  host="$RECIPE_EXPORT_HOST"
  rdir="${RECIPE_EXPORT_REMOTE_DIR:?RECIPE_EXPORT_REMOTE_DIR is required with RECIPE_EXPORT_HOST}"
  case "$rdir" in /|/home|/home/*/|/srv|/tmp|"~") die "refusing RECIPE_EXPORT_REMOTE_DIR=$rdir";; esac
  ssh_opts=(-o BatchMode=yes -o ServerAliveInterval=30)
  log "remote: $host:$rdir"
  ssh "${ssh_opts[@]}" "$host" "mkdir -p '$rdir/repo/tools/recipe-export' '$rdir/repo/tuxmine' '$rdir/out'"
  rsync -a --delete "$here/run.sh" "$host:$rdir/repo/tools/recipe-export/run.sh"
  rsync -a --delete --exclude '.env' --exclude '*.cfg.local' "$server_pack/" "$host:$rdir/repo/tuxmine/server/"
  rsync -a --delete --exclude 'World/' --exclude 'logs/' --exclude 'crash-reports/' "$pack_dir/" "$host:$rdir/pack/"
  rsync -a "$oracle_jar" "$host:$rdir/$(basename "$oracle_jar")"
  set +e
  ssh "${ssh_opts[@]}" "$host" "cd '$rdir' && RECIPE_EXPORT_NO_DB=1 ORACLE_JAR='$rdir/$(basename "$oracle_jar")' \
    JAVA='${RECIPE_EXPORT_REMOTE_JAVA:-java}' RECIPE_EXPORT_PORT='$port' RECIPE_EXPORT_MEM='$mem' \
    RECIPE_EXPORT_TIMEOUT='$timeout_s' RECIPE_EXPORT_SKIP='$skip' RECIPE_EXPORT_LOCK='$rdir/.lock' \
    RECIPE_EXPORT_WORK='$rdir/work' RECIPE_EXPORT_OUT='$rdir/out' bash '$rdir/repo/tools/recipe-export/run.sh' '$rdir/pack'"
  code=$?
  set -e
  # whatever happened, make sure no server of ours is left running there
  ssh "${ssh_opts[@]}" "$host" "pkill -f -- '-Dgtnh.oracle.outputDir=$rdir/' || true" || true
  [[ $code -eq 0 ]] || die "remote export failed ($code); log: $host:$rdir/work/server.log"
  mkdir -p "$out"
  rsync -a "$host:$rdir/out/" "$out/"
  log "export: $out/oracle-export.json ($(du -h "$out/oracle-export.json" | cut -f1)) from $host"
  if [[ "${RECIPE_EXPORT_NO_DB:-0}" != 1 ]]; then
    log "building $db"
    python3 -I "$repo/tools/recipes/build_db.py" "$out/oracle-export.json" "$db" --run-info "$out/run-info.json"
  fi
  log "done"
  exit 0
fi

java_major="$("$java_bin" -XshowSettings:properties -version 2>&1 | sed -n 's/.*java.specification.version = //p')"
[[ "${java_major:-0}" -ge 17 ]] || die "$java_bin is Java ${java_major:-?}; GTNH via lwjgl3ify needs 17+"
log "java: $java_bin (Java $java_major)"

# ---------------------------------------------------------------- 2. throwaway server copy
server="$work/server"
records="$work/oracle-records"
cache="$work/cache"
mkdir -p "$work" "$cache"
rm -rf "$server" "$records"
log "copying the server to $server"
cp -a --reflink=auto "$pack_dir" "$server"
rm -rf "$server/World" "$server/logs" "$server/crash-reports" "$server/GTNH-Calc-Oracle"
find "$server/mods" -maxdepth 1 -iname '*gtnh*calc*oracle*.jar' -delete

# our server pack: plain jars, then URL mods (sha256-checked, cached), then config
skipped() { local n="${1,,}" p; for p in $skip; do [[ "$n" == "${p,,}"* ]] && return 0; done; return 1; }
added=()
for jar in "$server_pack"/mods/*.jar; do
  [[ -e "$jar" ]] || continue
  name="$(basename "$jar")"
  if skipped "$name"; then log "skip $name"; continue; fi
  cp "$jar" "$server/mods/"; added+=("$name")
done
for meta in "$server_pack"/mods/*.pw.toml; do
  [[ -e "$meta" ]] || continue
  name="$(sed -n 's/^filename *= *"\(.*\)"/\1/p' "$meta")"
  url="$(sed -n 's/^url *= *"\(.*\)"/\1/p' "$meta")"
  sha="$(sed -n 's/^hash *= *"\(.*\)"/\1/p' "$meta")"
  fmt="$(sed -n 's/^hash-format *= *"\(.*\)"/\1/p' "$meta")"
  [[ -n "$name" && -n "$url" && -n "$sha" && "$fmt" == sha256 ]] || die "cannot read $meta"
  if skipped "$name"; then log "skip $name"; continue; fi
  if [[ ! -f "$cache/$name" ]] || [[ "$(sha256sum "$cache/$name" | cut -d' ' -f1)" != "$sha" ]]; then
    log "download $name"
    curl -fsSL --retry 2 -o "$cache/$name.part" "$url"
    [[ "$(sha256sum "$cache/$name.part" | cut -d' ' -f1)" == "$sha" ]] || die "sha256 mismatch for $name"
    mv "$cache/$name.part" "$cache/$name"
  fi
  cp "$cache/$name" "$server/mods/"; added+=("$name")
done
if [[ -d "$server_pack/config" ]]; then cp -r "$server_pack/config/." "$server/config/"; fi
cp "$oracle_jar" "$server/mods/"
log "added: ${added[*]:-none}"

echo "eula=true" > "$server/eula.txt"
props="$server/server.properties"
set_prop() { if grep -q "^$1=" "$props"; then sed -i "s|^$1=.*|$1=$2|" "$props"; else echo "$1=$2" >> "$props"; fi; }
set_prop online-mode false
set_prop server-ip 127.0.0.1
set_prop server-port "$port"
set_prop enable-query false
set_prop enable-rcon false
set_prop white-list true
set_prop level-name OracleWorld
set_prop snooper-enabled false
echo "[]" > "$server/whitelist.json"
echo "[]" > "$server/ops.json"

# ---------------------------------------------------------------- 3. run it
mkdir -p "$records"
runtime_log="$work/server.log"
: > "$runtime_log"
log "starting the server (heap $mem, timeout ${timeout_s}s, waits for $lock); log: $runtime_log"
start=$SECONDS
(
  cd "$server"
  exec setsid flock "$lock" "$java_bin" -Xms1G -Xmx"$mem" -Dfml.readTimeout=180 -Duser.language=en @java9args.txt \
    -Dgtnh.oracle.autorun=true -Dgtnh.oracle.outputDir="$records" -Dgtnh.oracle.datasetVersionId=dave \
    -jar lwjgl3ify-forgePatches.jar nogui < /dev/null
) >> "$runtime_log" 2>&1 &
pid=$!
cleanup() { kill -TERM -- "-$pid" 2>/dev/null || true; sleep 3; kill -KILL -- "-$pid" 2>/dev/null || true; }
trap cleanup INT TERM

status=""
while (( SECONDS - start < timeout_s )); do
  if ! kill -0 "$pid" 2>/dev/null; then
    set +e; wait "$pid"; code=$?; set -e
    status="exit $code"; break
  fi
  if grep -qE -- '---- Minecraft Crash Report ----|Fatal errors were detected during the transition' "$runtime_log"; then
    status="crash"; cleanup; break
  fi
  sleep 5
done
[[ -n "$status" ]] || { status="timeout"; cleanup; }
elapsed=$((SECONDS - start))
json="$(ls -t "$records"/gtnh-oracle-*.json 2>/dev/null | head -n 1 || true)"
log "server finished: $status after ${elapsed}s"
if [[ -z "$json" || "$status" != "exit 0" ]]; then
  grep -E 'GTNHCalcOracle|Exception|ERROR' "$runtime_log" | tail -n 40 >&2 || true
  die "no complete oracle export ($status). Full log: $runtime_log"
fi

# ---------------------------------------------------------------- 4. collect
mkdir -p "$out"
cp "$json" "$out/oracle-export.json"
pack_version="$(sed -n 's/^motd=.*Horizons \([0-9][0-9.a-zA-Z-]*\).*$/\1/p' "$pack_dir/server.properties" | head -n 1)"
python3 -I - "$out/run-info.json" "$pack_dir" "$server/mods" "$oracle_jar" "$java_bin" "$java_major" \
    "$elapsed" "${pack_version:-unknown}" "$server_pack/pack.toml" "${added[*]:-}" <<'PY'
import hashlib, json, os, sys, time
out, pack_dir, mods, jar, java, major, elapsed, version, server_toml, added = sys.argv[1:]
tux = ""
for line in open(server_toml, encoding="utf-8"):
    if line.startswith("version"):
        tux = line.split("=", 1)[1].strip().strip('"')
        break
info = {
    "pack_version": version, "tuxmine_server_version": tux, "pack_dir": pack_dir,
    "added_mods": added.split(), "mod_jars": sorted(f for f in os.listdir(mods) if f.endswith(".jar")),
    "oracle_jar": os.path.basename(jar), "oracle_sha256": hashlib.sha256(open(jar, "rb").read()).hexdigest(),
    "java": java, "java_major": int(major), "export_seconds": int(elapsed),
    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
}
json.dump(info, open(out, "w"), indent=2)
PY
log "export: $out/oracle-export.json ($(du -h "$out/oracle-export.json" | cut -f1))"

if [[ "${RECIPE_EXPORT_NO_DB:-0}" != 1 ]]; then
  log "building $db"
  python3 -I "$repo/tools/recipes/build_db.py" "$out/oracle-export.json" "$db" --run-info "$out/run-info.json"
fi
log "done"
