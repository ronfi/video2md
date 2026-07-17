# tools

本目录的辅助脚本。

**依赖统一安装**（在仓库根目录）：
```bash
pip install -r requirements.txt
```
> 注意用对 Python 环境：报 `ModuleNotFoundError` 通常是当前终端的 python/pip 不是安装时那个环境（如 conda env）。可用 `which python3` 确认，或直接 `python3 -m pip install -r requirements.txt`。

## bili_dl.py — B 站视频下载（API 通道）

绕开视频页 412 风控（数据中心 IP 常被拦、yt-dlp 因此失败），走 API 通道：
匿名 cookies → view API(标题/cid) → playurl API(DASH流) → 下载 → ffmpeg 合并。

```bash
pip install requests imageio-ffmpeg
python tools/bili_dl.py BV1GPTH6vErg              # 下到 ref/<BV号>.mp4
python tools/bili_dl.py <B站链接> -d ref -o 自定义名.mp4
python tools/bili_dl.py BVxxxx --page 2           # 多 P 视频选分 P
python tools/bili_dl.py BVxxxx --cookies bili.txt --qn 80   # 登录 cookies 解锁 1080p
```
- 未登录清晰度上限 **480p**；1080p 需登录 cookies（Netscape 格式）。
- ⚠️ 版权：仅个人学习/内容分析用，勿传播；大文件已被 `.gitignore`（`ref/BV*.mp4`）排除。
- 自动写 `<BV号>.title.txt` sidecar（视频标题），`video2md.py` 会读取用作文档标题与文件名后缀。
- 常与 `video2md.py` 连用：下载 → 转结构化文档。

## md2html.py — Markdown 批量转 HTML（本地浏览）

把仓库里的 .md 转成带样式的 HTML 并生成 index.html 索引，浏览器直接看（支持表格/折叠附录/关键帧图片/深色模式）。输出目录 `html/` 为临时产物，已被 `.gitignore`。

```bash
pip install markdown
python tools/md2html.py               # 全仓库 md -> html/，浏览器打开 html/index.html
python tools/md2html.py ref/x.md      # 只转指定文件
python tools/md2html.py -o /tmp/docs  # 自定义输出目录
```

## video2md.py — 视频转 Markdown

从**语音**(ASR 转写) 和**画面**(关键帧 + OCR) 提取关键信息，生成结构化 Markdown 文档。
适合把口播/教程/录屏视频快速转成可检索的图文文档。

### 能力
- 🎙 **语音转写**：faster-whisper（离线、CPU 可跑），带时间戳。
- 🖼 **画面提取**：按间隔抽关键帧，RapidOCR 识别画面文字（信息卡/字幕/标题）。
- ✂️ **自动去 UI 边**：`--auto-crop` 用方差法检测手机录屏的灰/白 UI 边，只 OCR 视频内容区。
- 🧹 **OCR 降噪**：自动过滤时间戳、倍速、状态栏、纯符号等噪声。
- 🧠 **整理成规范文档**：内置 DeepSeek API，把 raw 转写+OCR **去重、纠错、分章节排版**成规范 Markdown（概述/分章节正文/要点速览/术语表）；原始素材折叠进附录便于溯源。
- 🏷 **标题即文件名**：视频标题（`--title` / `<视频名>.title.txt` sidecar / LLM 自动概括）用作文档 H1，并作为输出文件名后缀，一眼可知内容。
- 🔤 **ASR 同音字修正**：LLM 借助**时间对齐的关键帧 OCR 词**修正转写中的同音/近音错字（如"高量→高亮"）；只输出修正对、程序端最小替换，不重写不润色。`--no-fix-asr` 可关。

### 安装依赖
```bash
pip install faster-whisper rapidocr-onnxruntime imageio-ffmpeg pillow numpy requests
```
> 首次运行自动下载 Whisper 模型（small≈460MB，base≈140MB）。无需 GPU。

### 用法
```bash
# DeepSeek 摘要需先设置 key（不设则自动跳过 LLM，仅出转写+OCR）
export DEEPSEEK_API_KEY=sk-xxx

# 基本（自动检测并裁掉手机录屏 UI 边）
python tools/video2md.py 录屏.mp4 -o out.md --auto-crop

# 手动指定裁剪区 W:H:X:Y
python tools/video2md.py video.mp4 --crop 720:420:0:508

# 不调用 DeepSeek / 不做 OCR
python tools/video2md.py video.mp4 --no-llm
python tools/video2md.py video.mp4 --no-ocr
```

### 参数
| 参数 | 默认 | 说明 |
|---|---|---|
| `video` | — | 输入视频路径（必填） |
| `-o, --out` | `<同名>.md` | 输出 Markdown 路径 |
| `--model` | `small` | Whisper 模型：tiny/base/small/medium |
| `--lang` | `zh` | 语音语言（whisper），如 zh/en |
| `--doc-lang` | `auto` | 输出文档语言：auto=跟随 --lang |
| `--interval` | `3.0` | 关键帧采样间隔（秒） |
| `--auto-crop` | 关 | 方差法自动检测并裁掉手机 UI 边 |
| `--crop W:H:X:Y` | — | 手动裁剪区（优先于 --auto-crop） |
| `--no-ocr` | 关 | 跳过画面 OCR |
| `--no-clean` | 关 | 关闭 OCR 降噪 |
| `--no-llm` | 关 | 不调用 DeepSeek（退回未整理的 raw 版式） |
| `--no-fix-asr` | 关 | 不做 OCR 辅助的同音字修正 |
| `--no-appendix` | 关 | 不输出「原始素材」折叠附录 |
| `--title` | 自动 | 视频标题：--title > `<视频名>.title.txt` > LLM 生成；作 H1 与文件名后缀 |
| `--url` | 自动 | 原始视频链接；缺省按文件名 BV 号推断 |
| `--llm-model` | `deepseek-chat` | DeepSeek 模型 |

### 输出
- 一个 `.md`：**正文** = DeepSeek 整理后的规范分章节文档（去重/纠错/排版）；**附录** = 折叠的原始转写(带时间戳) + 关键帧明细(含图)，便于溯源。
- 未设 key 或 `--no-llm` 时：退回未整理的 raw 版式（摘要初稿 + OCR 列表）。
- 中间产物在 `<视频名>_v2md/`（音轨 + 关键帧），已被 `.gitignore` 忽略。

### 局限
- OCR 对手机录屏的小字/特效字偶有错字；DeepSeek 摘要会在语义层平滑这些误差。
- 摘要质量依赖 DeepSeek，可用 `--no-llm` 退回纯转写+OCR。
