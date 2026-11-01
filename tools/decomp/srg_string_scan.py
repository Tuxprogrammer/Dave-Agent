#!/usr/bin/env python3
"""List jars whose classes contain SRG-looking *string constants* (CONSTANT_String), e.g. reflection names.
usage: srg_string_scan.py JAR...   -> prints "<jar>\t<count>\t<examples>"
"""
import re, struct, sys, zipfile
SRG = re.compile(rb'^(field_\d+_[A-Za-z]+_?|func_\d+_[A-Za-z]+_?)$')

def strings(b):
    n = struct.unpack_from('>H', b, 8)[0]; o = 10; utf = {}; sidx = []; i = 1
    while i < n:
        t = b[o]
        if t == 1:
            ln = struct.unpack_from('>H', b, o + 1)[0]; utf[i] = b[o + 3:o + 3 + ln]; o += 3 + ln
        elif t == 8:
            sidx.append(struct.unpack_from('>H', b, o + 1)[0]); o += 3
        elif t in (7, 16, 19, 20): o += 3
        elif t == 15: o += 4
        elif t in (3, 4, 9, 10, 11, 12, 17, 18): o += 5
        elif t in (5, 6): o += 9; i += 1
        else: raise ValueError(f'tag {t}')
        i += 1
    return [utf[j] for j in sidx if j in utf]

for jp in sys.argv[1:]:
    z = zipfile.ZipFile(jp); hits = []
    for nm in z.namelist():
        if nm.endswith('.class'):
            try:
                hits += [s.decode() for s in strings(z.read(nm)) if SRG.match(s)]
            except Exception as e:
                print(f'# parse error {jp}:{nm}: {e}', file=sys.stderr)
    if hits:
        print(f'{jp}\t{len(hits)}\t{",".join(sorted(set(hits))[:4])}')
