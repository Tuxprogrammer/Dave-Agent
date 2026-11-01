#!/usr/bin/env bash
# gregtech: Vineflower 1.12.0 needs >14 GB on gregtech/api/enums/ItemList (huge enum <clinit>),
# so that class is decompiled with CFR and everything else with Vineflower (full jar as library context).
# usage: gregtech_split.sh WORK_DIR(.work/gtnh-2.9.0) OUT_DIR(gtnh-src/mods/gregtech)
set -euo pipefail
# Absolute paths first: everything below runs after `cd "$S"`, so relative arguments would resolve there.
W=$(realpath -e "$1"); OUT=$(realpath -m "$2"); S=$W/gt-split; mkdir -p "$S"; cd "$S"
python3 -I - "$W/mods-work/prep/gregtech.jar" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
with zipfile.ZipFile('itemlist.jar', 'w') as a, zipfile.ZipFile('gt-rest.jar', 'w') as b:
    for n in z.namelist():
        (a if n.startswith('gregtech/api/enums/ItemList') else b).writestr(n, z.read(n))
PY
rm -rf out-rest out-itemlist "$OUT"
java -Xmx10g -jar "$W/tools/vineflower-1.12.0.jar" --folder --log-level=warn --thread-count=4 --indent-string="    " \
  --dump-bytecode-on-error=false -e="$W/mods-work/prep/gregtech.jar" gt-rest.jar out-rest > rest.log 2>&1
java -Xmx6g -jar "$W/tools/cfr-0.152.jar" itemlist.jar --extraclasspath "$W/mods-work/prep/gregtech.jar" --outputdir out-itemlist --silent true
mv out-rest "$OUT"
{ echo '// NOTE: decompiled with CFR 0.152 (Vineflower ran out of memory on this class).'; cat out-itemlist/gregtech/api/enums/ItemList.java; } > "$OUT/gregtech/api/enums/ItemList.java"
