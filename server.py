# -*- coding: utf-8 -*-
r"""
战雷圆桌工程 · 统一本地后端（纯 Python 标准库，不需要 pip 安装任何东西）

启动：双击 启动圆桌工程.bat   →   浏览器打开 http://127.0.0.1:8788

目录
    涂装\涂装库\      涂装母版
    涂装\色板\        GIMP 色板
    语音\原版\        从游戏里提取出来的原版乘员语音
    语音\工程\        每个语音包的工程（素材 / 转换结果 / bank）
    语音\成品\        打包好的可分发成品
    核心\            引擎（texconv / vgmstream / check_skin_compat）
    web\             前端
    config.json      路径与参数（首次运行自动生成）
"""

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
WEBROOT = os.path.join(BASE, 'web')
CORE = os.path.join(BASE, '核心')
CACHE = os.path.join(BASE, '_cache')
SKIN_ROOT = os.path.join(BASE, '涂装', '涂装库')
PALETTE = os.path.join(BASE, '涂装', '色板')
VOICE = os.path.join(BASE, '语音')
VOICE_ORIG = os.path.join(VOICE, '原版')
VOICE_PROJ = os.path.join(VOICE, '工程')
VOICE_REF = os.path.join(VOICE, '参考音色')
VOICE_PACK = os.path.join(VOICE, '成品')
TMP_IMPORT = os.path.join(BASE, '_import_tmp')
CONFIG_PATH = os.path.join(BASE, 'config.json')

TEXCONV = os.path.join(CORE, 'texconv.exe')
COMPAT = os.path.join(CORE, 'check_skin_compat.py')
VGM = os.path.join(CORE, 'vgmstream', 'vgmstream-cli.exe')
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
THUMB_MAX = 320
IMAGE_EXT = ('.tga', '.dds', '.png', '.bmp', '.jpg', '.jpeg')
AUDIO_EXT = ('.wav', '.mp3', '.flac', '.ogg', '.m4a', '.opus')

DEFAULT_CONFIG = {
    'game_root': '',
    'gimp': '',
    'port': 8788,
    'sdv_root': '',
    'tts_root': '',
    'uvr_root': '',
    'fmod_kit': '',
}

# 扩展（SDV / TTS）默认放在包内的这个目录下，用户解压进去即可
EXT_ROOT = os.path.join(BASE, '扩展')

# 语言代码 -> 显示名（游戏里实际存在的那些）
LANG_LABEL = {
    'en': '英语（英国）', 'en_us': '英语（美国）', 'en_au': '英语（澳洲）', 'en_za': '英语（南非）',
    'ru': '俄语', 'de': '德语', 'zh': '中文', 'jp': '日语', 'fr': '法语', 'it': '意大利语',
    'he': '希伯来语（以色列）', 'ar': '阿拉伯语', 'pl': '波兰语', 'cz': '捷克语', 'hu': '匈牙利语',
    'sr': '塞尔维亚语', 'ko': '韩语', 'th': '泰语', 'tr': '土耳其语', 'vi': '越南语',
    'pt': '葡萄牙语', 'sp': '西班牙语', 'fi': '芬兰语', 'nl': '荷兰语', 'sv': '瑞典语',
    'gl': '加利西亚语', 'lt': '立陶宛语', 'nw': '挪威语', 'hi': '印地语',
}
MAIN_LANGS = ['en', 'en_us', 'ru', 'de', 'zh', 'jp', 'fr', 'he']
# _crew_dialogs_ground_sm_XX —— 这六国的"第二套"陆战录音（内容仍是陆战台词）
SM_ALT = {'sm_uk': 'en', 'sm_us': 'en_us', 'sm_de': 'de', 'sm_jp': 'jp', 'sm_ru': 'ru', 'sm_zh': 'zh'}

_thumb_lock = threading.Lock()
_jobs = {}
_job_seq = [0]


# ================================================================= 配置

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                cfg.update({k: v for k, v in saved.items() if v not in (None, '')})
        except Exception:
            pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _steam_roots():
    roots = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                          (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ('SteamPath', 'InstallPath'):
                        try:
                            v = winreg.QueryValueEx(k, name)[0]
                            if v:
                                roots.append(str(v).replace('/', '\\'))
                        except OSError:
                            pass
            except OSError:
                pass
    except Exception:
        pass
    roots += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam',
              r'D:\steam', r'D:\Steam', r'E:\steam']
    return roots


def detect_game_root():
    for r in _steam_roots():
        p = os.path.join(r, 'steamapps', 'common', 'War Thunder')
        if os.path.isdir(os.path.join(p, 'sound')) or os.path.isdir(p):
            return p
    return ''


def detect_gimp():
    local = os.environ.get('LOCALAPPDATA', '')
    for root in (os.path.join(local, 'Programs'), r'C:\Program Files', r'C:\Program Files (x86)'):
        if not root or not os.path.isdir(root):
            continue
        try:
            for name in os.listdir(root):
                if name.lower().startswith('gimp'):
                    b = os.path.join(root, name, 'bin')
                    for exe in ('gimp-3.0.exe', 'gimp-2.10.exe', 'gimp.exe'):
                        p = os.path.join(b, exe)
                        if os.path.isfile(p):
                            return p
        except OSError:
            pass
    return ''


def resolved(cfg):
    gr = (cfg.get('game_root') or '').strip()
    if len(gr) > 1 and gr[1] == ':':
        gr = gr[0].upper() + gr[1:]
    cfg['game_root'] = os.path.normpath(gr) if gr else ''
    if not cfg['game_root'] or not os.path.isdir(cfg['game_root']):
        d = detect_game_root()
        if d:
            cfg['game_root'] = d
    if not cfg.get('gimp') or not os.path.isfile(cfg.get('gimp', '')):
        d = detect_gimp()
        if d:
            cfg['gimp'] = d
    # 扩展目录：优先用设置里的，其次看包内的「扩展」文件夹
    for key, names in (('sdv_root', ('SDV', 'SeedVC', 'sdv')),
                       ('tts_root', ('TTS', 'IndexTTS2', 'tts'))):
        if cfg.get(key) and os.path.isdir(cfg.get(key) or ''):
            continue
        for n in names:
            c = os.path.join(EXT_ROOT, n)
            if os.path.isdir(c):
                cfg[key] = c
                break
    fk = cfg.get('fmod_kit') or ''
    if fk and os.path.isdir(fk):
        cli = find_fmod_cli(cfg)
        if cli:
            cfg['fmod_cli'] = cli
    return cfg


def find_fmod_cli(cfg):
    kit = cfg.get('fmod_kit') or ''
    if not kit or not os.path.isdir(kit):
        return ''
    for name in sorted(os.listdir(kit)):
        d = os.path.join(kit, name)
        if os.path.isdir(d) and name.lower().startswith('fmod studio'):
            p = os.path.join(d, 'fmodstudiocl.exe')
            if os.path.isfile(p):
                return p
    return ''


def safe_join(base, *parts):
    p = os.path.realpath(os.path.join(base, *parts))
    rb = os.path.realpath(base)
    if p != rb and not p.startswith(rb + os.sep):
        raise ValueError('路径越界')
    return p


def clean_name(name):
    name = (name or '').strip()
    for ch in '\\/:*?"<>|\r\n\t':
        name = name.replace(ch, '_')
    return name.strip(' .')


def human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return ('%.1f %s' % (n, u)) if u != 'B' else ('%d B' % n)
        n /= 1024.0


# ================================================================= 作业系统

def jlog(job, msg):
    job['lines'].append(str(msg))


def start_job(title, fn):
    _job_seq[0] += 1
    jid = 'j%d' % _job_seq[0]
    job = {'id': jid, 'title': title, 'lines': [], 'done': False,
           'ok': None, 'started': time.time()}
    _jobs[jid] = job

    def run():
        try:
            fn(job)
            if job['ok'] is None:
                job['ok'] = True
        except Exception as e:
            job['lines'].append('✗ ' + str(e))
            job['ok'] = False
        finally:
            job['done'] = True
            job['elapsed'] = round(time.time() - job['started'], 1)

    threading.Thread(target=run, daemon=True).start()
    return jid


def run_stream(job, cmd, cwd=None, env_extra=None, prefix='', fold=0, head=15, cap=2000):
    """跑一个子进程，把它的输出送进作业日志。

    有些工具（比如 vgmstream 解一个 bank）单次就吐上万行，全部原样转发会把
    浏览器的日志区拖死，所以 fold>0 时对输出做折叠：开头 head 行和所有报错行
    原样保留，其余每 fold 行并成一条进度，最多保留 cap 行。
    fold=0 表示不折叠（默认，用于本来就该逐行看的进度输出）。
    """
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    if env_extra:
        env.update(env_extra)
    jlog(job, prefix + '> ' + ' '.join('"%s"' % c if ' ' in str(c) else str(c) for c in cmd))
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, bufsize=1,
                         universal_newlines=True, encoding='utf-8', errors='replace')
    err_keys = ('error', 'fail', 'fatal', 'unable', 'cannot', "can't",
                'not found', 'no such', 'denied', 'invalid', 'corrupt',
                'exception', 'traceback', 'unsupported')
    total = 0      # 子进程一共吐了多少行
    shown = 0      # 已经写进日志的行数
    pending = 0    # 攒着还没汇报的折叠行数
    for line in p.stdout:
        line = line.rstrip()
        if not line:
            continue
        total += 1
        low = line.lower()
        keep = (not fold) or (shown < cap and (shown < head or any(k in low for k in err_keys)))
        if keep:
            if pending:
                jlog(job, '  …（折叠 %d 行）' % pending)
                pending = 0
            jlog(job, line)
            shown += 1
        else:
            pending += 1
            if fold and pending >= fold:
                jlog(job, '  … 已读到第 %d 行输出，中间内容已折叠' % total)
                pending = 0
                shown += 1
    if pending:
        jlog(job, '  …（折叠 %d 行）' % pending)
    code = p.wait()
    if code != 0:
        raise RuntimeError('子进程退出码 %s' % code)
    return code


def collect_files(root, exts=None):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if exts and os.path.splitext(f)[1].lower() not in exts:
                continue
            out.append(os.path.join(dirpath, f))
    return out


# ---------------------------------------------------------- 音调 / 脚本解析

def _ffdir(cfg):
    return os.path.join(cfg.get('sdv_root') or '', 'ffmpeg')


def probe_rate(path):
    fp = os.path.join(os.environ.get('_WTRT_FFDIR', ''), 'ffprobe.exe')
    if not os.path.isfile(fp):
        return 0
    p = subprocess.run([fp, '-v', 'error', '-select_streams', 'a:0',
                        '-show_entries', 'stream=sample_rate', '-of', 'csv=p=0', path],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        return int((p.stdout or '').strip().splitlines()[0])
    except Exception:
        return 0


def pitch_shift_wav(cfg, path, semitones):
    """按半音移调，时长保持不变（asetrate + aresample + atempo）。"""
    semitones = int(semitones or 0)
    if semitones == 0:
        return False
    ffdir = _ffdir(cfg)
    ff = os.path.join(ffdir, 'ffmpeg.exe')
    if not os.path.isfile(ff):
        raise RuntimeError('找不到 ffmpeg（移调要用）：' + ff)
    os.environ['_WTRT_FFDIR'] = ffdir
    sr = probe_rate(path) or 22050
    k = 2.0 ** (semitones / 12.0)
    tmp = path + '.shift.wav'
    af = 'asetrate=%d,aresample=%d,atempo=%.6f' % (max(1000, int(sr * k)), sr, 1.0 / k)
    r = subprocess.run([ff, '-y', '-hide_banner', '-loglevel', 'error', '-i', path,
                        '-af', af, tmp], capture_output=True, creationflags=NO_WINDOW)
    if not os.path.isfile(tmp):
        raise RuntimeError('移调失败：' + (r.stderr or b'').decode('utf-8', 'replace')[:200])
    os.replace(tmp, path)
    return True


def parse_script(text):
    """把 'WT0001-xxx WT0002-yyy' 这种稿子拆成 [{id, text}, ...]。

    唯一的句子分割点 = 每句开头的 'WT' + 四位数字。
    """
    out = []
    for chunk in re.split(r'(?=W\s*T\s*\d{4})', text or ''):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r'^W\s*T\s*(\d{4})\s*[-–—－:：,，.、]?\s*(.*)$', chunk, re.S)
        if m:
            body = re.sub(r'\s+', ' ', m.group(2)).strip()
            if body:
                out.append({'id': 'WT' + m.group(1), 'text': body})
        else:
            body = re.sub(r'\s+', ' ', chunk).strip()
            if body:
                out.append({'id': '', 'text': body})
    return out


# ================================================================= 涂装模块

KB_PATH = os.path.join(CORE, '载具通用性知识库.json')
_NAME_CACHE = {'mtime': None, 'data': None}
_KB_CACHE = {'mtime': None, 'data': None}
NATION_RE = re.compile(r'^(us|g|ussr|uk|jp|cn|it|fr|sw|il)_[a-z0-9_]+$')
_FAM_STOP = {
    'tank', 'infantry', 'medium', 'light', 'heavy', 'super', 'main', 'battle', 'combat',
    'mk', 'mark', 'the', 'of', 'and', 'for', 'class', 'type', 'late', 'early', 'mod',
    'pz', 'kpfw', 'ausf', 'sfl', 'flak', 'spg', 'spaa', 'mbt', 'ifv', 'apc', 'aa', 'at',
}


def load_vehicle_names(cfg):
    """从游戏 lang\\units.csv 建 载具ID -> {zh,en} 表（带 mtime 缓存）。"""
    path = os.path.join(cfg.get('game_root') or '', 'lang', 'units.csv')
    if not os.path.isfile(path):
        return {}
    try:
        mt = os.path.getmtime(path)
        if _NAME_CACHE['mtime'] == mt and _NAME_CACHE['data']:
            return _NAME_CACHE['data']
        names = {}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if not line.startswith('"'):
                    continue
                cols = line.split('";"')
                key = cols[0].strip('"').strip()
                m = re.match(r'^(.+?)_([0-9])$', key)
                if not m:
                    continue
                base, idx = m.group(1), m.group(2)
                if not NATION_RE.match(base):
                    continue
                en = cols[1] if len(cols) > 1 else ''
                zh = cols[10].replace('\u200b', '') if len(cols) > 10 else ''
                en = en.replace('\u200b', '').strip()
                zh = zh.replace('\u200b', '').strip()
                cur = names.setdefault(base, {'en': '', 'zh': '', '_0': False})
                if idx == '0':
                    cur['en'], cur['zh'], cur['_0'] = en, zh, True
                elif not cur['_0'] and not cur['en']:
                    cur['en'], cur['zh'] = en, zh
        for v in names.values():
            v.pop('_0', None)
        _NAME_CACHE['mtime'] = mt
        _NAME_CACHE['data'] = names
        return names
    except Exception:
        return {}


def vehicle_label(cfg, veh_id):
    n = load_vehicle_names(cfg).get(veh_id)
    if not n:
        return ''
    return n.get('zh') or n.get('en') or ''


def parse_blk_text(text):
    out = []
    for m in re.finditer(r'(\w+)\s*\{([^}]*)\}', text or '', re.S):
        kind, body = m.group(1), m.group(2)
        d = dict(re.findall(r'(\w+)\s*:t\s*=\s*"([^"]*)"', body))
        frm = (d.get('from') or '').rstrip('*')
        if not frm:
            continue
        out.append({'kind': kind, 'from': frm, 'to': d.get('to', ''), 'param': d.get('param', '')})
    return out


def parse_blk_file(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            info = parse_blk_text(f.read())
    except OSError:
        return None
    t = {'body': '', 'turret': '', 'gun': '', 'camo': ''}
    for it in info:
        frm = it['from']
        if it['kind'] == 'replace_tex':
            t['camo'] = t['camo'] or frm
        elif frm.endswith('_body_c'):
            t['body'] = frm
        elif frm.endswith('_turret_c'):
            t['turret'] = frm
        elif frm.endswith('_gun_c'):
            t['gun'] = frm
    return t


def family_key(en):
    words = re.findall(r'[A-Za-z][A-Za-z0-9\-\.]{2,}', en or '')
    cand = [w for w in words if w.lower().strip('.') not in _FAM_STOP]
    return max(cand, key=len) if cand else ''


def build_kb(cfg):
    names = load_vehicle_names(cfg)
    textures, src = {}, {}
    for root, label in ((skin_dir_of(cfg), '游戏 UserSkins'), (SKIN_ROOT, '本工程涂装库')):
        if not os.path.isdir(root):
            continue
        for path in collect_files(root, ('.blk',)):
            veh = os.path.splitext(os.path.basename(path))[0]
            t = parse_blk_file(path)
            if not t:
                continue
            prev = textures.get(veh)
            if prev is None or (not prev.get('body') and t.get('body')):
                textures[veh] = t
                src[veh] = path
    fams = {}
    for vid, n in names.items():
        k = family_key(n.get('en') or '')
        if k:
            fams.setdefault(k, []).append(vid)
    kb = {
        'updated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'game': cfg.get('game_root') or '',
        'names': names,
        'textures': textures,
        'sources': src,
        'families': {k: sorted(v) for k, v in fams.items() if len(v) > 1},
    }
    try:
        with open(KB_PATH, 'w', encoding='utf-8') as f:
            json.dump(kb, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return kb


def load_kb(cfg, rebuild=False):
    if not rebuild and os.path.isfile(KB_PATH):
        mt = os.path.getmtime(KB_PATH)
        if _KB_CACHE['mtime'] == mt and _KB_CACHE['data']:
            return _KB_CACHE['data']
        try:
            with open(KB_PATH, 'r', encoding='utf-8') as f:
                kb = json.load(f)
            if kb.get('textures') is not None and kb.get('names'):
                _KB_CACHE.update(mtime=mt, data=kb)
                return kb
        except Exception:
            pass
    return build_kb(cfg)


def _same_tex(a, b, part):
    return (a or {}).get(part, '') != '' and (a or {}).get(part, '') == (b or {}).get(part, '')


def check_compat(cfg, vehicle, skin=''):
    kb = load_kb(cfg)
    names = kb.get('names') or {}
    tex = kb.get('textures') or {}
    tgt = tex.get(vehicle)
    fam = []
    n = names.get(vehicle)
    if n:
        fk = family_key(n.get('en') or '')
        fam = [v for v in (kb.get('families') or {}).get(fk, []) if v != vehicle]
    same, partial, unknown = [], [], []
    if tgt:
        for v, t in tex.items():
            if v == vehicle:
                continue
            parts = {p: _same_tex(tgt, t, p) for p in ('body', 'turret', 'gun', 'camo')}
            rec = {'id': v, 'label': (names.get(v) or {}).get('zh') or (names.get(v) or {}).get('en') or v,
                   'parts': parts}
            if all(parts.values()):
                same.append(rec)
            elif parts['body']:
                partial.append(rec)
    for v in fam:
        if v not in tex:
            unknown.append({'id': v, 'label': (names.get(v) or {}).get('zh') or (names.get(v) or {}).get('en') or v})
    return {
        'vehicle': vehicle,
        'vehicleLabel': (names.get(vehicle) or {}).get('zh') or (names.get(vehicle) or {}).get('en') or '',
        'skin': skin,
        'textures': tgt or {},
        'family': (family_key(n.get('en')) if n else ''),
        'familyTotal': len((kb.get('families') or {}).get(family_key(n.get('en')), [])) if n else 0,
        'same': same, 'partial': partial, 'unknown': unknown,
        'kbUpdated': kb.get('updated'),
        'kbCount': len(tex),
    }

def _u16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def _u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def image_size(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, 'rb') as f:
            head = f.read(32)
        if ext == '.tga':
            return _u16(head, 12), _u16(head, 14)
        if ext == '.dds':
            return _u32(head, 16), _u32(head, 12)
        if ext == '.png':
            return _u32(head, 16), _u32(head, 20)
        if ext == '.bmp':
            return _u32(head, 18), _u32(head, 22)
    except Exception:
        pass
    return None


def texconv_thumb(src, dst):
    if not os.path.isfile(TEXCONV):
        raise RuntimeError('找不到 核心\\texconv.exe')
    args = [TEXCONV, '-nologo', '-y', '-f', 'B8G8R8X8_UNORM', '-ft', 'png']
    size = image_size(src)
    if size and size[0] and size[1]:
        w, h = size
        s = min(1.0, THUMB_MAX / float(max(w, h)))
        args += ['-w', str(max(1, int(round(w * s)))), '-h', str(max(1, int(round(h * s))))]
    tmp = os.path.join(CACHE, '_t%d' % (int(time.time() * 1000) % 100000))
    os.makedirs(tmp, exist_ok=True)
    args += ['-o', tmp, src]
    p = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
    made = os.path.join(tmp, os.path.splitext(os.path.basename(src))[0] + '.png')
    if not os.path.isfile(made):
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError('缩略图转换失败：' + (p.stderr or b'').decode('utf-8', 'replace')[:160])
    os.replace(made, dst)
    shutil.rmtree(tmp, ignore_errors=True)


def thumbnail(vehicle, skin, fname):
    src = safe_join(safe_join(SKIN_ROOT, vehicle), skin, fname)
    if os.path.splitext(fname)[1].lower() not in IMAGE_EXT:
        raise ValueError('不是图片')
    if not os.path.isfile(src):
        raise FileNotFoundError('文件不存在')
    key = hashlib.md5((src + '|' + str(os.path.getmtime(src))).encode('utf-8')).hexdigest()
    dst = os.path.join(CACHE, key + '.png')
    if not os.path.isfile(dst):
        with _thumb_lock:
            if not os.path.isfile(dst):
                texconv_thumb(src, dst)
    return dst


def skin_dir_of(cfg):
    return os.path.join(cfg.get('game_root') or '', 'UserSkins')


def list_skins(cfg):
    skins_dir = skin_dir_of(cfg)
    items = []
    if not os.path.isdir(SKIN_ROOT):
        return items
    for vehicle in sorted(os.listdir(SKIN_ROOT)):
        vdir = os.path.join(SKIN_ROOT, vehicle)
        if not os.path.isdir(vdir):
            continue
        for skin in sorted(os.listdir(vdir)):
            sdir = os.path.join(vdir, skin)
            if not os.path.isdir(sdir):
                continue
            files, size, mtime = [], 0, 0
            for f in sorted(os.listdir(sdir)):
                fp = os.path.join(sdir, f)
                if os.path.isfile(fp):
                    files.append(f)
                    size += os.path.getsize(fp)
                    mtime = max(mtime, os.path.getmtime(fp))
            blks = [f for f in files if f.lower().endswith('.blk')]
            inst = os.path.join(skins_dir, skin) if skins_dir else ''
            installed = bool(inst) and os.path.isdir(inst)
            dirty = False
            if installed:
                try:
                    back = [f for f in os.listdir(inst) if os.path.isfile(os.path.join(inst, f))]
                    if sorted(back) != sorted(files):
                        dirty = True
                    else:
                        for f in files:
                            a, b = os.path.join(sdir, f), os.path.join(inst, f)
                            if (os.path.getsize(a) != os.path.getsize(b)
                                    or int(os.path.getmtime(a)) != int(os.path.getmtime(b))):
                                dirty = True
                                break
                except OSError:
                    dirty = True
            items.append({
                'vehicle': vehicle, 'name': skin, 'files': files,
                'images': [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXT],
                'blk': blks[0] if blks else None, 'blkCount': len(blks),
                'sizeKB': round(size / 1024.0, 1), 'installed': installed, 'dirty': dirty,
                'mtime': int(mtime),
            })
    return items


def read_blk(vehicle, skin):
    d = safe_join(safe_join(SKIN_ROOT, vehicle), skin)
    out = []
    for f in sorted(os.listdir(d)):
        if f.lower().endswith('.blk'):
            with open(os.path.join(d, f), 'r', encoding='utf-8', errors='replace') as fh:
                out.append([f, fh.read()])
    return out


def do_skin_install(cfg, p):
    src = safe_join(safe_join(SKIN_ROOT, p['vehicle']), p['name'])
    root = skin_dir_of(cfg)
    if not os.path.isdir(root):
        raise RuntimeError('找不到 UserSkins，检查游戏路径：' + root)
    dst = os.path.join(root, p['name'])
    if os.path.isdir(dst) and not p.get('overwrite'):
        return {'needConfirm': True, 'message': '游戏目录里已有同名文件夹「%s」，要覆盖吗？' % p['name']}
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return {'ok': True, 'message': '已装进游戏：' + p['name']}


def do_skin_uninstall(cfg, p):
    root = skin_dir_of(cfg)
    dst = safe_join(root, p['target'])
    if not os.path.isdir(dst):
        raise RuntimeError('游戏目录里没有「%s」' % p['target'])
    shutil.rmtree(dst)
    return {'ok': True, 'message': '已从游戏移除：' + p['target']}


def do_skin_delete(cfg, p):
    shutil.rmtree(safe_join(safe_join(SKIN_ROOT, p['vehicle']), p['name']))
    parent = safe_join(SKIN_ROOT, p['vehicle'])
    try:
        if not os.listdir(parent):
            os.rmdir(parent)
    except OSError:
        pass
    return {'ok': True, 'message': '已从库中删除：' + p['name']}


def do_skin_rename(cfg, p):
    new = clean_name(p['newName'])
    if not new:
        raise RuntimeError('名字不能为空')
    src = safe_join(safe_join(SKIN_ROOT, p['vehicle']), p['name'])
    dst = safe_join(safe_join(SKIN_ROOT, p['vehicle']), new)
    if os.path.exists(dst):
        raise RuntimeError('已经有一套叫「%s」的了' % new)
    os.rename(src, dst)
    return {'ok': True, 'message': '已改名为：' + new}


def do_skin_new(cfg, p):
    name = clean_name(p.get('name') or '')
    if not name:
        raise RuntimeError('新涂装名不能为空')
    src = safe_join(safe_join(SKIN_ROOT, p['vehicle']), p['base'])
    vdir = safe_join(SKIN_ROOT, p['vehicle'])
    os.makedirs(vdir, exist_ok=True)
    dst = os.path.join(vdir, name)
    if os.path.exists(dst):
        raise RuntimeError('已经有一套叫「%s」的了' % name)
    shutil.copytree(src, dst)
    return {'ok': True, 'message': '已新建：' + name}


def do_skin_edit(cfg, p):
    gimp = cfg.get('gimp') or detect_gimp()
    d = safe_join(safe_join(SKIN_ROOT, p['vehicle']), p['name'])
    imgs = [os.path.join(d, f) for f in sorted(os.listdir(d))
            if os.path.splitext(f)[1].lower() in IMAGE_EXT]
    if not imgs:
        raise RuntimeError('这一套里没有图片')
    if not gimp or not os.path.isfile(gimp):
        if os.name == 'nt':
            os.startfile(d)
        raise RuntimeError('找不到 GIMP，请在设置里填路径（已帮你打开该文件夹）')
    subprocess.Popen([gimp] + imgs, creationflags=NO_WINDOW)
    return {'ok': True, 'message': '已用 GIMP 打开 %d 个文件' % len(imgs)}


def do_skin_convert(cfg, p):
    d = safe_join(safe_join(SKIN_ROOT, p['vehicle']), p['name'])
    out = os.path.join(os.path.dirname(d), os.path.basename(d) + '_dds')
    os.makedirs(out, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(d)):
        if os.path.splitext(f)[1].lower() in ('.tga', '.png'):
            subprocess.run([TEXCONV, '-nologo', '-f', 'BC3_UNORM', '-m', '1', '-y', '-o', out,
                            os.path.join(d, f)], capture_output=True, creationflags=NO_WINDOW)
            n += 1
    return {'ok': True, 'message': '已转换 %d 张 → %s' % (n, out)}


def do_compat(cfg):
    if not os.path.isfile(COMPAT):
        raise RuntimeError('找不到 核心\\check_skin_compat.py')
    p = subprocess.run([sys.executable, COMPAT, cfg.get('game_root') or ''],
                       capture_output=True, creationflags=NO_WINDOW)
    return {'ok': True, 'text': ((p.stdout or b'') + (p.stderr or b'')).decode('utf-8', 'replace').strip()}


# ================================================================= 语音模块

def sound_dir(cfg):
    return os.path.join(cfg.get('game_root') or '', 'sound')


def mod_dir(cfg):
    return os.path.join(sound_dir(cfg), 'mod')


def config_blk_path(cfg):
    return os.path.join(cfg.get('game_root') or '', 'config.blk')


def mod_enabled(cfg):
    """读 config.blk 里 sound{ enable_mod } —— True / False / None（读不到）"""
    p = config_blk_path(cfg)
    if not os.path.isfile(p):
        return None
    try:
        txt = open(p, 'rb').read().decode('latin-1')
    except Exception:
        return None
    m = re.search(r'sound\s*\{(.*?)\}', txt, re.S | re.I)
    if not m:
        return None
    mm = re.search(r'enable_mod\s*:\s*b\s*=\s*(yes|no)', m.group(1), re.I)
    if not mm:
        return False
    return mm.group(1).lower() == 'yes'


def enable_mods(cfg):
    """建好 sound\\mod，并把 config.blk 里的模组开关打开。改之前先备份 config.blk。
    全程用 latin-1 读写，保证除开关之外一个字节都不动。"""
    steps = []
    md = mod_dir(cfg)
    if os.path.isdir(md):
        steps.append('sound\\mod 已经存在')
    else:
        os.makedirs(md, exist_ok=True)
        steps.append('已建好目录 ' + md)

    p = config_blk_path(cfg)
    if not os.path.isfile(p):
        steps.append('没找到 config.blk，跳过（进游戏后请到声音设置里手动打开模组支持）')
        return steps
    raw = open(p, 'rb').read()
    txt = raw.decode('latin-1')
    bak = p + '.bak-圆桌工程'
    if not os.path.isfile(bak):
        with open(bak, 'wb') as fh:
            fh.write(raw)
        steps.append('config.blk 已备份为 config.blk.bak-圆桌工程')

    m = re.search(r'(sound\s*\{)(.*?)(\})', txt, re.S | re.I)
    if not m:
        steps.append('config.blk 里没有 sound 段，跳过（请到游戏声音设置里手动打开模组支持）')
        return steps
    body = m.group(2)
    if re.search(r'enable_mod\s*:\s*b\s*=\s*yes', body, re.I):
        steps.append('enable_mod 本来就是 yes，没动它')
    else:
        if re.search(r'enable_mod\s*:\s*b\s*=\s*no', body, re.I):
            body = re.sub(r'enable_mod\s*:\s*b\s*=\s*no', 'enable_mod:b=yes', body, flags=re.I)
        else:
            body = '\r\n  enable_mod:b=yes' + body
        steps.append('enable_mod 改成 yes')
    if re.search(r'fmod_sound_enable\s*:\s*b\s*=\s*no', body, re.I):
        body = re.sub(r'fmod_sound_enable\s*:\s*b\s*=\s*no', 'fmod_sound_enable:b=yes', body, flags=re.I)
        steps.append('fmod_sound_enable 改成 yes')
    txt = txt[:m.start(2)] + body + txt[m.end(2):]
    with open(p, 'wb') as fh:
        fh.write(txt.encode('latin-1'))
    steps.append('config.blk 已保存')
    return steps


# bank 文件名 → 类别 / 语言
MOD_CAT_LABEL = {'ground': '陆战', 'naval': '海战', 'common': '通用播报'}


def mod_bank_info(name):
    m = re.match(r'^_crew_dialogs_([a-z]+)_(.+?)(?:\.assets)?\.bank$', name, re.I)
    if not m:
        return '', '', ''
    cat, lang = m.group(1).lower(), m.group(2).lower()
    if lang == 'aircraft_gui':
        return cat, lang, '空战告警'
    if lang in SM_ALT:
        return cat, lang, LANG_LABEL.get(SM_ALT[lang], lang) + ' · 备用录音'
    return cat, lang, LANG_LABEL.get(lang, lang)


# 语音来源分类（三层导航的第二层）
CAT_META = [
    {'id': 'ground', 'name': '陆战乘员组', 'desc': '地面载具：指挥官 / 车长 / 炮手 / 驾驶员 / 装填手'},
    {'id': 'naval',  'name': '海战乘员组', 'desc': '舰艇乘员'},
    {'id': 'air',    'name': '空战告警语音', 'desc': '机体告警（VWS · Betty / Rita / 小九〇六），从 aircraft_gui 里解出'},
    {'id': 'common', 'name': '通用战场播报', 'desc': '基地占领 / 任务开始 / 胜利播报与通用战术口令，陆海空都会用到'},
]


def bank_path(cfg, cat, code):
    sd = sound_dir(cfg)
    if cat == 'vws':
        return os.path.join(sd, 'aircraft_gui.assets.bank')
    return os.path.join(sd, '_crew_dialogs_%s_%s.assets.bank' % (cat, code))


def src_out(cat, code):
    return os.path.join(VOICE_ORIG, 'vws' if cat == 'vws' else '%s_%s' % (cat, code))


def _src_item(cfg, cat, code, label, main=None, alt=False):
    b = bank_path(cfg, cat, code)
    if cat == 'vws' and not os.path.isfile(b):
        b = os.path.join(sound_dir(cfg), '_crew_dialogs_ground_aircraft_gui.assets.bank')
    exists = os.path.isfile(b)
    out = src_out(cat, code)
    files = [f for f in os.listdir(out) if f.lower().endswith('.wav')] if os.path.isdir(out) else []
    mb = round(sum(os.path.getsize(os.path.join(out, f)) for f in files) / 1048576.0, 1) if files else 0
    return {'cat': cat, 'code': code, 'label': label, 'alt': alt,
            'bank': b if exists else '', 'bankName': os.path.basename(b),
            'bankMB': round(os.path.getsize(b) / 1048576.0, 1) if exists else 0,
            'outDir': out, 'extracted': len(files), 'outMB': mb,
            'main': True if cat == 'vws' else (main if main is not None else (code in MAIN_LANGS)),
            'available': exists}


def list_sources(cfg):
    sd = sound_dir(cfg)
    if not os.path.isdir(sd):
        return []
    names = set(os.listdir(sd))
    out = []
    for cat in ('ground', 'naval', 'common'):
        for f in sorted(names):
            m = re.match(r'^_crew_dialogs_%s_([a-z0-9_]+)\.assets\.bank$' % cat, f)
            if m:
                code = m.group(1)
                if cat == 'ground' and code in SM_ALT:
                    base = SM_ALT[code]
                    out.append(_src_item(cfg, cat, code,
                                         LANG_LABEL.get(base, base) + ' · 备用录音',
                                         main=base in MAIN_LANGS, alt=True))
                else:
                    out.append(_src_item(cfg, cat, code, LANG_LABEL.get(code, code)))
    if 'aircraft_gui.assets.bank' in names or '_crew_dialogs_ground_aircraft_gui.assets.bank' in names:
        out.append(_src_item(cfg, 'vws', 'vws', '机体告警语音（VWS）'))
    return out


def game_slots(cfg):
    """游戏本体实际支持的乘员组语音 —— 这是"游戏支持哪些语言"的真实答案。
    注意它和 kit_slots() 是两回事：工程没带素材 ≠ 游戏不支持。"""
    sd = sound_dir(cfg)
    out = {'ground': [], 'naval': [], 'common': [], 'vws': []}
    if not os.path.isdir(sd):
        return out
    try:
        names = os.listdir(sd)
    except OSError:
        return out
    for cat in ('ground', 'naval', 'common'):
        for f in names:
            m = re.match(r'^_crew_dialogs_%s_([a-z0-9_]+)\.assets\.bank$' % cat, f)
            if m:
                code = m.group(1)
                if cat == 'ground' and code in SM_ALT:
                    continue                      # 备用录音不算独立语言
                out[cat].append({'code': code, 'label': LANG_LABEL.get(code, code),
                                 'mb': round(os.path.getsize(os.path.join(sd, f)) / 1048576.0, 1)})
    if 'aircraft_gui.assets.bank' in names:
        out['vws'].append({'code': 'vws', 'label': '机体告警（英/日/中三套）',
                           'mb': round(os.path.getsize(os.path.join(sd, 'aircraft_gui.assets.bank')) / 1048576.0, 1)})
    for k in out:
        out[k].sort(key=lambda x: x['label'])
    return out


def kit_slots(cfg):
    """官方工程能构建哪些语音槽位 —— 这就是「能做哪些语言」的硬边界。"""
    counts = {}
    for rel in kit_audio_index(cfg):
        r, l = _kit_lang_of(rel)
        if not r:
            continue
        counts[(r, l)] = counts.get((r, l), 0) + 1
    out = []
    for r in ('dialogs_wt_tanks_2023', 'dialogs_wt_ships_2022', 'dialogs_wopl', 'vws', 'radio_chat'):
        for (rr, l), n in counts.items():
            if rr == r:
                out.append({'root': rr, 'lang': l,
                            'rootLabel': KIT_ROOT_LABEL.get(rr, rr),
                            'langLabel': KIT_LANG_LABEL.get(l, l), 'total': n})
    return out


def list_projects():
    out = []
    if not os.path.isdir(VOICE_PROJ):
        return out
    for name in sorted(os.listdir(VOICE_PROJ)):
        d = os.path.join(VOICE_PROJ, name)
        if not os.path.isdir(d):
            continue
        def cnt(exts=None):
            return len(collect_files(d, exts))
        out.append({
            'name': name, 'path': d,
            'audio': cnt(AUDIO_EXT),
            'banks': [f for f in collect_files(d, ('.bank',))],
            'mb': round(sum(os.path.getsize(f) for f in collect_files(d)) / 1048576.0, 1),
        })
    return out


def list_installed_mods(cfg):
    md = mod_dir(cfg)
    out = []
    if not os.path.isdir(md):
        return out
    for f in sorted(os.listdir(md)):
        if f.lower().endswith('.bank'):
            fp = os.path.join(md, f)
            cat, lang, label = mod_bank_info(f)
            out.append({'name': f, 'MB': round(os.path.getsize(fp) / 1048576.0, 1),
                        'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(fp))),
                        'cat': cat, 'catLabel': MOD_CAT_LABEL.get(cat, cat),
                        'lang': lang, 'langLabel': label})
    return out


def voice_state(cfg):
    sdv = cfg.get('sdv_root') or ''
    tts = cfg.get('tts_root') or ''
    sdv_py = os.path.join(sdv, 'python', 'cpython-3.10.22-windows-x86_64-none', 'python.exe')
    fmod_cli = cfg.get('fmod_cli') or find_fmod_cli(cfg)
    fmod_proj = ''
    kit = cfg.get('fmod_kit') or ''
    if kit and os.path.isdir(kit):
        for f in os.listdir(kit):
            if f.lower().endswith('.fspro'):
                fmod_proj = os.path.join(kit, f)
    return {
        'gameRoot': cfg.get('game_root') or '',
        'soundDir': sound_dir(cfg),
        'modDir': mod_dir(cfg),
        'modEnabled': mod_enabled(cfg),
        'voiceRoot': VOICE,
        'origRoot': VOICE_ORIG,
        'projRoot': VOICE_PROJ,
        'packRoot': VOICE_PACK,
        'refRoot': VOICE_REF,
        'sources': list_sources(cfg),
        'catMeta': CAT_META,
        'projects': list_projects(),
        'kitSlots': kit_slots(cfg),
        'gameSlots': game_slots(cfg),
        'installed': list_installed_mods(cfg),
        'tools': {
            'vgmstream': os.path.isfile(VGM),
            'texconv': os.path.isfile(TEXCONV),
            'sdv': os.path.isfile(sdv_py),
            'sdvRoot': sdv,
            'tts': os.path.isdir(os.path.join(tts, 'index-tts')),
            'ttsRoot': tts,
            'uvr': os.path.isdir(cfg.get('uvr_root') or ''),
            'uvrRoot': cfg.get('uvr_root') or '',
            'fmodCli': fmod_cli,
            'fmodProject': fmod_proj,
            'fmodKit': kit,
        },
    }


def sdv_python(cfg):
    root = cfg.get('sdv_root') or ''
    if not root:
        return ''
    import glob
    cands = glob.glob(os.path.join(root, 'python', '*', 'python.exe'))
    cands += [os.path.join(root, 'seed-vc', '.venv', 'Scripts', 'python.exe'),
              os.path.join(root, '.venv', 'Scripts', 'python.exe'),
              os.path.join(root, 'python.exe')]
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[0] if cands else ''


def tts_python(cfg):
    root = cfg.get('tts_root') or ''
    if not root:
        return ''
    for c in (os.path.join(root, 'index-tts', '.venv', 'Scripts', 'python.exe'),
              os.path.join(root, '.venv', 'Scripts', 'python.exe')):
        if os.path.isfile(c):
            return c
    return os.path.join(root, 'index-tts', '.venv', 'Scripts', 'python.exe')


def job_extract(job, cfg, code, kind):
    bank = bank_path(cfg, kind, code)
    if kind == 'vws' and not os.path.isfile(bank):
        bank = os.path.join(sound_dir(cfg), '_crew_dialogs_ground_aircraft_gui.assets.bank')
    if not os.path.isfile(bank):
        raise RuntimeError('找不到 bank：' + bank)
    out = src_out(kind, code)
    os.makedirs(out, exist_ok=True)
    jlog(job, '来源：%s（%.1f MB）' % (os.path.basename(bank), os.path.getsize(bank) / 1048576.0))
    jlog(job, '输出：%s' % out)
    jlog(job, '正在一次性解出全部命名音频流（这步可能要几分钟，别关窗口）…')
    # vgmstream 每解一个流就吐一大段解码信息，一个 bank 上万行，这里折叠掉
    run_stream(job, [VGM, '-S', '0', '-o', os.path.join(out, '?n.wav'), bank], fold=200)
    n = [f for f in os.listdir(out) if f.lower().endswith('.wav')]
    mb = sum(os.path.getsize(os.path.join(out, f)) for f in n) / 1048576.0
    jlog(job, '完成：%d 个 wav，共 %.1f MB' % (len(n), mb))
    if not n:
        raise RuntimeError('没有解出任何音频，检查 vgmstream 是否正常')


def job_sdv(job, cfg, src, dst, ref, steps, f0, pitch=0, limit=0):
    py = sdv_python(cfg)
    root = os.path.join(cfg.get('sdv_root') or '', 'seed-vc')
    script = os.path.join(root, 'batch_svc.py')
    if not os.path.isfile(py) or not os.path.isfile(script):
        raise RuntimeError('SeedVC 不完整：%s' % root)
    if not os.path.isfile(ref):
        raise RuntimeError('参考音频不存在：' + ref)
    os.makedirs(dst, exist_ok=True)
    cmd = [py, script, '--reference', ref, '--input', src, '--output', dst,
           '--diffusion-steps', str(steps), '--recursive', '--overwrite']
    if not f0:
        cmd.append('--no-f0')
    if int(pitch or 0):
        cmd += ['--semi-tone-shift', str(int(pitch))]
        jlog(job, '输出音调：%+d 半音' % int(pitch))
    if limit:
        cmd += ['--limit', str(limit)]
    jlog(job, '设备：优先 CUDA；参考音色：%s' % os.path.basename(ref))
    run_stream(job, cmd, cwd=root, env_extra={
        'PATH': os.path.join(cfg.get('sdv_root') or '', 'ffmpeg') + os.pathsep + os.environ.get('PATH', ''),
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_SYMLINKS_WARNING': '1',
    })
    n = collect_files(dst, AUDIO_EXT)
    jlog(job, '完成：输出 %d 个音频 → %s' % (len(n), dst))


def job_radio(job, cfg, src, dst, preset):
    py = sdv_python(cfg)
    script = os.path.join(cfg.get('sdv_root') or '', 'radio_fx.py')
    if not os.path.isfile(py) or not os.path.isfile(script):
        raise RuntimeError('找不到 radio_fx.py')
    os.makedirs(dst, exist_ok=True)
    run_stream(job, [py, script, '--input', src, '--output', dst,
                     '--preset', str(preset), '--recursive', '--overwrite'],
               cwd=os.path.dirname(script),
               env_extra={'PATH': os.path.join(cfg.get('sdv_root') or '', 'ffmpeg') + os.pathsep + os.environ.get('PATH', '')})
    jlog(job, '完成：%d 个音频 → %s' % (len(collect_files(dst, AUDIO_EXT)), dst))


def job_tts(job, cfg, ref, entries, lang, dst, emo_ref='', pitch=0):
    root = os.path.join(cfg.get('tts_root') or '', 'index-tts')
    driver = os.path.join(CORE, 'tts_batch.py')
    py = os.path.join(root, '.venv', 'Scripts', 'python.exe')
    if not os.path.isdir(root):
        raise RuntimeError('找不到 IndexTTS2：' + root)
    if not os.path.isfile(py):
        py = os.path.join(cfg.get('tts_root') or '', 'uv.exe')
    if not os.path.isfile(py):
        raise RuntimeError('找不到 IndexTTS2 的 Python：' + root)
    if not os.path.isfile(driver):
        raise RuntimeError('找不到批处理驱动：' + driver)
    if not os.path.isfile(ref):
        raise RuntimeError('参考音频不存在：' + ref)
    entries = [e for e in (entries or []) if (e.get('text') or '').strip()]
    if not entries:
        raise RuntimeError('没有要朗读的内容')
    os.makedirs(dst, exist_ok=True)

    # 官方 cli_v2 的 batch 走的是旧版 infer_v2，**没有 lang 参数**，
    # 所有文本都会被当默认语言读（德语直接变成气音）。
    # 这里改用我们自己的驱动：直接调 infer_v2_5，每条都能指定语言。
    jobs_file = os.path.join(BASE, '_tts_jobs.json')
    outs = []
    tasks = []
    for i, e in enumerate(entries, 1):
        name = ((e.get('id') or '').strip() or '%03d' % i) + '.wav'
        out = os.path.join(dst, name)
        t = {'text': e['text'].strip(), 'output': out, 'voice': ref}
        if emo_ref:
            t['emotion_audio'] = emo_ref
        if lang:
            t['lang'] = lang
        tasks.append(t)
        outs.append(out)
    with open(jobs_file, 'w', encoding='utf-8') as f:
        json.dump({'root': root, 'model_dir': os.path.join(root, 'checkpoints'),
                   'lang': lang or 'ZH', 'tasks': tasks}, f, ensure_ascii=False, indent=1)
    jlog(job, '共 %d 条 · 语言 %s · 清单：%s' % (len(entries), lang or 'ZH', jobs_file))

    run_stream(job, [py, driver, '--jobs', jobs_file], cwd=root, env_extra={
                   'HF_ENDPOINT': 'https://hf-mirror.com',
                   'NO_PROXY': 'hf-mirror.com,localhost,127.0.0.1',
                   'UV_PYTHON_INSTALL_DIR': os.path.join(cfg.get('tts_root') or '', 'python'),
                   'PYTHONPATH': root,
               }, prefix='  ')

    made = [o for o in outs if os.path.isfile(o)]
    if not made:
        raise RuntimeError('没有生成任何音频，检查上面的报错')
    if int(pitch or 0):
        jlog(job, '输出音调：%+d 半音，正在逐条移调…' % int(pitch))
        for o in made:
            pitch_shift_wav(cfg, o, int(pitch))
    jlog(job, '完成：%d 条 → %s' % (len(made), dst))


# 官方 FMOD 工程里的目录名 -> 人话
KIT_ROOT_LABEL = {
    'dialogs_wt_tanks_2023': '陆战车组',
    'dialogs_wt_ships_2022': '海战车组',
    'dialogs_wopl': '空战对白',
    'radio_chat': '无线电通话',
    'vws': '机体告警',
}
KIT_LANG_LABEL = {
    'english_uk': '英国', 'english_us': '美国', 'german_new': '德国', 'russian_new': '苏联/俄罗斯',
    'english': '英语', 'german': '德语', 'russian': '俄语', 'french': '法语',
    'italian': '意大利语', 'japanese': '日语', 'eng': '英语', 'ru': '俄语',
    'betty': '英式告警 Betty', 'rita': '日式告警 Rita', 'xiao906': '中式告警 小九〇六',
}
# 用户素材文件夹名里可能出现的中文/别名 -> 工程目录名
KIT_LANG_ALIAS = {
    '英国': 'english_uk', '英系': 'english_uk', 'uk': 'english_uk', 'en_uk': 'english_uk',
    '美国': 'english_us', '美系': 'english_us', 'us': 'english_us', 'en_us': 'english_us',
    '德国': 'german_new', '德系': 'german_new', 'de': 'german_new', 'german': 'german_new',
    '苏联': 'russian_new', '俄罗斯': 'russian_new', '苏系': 'russian_new', '俄系': 'russian_new',
    'ru': 'russian_new', 'ussr': 'russian_new',
}

_KIT_IDX = {'key': None, 'data': None}


def kit_audio_index(cfg):
    """官方 FMOD 工程里「每条音频该放在哪」。

    工程里音频的引用路径（assetPath）就是相对 Assets 的真实目录结构，
    而且仓库里的 Assets 目录与之一一对应 —— 所以直接扫 Assets 就够了，
    比逐个解析 6 万多个 Metadata XML 快两个数量级。"""
    global _KIT_IDX
    kit = cfg.get('fmod_kit') or ''
    assets = os.path.join(kit, 'Assets')
    if not kit or not os.path.isdir(assets):
        return []
    if _KIT_IDX['data'] is not None:
        return _KIT_IDX['data']
    idx = []
    for root, _d, files in os.walk(assets):
        rel_dir = os.path.relpath(root, assets)
        prefix = '' if rel_dir == '.' else rel_dir.replace('/', '\\') + '\\'
        for fn in files:
            if os.path.splitext(fn)[1].lower() in AUDIO_EXT:
                idx.append(prefix + fn)
    _KIT_IDX['data'] = idx
    return idx


def _kit_lang_of(rel):
    parts = rel.replace('/', '\\').split('\\')
    if len(parts) >= 2 and parts[0] and parts[1] and '.' not in parts[1]:
        return parts[0], parts[1]
    return '', ''          # 直接放在分类目录下的公共音频：不属于任何语言槽位，忽略


def analyze_material(cfg, src_dir):
    """看用户给的素材能不能对上官方工程里的位置。只读，不改任何东西。"""
    idx = kit_audio_index(cfg)
    if not idx:
        raise RuntimeError('没找到官方 FMOD 工程（检查设置里的 FMOD 模组包目录）\n'
                           '需要它里面的 Metadata 目录才能判断素材该放哪。')
    if not src_dir or not os.path.isdir(src_dir):
        raise RuntimeError('选中的素材文件夹不存在：%s' % (src_dir or '(空)'))

    by_name = {}
    buckets = {}
    for rel in idx:
        by_name.setdefault(os.path.basename(rel).lower(), []).append(rel)
        k = _kit_lang_of(rel)
        if not k[0]:
            continue
        buckets.setdefault(k, {'total': 0, 'hit': 0})
        buckets[k]['total'] += 1

    files = collect_files(src_dir, AUDIO_EXT)
    # 每个同名文件可能在多个语言里都存在，先给每个语言桶记一次"能命中"
    for f in files:
        for rel in by_name.get(os.path.basename(f).lower(), []):
            buckets[_kit_lang_of(rel)]['hit'] += 1

    hint = os.path.basename(os.path.normpath(src_dir)).lower()
    hint_langs = {v for k, v in KIT_LANG_ALIAS.items() if k in hint}

    langs = [{'root': r, 'lang': l,
              'rootLabel': KIT_ROOT_LABEL.get(r, r),
              'langLabel': KIT_LANG_LABEL.get(l, l),
              'hit': b['hit'], 'total': b['total'],
              'cover': round(b['hit'] * 100.0 / b['total'], 1) if b['total'] else 0}
             for (r, l), b in buckets.items() if b['hit']]
    # 文件夹名对得上就打头阵，否则按命中数量排
    langs.sort(key=lambda x: (x['lang'] not in hint_langs, -x['hit']))
    best = langs[0] if langs else None

    unmatched, matched = [], 0
    if best:
        want = {}
        for rel in idx:
            if _kit_lang_of(rel) == (best['root'], best['lang']):
                want.setdefault(os.path.basename(rel).lower(), rel)
        for f in files:
            if os.path.basename(f).lower() in want:
                matched += 1
            else:
                unmatched.append(os.path.basename(f))

    return {'src': src_dir, 'files': len(files),
            'matched': matched,
            'unmatched': unmatched[:60], 'unmatchedCount': len(unmatched),
            'langs': langs[:12], 'best': best,
            'hintLanguages': sorted(hint_langs)}


def job_apply_material(job, cfg, src_dir, root, lang, out_dir):
    """把用户素材按官方工程的 assetPath 归位（原文件先备份），再构建 bank。"""
    kit = cfg.get('fmod_kit') or ''
    idx = kit_audio_index(cfg)
    if not idx:
        raise RuntimeError('没找到官方 FMOD 工程')
    by_name = {}
    for rel in idx:
        r, l = _kit_lang_of(rel)
        if r == root and l == lang:
            by_name.setdefault(os.path.basename(rel).lower(), rel)
    if not by_name:
        raise RuntimeError('工程里没有 %s / %s 这套素材' % (root, lang))
    backup_root = os.path.join(VOICE_PROJ, '_原始备份', root, lang)
    assets = os.path.join(kit, 'Assets')
    placed = skipped = 0
    for f in collect_files(src_dir, AUDIO_EXT):
        rel = by_name.get(os.path.basename(f).lower())
        if not rel:
            skipped += 1
            continue
        dst = os.path.join(assets, rel)
        if os.path.isfile(dst):
            bak = os.path.join(backup_root, rel)
            if not os.path.isfile(bak):
                os.makedirs(os.path.dirname(bak), exist_ok=True)
                shutil.copy2(dst, bak)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(f, dst)
        placed += 1
    jlog(job, '归位 %d 条，跳过（工程里没这个文件名）%d 条' % (placed, skipped))
    if not placed:
        raise RuntimeError('一条都没对上 —— 素材文件名跟官方工程对不上，没法自动整理')
    jlog(job, '原文件备份在：%s' % backup_root)
    jlog(job, '开始构建 bank …')
    job_fmod_build(job, cfg, '', out_dir)


def job_fmod_build(job, cfg, src_dir, out_dir):
    cli = cfg.get('fmod_cli') or find_fmod_cli(cfg)
    kit = cfg.get('fmod_kit') or ''
    proj = ''
    if kit and os.path.isdir(kit):
        for f in os.listdir(kit):
            if f.lower().endswith('.fspro'):
                proj = os.path.join(kit, f)
    if not cli or not proj:
        raise RuntimeError('找不到 FMOD 命令行或 .fspro 工程')
    if src_dir and os.path.isdir(src_dir):
        jlog(job, '共享素材目录：%s' % src_dir)
        cmd = [cli, '-build', '-ignore-warnings', '-shared-audio-source-dir', src_dir, proj]
    else:
        cmd = [cli, '-build', '-ignore-warnings', proj]
    run_stream(job, cmd, cwd=os.path.dirname(proj))
    build_root = os.path.join(kit, 'Build')
    banks = collect_files(build_root, ('.bank',)) if os.path.isdir(build_root) else []
    jlog(job, '构建产出 %d 个 bank 文件（在 %s）' % (len(banks), build_root))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for b in banks:
            shutil.copy2(b, os.path.join(out_dir, os.path.basename(b)))
        jlog(job, '已收集到：%s' % out_dir)
    if not banks:
        raise RuntimeError('没有找到构建产物，检查 FMOD 工程的 Build 目录')


def job_install_mod(job, cfg, src_dir, names=None):
    md = mod_dir(cfg)
    os.makedirs(md, exist_ok=True)
    banks = [f for f in collect_files(src_dir, ('.bank',))]
    if names:
        banks = [b for b in banks if os.path.basename(b) in names]
    if not banks:
        raise RuntimeError('这个目录里没有 .bank 文件')
    for b in banks:
        dst = os.path.join(md, os.path.basename(b))
        shutil.copy2(b, dst)
        jlog(job, '已安装 %s（%.1f MB）' % (os.path.basename(b), os.path.getsize(dst) / 1048576.0))
    jlog(job, '目标目录：%s' % md)
    jlog(job, '重启游戏后生效。')


def job_collect_banks(job, cfg, src, dst):
    """把 FMOD 已经构建好的 bank（Build 目录）收集到一个地方。"""
    root = src or os.path.join(cfg.get('fmod_kit') or '', 'Build')
    if not os.path.isdir(root):
        raise RuntimeError('找不到构建目录：%s\n'
                           '（先在 FMOD Studio 里 File → Build，或者用上面的「构建 bank」）' % root)
    banks = collect_files(root, ('.bank',))
    if not banks:
        raise RuntimeError('这个目录里没有 .bank：' + root)
    jlog(job, '在 %s 下找到 %d 个 bank' % (root, len(banks)))
    dst = dst or VOICE_PACK
    os.makedirs(dst, exist_ok=True)
    for b in banks:
        rel = os.path.relpath(b, root)
        jlog(job, '  %s  （%.1f MB）' % (rel, os.path.getsize(b) / 1048576.0))
        shutil.copy2(b, os.path.join(dst, os.path.basename(b)))
    jlog(job, '已收集到：%s' % dst)


def job_extract_avatars(job, cfg):
    """从玩家的游戏里解包全部头像 / 头像框 / 资料页头图。"""
    src = os.path.join(cfg.get('game_root') or '', 'ui', 'images.vromfs.bin')
    if not os.path.isfile(src):
        raise RuntimeError('找不到游戏文件：%s\n（在设置里把游戏根目录指对）' % src)
    script = os.path.join(CORE, '提取战雷头像.py')
    if not os.path.isfile(script):
        raise RuntimeError('找不到提取脚本：' + script)
    jlog(job, '来源：%s（%.0f MB）' % (src, os.path.getsize(src) / 1048576.0))
    jlog(job, '输出：%s' % AVATAR_DIR)
    run_stream(job, [sys.executable, script, '--src', src, '--out', AVATAR_DIR])
    n = 0
    for k, _lbl in AVATAR_KINDS:
        d = os.path.join(AVATAR_DIR, k)
        if os.path.isdir(d):
            n += len([f for f in os.listdir(d) if f.lower().endswith('.avif')])
    jlog(job, '完成：共 %d 个（头像 / 头像框 / 资料页头图）' % n)


# ================================================================= 环境检测（发行版用）

AVATAR_DIR = os.path.join(BASE, '头像')
AVATAR_KINDS = [('avatars', '头像'), ('avatar_frames', '头像框'), ('profile_headers', '资料页头图')]
AVATAR_NAMES_PATH = os.path.join(CORE, '头像中文名.json')
AVATAR_INTRO_PATH = os.path.join(CORE, '头像介绍.json')

# IndexTTS2 的"语言表"和"实际会说的语言"是两回事，这里只列实测结果
TTS_LANG_OK = ['中文（ZH）', '英文（EN）']
TTS_LANG_MAYBE = ['日语（JA）', '西班牙语（ES）']
TTS_LANG_BAD = ['德语', '俄语', '法语', '意大利语', '波兰语', '葡萄牙语', '土耳其语',
                '韩语', '阿拉伯语', '荷兰语', '瑞典语', '芬兰语', '越南语',
                '印尼语', '印地语', '加泰罗尼亚语']
TTS_LANG_NOTE = ('IndexTTS2 的参数表里列了几十种语言，但它的文本前端实际只训练过中/英/日。'
                 '实测德语把我们写的 "Ziel erkannt! Feuer!" 念成了气音，其余小语种同理。')

# 想造其他语言时推荐的项目
OTHER_TTS = [
    {'name': 'Piper', 'why': '本地跑、CPU 就行、支持 30+ 语言（德语模型质量不错），最适合"只要会说别的语言"',
     'url': 'https://github.com/rhasspy/piper', 'license': 'MIT（模型多为 CC-BY / MIT）'},
    {'name': 'XTTS-v2 (Coqui)', 'why': '音色克隆 + 17 种语言，含德语、俄语、法语，效果比 Piper 自然',
     'url': 'https://huggingface.co/coqui/XTTS-v2', 'license': 'CPML（仅限非商业）'},
    {'name': 'CosyVoice 2（阿里）', 'why': '中英日韩粤 + 多语种，中文场景很强，国内可下',
     'url': 'https://github.com/FunAudioLLM/CosyVoice', 'license': 'Apache-2.0'},
    {'name': 'GPT-SoVITS', 'why': '中英日韩粤，音色克隆门槛低，社区教程多',
     'url': 'https://github.com/RVC-Boss/GPT-SoVITS', 'license': 'MIT'},
    {'name': 'edge-tts', 'why': '微软在线语音，100+ 语言、不用显卡，但必须联网且不是克隆音色',
     'url': 'https://github.com/rany2/edge-tts', 'license': 'GPL-3.0（调用微软在线服务）'},
]


def _reg_photoshop():
    exe, plug = '', ''
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r'SOFTWARE\Adobe\Photoshop', r'SOFTWARE\WOW6432Node\Adobe\Photoshop'):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            ver = winreg.EnumKey(k, i)
                            with winreg.OpenKey(k, ver) as vk:
                                try:
                                    p = str(winreg.QueryValueEx(vk, 'ApplicationPath')[0])
                                    if os.path.isfile(os.path.join(p, 'Photoshop.exe')):
                                        exe = os.path.join(p, 'Photoshop.exe')
                                except OSError:
                                    pass
                                try:
                                    plug = str(winreg.QueryValueEx(vk, 'PluginPath')[0])
                                except OSError:
                                    pass
                except OSError:
                    pass
    except Exception:
        pass
    return exe, plug


def detect_photoshop():
    exe, plug = _reg_photoshop()
    if not exe:
        for r in (r'C:\Program Files\Adobe', r'D:\Program Files\Adobe',
                  r'C:\Program Files (x86)\Adobe', r'D:\Adobe', r'C:\Adobe'):
            if not os.path.isdir(r):
                continue
            for d in os.listdir(r):
                if d.lower().startswith('adobe photoshop'):
                    p = os.path.join(r, d, 'Photoshop.exe')
                    if os.path.isfile(p):
                        exe = p
    return exe, plug


def find_dds_plugins(ps_exe, ps_plug):
    """找 Photoshop / GIMP 的 DDS 支持（.8bi 插件 或 GIMP 的 file-dds）。"""
    ps_dds = ''
    dirs = []
    if ps_plug and os.path.isdir(ps_plug):
        dirs.append(ps_plug)
    if ps_exe:
        base = os.path.dirname(ps_exe)
        dirs += [os.path.join(base, 'Plug-ins'), os.path.join(base, 'Required', 'Plug-ins'),
                 os.path.join(base, 'Plugins')]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            for root, _dirs, files in os.walk(d):
                for f in files:
                    low = f.lower()
                    if low.endswith('.8bi') and ('dds' in low or 'nvidia' in low or 'texture' in low):
                        ps_dds = os.path.join(root, f)
                        break
                if ps_dds:
                    break
        except OSError:
            pass
        if ps_dds:
            break
    gimp_exe = detect_gimp()
    gimp_dds = ''
    if gimp_exe:
        root = os.path.dirname(os.path.dirname(gimp_exe))
        for ver in ('3.0', '2.10', '2.0'):
            p = os.path.join(root, 'lib', 'gimp', ver, 'plug-ins', 'file-dds', 'file-dds.exe')
            if os.path.isfile(p):
                gimp_dds = p
                break
    return ps_dds, gimp_dds


_GPU_CACHE = None


def detect_gpu():
    """显卡与驱动。SDV / TTS 都靠它跑，「装了却跑不起来」多半是这里的问题。"""
    global _GPU_CACHE
    if _GPU_CACHE is not None:
        return _GPU_CACHE
    out = {'ok': False, 'name': '', 'driver': '', 'vram': '', 'note': ''}
    exe = shutil.which('nvidia-smi')
    if not exe:
        for c in (r'C:\Windows\System32\nvidia-smi.exe',
                  r'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe'):
            if os.path.isfile(c):
                exe = c
                break
    if not exe:
        out['note'] = '没找到 nvidia-smi：可能不是 N 卡，也可能显卡驱动没装好。'
        _GPU_CACHE = out
        return out
    try:
        r = subprocess.run(
            [exe, '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        first = (r.stdout or '').strip().splitlines()
        if first:
            p = [x.strip() for x in first[0].split(',')]
            out.update({'ok': True, 'name': p[0] if p else '',
                        'driver': p[1] if len(p) > 1 else '',
                        'vram': (p[2] + ' MB') if len(p) > 2 else ''})
            out['note'] = '驱动正常。'
        else:
            out['note'] = 'nvidia-smi 没有返回信息：' + (r.stderr or '').strip()[:200]
    except Exception as ex:
        out['note'] = '调用 nvidia-smi 失败：%s' % ex
    _GPU_CACHE = out
    return out


def env_state(cfg):
    gpu = detect_gpu()
    ps_exe, ps_plug = detect_photoshop()
    ps_dds, gimp_dds = find_dds_plugins(ps_exe, ps_plug)
    gimp_exe = cfg.get('gimp') or detect_gimp()
    sdv_root = cfg.get('sdv_root') or ''
    sdv_py = sdv_python(cfg)
    sdv_ckpt = os.path.join(sdv_root, 'seed-vc', 'checkpoints')
    sdv_ok = os.path.isfile(sdv_py) and os.path.isfile(os.path.join(sdv_root, 'seed-vc', 'batch_svc.py')) and os.path.isdir(sdv_ckpt)
    tts_root = cfg.get('tts_root') or ''
    tts_py = tts_python(cfg)
    tts_ckpt = os.path.join(tts_root, 'index-tts', 'checkpoints')
    tts_ok = os.path.isfile(tts_py) and os.path.isdir(tts_ckpt) and os.path.isfile(os.path.join(tts_ckpt, 'gpt.pth'))
    shared = bool(sdv_py and tts_py and os.path.normcase(os.path.dirname(sdv_py)) == os.path.normcase(os.path.dirname(tts_py)))
    return {
        'voice': {
            'extRoot': EXT_ROOT,
            'gpu': gpu,
            'sdv': {'ok': sdv_ok, 'root': sdv_root, 'python': sdv_py,
                    'want': os.path.join(EXT_ROOT, 'SDV'),
                    'hasPython': os.path.isfile(sdv_py),
                    'hasCode': os.path.isfile(os.path.join(sdv_root, 'seed-vc', 'batch_svc.py')),
                    'hasModel': os.path.isdir(sdv_ckpt),
                    'sizeGB': 8.7, 'vram': '4 GB 以上'},
            'tts': {'ok': tts_ok, 'root': tts_root, 'python': tts_py,
                    'want': os.path.join(EXT_ROOT, 'TTS'),
                    'hasPython': os.path.isfile(tts_py),
                    'hasCode': os.path.isdir(os.path.join(tts_root, 'index-tts')),
                    'hasModel': os.path.isfile(os.path.join(tts_ckpt, 'gpt.pth')),
                    'sizeGB': 18.7, 'vram': '6~8 GB'},
            'shared': {'ok': shared, 'note': '两个扩展各自带一套 PyTorch 环境，重复占用约 6 GB。'
                                             '官方安装器设计为共用一套运行时，只装一份。'},
            'ttsLang': {'ok': TTS_LANG_OK, 'maybe': TTS_LANG_MAYBE, 'bad': TTS_LANG_BAD, 'note': TTS_LANG_NOTE},
            'otherTts': OTHER_TTS,
        },
        'skin': {
            'gimp': {'exe': gimp_exe, 'ok': bool(gimp_exe),
                     'dds': gimp_dds, 'ddsOk': bool(gimp_dds),
                     'url': 'https://www.gimp.org/downloads/'},
            'ps': {'exe': ps_exe, 'ok': bool(ps_exe),
                   'dds': ps_dds, 'ddsOk': bool(ps_dds),
                   'url': 'https://www.adobe.com/products/photoshop.html',
                   'ddsUrl': 'https://developer.nvidia.com/texture-tools-exporter'},
            'bundled': {'texconv': os.path.isfile(TEXCONV), 'note': '内置 texconv，不需要额外装东西也能转 DDS。'},
        },
        'avatars': {'dir': AVATAR_DIR, 'extracted': sum(
            len([f for f in os.listdir(os.path.join(AVATAR_DIR, k)) if f.lower().endswith('.avif')])
            if os.path.isdir(os.path.join(AVATAR_DIR, k)) else 0 for k, _n in AVATAR_KINDS)},
    }


# ------------------------------------------------------------------ 头像

def _avatar_names():
    try:
        with open(AVATAR_NAMES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _avatar_intros():
    try:
        with open(AVATAR_INTRO_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


_GAME_DESC_CACHE = None
_GAME_DESC_FOR = ''


def _game_descs():
    """游戏自带语言表里对每个头像的官方中文说明（cardicon_x/desc 那一列）。"""
    global _GAME_DESC_CACHE, _GAME_DESC_FOR
    root = resolved(load_config()).get('game_root', '')
    if _GAME_DESC_CACHE is not None and _GAME_DESC_FOR == root:
        return _GAME_DESC_CACHE
    out = {}
    try:
        path = os.path.join(root, 'lang', 'unlocks_achievements.csv')
        strip = dict.fromkeys(map(ord, '\u200b\u200c\u200e\u200f'), None)
        with open(path, 'r', encoding='utf-8', errors='replace', newline='') as f:
            for row in csv.reader(f, delimiter=';', quotechar='"'):
                if len(row) < 2 or not row[0].startswith('cardicon_') or not row[0].endswith('/desc'):
                    continue
                cid = row[0][:-len('/desc')]
                zh = (row[10] if len(row) > 10 else '').translate(strip).strip()
                en = row[1].translate(strip).strip()
                if zh or en:
                    out[cid] = zh or en
    except Exception:
        out = {}
    _GAME_DESC_CACHE = out
    _GAME_DESC_FOR = root
    return out


# 语言表里没收录的头像：按 ID 词根组装中文名
# 顺序约定：[国家] + [修饰] + [角色] + [数字]，一眼能看懂是谁
def _generic_note(cid):
    """基础头像本来就没有背景故事，给一句实话，胜过只写“说明缺失”。"""
    if cid.startswith('frame_'):
        return '头像框，纯装饰，游戏内没有附带背景说明。'
    if cid.startswith('profile_header_'):
        return '资料页头图，纯装饰，游戏内没有附带背景说明。'
    if re.fullmatch(r'cardicon_\d+', cid):
        return '游戏自带的基础头像，没有特定人物原型。'
    if re.match(r'cardicon_(sailor|tanker|pilot|heli|crew|officer|fem|afro|'
                r'ussr|ru|cn|us|usa|uk|jp|fr|it|ger|sw|il)_', cid):
        return '游戏自带的标准乘员头像，没有特定人物原型。'
    if cid.startswith('cardicon_thunder_league'):
        return '“雷霆联赛”官方赛事相关头像。'
    if cid.startswith('cardicon_wtm_'):
        return '《战争雷霆手游》相关头像。'
    if cid in ('cardicon_combat', 'cardicon_bot'):
        return '游戏自带头像，没有特定人物原型。'
    return ''


_NATION_TOK = {
    'cn': '中国', 'us': '美国', 'usa': '美国', 'uk': '英国', 'ussr': '苏联', 'ru': '俄罗斯',
    'ger': '德国', 'germany': '德国', 'jp': '日本', 'japan': '日本', 'fr': '法国',
    'france': '法国', 'it': '意大利', 'italy': '意大利', 'sw': '瑞典', 'il': '以色列',
    'ind': '印度', 'au': '澳大利亚', 'za': '南非', 'he': '以色列',
}
_ROLE_TOK = {
    'tanker': '坦克手', 'pilot': '飞行员', 'sailor': '水手', 'crew': '乘员', 'officer': '军官',
    'heli': '直升机飞行员', 'helicopterpilot': '直升机飞行员', 'captain': '舰长',
    'commander': '指挥官', 'driver': '驾驶员', 'gunner': '炮手', 'loader': '装填手',
    'scout': '侦察兵', 'paratrooper': '空降兵', 'soldier': '士兵', 'swimmer': '蛙人',
    'assault': '突击兵', 'guardsman': '卫兵', 'narrator': '播报员',
}
_MOD_TOK = {
    # 修饰
    'fem': '女性', 'woman': '女性', 'female': '女性', 'man': '男性', 'male': '男性',
    'modern': '现代', 'early': '早期', 'access': '测试', 'veteran': '老兵', 'default': '默认',
    'combat': '战斗', 'bot': '机器人', 'royal': '皇家', 'special': '特种', 'forces': '部队',
    'night': '夜间', 'desert': '沙漠', 'winter': '冬季', 'snow': '雪地', 'sea': '海洋',
    'navy': '海军', 'naval': '海军',
    # 材质 / 颜色 / 形状
    'gold': '金', 'golden': '金', 'silver': '银', 'bronze': '青铜', 'wooden': '木质',
    'metal': '金属', 'neon': '霓虹', 'flat': '平面', 'textured': '纹理', 'figured': '花纹',
    'inlay': '镶嵌', 'insert': '嵌条', 'solid': '纯色', 'simple': '简约', 'corner': '边角',
    'accent': '点缀', 'diagonal': '斜纹', 'stripes': '条纹', 'dottet': '点线', 'line': '线条',
    'black': '黑', 'grey': '灰', 'gray': '灰', 'orange': '橙', 'red': '红', 'blue': '蓝',
    'green': '绿', 'yellow': '黄', 'teal': '青', 'turquoise': '绿松石', 'purple': '紫',
    'multicolored': '多彩', 'double': '双色', 'bluered': '蓝红', 'redorange': '红橙',
    'cherry': '樱桃木', 'ebony': '黑檀', 'pine': '松木', 'walnut': '胡桃木',
    # 事件 / 主题
    'thunder': '雷霆', 'league': '联赛', 'bday': '周年', 'wtm': '战雷手游', 'event': '活动',
    'football': '足球', 'tank': '坦克', 'stadium': '体育场', 'goalpost': '球门',
    'forest': '森林', 'mountain': '山脉', 'waves': '波浪', 'air': '空战', 'burst': '爆发',
    'superiority': '制空权', 'cas': '近距支援', 'victory': '胜利', 'day': '日',
    'operation': '行动', 'vulcan': '火神', 'scorched': '焦土', 'earth': '焦土',
    'landing': '登陆', 'top': '顶级', 'secret': '机密', 'titan': '泰坦', 'ammo': '弹药',
    'box': '箱', 'cup': '奖杯', 'pancakes': '煎饼', 'halloween': '万圣节',
    'pumpkins': '南瓜', 'witch': '女巫', 'lunar': '农历', 'ny': '新年', 'dragons': '龙',
    'vintage': '复古', 'shards': '碎片', 'crystal': '水晶', 'apex': '巅峰', 'armored': '装甲',
    'moon': '月球', 'santa': '圣诞老人', 'xmas': '圣诞', 'winterwarrior': '冬战勇士',
    'marathon': '马拉松', 'animal': '动物', 'general': '将军', 'hunter': '猎手',
    'star': '星', 'cruiser': '巡洋舰',
}

# 整组统一命名的前缀（比逐个写 override 清楚）
_OVERRIDE_PREFIX = {
    'cardicon_afro_': '非裔飞行员 ',   # 图检：深肤色男性飞行员，飞行帽+护目镜+螺旋桨背景
}

# 个别需要人工定的名字（语言表里没有，或官方中文不对）
_MOD_FIRST = {'现代', '早期', '测试'}   # 这几个修饰要排在"女性"前面：俄罗斯现代女性 01

_OVERRIDE = {
    'frame_event_xmas_2024': '圣诞活动 2024',
    'profile_header_event_xmas_2024': '圣诞活动 2024',
    'frame_gold_vintage': '复古描金',
    'frame_silver_figured_blue_inlay': '银纹蓝镶嵌',
    'profile_header_air_superiority': '制空权',
    'profile_header_sea_waves_01': '海面波浪 01',
    'profile_header_sea_waves_02': '海面波浪 02',
    'cardicon_konstantin_olshansky': '康斯坦丁·奥利尚斯基',
    'cardicon_us_navy_commander': '美国舰长',
    'cardicon_28_panfilovcev': '潘菲洛夫二十八勇士',
    'cardicon_bot': '机器人',
    'cardicon_combat': '战斗',
    'cardicon_default': '默认头像',
    'cardicon_thunder_league_01': '雷霆联赛 01',
    'cardicon_thunder_league_02': '雷霆联赛 02',
    'cardicon_thunder_league_03': '雷霆联赛 03',
    'cardicon_fr_captain_cruiser': '法国巡洋舰舰长',
    'cardicon_wtm_bday_26_pilot': '战雷手游周年·飞行员',
    'cardicon_wtm_bday_26_sailor': '战雷手游周年·水手',
    'cardicon_wtm_bday_26_tanker': '战雷手游周年·坦克手',
    'cardicon_wtm_jp_tanker_early_access': '战雷手游·日本坦克手（抢先体验）',
    'profile_header_d_day': '诺曼底登陆日',
    'profile_header_iwo_jima_landing': '硫磺岛登陆',
    'profile_header_cas': '近距空中支援',
    'profile_header_efv_p1': 'EFV 两栖突击车',
    'profile_header_it_fiat_6616_ub': '意大利 菲亚特 6616',
    'profile_header_t_44_po': 'T-44 试验车',
    'profile_header_tu_95m': '图-95M',
    'profile_header_xf5u': 'XF5U 飞饼',
    'profile_header_air_burst_01': '空战·爆发 01',
    'profile_header_scorched_earth_01': '焦土 01',
}

# 官方中文翻得不妥的地方：只改显示名，不删官方名
_OFFICIAL_FIX = {
    'cardicon_desert_cinnamon_01': '伯尼·马勒克（香料觉醒）',
    'cardicon_desert_cinnamon_02': '战鹰家族王子（香料觉醒）',
    'cardicon_desert_cinnamon_03': '卡纳安·德纳利（香料觉醒）',
}
_NOTE = {
    'cardicon_desert_01': '沙漠星球三部曲之一 —— 战鹰家族的副官，随王子来到沙丘星球。',
    'cardicon_desert_02': '沙漠星球三部曲之一 —— 贵族家族的年轻统治者，沙丘星球的主人。',
    'cardicon_desert_03': '沙漠星球三部曲之一 —— 战鹰家族的武器大师，王子的护卫与导师。',
    'cardicon_desert_cinnamon_01': '香料觉醒版。英文描述写的是"在弥漫肉桂香气的沙漠中久居，蓝眼如印记"——'
                                  '沙丘星球、贵族家族、香料、蓝眼，这一整组是《沙丘》的致敬。',
    'cardicon_desert_cinnamon_02': '香料觉醒版。描述为"流亡沙漠途中接触到香料，留下了印记"。',
    'cardicon_desert_cinnamon_03': '香料觉醒版。描述为"追随主人走进无尽沙漠，无处不在的香料也在他身上留下了印记"。',
    'cardicon_konstantin_olshansky': '康斯坦丁·费奥多罗维奇·奥利尚斯基（1915–1944），苏联海军陆战队军官，'
                                     '苏联英雄；乌克兰海军的"康斯坦丁·奥利尚斯基号"登陆舰即以他命名。',
}


def _pretty_id(cid):
    for pre, name in _OVERRIDE_PREFIX.items():
        if cid.startswith(pre):
            tail = cid[len(pre):].lstrip('_')
            return (name + tail) if tail.isdigit() else name.strip()
    s = cid
    for pre in ('cardicon_', 'frame_', 'profile_header_'):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    parts = [p for p in s.split('_') if p]
    if len(parts) == 1 and parts[0].isdigit():
        return '默认头像 %s' % parts[0]
    nation, mod, role, num, other = [], [], [], [], []
    for p in parts:
        low = p.lower()
        if low.isdigit():
            num.append(p)
        elif low in _NATION_TOK:
            nation.append(_NATION_TOK[low])
        elif low in _ROLE_TOK:
            role.append(_ROLE_TOK[low])
        elif low in _MOD_TOK:
            mod.append(_MOD_TOK[low])
        else:
            other.append(p.capitalize() if len(p) > 3 else p.upper())
    mod_first = [m for m in mod if m in _MOD_FIRST]
    mod_rest = [m for m in mod if m not in _MOD_FIRST]
    zh = ''.join(nation) + ''.join(mod_first) + ''.join(mod_rest) + ''.join(role) + ''.join(other)
    tail = (' ' + ' '.join(num)) if num else ''
    return (zh + tail).strip() or cid


def list_avatars():
    names = {x['id']: x for x in _avatar_names()} if isinstance(_avatar_names(), list) else _avatar_names()
    intros = _avatar_intros()
    gamedesc = _game_descs()
    out = []
    for kind, label in AVATAR_KINDS:
        d = os.path.join(AVATAR_DIR, kind)
        files = []
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if not f.lower().endswith('.avif'):
                    continue
                cid = os.path.splitext(f)[0]
                info = names.get(cid) or {}
                official = info.get('zh') or ''
                fixed = _OVERRIDE.get(cid) or _OFFICIAL_FIX.get(cid) or ''
                zh = fixed or official or _pretty_id(cid)
                desc = _NOTE.get(cid) or gamedesc.get(cid) or (info.get('desc') or '')
                gen = '' if (intros.get(cid) or desc) else _generic_note(cid)
                files.append({'file': f, 'id': cid,
                              'zh': zh, 'official': official, 'fixed': bool(fixed),
                              'en': info.get('en') or '',
                              'named': bool(official),
                              'intro': intros.get(cid) or '',
                              'desc': desc[:220],
                              'gen': gen,
                              'url': '/api/avatars/file?c=%s&f=%s' % (kind, f)})
        out.append({'key': kind, 'label': label, 'count': len(files), 'files': files})
    return out


# ================================================================= HTTP

def static_map():
    return {'/': 'index.html', '/style.css': 'style.css', '/app.js': 'app.js'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'WTRoundtable/1.0'

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype=None, cache=False):
        if not os.path.isfile(path):
            self.send_error(404)
            return
        if ctype is None:
            ext = os.path.splitext(path)[1].lower()
            ctype = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
                     '.js': 'application/javascript; charset=utf-8', '.png': 'image/png',
                     '.svg': 'image/svg+xml', '.ico': 'image/x-icon'}.get(ext, 'application/octet-stream')
        with open(path, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'public, max-age=86400' if cache else 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        cfg = resolved(load_config())
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = unquote(u.path)
        try:
            if path in static_map():
                return self.send_file(os.path.join(WEBROOT, static_map()[path]))
            if path == '/api/state':
                return self.send_json({'ok': True, 'skin': self.skin_state(cfg),
                                       'voice': voice_state(cfg),
                                       'env': env_state(cfg),
                                       'avatars': list_avatars(),
                                       'config': {k: cfg.get(k, '') for k in
                                                  ('game_root', 'gimp', 'sdv_root', 'tts_root',
                                                   'uvr_root', 'fmod_kit')}})
            if path == '/api/env':
                return self.send_json({'ok': True, 'env': env_state(cfg)})
            if path == '/api/avatars/file':
                c = q['c'][0]
                f = q['f'][0]
                if c not in [k for k, _n in AVATAR_KINDS]:
                    raise ValueError('分类不对')
                fp = safe_join(os.path.join(AVATAR_DIR, c), f)
                return self.send_file(fp, 'image/avif', cache=True)
            if path == '/api/skin/thumb':
                return self.send_file(thumbnail(q['v'][0], q['s'][0], q['f'][0]), 'image/png', cache=True)
            if path == '/api/skin/blk':
                return self.send_json({'ok': True, 'blocks': read_blk(q['v'][0], q['s'][0])})
            if path == '/api/skin/compat':
                return self.send_json(do_compat(cfg))
            if path == '/api/job':
                jid = q['id'][0]
                from_i = int(q.get('from', ['0'])[0])
                job = _jobs.get(jid)
                if not job:
                    return self.send_json({'ok': False, 'error': '没有这个作业'}, 404)
                return self.send_json({'ok': True, 'id': jid, 'title': job['title'],
                                       'lines': job['lines'][from_i:], 'next': len(job['lines']),
                                       'done': job['done'], 'ok2': job['ok'],
                                       'elapsed': job.get('elapsed')})
            if path == '/api/browse':
                d = unquote(q.get('dir', [BASE])[0]) or BASE
                if not os.path.isdir(d):
                    d = BASE
                dirs, files = [], []
                try:
                    for e in sorted(os.listdir(d)):
                        fp = os.path.join(d, e)
                        if os.path.isdir(fp):
                            dirs.append(e)
                        elif e.lower().endswith(AUDIO_EXT + IMAGE_EXT + ('.bank', '.blk', '.zip')):
                            files.append({'name': e, 'mb': round(os.path.getsize(fp) / 1048576.0, 2)})
                except OSError as e:
                    return self.send_json({'ok': False, 'error': str(e)}, 403)
                parent = os.path.dirname(os.path.abspath(d))
                if parent == d:
                    parent = ''
                return self.send_json({'ok': True, 'path': d, 'parent': parent,
                                       'dirs': dirs, 'files': files,
                                       'shortcuts': [['圆桌工程', BASE], ['涂装库', SKIN_ROOT],
                                                     ['语音工程', VOICE], ['原版语音', VOICE_ORIG],
                                                     ['成品', VOICE_PACK], ['参考音色', VOICE_REF],
                                                     ['桌面', os.path.expanduser('~\\Desktop')],
                                                     ['D 盘', 'D:\\'], ['C 盘', 'C:\\']]})
            self.send_error(404)
        except KeyError as e:
            self.send_json({'ok': False, 'error': '缺少参数 %s' % e}, 400)
        except Exception as e:
            self.send_json({'ok': False, 'error': str(e)}, 500)

    def skin_state(self, cfg):
        skins = list_skins(cfg)
        names = load_vehicle_names(cfg)
        used = {}
        for s in skins:
            if s['vehicle'] not in used:
                n = names.get(s['vehicle']) or {}
                used[s['vehicle']] = {'zh': n.get('zh', ''), 'en': n.get('en', '')}
        kb = load_kb(cfg)
        return {'libraryRoot': SKIN_ROOT, 'paletteRoot': PALETTE, 'gameRoot': cfg.get('game_root') or '',
                'skinRoot': skin_dir_of(cfg), 'gimp': cfg.get('gimp') or '',
                'gimpFound': bool(cfg.get('gimp')) and os.path.isfile(cfg['gimp']),
                'texconvFound': os.path.isfile(TEXCONV), 'skins': skins,
                'vehicleNames': used,
                'kb': {'updated': kb.get('updated') or '', 'count': len(kb.get('textures') or {}),
                       'names': len(kb.get('names') or {}),
                       'families': len(kb.get('families') or {})}}

    def read_body(self):
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b'{}'
        return json.loads(raw.decode('utf-8') or '{}')

    def do_POST(self):
        cfg = resolved(load_config())
        path = unquote(urlparse(self.path).path)
        try:
            p = self.read_body()
        except Exception as e:
            return self.send_json({'ok': False, 'error': '解析失败：%s' % e}, 400)
        try:
            r = self.dispatch(cfg, path, p)
            return self.send_json(r)
        except Exception as e:
            self.send_json({'ok': False, 'error': str(e)}, 500)

    def dispatch(self, cfg, path, p):
        # ---- 通用
        if path == '/api/config':
            for k in ('game_root', 'gimp', 'sdv_root', 'tts_root', 'uvr_root', 'fmod_kit'):
                if k in p:
                    cfg[k] = str(p[k]).strip()
            save_config(cfg)
            cfg = resolved(cfg)
            save_config(cfg)
            return {'ok': True, 'message': '设置已保存'}
        if path == '/api/open':
            t = p.get('target')
            table = {'library': SKIN_ROOT, 'game': skin_dir_of(cfg), 'palette': PALETTE,
                     'voice': VOICE, 'orig': VOICE_ORIG, 'proj': VOICE_PROJ, 'pack': VOICE_PACK,
                     'ref': VOICE_REF, 'mod': mod_dir(cfg), 'core': CORE,
                     'sdv': cfg.get('sdv_root') or '', 'tts': cfg.get('tts_root') or '',
                     'uvr': cfg.get('uvr_root') or '', 'fmodkit': cfg.get('fmod_kit') or '',
                     'avatars': AVATAR_DIR}
            d = table.get(t) or ''
            if not d or not os.path.isdir(d):
                raise RuntimeError('打不开：%s' % d)
            if os.name == 'nt':
                os.startfile(d)
            return {'ok': True, 'message': '已打开 ' + d}

        # ---- 涂装
        if path == '/api/skin/install':
            return do_skin_install(cfg, p)
        if path == '/api/skin/uninstall':
            return do_skin_uninstall(cfg, p)
        if path == '/api/skin/delete':
            return do_skin_delete(cfg, p)
        if path == '/api/skin/rename':
            return do_skin_rename(cfg, p)
        if path == '/api/skin/new':
            return do_skin_new(cfg, p)
        if path == '/api/skin/edit':
            return do_skin_edit(cfg, p)
        if path == '/api/skin/convert':
            return do_skin_convert(cfg, p)
        if path == '/api/skin/import':
            return self.import_skin(p)
        if path == '/api/skin/kb-scan':
            kb = build_kb(cfg)
            _KB_CACHE['mtime'] = None
            return {'ok': True, 'message': '知识库已更新：收录 %d 台载具的纹理映射、%d 个车族'
                                           % (len(kb.get('textures') or {}), len(kb.get('families') or {}))}
        if path == '/api/skin/check':
            return dict({'ok': True}, **check_compat(cfg, p.get('vehicle', ''), p.get('name', '')))
        if path == '/api/upload':
            d = p.get('dir') or VOICE_REF
            os.makedirs(d, exist_ok=True)
            n = 0
            for item in p.get('files', []):
                fn = clean_name(os.path.basename(item['name'].replace('\\', '/')))
                if not fn:
                    continue
                with open(os.path.join(d, fn), 'wb') as f:
                    f.write(base64.b64decode(item['b64']))
                n += 1
            return {'ok': True, 'message': '已复制 %d 个文件到 %s' % (n, d)}

        # ---- 语音
        if path == '/api/voice/extract':
            jid = start_job('提取原版语音 %s' % p['code'],
                            lambda j: job_extract(j, cfg, p['code'], p.get('cat') or p.get('kind') or 'ground'))
            return {'ok': True, 'job': jid, 'message': '已开始提取'}
        if path == '/api/voice/sdv':
            jid = start_job('SeedVC 批量转换',
                            lambda j: job_sdv(j, cfg, p['src'], p['dst'], p['ref'],
                                              p.get('steps', 30), p.get('f0', True),
                                              p.get('pitch', 0), p.get('limit', 0)))
            return {'ok': True, 'job': jid, 'message': '已开始转换'}
        if path == '/api/voice/radio':
            jid = start_job('无线电效果',
                            lambda j: job_radio(j, cfg, p['src'], p['dst'], p.get('preset', '1')))
            return {'ok': True, 'job': jid, 'message': '已开始处理'}
        if path == '/api/voice/tts':
            entries = None
            if p.get('rawText'):
                entries = parse_script(p['rawText'])
            if not entries:
                entries = [{'id': '', 'text': t.strip()}
                           for t in (p.get('text') or '').splitlines() if t.strip()]
            jid = start_job('TTS 批量生成',
                            lambda j: job_tts(j, cfg, p['ref'], entries, p.get('lang', 'EN'),
                                              p['dst'], p.get('emoRef', ''), p.get('pitch', 0)))
            return {'ok': True, 'job': jid, 'message': '已开始生成'}
        if path == '/api/voice/parse':
            return {'ok': True, 'entries': parse_script(p.get('rawText') or '')}
        if path == '/api/voice/fmod-build':
            jid = start_job('FMOD 打包',
                            lambda j: job_fmod_build(j, cfg, p.get('src', ''), p.get('dst', '')))
            return {'ok': True, 'job': jid, 'message': '已开始打包'}
        if path == '/api/voice/collect':
            jid = start_job('收集已构建的 bank',
                            lambda j: job_collect_banks(j, cfg, p.get('src', ''), p.get('dst', '')))
            return {'ok': True, 'job': jid, 'message': '已开始收集'}
        if path == '/api/voice/scan-material':
            return {'ok': True, 'result': analyze_material(cfg, p.get('src', ''))}
        if path == '/api/voice/pack':
            jid = start_job('整理素材并打包',
                            lambda j: job_apply_material(j, cfg, p.get('src', ''),
                                                         p.get('root', ''), p.get('lang', ''),
                                                         p.get('dst', '') or VOICE_PACK))
            return {'ok': True, 'job': jid, 'message': '已开始整理并打包'}
        if path == '/api/avatars/extract':
            jid = start_job('提取战雷头像',
                            lambda j: job_extract_avatars(j, cfg))
            return {'ok': True, 'job': jid, 'message': '已开始提取头像'}
        if path == '/api/voice/install':
            jid = start_job('安装到游戏', lambda j: job_install_mod(j, cfg, p['src'], p.get('names')))
            return {'ok': True, 'job': jid, 'message': '已开始安装'}
        if path == '/api/voice/prepare-mod':
            steps = enable_mods(cfg)
            return {'ok': True, 'message': '；'.join(steps), 'steps': steps,
                    'modEnabled': mod_enabled(cfg)}
        if path == '/api/voice/uninstall':
            name = clean_name(p['name'])
            f = safe_join(mod_dir(cfg), name)
            if not os.path.isfile(f):
                raise RuntimeError('没找到 ' + name)
            os.remove(f)
            return {'ok': True, 'message': '已移除 ' + name}
        if path == '/api/voice/uninstall-all':
            md = mod_dir(cfg)
            n = 0
            if os.path.isdir(md):
                for f in os.listdir(md):
                    if f.lower().endswith('.bank'):
                        os.remove(os.path.join(md, f))
                        n += 1
            return {'ok': True, 'message': '清空了 sound\\mod（%d 个文件）' % n}
        if path == '/api/voice/new-project':
            name = clean_name(p['name'])
            if not name:
                raise RuntimeError('名字不能为空')
            d = os.path.join(VOICE_PROJ, name)
            if os.path.exists(d):
                raise RuntimeError('已存在同名工程')
            for sub in ('01-原声', '02-转换', '03-效果', '04-打包'):
                os.makedirs(os.path.join(d, sub), exist_ok=True)
            return {'ok': True, 'message': '已新建工程：' + name, 'path': d}
        if path == '/api/voice/import':  # 导入"已经有成品"
            return self.import_voice(p)
        raise RuntimeError('未知接口 ' + path)

    # ---- 导入

    def import_skin(self, p):
        tmp = materialize(p)
        try:
            entries = os.listdir(tmp)
            while len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
                tmp = os.path.join(tmp, entries[0])
                entries = os.listdir(tmp)
            blks = [e for e in entries if e.lower().endswith('.blk')]
            if not blks:
                raise RuntimeError('里面没有 .blk，游戏不会认这套涂装')
            vehicle = clean_name(p.get('vehicle') or os.path.splitext(blks[0])[0])
            name = clean_name(p.get('name') or vehicle)
            vdir = os.path.join(SKIN_ROOT, vehicle)
            os.makedirs(vdir, exist_ok=True)
            dst = os.path.join(vdir, name)
            i = 2
            while os.path.exists(dst):
                dst = os.path.join(vdir, '%s (%d)' % (name, i))
                i += 1
            shutil.copytree(tmp, dst)
            return {'ok': True, 'message': '已导入涂装：%s' % os.path.basename(dst)}
        finally:
            shutil.rmtree(TMP_IMPORT, ignore_errors=True)

    def import_voice(self, p):
        tmp = materialize(p)
        try:
            entries = os.listdir(tmp)
            while len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
                tmp = os.path.join(tmp, entries[0])
                entries = os.listdir(tmp)
            if not any(e.lower().endswith('.bank') for e in entries):
                raise RuntimeError('这个包里没有 .bank 文件')
            name = clean_name(p.get('name') or '导入的语音包')
            dst = os.path.join(VOICE_PACK, name)
            i = 2
            while os.path.exists(dst):
                dst = os.path.join(VOICE_PACK, '%s (%d)' % (name, i))
                i += 1
            shutil.copytree(tmp, dst)
            return {'ok': True, 'message': '已导入成品：%s' % os.path.basename(dst), 'path': dst}
        finally:
            shutil.rmtree(TMP_IMPORT, ignore_errors=True)


def materialize(p):
    shutil.rmtree(TMP_IMPORT, ignore_errors=True)
    os.makedirs(TMP_IMPORT, exist_ok=True)
    if p.get('zipb64'):
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(p['zipb64']))) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                rel = info.filename.replace('\\', '/')
                if rel.startswith('/') or '..' in rel.split('/'):
                    continue
                dst = os.path.join(TMP_IMPORT, *rel.split('/'))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(info) as fs, open(dst, 'wb') as fd:
                    shutil.copyfileobj(fs, fd)
    elif p.get('files'):
        for item in p['files']:
            fn = os.path.basename(item['name'].replace('\\', '/'))
            with open(os.path.join(TMP_IMPORT, fn), 'wb') as f:
                f.write(base64.b64decode(item['b64']))
    elif p.get('dir') and os.path.isdir(p['dir']):
        shutil.rmtree(TMP_IMPORT, ignore_errors=True)
        return p['dir']
    else:
        raise RuntimeError('没有可导入的内容')
    return TMP_IMPORT


def pick_port(preferred):
    for p in [preferred] + list(range(preferred + 1, preferred + 20)):
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', p))
            s.close()
            return p
        except OSError:
            s.close()
    return preferred


def main():
    argv = sys.argv[1:]
    no_browser = '--no-browser' in [a.lower() for a in argv]
    cfg = resolved(load_config())
    save_config(cfg)
    for d in (CACHE, SKIN_ROOT, PALETTE, VOICE_ORIG, VOICE_PROJ, VOICE_PACK, VOICE_REF):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    digits = [a for a in argv if a.isdigit()]
    port = pick_port(int(digits[0]) if digits else int(cfg.get('port') or 8788))
    url = 'http://127.0.0.1:%d/' % port
    print('=' * 64)
    print('  战雷圆桌工程 已启动')
    print('  地址 : ' + url)
    print('  游戏 : ' + (cfg.get('game_root') or '（没找到，请在网页设置里填）'))
    print('  SeedVC : ' + (cfg.get('sdv_root') or '') + ('  [OK]' if os.path.isfile(sdv_python(cfg)) else '  [缺]'))
    print('  FMOD CLI : ' + (find_fmod_cli(cfg) or '（没找到）'))
    print('=' * 64)
    print('关掉这个窗口 = 关掉圆桌工程。')
    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
