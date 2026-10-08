# -*- coding: utf-8 -*-
"""从《Your Fiancée》的 CharacterVoice AssetBundle 里导出全部角色语音。"""
import json
import os
import sys

import UnityPy

SRC = r"D:\steam\steamapps\common\Your Fiancée\Your Fiancée_Data\StreamingAssets\CharacterVoice"
OUT = r"D:\AI\YourFiancee-语音"


def main():
    cat = json.load(open(os.path.join(SRC, 'catalog.json'), encoding='utf-8'))
    entries = cat['entries']
    os.makedirs(OUT, exist_ok=True)

    seq = {}
    ok = fail = 0
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for e in entries:
        folder = e['folder']
        bundle = os.path.join(SRC, e['bundle'])
        if only and only not in bundle:
            continue
        seq[folder] = seq.get(folder, 0) + 1
        try:
            env = UnityPy.load(bundle)
            got = 0
            for obj in env.objects:
                if obj.type.name != 'AudioClip':
                    continue
                clip = obj.read()
                try:
                    samples = clip.samples
                except Exception as ex:
                    print('  [%s] 解码失败: %s' % (e['bundle'], ex))
                    continue
                for i, (nm, data) in enumerate(samples.items()):
                    suffix = '' if len(samples) == 1 else '_%d' % i
                    dst = os.path.join(OUT, folder, '%s_%02d%s.wav' % (folder, seq[folder], suffix))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, 'wb') as f:
                        f.write(data)
                    got += 1
            if got:
                ok += 1
                print('%-14s %-46s -> %d 个音频  %s' % (folder, e['bundle'], got, os.path.basename(os.path.dirname(dst))))
            else:
                fail += 1
                print('%-14s %-46s -> 没有音频对象' % (folder, e['bundle']))
        except Exception as ex:
            fail += 1
            print('%-14s %-46s -> 出错: %s' % (folder, e['bundle'], ex))
    print('\n完成：成功 %d，失败 %d，输出目录 %s' % (ok, fail, OUT))


if __name__ == '__main__':
    main()
