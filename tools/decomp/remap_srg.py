#!/usr/bin/env python3
"""Token-level SRG -> MCP rename of decompiled .java and .kt files, in place.

Replaces field_NNN_x / func_NNN_x (fields.csv, methods.csv) and p_NNN_N_ / p_iNNN_N_ (params.csv).
SRG names are globally unique, so no type context is needed. Unmapped names are left as-is.
String and char literals are NOT touched: SRG names in strings (reflection lookups such as
ReflectionHelper.findField(cls, "inventory", "field_71071_by")) are what a production server needs.

usage: remap_srg.py MAPPINGS_DIR STATS.json DIR [DIR...]
"""
import csv, json, os, re, sys
from multiprocessing import Pool

TOKEN = re.compile(r'\b(?:field_\d+_[A-Za-z]+_?|func_\d+_[A-Za-z]+_?|p_i?\d+_\d+_)\b')
# Scanned left to right: comments and literals are consumed whole, so tokens inside them are seen in context.
LEXER = re.compile(r'(?P<cmt>//[^\n]*|/\*[\s\S]*?\*/)'
                   r'|(?P<lit>"""[\s\S]*?"""|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)+\')'
                   r'|(?P<tok>' + TOKEN.pattern + ')')
MAP = {}


def load(mdir):
    m = {}
    for fn, key in (('fields.csv', 'searge'), ('methods.csv', 'searge'), ('params.csv', 'param')):
        with open(os.path.join(mdir, fn), newline='') as f:
            for row in csv.DictReader(f):
                m[row[key]] = row['name']
    return m


def init(mdir):
    global MAP
    MAP = load(mdir)


def work(path):
    with open(path, encoding='utf-8', errors='surrogateescape') as f:
        src = f.read()
    hits = [0, 0, 0]
    unmapped = set()

    def sub(mt):
        t = mt.group(0)
        n = MAP.get(t)
        if n is None:
            hits[1] += 1; unmapped.add(t)
            return t
        hits[0] += 1
        return n

    def lex(mt):
        if mt.group('lit') is not None:
            if TOKEN.search(mt.group('lit')):
                hits[2] += 1
            return mt.group('lit')
        if mt.group('cmt') is not None:
            return TOKEN.sub(sub, mt.group('cmt'))
        return sub(mt)

    out = LEXER.sub(lex, src)
    if hits[0]:
        with open(path, 'w', encoding='utf-8', errors='surrogateescape') as f:
            f.write(out)
    return path, hits[0], hits[1], unmapped, hits[2]


def main():
    mdir, stats_path, dirs = sys.argv[1], sys.argv[2], sys.argv[3:]
    files = [os.path.join(dp, f) for d in dirs for dp, _, fs in os.walk(d) for f in fs if f.endswith(('.java', '.kt'))]
    tot = [0, 0, 0, 0]; unmapped = {}
    per_dir = {}
    with Pool(os.cpu_count(), initializer=init, initargs=(mdir,)) as p:
        for path, r, u, un, sl in p.imap_unordered(work, files, chunksize=64):
            tot[0] += 1; tot[1] += r; tot[2] += u; tot[3] += sl
            top = next((d for d in dirs if path.startswith(d.rstrip('/') + '/')), '?')
            pd = per_dir.setdefault(os.path.basename(top.rstrip('/')), [0, 0])
            pd[0] += r; pd[1] += u
            for t in un:
                unmapped[t] = unmapped.get(t, 0) + 1
    st = {'files': tot[0], 'replaced': tot[1], 'unmapped_occurrences': tot[2],
          'unmapped_distinct': len(unmapped), 'string_literals_with_srg_kept': tot[3],
          'unmapped_sample': sorted(unmapped, key=lambda k: -unmapped[k])[:50], 'per_dir': per_dir}
    with open(stats_path, 'w') as f:
        json.dump(st, f, indent=1)
    print({k: v for k, v in st.items() if k not in ('per_dir', 'unmapped_sample')})


if __name__ == '__main__':
    main()
