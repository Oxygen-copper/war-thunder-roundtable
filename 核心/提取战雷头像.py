# -*- coding: utf-8 -*-
"""把战雷 ui\\images.vromfs.bin 里的所有头像 / 头像框按原名导出。"""
import os
import re
import struct

SRC_DEFAULT = r"D:\steam\steamapps\common\War Thunder\ui\images.vromfs.bin"
TBL = 278816
PAT = re.compile(rb'[A-Za-z0-9_\-\./+]{4,120}\.(?:avif|ddsx|tga|dds)\x00')
PREFIXES = ('images/avatars/', 'images/avatar_frames/', 'images/profile_headers/')


def main():
    import argparse
    ap = argparse.ArgumentParser(description='从战雷 ui\\images.vromfs.bin 导出全部头像')
    ap.add_argument('--src', default=SRC_DEFAULT, help='游戏里的 ui\\images.vromfs.bin')
    ap.add_argument('--out', default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '头像'), help='输出目录')
    a = ap.parse_args()
    src, out = a.src, a.out
    if not os.path.isfile(src):
        raise SystemExit('找不到文件：' + src)
    data = open(src, 'rb').read()
    hits = [(m.start(), m.group(0)[:-1].decode()) for m in PAT.finditer(data)]
    groups, cur = [], [hits[0]]
    for (o1, n1), (o2, n2) in zip(hits, hits[1:]):
        if o2 - o1 <= len(n1) + 24:
            cur.append((o2, n2))
        else:
            groups.append(cur)
            cur = [(o2, n2)]
    groups.append(cur)
    names = []
    for g in groups:
        if len(g) >= 8:
            names.extend(n for _o, n in g)
    avif = [n for n in names if n.endswith('.avif')]

    recs = []
    for i in range(5900):
        off, size, _a, _b = struct.unpack_from('<4I', data, TBL + i * 16)
        start = off + 16
        if data[start + 4:start + 8] != b'ftyp':
            continue
        p, limit = start, off + size + 16
        while p + 8 <= len(data) and p < limit:
            bsz = int.from_bytes(data[p:p + 4], 'big')
            bty = data[p + 4:p + 8]
            if bsz < 8 or p + bsz > limit or not all(48 <= c < 123 for c in bty):
                break
            p += bsz
        recs.append(data[start:p])

    print('全局 .avif 名字 %d · AVIF 记录 %d' % (len(avif), len(recs)))
    os.makedirs(out, exist_ok=True)
    n = 0
    for k, nm in enumerate(avif):
        if not nm.startswith(PREFIXES) or k >= len(recs):
            continue
        sub = nm.split('/')[1]
        d = os.path.join(out, sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, os.path.basename(nm)), 'wb') as f:
            f.write(recs[k])
        n += 1
    print('已导出 %d 个到 %s' % (n, out))


if __name__ == '__main__':
    main()
