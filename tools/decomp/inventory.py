#!/usr/bin/env python3
"""Inventory jars: class counts per top-level package (3 segments), nested jars, mcmod.info presence."""
import sys, zipfile, collections, os
for jp in sys.argv[1:]:
    z = zipfile.ZipFile(jp)
    c = collections.Counter(); nested=[]; total=0; res=collections.Counter()
    for n in z.namelist():
        if n.endswith('.class'):
            total += 1; c['/'.join(n.split('/')[:3]) if n.count('/')>=3 else '/'.join(n.split('/')[:-1])] += 1
        elif n.endswith('.jar') or n.endswith('.zip'): nested.append(n)
        elif not n.endswith('/'): res[os.path.splitext(n)[1].lower()] += 1
    top = ', '.join(f'{k}:{v}' for k,v in c.most_common(4))
    print(f'{os.path.basename(jp)}\t{total}\t{top}\tNESTED={nested[:5]}' )
