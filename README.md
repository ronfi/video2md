# video — 视频转写研报库

把 B 站视频一键变成**可检索、可阅读的结构化文档**：
语音转写（Whisper）+ 画面文字（关键帧 OCR）→ LLM 去重纠错、分章节整理 → 本地 HTML 阅读。

```
下载              转写提取                整理                 阅读
bili_dl.py  ──►  video2md.py  ──►  DeepSeek 结构化  ──►  md2html.py
(B站API通道)     (ASR+OCR+同音字修正)   (正文+折叠附录)      (html/index.html)
```

## 快速开始

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY=sk-xxx        # LLM 整理用；不设则降级为纯转写

# 三步出文档
python3 tools/bili_dl.py BV1fj5f6iEH5                          # 1. 下载到 ref/
python3 tools/video2md.py ref/BV1fj5f6iEH5.mp4 --auto-crop     # 2. 转写 -> ref/<BV>-<标题>.md
python3 tools/md2html.py                                       # 3. 出 HTML，打开 html/index.html
```

> 长视频（>15 分钟）建议加 `--interval 10` 降低关键帧密度。
> 全流程 CPU 可跑，无需 GPU（35 分钟音频约 15 分钟转完）。

## 特性

- **标题即文件名**：下载时自动记录视频标题，文档命名如
  `BV1fj5f6iEH5-长鑫存储10大核心供应商.md`，并自动附原视频链接。
- **同音字修正**：LLM 借助时间对齐的画面 OCR 修正 ASR 同音错字
  （如"中级虚创→中际旭创"、"科丧50→科创50"），只做最小替换、可审计。
- **繁简统一**：简体引导 + OpenCC 兜底，杜绝 Whisper 偶发繁体输出。
- **正文 + 附录**：LLM 整理出分章节规范正文（概述/要点/术语表）；
  原始带时间戳转写与关键帧截图折叠在附录，随时溯源。
- **HTML 阅读**：卡片式索引 + 阅读版式（浅/暗色自适应、关键帧懒加载）。

## 目录

```
tools/            bili_dl.py · video2md.py · md2html.py（详细用法见 tools/README.md）
ref/              转写文档（.md 入库）与视频（BV*.mp4 不入库）
html/             生成的阅读页面（临时产物，随时可重建）
requirements.txt  依赖清单
```

## 说明

- B 站下载走 **API 通道**（服务器 IP 访问视频页常被 412 风控，yt-dlp 不可用）；
  未登录清晰度上限 480p，内容分析足够。
- ⚠️ 版权：下载内容仅供个人学习与内容分析，请勿传播；视频大文件已被 `.gitignore` 排除。
