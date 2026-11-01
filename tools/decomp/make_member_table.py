#!/usr/bin/env python3
"""Write a class-aware member table: one row per vanilla field/method declared in joined.srg.

Columns: class (MCP/SRG class name, slash form), kind (field|method), mcp_name, srg_name,
notch_owner, notch_name, srg_desc (methods only).
On a production (obfuscated) Forge server, reflection must use srg_name.

usage: make_member_table.py MAPPINGS_DIR OUT.tsv
"""
import csv, os, sys


def main(mdir, out):
    names = {}
    for fn in ('fields.csv', 'methods.csv'):
        with open(os.path.join(mdir, fn), newline='') as f:
            for r in csv.DictReader(f):
                names[r['searge']] = r['name']
    rows = []
    with open(os.path.join(mdir, 'joined.srg')) as f:
        for line in f:
            p = line.split()
            if p[0] == 'FD:':
                no, nn = p[1].rsplit('/', 1); so, sn = p[2].rsplit('/', 1)
                rows.append((so, 'field', names.get(sn, sn), sn, no, nn, ''))
            elif p[0] == 'MD:':
                no, nn = p[1].rsplit('/', 1); so, sn = p[3].rsplit('/', 1)
                rows.append((so, 'method', names.get(sn, sn), sn, no, nn, p[4]))
    rows.sort()
    with open(out, 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(['class', 'kind', 'mcp_name', 'srg_name', 'notch_owner', 'notch_name', 'srg_desc'])
        w.writerows(rows)
    print(len(rows), 'rows')


if __name__ == '__main__':
    main(*sys.argv[1:3])
