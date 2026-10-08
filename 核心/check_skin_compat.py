# -*- coding: utf-8 -*-
"""War Thunder user-skin interoperability checker.

战雷自制涂装「跨载具共用」核对工具

用法（在游戏根目录下，或直接指定 UserSkins 路径）:
    python check_skin_compat.py "D:\\steam\\steamapps\\common\\War Thunder"
    python check_skin_compat.py "D:\\steam\\steamapps\\common\\War Thunder\\UserSkins"

它做什么：
  1) 扫描 UserSkins 下每个 template_* 文件夹里的 .blk，解析出
     replace_tex / set_tex 的 from（被替换的原纹理）与 to（你的新纹理）；
  2) 把「引用了同一批原纹理」的载具聚成共用组——同组 = 涂装可以互相通用；
  3) 反过来列出「每台车独有的原纹理」——这些部件不能照搬（典型：不同炮管、不同裙板）；
  4) 顺带做一遍市场合规自检（文件名只能英文数字、blk 与文件必须一一对应、大小写一致）。
"""
import os
import re
import sys
from collections import defaultdict

TEX_BLOCK = re.compile(r'(replace_tex|set_tex)\s*\{(.*?)\}', re.S)
FIELD = re.compile(r'(from|to|param)\s*:\s*t\s*=\s*"([^"]+)"')


def parse_blk(path):
    """返回 (replace_from, set_from, to_list)"""
    txt = open(path, "r", encoding="utf-8", errors="replace").read()
    rep, setf, tos = [], [], []
    for kind, body in TEX_BLOCK.findall(txt):
        fields = dict(FIELD.findall(body))
        src, dst = fields.get("from"), fields.get("to")
        if dst:
            tos.append(dst)
        if not src:
            continue
        if kind == "set_tex" and fields.get("param") == "camo_skin_tex":
            setf.append(src)
        else:
            rep.append(src)
    return rep, setf, tos


def norm(pattern):
    """from:t="us_camo_olive*" → us_camo_olive"""
    return pattern.rstrip("*").strip()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    root = sys.argv[1]
    skins = root if os.path.basename(root).lower() == "userskins" else os.path.join(root, "UserSkins")
    if not os.path.isdir(skins):
        print("找不到 UserSkins 目录：%s" % skins)
        print("（先在游戏个性化菜单里点一次「创建迷彩示例」，它才会被创建）")
        return 1

    veh = {}
    for name in sorted(os.listdir(skins)):
        folder = os.path.join(skins, name)
        if not os.path.isdir(folder):
            continue
        blks = [f for f in os.listdir(folder) if f.lower().endswith(".blk")]
        if not blks:
            continue
        rep, setf, tos = [], [], []
        for b in blks:
            r, s, t = parse_blk(os.path.join(folder, b))
            rep += r
            setf += s
            tos += t
        veh[name] = {"blk": blks, "replace": rep, "set": setf, "to": tos, "dir": folder}

    if not veh:
        print("UserSkins 里没有找到任何带 .blk 的涂装文件夹。")
        return 1

    print("=" * 78)
    print("共发现 %d 套涂装（每个文件夹 = 一台车的一次「创建迷彩示例」）" % len(veh))
    print("=" * 78)
    for v, d in veh.items():
        print("\n● %s" % v)
        print("   blk: %s" % ", ".join(d["blk"]))
        if d["set"]:
            print("   固定(set_tex，可贴贴花) %d 项：" % len(d["set"]))
            for s in d["set"]:
                print("      - %s" % s)
        if d["replace"]:
            print("   可缩放/替换(replace_tex) %d 项：" % len(d["replace"]))
            for s in d["replace"]:
                print("      - %s" % s)
        if not d["set"] and not d["replace"]:
            print("   [!] 没解析到任何 from:t=，请检查 blk 内容。")

    by_tex = defaultdict(set)
    for v, d in veh.items():
        for s in d["replace"] + d["set"]:
            by_tex[norm(s)].add(v)

    shared = {t: vs for t, vs in by_tex.items() if len(vs) > 1}
    unique = {t: vs for t, vs in by_tex.items() if len(vs) == 1}

    print("\n" + "=" * 78)
    print("一、被两台以上载具共用的原纹理（这些部件完全通用）")
    print("=" * 78)
    if not shared:
        print("  （没有共用；说明这几台车的纹理名互不相同）")
    for t, vs in sorted(shared.items(), key=lambda x: -len(x[1])):
        print("  %-42s <- %s" % (t, "、".join(sorted(vs))))

    print("\n" + "=" * 78)
    print("二、每台车独有的原纹理（这些部件不可照搬，要单独画）")
    print("=" * 78)
    only = defaultdict(list)
    for t, vs in unique.items():
        only[list(vs)[0]].append(t)
    for v in sorted(only):
        if only[v]:
            print("  ● %s 独有 %d 项：" % (v, len(only[v])))
            for t in sorted(only[v]):
                print("      - %s" % t)

    print("\n" + "=" * 78)
    print("三、结论：哪些载具可以整包直接互换")
    print("=" * 78)
    reported = set()
    for v, d in veh.items():
        a = set(map(norm, d["replace"] + d["set"]))
        for w, e in veh.items():
            if w == v or (v, w) in reported:
                continue
            b = set(map(norm, e["replace"] + e["set"]))
            if not a or not b:
                continue
            if a == b:
                reported.add((v, w)); reported.add((w, v))
                print("  [==] %s 与 %s：完全通用（可直接复制整个文件夹）"
                      % (v.replace("template_", ""), w.replace("template_", "")))
            elif a & b:
                reported.add((v, w)); reported.add((w, v))
                print("  [~ ] %s 与 %s：部分通用（%d 项相同，%d 项只属于一边）→ 可移植，独有部件要另画"
                      % (v.replace("template_", ""), w.replace("template_", ""),
                         len(a & b), len(a ^ b)))
    if len(veh) == 1:
        print("  只扫描到一个文件夹——把要对比的载具都先「创建迷彩示例」，再跑一次。")
    if not reported and len(veh) > 1:
        print("  没有任何一对共用纹理 → 这些车的涂装不能互相移植。")

    print("\n" + "=" * 78)
    print("四、市场合规自检（提交 WT Live / 奖杯前过一遍）")
    print("=" * 78)
    for v, d in veh.items():
        files = set(os.listdir(d["dir"]))
        problems = []
        if len(d["blk"]) != 1:
            problems.append("blk 数量=%d（要求恰好 1 个）" % len(d["blk"]))
        for f in files:
            if os.path.isdir(os.path.join(d["dir"], f)):
                continue
            stem = os.path.splitext(f)[0]
            if not re.fullmatch(r"[A-Za-z0-9_]+", stem):
                problems.append("文件名含非法字符（只能英文/数字/下划线）：%s" % f)
        for t in d["to"]:
            if t not in files:
                problems.append("blk 引用了不存在的纹理（或大小写不一致）：%s" % t)
        texs = {f for f in files if f.lower().endswith((".dds", ".tga"))}
        extra = texs - set(d["to"])
        if extra:
            problems.append("包里有 blk 未引用的纹理：%s" % "、".join(sorted(extra)))
        print("  ● %s：%s" % (v, "OK 通过" if not problems else "[!] " + "；".join(problems)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
