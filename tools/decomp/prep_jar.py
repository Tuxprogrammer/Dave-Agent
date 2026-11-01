#!/usr/bin/env python3
"""Build a filtered copy of a mod jar for decompilation.

- Multi-release jars: for each class, keep the highest META-INF/versions/N copy
  (that is what a Java 17+ JVM loads), written at its normal path.
- Drops shaded third-party subtrees (any path segment shadow/ repack/ repackage/).
- Keeps only small text resources that matter (mcmod.info, lang, json, cfg, lua, ...).
  Textures, sounds, models, natives, nested archives are dropped.

usage: prep_jar.py SRC.jar OUT.jar STATS.json
"""
import json, os, re, sys, zipfile

SHADED = re.compile(r'(^|/)(shadow|repack|repackage)/')
MRJ = re.compile(r'^META-INF/versions/(\d+)/(.+)$')
KEEP_EXT = {'.info', '.lang', '.json', '.txt', '.cfg', '.properties', '.xml', '.lua',
            '.zs', '.js', '.groovy', '.toml', '.yml', '.yaml', '.csv', '.md', '.mf', '.at', '.list'}
DROP_DIRS = re.compile(r'(^|/)(textures|sounds|models|blockstates|shaders|fonts|font)/')


def main(src, out, stats_path):
    z = zipfile.ZipFile(src)
    classes = {}  # path -> (version, zipinfo)
    resources = []
    st = {'classes_in': 0, 'shaded_dropped': 0, 'mrj_overrides': 0, 'mrj_versions': set(),
          'resources_kept': 0, 'resources_dropped': 0, 'shaded_roots': set()}
    for info in z.infolist():
        n = info.filename
        if n.endswith('/'):
            continue
        if n.endswith('.class'):
            st['classes_in'] += 1
            ver, path = 0, n
            m = MRJ.match(n)
            if m:
                ver, path = int(m.group(1)), m.group(2)
                st['mrj_versions'].add(ver)
            if path == 'module-info.class':
                continue
            sm = SHADED.search(path)
            if sm:
                st['shaded_dropped'] += 1
                st['shaded_roots'].add(path[:sm.end()])
                continue
            prev = classes.get(path)
            if prev is None or ver > prev[0]:
                if prev is not None:
                    st['mrj_overrides'] += 1
                classes[path] = (ver, info)
            else:
                st['mrj_overrides'] += 1
            continue
        if MRJ.match(n):
            st['resources_dropped'] += 1
            continue
        ext = os.path.splitext(n)[1].lower()
        base = os.path.basename(n).lower()
        if (ext in KEEP_EXT or base in ('mcmod.info', 'pack.mcmeta')) and not DROP_DIRS.search(n) \
                and not SHADED.search(n) and info.file_size < 8 * 1024 * 1024:
            resources.append(info)
            st['resources_kept'] += 1
        else:
            st['resources_dropped'] += 1
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as o:
        for path, (ver, info) in sorted(classes.items()):
            o.writestr(path, z.read(info))
        for info in resources:
            o.writestr(info.filename, z.read(info))
    st['classes_out'] = len(classes)
    st['mrj_versions'] = sorted(st['mrj_versions'])
    st['shaded_roots'] = sorted(st['shaded_roots'])
    with open(stats_path, 'w') as f:
        json.dump(st, f, indent=1)


if __name__ == '__main__':
    main(*sys.argv[1:4])
