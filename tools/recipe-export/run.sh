#!/usr/bin/env bash
# Export every recipe of OUR pack with the GTNH calculation oracle, headless, on a throwaway server copy.
#
#   tools/recipe-export/run.sh <pack-dir>
#
# <pack-dir> is a stock GTNH server directory (the extracted GT_New_Horizons_<ver>_Server zip, e.g.
# .work/gtnh-2.9.0/pack). It is only read: the run copies it to $RECIPE_EXPORT_WORK/server, adds our server
# pack's mods and configs from $TUXMINE_DIR/server and the oracle jar, starts it with -Dgtnh.oracle.autorun=true,
# and collects the JSON the oracle writes 20 server ticks after start (some mods, GTNHRates among them, rewrite
# recipes on the first tick) before it exits the JVM. Nothing connects to the production server; the copy listens
# on 127.0.0.1 only, on a spare port, with online-mode off.
#
# Then it builds the recipe database (tools/recipes/build_db.py) unless RECIPE_EXPORT_NO_DB=1, and stamps the
# `recipes` component with tools/packstate.py when that database is <root>/data/recipes.sqlite and the packs did
# not change during the run. A failed or partial export (oracle crash, timeout, a core adapter not "computed")
# builds nothing and stamps nothing.
#
# Our server pack's jars come from `packstate.py jars --fetch`: plain jars from the pack, URL mods from the
# sha256-checked cache in <root>/.work/tuxmine-jars (downloaded on first use). Only jars the server pack carries
# and packwiz would install on a server (side != client) are added.
#
# Environment (all optional):
#   DAVE_AGENT_ROOT      checkout whose tuxmine/, data/ and .work/ are used (default: this repo). Set it to the
#                        main checkout when running from a git worktree, which lacks the git-ignored data
#   TUXMINE_DIR          our packwiz packs         default <root>/tuxmine
#   RECIPE_EXPORT_WORK   scratch dir               default <root>/.work/recipe-export
#   RECIPE_EXPORT_OUT    where the JSON lands       default <root>/data/exports/recipes
#   DAVE_RECIPES_DB      the database to build      default <root>/data/recipes.sqlite
#   JAVA                 java binary (17+)          default /usr/lib/jvm/java-25-openjdk/bin/java, else `java`
#   JAVA_HOME_BUILD      JDK for the Gradle build (default: the JDK of $JAVA if it has javac, else java-25)
#   RECIPE_EXPORT_MEM    max heap                   default 6G (GTNH 2.9.0 needs about 5-6 GB)
#   RECIPE_EXPORT_LOCK   lock file; only one heavy JVM at a time across agents  default /tmp/dave-agent-heavy-jvm.lock
#   RECIPE_EXPORT_TIMEOUT seconds                   default 3600
#   RECIPE_EXPORT_PORT   server port                default 25599
#   RECIPE_EXPORT_SKIP   space-separated jar-name prefixes from the server pack to leave out
#                        default "davebridge DiscordIntegration journeymap" (no recipes; DaveBridge opens a
#                        WebSocket listener and DiscordIntegration logs in to Discord)
#   ORACLE_JAR           use this oracle jar instead of building tools/recipe-export/oracle
#   RECIPE_EXPORT_HOST   run the server on this ssh host instead (e.g. a big build box). The oracle jar is built
#                        and our mods are resolved here; run.sh, the staged mods/configs and the pack are rsynced to
#                        RECIPE_EXPORT_REMOTE_DIR (required with HOST), the export runs there with
#                        RECIPE_EXPORT_REMOTE_JAVA (default `java`), and the JSON is rsynced back to RECIPE_EXPORT_OUT.
#                        The database is always built (and stamped) here. Nothing is left running on the host.
#   RECIPE_EXPORT_STAGED internal: a staged mods/ + config/ + stage.json dir to use instead of resolving the pack
#                        (the remote run gets this; it has no tuxmine/ and no packstate.py)
set -euo pipefail

usage() { sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[[ $# -eq 1 && "$1" != -h && "$1" != --help ]] || usage

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
pack_dir="$(cd "$1" && pwd)"
root="${DAVE_AGENT_ROOT:-$repo}"
root="$(cd "$root" && pwd)"
tux="${TUXMINE_DIR:-$root/tuxmine}"
work="${RECIPE_EXPORT_WORK:-$root/.work/recipe-export}"
out="${RECIPE_EXPORT_OUT:-$root/data/exports/recipes}"
db="${DAVE_RECIPES_DB:-$root/data/recipes.sqlite}"
mem="${RECIPE_EXPORT_MEM:-6G}"
lock="${RECIPE_EXPORT_LOCK:-/tmp/dave-agent-heavy-jvm.lock}"
timeout_s="${RECIPE_EXPORT_TIMEOUT:-3600}"
port="${RECIPE_EXPORT_PORT:-25599}"
skip="${RECIPE_EXPORT_SKIP:-davebridge DiscordIntegration journeymap}"
server_pack="$tux/server"
staged="${RECIPE_EXPORT_STAGED:-}"

if [[ -n "${JAVA:-}" ]]; then java_bin="$JAVA"
elif [[ -x /usr/lib/jvm/java-25-openjdk/bin/java ]]; then java_bin=/usr/lib/jvm/java-25-openjdk/bin/java
else java_bin="$(command -v java)"; fi

log() { printf '[recipe-export %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

for f in lwjgl3ify-forgePatches.jar java9args.txt mods config; do
  [[ -e "$pack_dir/$f" ]] || die "$pack_dir is not a GTNH Java 17+ server directory (no $f)"
done
case "$work" in ""|/|"$HOME"|"$repo"|"$root") die "refusing RECIPE_EXPORT_WORK=$work";; esac

log "pack: $pack_dir"

# packstate.py with this run's packs (the pack dir given, $TUXMINE_DIR, $DAVE_AGENT_ROOT)
packstate() {
  DAVE_AGENT_ROOT="$root" TUXMINE_DIR="$tux" GTNH_PACK_DIR="$pack_dir" python3 -I "$repo/tools/packstate.py" "$@"
}
recipes_fingerprint() {
  packstate show | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["fingerprints"]["recipes"])'
}

# ---------------------------------------------------------------- 0. our server pack: mods and configs, staged
if [[ -n "$staged" ]]; then
  [[ -f "$staged/stage.json" && -d "$staged/mods" ]] || die "RECIPE_EXPORT_STAGED=$staged is not a staged dir"
else
  [[ -f "$server_pack/pack.toml" ]] || die "no $server_pack/pack.toml (set TUXMINE_DIR or DAVE_AGENT_ROOT)"
  case "$work" in "$tux"|"$tux"/*) die "refusing RECIPE_EXPORT_WORK inside $tux";; esac
  staged="$work/stage"
  rm -rf "$staged"
  mkdir -p "$staged/mods" "$staged/config"
  fingerprint="$(recipes_fingerprint)"
  log "resolving $server_pack (packstate recipes fingerprint $fingerprint)"
  packstate jars --fetch > "$staged/jars.json"
  skipped() { local n="${1,,}" p; for p in $skip; do [[ "$n" == "${p,,}"* ]] && return 0; done; return 1; }
  while IFS=$'\t' read -r name path; do
    if skipped "$name"; then log "skip $name"; continue; fi
    [[ -f "$path" ]] || die "no file for $name ($path)"
    cp "$path" "$staged/mods/$name"
  done < <(python3 -I -c '
import json, sys
for e in json.load(open(sys.argv[1], encoding="utf-8")):
    if "server" in e["packs"] and e.get("pw_side") != "client":
        print(e["name"] + "\t" + (e["path"] or ""))' "$staged/jars.json")
  if [[ -d "$server_pack/config" ]]; then cp -r "$server_pack/config/." "$staged/config/"; fi
  python3 -I - "$staged" "$server_pack/pack.toml" "$fingerprint" <<'PY'
import hashlib, json, os, sys, tomllib
staged, toml, fp = sys.argv[1:]
pack = tomllib.loads(open(toml, encoding="utf-8").read())
cfg = os.path.join(staged, "config")
configs = {}
for d, _, files in os.walk(cfg):
    for f in files:
        p = os.path.join(d, f)
        configs[os.path.relpath(p, cfg)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
info = {"tuxmine_server_version": pack.get("version"), "tuxmine_server_index_hash": pack.get("index", {}).get("hash"),
        "packstate": {"component": "recipes", "fingerprint": fp},
        "added_mods": sorted(os.listdir(os.path.join(staged, "mods")), key=str.lower),
        "tuxmine_configs": dict(sorted(configs.items()))}
json.dump(info, open(os.path.join(staged, "stage.json"), "w", encoding="utf-8"), indent=2)
PY
fi
fingerprint="$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["packstate"]["fingerprint"])' \
  "$staged/stage.json")"

# Stamp `recipes` after a successful database build, if that database is the one packstate tracks and the packs
# are still the ones this run exported.
stamp_recipes() {
  local want now
  want="$(realpath -m "$root/data/recipes.sqlite")"
  if [[ "$(realpath -m "$db")" != "$want" ]]; then
    log "not stamping recipes: $db is not $want"; return 0
  fi
  now="$(recipes_fingerprint)"
  if [[ "$now" != "$fingerprint" ]]; then
    log "WARNING: the packs changed during the export ($fingerprint -> $now); not stamping recipes. Run again."
    return 0
  fi
  packstate stamp recipes --note "tools/recipe-export/run.sh: $(python3 -I -c '
import json, sys; i = json.load(open(sys.argv[1])); print("tuxmine-server %s, export %s" % (
    i.get("tuxmine_server_version"), i.get("finished_at")))' "$out/run-info.json")"
}

build_db() {
  log "building $db"
  python3 -I "$repo/tools/recipes/build_db.py" "$out/oracle-export.json" "$db" --run-info "$out/run-info.json"
  stamp_recipes
}

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
  ssh "${ssh_opts[@]}" "$host" "mkdir -p '$rdir/repo/tools/recipe-export' '$rdir/stage' '$rdir/out'"
  rsync -a --delete "$here/run.sh" "$host:$rdir/repo/tools/recipe-export/run.sh"
  rsync -a --delete "$staged/" "$host:$rdir/stage/"
  rsync -a --delete --exclude 'World/' --exclude 'logs/' --exclude 'crash-reports/' "$pack_dir/" "$host:$rdir/pack/"
  rsync -a "$oracle_jar" "$host:$rdir/$(basename "$oracle_jar")"
  set +e
  ssh "${ssh_opts[@]}" "$host" "cd '$rdir' && RECIPE_EXPORT_NO_DB=1 ORACLE_JAR='$rdir/$(basename "$oracle_jar")' \
    JAVA='${RECIPE_EXPORT_REMOTE_JAVA:-java}' RECIPE_EXPORT_PORT='$port' RECIPE_EXPORT_MEM='$mem' \
    RECIPE_EXPORT_TIMEOUT='$timeout_s' RECIPE_EXPORT_LOCK='$rdir/.lock' RECIPE_EXPORT_STAGED='$rdir/stage' \
    RECIPE_EXPORT_WORK='$rdir/work' RECIPE_EXPORT_OUT='$rdir/out' bash '$rdir/repo/tools/recipe-export/run.sh' '$rdir/pack'"
  code=$?
  set -e
  # whatever happened, make sure no server of ours is left running there
  ssh "${ssh_opts[@]}" "$host" "pkill -f -- '-Dgtnh.oracle.outputDir=$rdir/' || true" || true
  [[ $code -eq 0 ]] || die "remote export failed ($code); log: $host:$rdir/work/server.log"
  mkdir -p "$out"
  rm -f "$out/oracle-export.json" "$out/run-info.json"
  rsync -a "$host:$rdir/out/" "$out/"
  [[ -f "$out/oracle-export.json" && -f "$out/run-info.json" ]] || die "the remote run left no export in $rdir/out"
  log "export: $out/oracle-export.json ($(du -h "$out/oracle-export.json" | cut -f1)) from $host"
  if [[ "${RECIPE_EXPORT_NO_DB:-0}" != 1 ]]; then build_db; fi
  log "done"
  exit 0
fi

java_major="$("$java_bin" -XshowSettings:properties -version 2>&1 | sed -n 's/.*java.specification.version = //p')"
[[ "${java_major:-0}" -ge 17 ]] || die "$java_bin is Java ${java_major:-?}; GTNH via lwjgl3ify needs 17+"
log "java: $java_bin (Java $java_major)"

# ---------------------------------------------------------------- 2. throwaway server copy
server="$work/server"
records="$work/oracle-records"
mkdir -p "$work"
rm -rf "$server" "$records"
log "copying the server to $server"
cp -a --reflink=auto "$pack_dir" "$server"
rm -rf "$server/World" "$server/logs" "$server/crash-reports" "$server/GTNH-Calc-Oracle"
find "$server/mods" -maxdepth 1 -iname '*gtnh*calc*oracle*.jar' -delete

added=()
for jar in "$staged"/mods/*.jar; do
  [[ -e "$jar" ]] || continue
  cp "$jar" "$server/mods/"; added+=("$(basename "$jar")")
done
if [[ -d "$staged/config" ]]; then cp -r "$staged/config/." "$server/config/"; fi
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
    "$elapsed" "${pack_version:-unknown}" "$staged/stage.json" <<'PY'
import hashlib, json, os, sys, time
out, pack_dir, mods, jar, java, major, elapsed, version, stage = sys.argv[1:]
stage = json.load(open(stage, encoding="utf-8"))
info = {
    "pack_version": version, "tuxmine_server_version": stage.get("tuxmine_server_version"),
    "tuxmine_server_index_hash": stage.get("tuxmine_server_index_hash"), "packstate": stage.get("packstate"),
    "pack_dir": pack_dir, "added_mods": stage.get("added_mods"), "tuxmine_configs": stage.get("tuxmine_configs"),
    "mod_jars": sorted(f for f in os.listdir(mods) if f.endswith(".jar")),
    "oracle_jar": os.path.basename(jar), "oracle_sha256": hashlib.sha256(open(jar, "rb").read()).hexdigest(),
    "java": java, "java_major": int(major), "export_seconds": int(elapsed),
    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
}
json.dump(info, open(out, "w"), indent=2)
PY
log "export: $out/oracle-export.json ($(du -h "$out/oracle-export.json" | cut -f1))"

if [[ "${RECIPE_EXPORT_NO_DB:-0}" != 1 ]]; then build_db; fi
log "done"
