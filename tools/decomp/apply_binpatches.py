#!/usr/bin/env python3
"""Apply Forge 1.7.10 binpatches (GDiff, as read by FML ClassPatchManager) to the vanilla server jar.

usage: apply_binpatches.py minecraft_server.jar binpatches.jar SIDE out.jar
Classes Forge creates from scratch under net.minecraft.client.* are skipped.
Keeps only Minecraft's own classes (root-package notch classes + net/minecraft/**),
dropping the libraries bundled into the server jar.
"""
import io, struct, sys, zipfile, zlib


def read_utf(b, o):
    n = struct.unpack_from('>H', b, o)[0]; o += 2
    return b[o:o + n].decode('utf-8'), o + n


def gdiff(src, patch):
    p = io.BytesIO(patch)
    if p.read(5) != b'\xd1\xff\xd1\xff\x04':
        raise ValueError('bad gdiff magic')
    out = bytearray()
    rd = lambda fmt: struct.unpack('>' + fmt, p.read(struct.calcsize(fmt)))[0]
    while True:
        c = p.read(1)[0]
        if c == 0:
            return bytes(out)
        if c <= 246:
            out += p.read(c)
        elif c == 247:
            out += p.read(rd('H'))
        elif c == 248:
            out += p.read(rd('i'))
        else:
            off_fmt, len_fmt = {249: 'HB', 250: 'HH', 251: 'Hi', 252: 'iB', 253: 'iH', 254: 'ii', 255: 'qi'}[c]
            off = rd(off_fmt[0]); ln = rd(len_fmt[-1])
            out += src[off:off + ln]


def main(server, patches, side, out):
    sz = zipfile.ZipFile(server)
    classes = {n: sz.read(n) for n in sz.namelist()
               if n.endswith('.class') and ('/' not in n or n.startswith('net/minecraft/'))}
    pz = zipfile.ZipFile(patches)
    applied = created = missing = badsum = skipped_client = 0
    for n in pz.namelist():
        if not n.startswith(f'binpatch/{side}/') or not n.endswith('.binpatch'):
            continue
        b = pz.read(n)
        name, o = read_utf(b, 0)
        src_name, o = read_utf(b, o)
        tgt_name, o = read_utf(b, o)
        exists = b[o] != 0; o += 1
        checksum = None
        if exists:
            checksum = struct.unpack_from('>I', b, o)[0]; o += 4
        plen = struct.unpack_from('>i', b, o)[0]; o += 4
        patch = b[o:o + plen]
        key = src_name.replace('.', '/') + '.class'
        if exists:
            if key not in classes:
                missing += 1; continue
            src = classes[key]
            if zlib.adler32(src) & 0xffffffff != checksum:
                badsum += 1
            classes[key] = gdiff(src, patch); applied += 1
        elif tgt_name.startswith('net.minecraft.client.'):
            skipped_client += 1  # client-only class Forge would synthesize; useless on a dedicated server
        else:
            classes[key] = gdiff(b'', patch); created += 1
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as o:
        for k in sorted(classes):
            o.writestr(k, classes[k])
    print(f'classes={len(classes)} patched={applied} created={created} missing_src={missing} bad_checksum={badsum} skipped_client_created={skipped_client}')


if __name__ == '__main__':
    main(*sys.argv[1:5])
