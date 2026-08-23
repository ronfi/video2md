#!/usr/bin/env python3
"""
视频 -> Markdown：从【语音】(ASR) 和【画面】(关键帧 + OCR) 提取关键信息，生成结构化文档。
含：A 画面裁剪(去手机UI) · B OCR 降噪 · C DeepSeek 生成结构化摘要。

离线部分(ASR/OCR) CPU 可跑；摘要走 DeepSeek API(需 DEEPSEEK_API_KEY)。
依赖：pip install faster-whisper rapidocr-onnxruntime imageio-ffmpeg pillow requests

用法：
  export DEEPSEEK_API_KEY=sk-xxx
  python tools/video2md.py ref/ref.mp4 -o out.md --crop 720:420:0:508
  python tools/video2md.py v.mp4 --auto-crop           # 自动检测内容区(去黑边)
  python tools/video2md.py v.mp4 --no-llm              # 不调用 DeepSeek
"""
import argparse, os, re, subprocess, datetime
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()

def hhmmss(t):
    t = int(t); return f"{t//60:02d}:{t%60:02d}"

def probe(video):
    out = subprocess.run([FF, "-i", video], capture_output=True, text=True).stderr
    dur, res = 0.0, "?"
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    if m: dur = int(m[1])*3600 + int(m[2])*60 + float(m[3])
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    if m: res = f"{m[1]}x{m[2]}"
    return dur, res

def extract_audio(video, wav):
    subprocess.run([FF, "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav],
                   check=True, stderr=subprocess.DEVNULL)

def _content_span(act):
    """逐行/列活跃度 -> 内容带 [start,end)（平滑+阈值+桥接小缝隙取最长段）。"""
    import numpy as np
    a = act.astype(np.float32)
    k = max(1, int(len(a) * 0.02))
    s = np.convolve(a, np.ones(2*k+1)/(2*k+1), mode="same")   # 平滑
    idx = np.where(s > s.max() * 0.18)[0]                      # 高活跃行/列
    if len(idx) == 0:
        return 0, len(a)
    gap = max(1, int(len(a) * 0.03))
    segs, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev <= gap:
            prev = i
        else:
            segs.append((start, prev)); start = prev = i
    segs.append((start, prev))
    s0, s1 = max(segs, key=lambda p: p[1] - p[0])
    return int(s0), int(s1) + 1

def detect_ui_crop(video, dur):
    """方差法检测手机录屏的内容区(去灰/白UI边)：内容区像素方差高，UI边纯色方差低。"""
    import numpy as np, glob, tempfile, shutil
    from PIL import Image
    tmp = tempfile.mkdtemp()
    try:
        n = 8; interval = max(1.0, dur / (n + 1))
        subprocess.run([FF, "-y", "-i", video, "-vf", f"fps=1/{interval}", "-q:v", "3",
                        os.path.join(tmp, "f_%03d.jpg")], check=True, stderr=subprocess.DEVNULL)
        files = sorted(glob.glob(os.path.join(tmp, "f_*.jpg")))[:n]
        if not files:
            return None
        row_act = col_act = None
        for fp in files:
            g = np.asarray(Image.open(fp).convert("L"), dtype=np.float32)
            r, c = g.std(axis=1), g.std(axis=0)
            row_act = r if row_act is None else row_act + r
            col_act = c if col_act is None else col_act + c
        y0, y1 = _content_span(row_act / len(files))
        x0, x1 = _content_span(col_act / len(files))
        H, W = len(row_act), len(col_act)
        x0 &= ~1; y0 &= ~1
        w = (x1 - x0) & ~1; h = (y1 - y0) & ~1
        if w >= W * 0.97 and h >= H * 0.97:
            return None   # 几乎整帧，无需裁剪
        return f"{w}:{h}:{x0}:{y0}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def transcribe(wav, model_size, lang):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    # 简体引导词：抑制 Whisper 偶发输出繁体
    prompt = "以下是普通话内容，请用简体中文输出。" if lang == "zh" else None
    segs, _ = model.transcribe(wav, language=lang, vad_filter=True, initial_prompt=prompt)
    out = [(s.start, s.end, s.text.strip()) for s in segs if s.text.strip()]
    if lang == "zh":
        try:  # OpenCC 繁->简兜底（未安装则跳过）
            from opencc import OpenCC
            cc = OpenCC("t2s")
            out = [(s, e, cc.convert(t)) for s, e, t in out]
        except ImportError:
            pass
    return out

def extract_keyframes(video, outdir, interval, crop=None):
    os.makedirs(outdir, exist_ok=True)
    vf = f"fps=1/{interval}"
    if crop: vf = f"crop={crop}," + vf
    subprocess.run([FF, "-y", "-i", video, "-vf", vf, "-q:v", "3",
                    os.path.join(outdir, "kf_%04d.jpg")], check=True, stderr=subprocess.DEVNULL)
    frames = sorted(f for f in os.listdir(outdir) if f.startswith("kf_"))
    return [(os.path.join(outdir, f), i*interval) for i, f in enumerate(frames)]

# ---------- B: OCR 降噪 ----------
_NOISE = [
    re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$"),   # 时间 06:23 / 00:01:02
    re.compile(r"^\d+(\.\d+)?x$", re.I),        # 1x 1.5x 倍速
    re.compile(r"^[0-9A-Za-z]{1,3}$"),          # 短英数噪声 5A 00 4G
    re.compile(r"^[\W_]+$"),                     # 全符号
]
def _is_noise(t):
    t = t.strip()
    if len(t) < 2: return True
    if any(p.match(t) for p in _NOISE): return True
    real = len(re.findall(r"[一-龥A-Za-z0-9%]", t))
    return real / max(1, len(t)) < 0.5          # 符号占比过高

def ocr_frames(frame_paths, clean=True):
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    per = []
    for p in frame_paths:
        res, _ = ocr(p)
        lines = []
        if res:
            for item in res:
                t = item[1].strip()
                if clean and _is_noise(t): continue
                if not clean and len(t) < 2: continue
                lines.append(t)
        per.append(lines)
    return per

# ---------- C0: DeepSeek 借助 OCR 修正 ASR 同音字 ----------
def _llm_chat(prompt, model, max_tokens=4000, timeout=240):
    import requests
    key = os.environ.get("DEEPSEEK_API_KEY")
    r = requests.post("https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.1, "max_tokens": max_tokens, "stream": False}, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def llm_fix_transcript(segments, kf_ocr, model="deepseek-chat", batch=120, doc_lang="zh"):
    """用时间对齐的画面 OCR 词修正 ASR 同音字。返回(新segments, 修正数)。
    只让 LLM 输出修正对 {i, from, to}，程序端最小替换——不重写、可审计。"""
    if not os.environ.get("DEEPSEEK_API_KEY") or not segments:
        return segments, 0
    import json as _json
    segs = list(segments)
    # 全局 OCR 术语表（去重），供跨窗口专有名词参考
    seen, vocab = set(), []
    for _p, _t, lines in kf_ocr:
        for ln in lines:
            if ln not in seen:
                seen.add(ln); vocab.append(ln)
    total_fix = 0
    for b0 in range(0, len(segs), batch):
        chunk = segs[b0:b0 + batch]
        t_lo, t_hi = chunk[0][0] - 12, chunk[-1][1] + 12
        ocr_win = []
        for _p, t, lines in kf_ocr:
            if t_lo <= t <= t_hi:
                for ln in lines:
                    if ln not in ocr_win:
                        ocr_win.append(ln)
        seg_lines = "\n".join(f"[{i}] [{hhmmss(s)}] {txt}"
                              for i, (s, _e, txt) in enumerate(chunk, start=b0))
        if doc_lang == "en":
            prompt = (
                "Below are ASR transcript segments from a video (often containing mis-recognized "
                "words) and the on-screen OCR text from the same time window plus a full-video "
                "term list. Find words the ASR likely mis-recognized (homophones/near-homophones, "
                "proper nouns, technical terms) and correct them based on the on-screen text.\n"
                "Rules: fix wrong words only; no rewriting or polishing; skip if unsure.\n"
                'Output ONLY a JSON array (no other text/code fence): '
                '[{"i":segment_index,"from":"wrong","to":"correct"}]; output [] if nothing to fix.\n\n'
                f"[ASR segments]\n{seg_lines}\n\n"
                "[On-screen OCR in this window]\n" + "\n".join(ocr_win[:80]) +
                "\n\n[Full-video term list]\n" + " / ".join(vocab[:150])
            )
        else:
            prompt = (
            "下面是视频的【语音转写片段】(ASR，常见同音字错误) 和同一时间段的【画面文字OCR】"
            "以及【全片画面术语表】。请找出转写里的**同音/近音错别字**（尤其专有名词、术语），"
            "以画面文字为准给出修正。\n"
            "规则：只修错字，不改语气助词、不做润色、不合并句子；没把握就不修。\n"
            '只输出 JSON 数组（不要任何其它文字/代码块）：[{"i":段号,"from":"原词","to":"正词"}]；'
            "无需修正则输出 []。\n\n"
            f"【语音转写片段】\n{seg_lines}\n\n"
            f"【同时间段画面OCR】\n" + "\n".join(ocr_win[:80]) +
            f"\n\n【全片画面术语表】\n" + " / ".join(vocab[:150])
        )
        try:
            out = _llm_chat(prompt, model)
            out = re.sub(r"^```(json)?|```$", "", out.strip(), flags=re.M).strip()
            fixes = _json.loads(out)
        except Exception as e:
            print(f"      ⚠ 修正批次 {b0} 失败，跳过：{e}")
            continue
        for f in fixes:
            try:
                i, frm, to = int(f["i"]), str(f["from"]), str(f["to"])
            except Exception:
                continue
            if 0 <= i < len(segs) and frm and frm != to and frm in segs[i][2]:
                s, e, txt = segs[i]
                segs[i] = (s, e, txt.replace(frm, to))
                total_fix += 1
    return segs, total_fix

# ---------- C: DeepSeek 整理成规范文档 ----------
def llm_document(seg_lines, ocr_lines, model="deepseek-chat", doc_lang="zh"):
    """把 raw 转写+OCR 交给 DeepSeek，产出去重、纠错、分章节的完整文档正文。"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None, "未设置 DEEPSEEK_API_KEY，跳过 LLM 整理"
    import requests
    if doc_lang == "en":
        prompt = (
            "You are a professional documentation editor. Below are the auto-extracted "
            "[speech transcript] (spoken, possibly repetitive) and [on-screen OCR text] "
            "(repeated across frames, may contain typos) of a video. Organize them into a "
            "well-structured, readable, deduplicated English Markdown document.\n\n"
            "Requirements:\n"
            "1. Deduplicate; present each piece of information once.\n"
            "2. Fix obvious OCR/ASR errors from context; never invent facts.\n"
            "3. Use ## / ### headings; start with '## Overview'.\n"
            "4. Use lists, **bold** keywords, and tables where appropriate.\n"
            "5. Keep all steps, data, tool names, terminology; end with '## Key Terms' or "
            "'## Quick Takeaways'.\n"
            "6. First line: `TITLE: <a title within 15 words>`, then a blank line, then the body "
            "starting at '## Overview' (no H1, no code fences around the doc).\n\n"
            "[Speech transcript (timed)]\n" + "\n".join(seg_lines) +
            "\n\n[On-screen OCR (deduped)]\n" + "\n".join(ocr_lines)
        )
    else:
        prompt = (
        "你是专业的文档整理编辑。下面是某视频自动提取的【语音转写】(口语、可能啰嗦重复)"
        "和【画面文字OCR】(跨帧重复、可能有错字)。请整理成一篇**规范、易读、去重**的中文 Markdown 文档。\n\n"
        "硬性要求：\n"
        "1. **去重**：合并语音里重复的口语、OCR 跨帧重复的文字；同一信息只呈现一次。\n"
        "2. **纠错**：依据上下文修正明显的 OCR/转写错别字（如\"分镇\"→\"分镜\"），不改原意、不编造。\n"
        "3. **分章节**：用 ## / ### 标题按逻辑组织全文；开头写一段「## 概述」。\n"
        "4. **规范排版**：恰当使用有序/无序列表、**加粗**关键词；并列数据或步骤优先用表格。\n"
        "5. **信息完整**：保留全部步骤、数据、工具名、术语；结尾加「## 关键术语」或「## 要点速览」。\n"
        "6. **第一行**输出 `TITLE: <不超过25字、概括视频主题的标题>`，然后空一行，"
        "再输出文档正文，**从 `## 概述` 开始**（不要写一级标题、不要用 ``` 包裹整篇）。\n\n"
        "【语音转写(含时间)】\n" + "\n".join(seg_lines) +
        "\n\n【画面文字OCR(已去重)】\n" + "\n".join(ocr_lines)
    )
    try:
        r = requests.post("https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": 8000, "stream": False}, timeout=240)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip(), None
    except Exception as e:
        return None, f"DeepSeek 调用失败：{e}"

def sanitize_title(t, maxlen=30):
    """标题 -> 可作文件名后缀的安全片段。"""
    t = re.sub(r'[\\/:*?"<>|#\[\]]+', "", t)
    t = re.sub(r"\s+", "", t).strip("-_.")
    return t[:maxlen]

def resolve_title(video, cli_title):
    """标题来源：--title > 同名 sidecar（<视频名去扩展>.title.txt，bili_dl 自动生成）> None(交给LLM)。"""
    if cli_title:
        return cli_title.strip()
    sidecar = os.path.splitext(video)[0] + ".title.txt"
    if os.path.exists(sidecar):
        t = open(sidecar, encoding="utf-8").read().strip()
        if t:
            return t
    return None

def guess_source_url(video):
    """从文件名推断原始视频链接（目前支持 B 站 BV 号）。"""
    m = re.search(r"(BV[0-9A-Za-z]{10})", os.path.basename(video))
    return f"https://www.bilibili.com/video/{m.group(1)}" if m else None

def build_md(video, dur, res, segments, kf_ocr, today, doc_body, note,
             appendix=True, source_url=None, title=None):
    name = os.path.basename(video)
    full_text = "".join(s[2] for s in segments)
    seen, uniq = set(), []
    for _p, _t, lines in kf_ocr:
        for ln in lines:
            if ln not in seen:
                seen.add(ln); uniq.append(ln)

    src = f"来源 `{video}`"
    if source_url:
        src += f" · [视频链接]({source_url})"
    md = [f"# {title or os.path.splitext(name)[0]}\n",
          f"> 时长 {hhmmss(dur)} · 分辨率 {res} · 生成于 {today}　|　{src}\n"]

    if doc_body:                       # LLM 整理后的规范正文（主体）
        md.append(doc_body + "\n")
    else:                              # 无 LLM：退回 raw 版式
        md.append(f"> （{note}）以下为未经整理的原始提取：\n")
        md.append("## 内容摘要（自动初稿）\n")
        md.append(full_text[:200] + ("…" if len(full_text) > 200 else "") + "\n")
        md.append("## 画面关键文字（OCR 去重）\n")
        md += [f"- {ln}" for ln in uniq] or ["- （无）"]

    if appendix:                       # 原始素材折叠进附录，便于溯源、不干扰阅读
        md.append("\n---\n")
        md.append("## 附录：原始提取素材\n")
        md.append("<details>\n<summary>语音全文转写（带时间戳）</summary>\n")
        md += [f"- `[{hhmmss(s)}–{hhmmss(e)}]` {t}" for s, e, t in segments] or ["- （无）"]
        md.append("\n</details>\n")
        md.append("<details>\n<summary>关键帧 + OCR</summary>\n")
        for p, t, lines in kf_ocr:
            md.append(f"\n**`[{hhmmss(t)}]`** " + ("　/　".join(lines) if lines else "（无文字）"))
            md.append(f"\n![{hhmmss(t)}]({p})")
        md.append("\n</details>\n")
    return "\n".join(md)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--model", default="small", help="whisper: tiny/base/small/medium")
    ap.add_argument("--lang", default="zh", help="语音语言（whisper），如 zh/en")
    ap.add_argument("--doc-lang", default="auto", choices=["auto", "zh", "en"],
                    help="输出文档语言：auto=跟随 --lang（zh->中文，其它->英文）")
    ap.add_argument("--interval", type=float, default=3.0, help="关键帧间隔(秒)")
    ap.add_argument("--crop", default=None, help="画面裁剪 W:H:X:Y(去手机UI)")
    ap.add_argument("--auto-crop", action="store_true", help="自动检测内容区(去黑边)")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--no-clean", action="store_true", help="关闭 OCR 降噪")
    ap.add_argument("--no-llm", action="store_true", help="不调用 DeepSeek 整理（退回 raw 版式）")
    ap.add_argument("--no-fix-asr", action="store_true", help="不做 OCR 辅助的同音字修正")
    ap.add_argument("--no-appendix", action="store_true", help="不输出原始素材附录")
    ap.add_argument("--url", default=None, help="原始视频链接（缺省时按文件名 BV 号自动推断）")
    ap.add_argument("--title", default=None, help="视频标题（缺省：读 <视频名>.title.txt，再缺省由 LLM 生成）；用作文档 H1 与输出文件名后缀")
    ap.add_argument("--llm-model", default="deepseek-chat")
    args = ap.parse_args()
    doc_lang = args.doc_lang if args.doc_lang != "auto" else ("zh" if args.lang == "zh" else "en")

    base = os.path.splitext(args.video)[0]
    out_md = args.out or base + ".md"
    work = base + "_v2md"; os.makedirs(work, exist_ok=True)
    wav = os.path.join(work, "audio.wav")
    today = datetime.date.today().isoformat()

    print("[1/5] 探测 + 抽音轨…"); dur, res = probe(args.video); extract_audio(args.video, wav)
    print(f"      时长 {hhmmss(dur)} 分辨率 {res}")
    crop = args.crop
    if args.auto_crop and not crop:
        crop = detect_ui_crop(args.video, dur)
        print(f"      自动检测内容区: {crop or '整帧(无需裁剪)'}")
    print(f"[2/5] 语音转写 (whisper {args.model})…"); segments = transcribe(wav, args.model, args.lang)
    print(f"      {len(segments)} 段")
    print(f"[3/5] 抽关键帧 (每 {args.interval}s{', crop='+crop if crop else ''})…")
    frames = extract_keyframes(args.video, os.path.join(work, "frames"), args.interval, crop)
    print(f"      {len(frames)} 帧")
    if args.no_ocr:
        kf_ocr = [(p, t, []) for p, t in frames]
    else:
        print(f"[4/5] 画面 OCR{'（降噪）' if not args.no_clean else ''}…")
        per = ocr_frames([p for p, _ in frames], clean=not args.no_clean)
        kf_ocr = [(p, t, lines) for (p, t), lines in zip(frames, per)]

    if not args.no_llm and not args.no_fix_asr and not args.no_ocr:
        print(f"[4.5/5] OCR 辅助修正 ASR 同音字 ({args.llm_model})…")
        segments, nfix = llm_fix_transcript(segments, kf_ocr, args.llm_model, doc_lang=doc_lang)
        print(f"      修正 {nfix} 处")

    title = resolve_title(args.video, args.title)

    doc_body, note = (None, "已用 --no-llm 关闭")
    if not args.no_llm:
        print(f"[5/5] DeepSeek 整理成规范文档 ({args.llm_model})…")
        seg_lines = [f"[{hhmmss(s)}] {t}" for s, _e, t in segments]
        uniq = []
        [uniq.append(l) for _p, _t, ls in kf_ocr for l in ls if l not in uniq]
        doc_body, note = llm_document(seg_lines, uniq, args.llm_model, doc_lang=doc_lang)
        print("      " + ("✅ 完成" if doc_body else "⚠ " + note))
        # 解析 LLM 首行 TITLE:（作为标题兜底）
        if doc_body:
            m = re.match(r"^TITLE[:：]\s*(.+?)\s*\n+", doc_body)
            if m:
                doc_body = doc_body[m.end():]
                if not title:
                    title = m.group(1).strip()

    md = build_md(args.video, dur, res, segments, kf_ocr, today, doc_body, note,
                  appendix=not args.no_appendix,
                  source_url=args.url or guess_source_url(args.video),
                  title=title)
    # 标题作为输出文件名后缀（便于一眼识别内容）
    if title:
        safe = sanitize_title(title)
        stem, ext = os.path.splitext(out_md)
        if safe and safe not in os.path.basename(stem):
            out_md = f"{stem}-{safe}{ext}"
    open(out_md, "w", encoding="utf-8").write(md)
    print(f"\n✅ 文档已生成：{out_md}\n   关键帧：{os.path.join(work, 'frames')}")

if __name__ == "__main__":
    main()
