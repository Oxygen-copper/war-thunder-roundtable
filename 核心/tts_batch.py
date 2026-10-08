# -*- coding: utf-8 -*-
"""战雷圆桌工程 · IndexTTS2 v2.5 批处理驱动（带语言 / 情绪参数）

为什么不用官方 cli_v2 的 batch：
    它 import 的是旧版 indextts.infer_v2，那个 API 里**没有 lang 参数**，
    等于所有文本都按默认语言读 —— 德语进去就变成一串气音。
    这里直接调 infer_v2_5.IndexTTS2，并且每条都能指定语言。

用法：python tts_batch.py --jobs jobs.json
jobs.json:
    {
      "root": "...\\index-tts",
      "model_dir": "...\\checkpoints",
      "lang": "ZH",
      "tasks": [ {"text": "...", "output": "...", "voice": "...",
                  "lang": "DE", "emotion_audio": "...", "emotion_alpha": 1.0} ]
    }
"""

import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', required=True)
    ap.add_argument('--root')
    ap.add_argument('--model-dir')
    a = ap.parse_args()

    with open(a.jobs, encoding='utf-8') as f:
        cfg = json.load(f)
    root = a.root or cfg['root']
    model_dir = a.model_dir or cfg['model_dir']
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault('HF_HUB_CACHE', os.path.join(model_dir, 'hf_cache'))
    os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

    import torch
    from indextts.infer_v2_5 import IndexTTS2

    use_bf16 = bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())
    tts = IndexTTS2(
        model_dir=model_dir,
        cfg_path=os.path.join(model_dir, 'config.yaml'),
        use_deepspeed=False,
        use_cuda_kernel=False,
        use_accel=False,
        use_torch_compile=False,
        use_qwen_emo=False,
        use_bf16=use_bf16,
    )

    tasks = cfg.get('tasks') or []
    print('模型就绪，共 %d 条' % len(tasks), flush=True)
    ok = 0
    for i, t in enumerate(tasks, 1):
        out = t['output']
        d = os.path.dirname(out)
        if d:
            os.makedirs(d, exist_ok=True)
        kw = dict(
            spk_audio_prompt=t['voice'],
            text=t['text'],
            output_path=out,
            lang=t.get('lang') or cfg.get('lang') or 'ZH',
            emo_audio_prompt=t.get('emotion_audio'),
            emo_alpha=float(t.get('emotion_alpha', 1.0)),
            verbose=True,
            max_text_tokens_per_segment=120,
            duration_factor=float(t.get('duration_factor', 1.0)),
        )
        print('[%d/%d] %s | %s' % (i, len(tasks), kw['lang'], t['text'][:44]), flush=True)
        try:
            tts.infer(**kw)
            ok += 1
            print('    -> %s' % out, flush=True)
        except Exception as e:
            print('    !! 失败：%s' % e, flush=True)
    print('DONE %d/%d' % (ok, len(tasks)), flush=True)


if __name__ == '__main__':
    main()
