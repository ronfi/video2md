# CLAUDE.md — video 仓库工作指南

## 项目定位
**视频转写 AI 工具**（video2md）：任意视频（本地文件/录屏/B 站链接）→ 语音/画面提取转写 →
结构化 Markdown → HTML 阅读。B 站下载（bili_dl）是可选前置。
`ref/` 下持续积累转写文档（长鑫存储、泡泡玛特、AI 行业等）。

## 目录速览
```
tools/            # 三件套：bili_dl.py / video2md.py / md2html.py（用法详见 tools/README.md）
ref/              # 视频与转写文档；BV*.mp4 大文件不入库，<BV>.title.txt sidecar 入库
html/             # md2html 输出（临时，不入库，可随时重建）
requirements.txt  # 依赖统一安装
README.md / README.en.md   # 项目说明（中/英双语，改动需同步两份）
```

## 标准工作流
```bash
python3 tools/bili_dl.py <BV号或链接>                 # 下到 ref/，自动写 <BV>.title.txt
python3 tools/video2md.py ref/<BV>.mp4 --model small --auto-crop [--interval 10]
python3 tools/md2html.py                              # 全量重建 html/（会清理过期页面）
# 然后 git add -A && commit && push（见 Git 约定）
```
- **长视频（>15min）加 `--interval 10`**；短视频默认 3s。
- **多条视频并行**：每条开一个进程、各限 `OMP_NUM_THREADS=16`
  （单进程 ctranslate2 会吃 ~33 核，多进程不限线程会互踩；用户已确认此偏好）。
- 长任务（>10min）放后台跑（`run_in_background`），完成后统一收尾（出 HTML→提交→汇报修正数）。
- video2md 全自动特性：标题进文件名/H1、BV 号自动生成视频链接、OCR 辅助同音字修正、
  简体引导+OpenCC 兜底（Whisper 偶发繁体已治）、DeepSeek 整理正文+折叠附录。

## 环境要点
- Python 用 conda **rf** 环境（`/home/bsc/miniconda3/envs/rf/`）；报 ModuleNotFoundError 先查环境。
- **无 GPU**，64 核/125G 内存；Whisper 纯 CPU（35min 音频 ≈ 15min）。
- 需要 `DEEPSEEK_API_KEY` 环境变量（LLM 修正与整理；缺失时自动降级为 raw 版式）。
- ffmpeg 无系统安装，统一用 `imageio_ffmpeg.get_ffmpeg_exe()`。
- B 站下载**只能走 bili_dl.py 的 API 通道**（视频页对本机 IP 412 风控，yt-dlp 不可用）；
  未登录上限 480p。抖音无法服务端下载（动态签名），需用户录屏/保存后提供文件。

## Git 约定（重要）
- **用户已授权：改动完成后自动 `git commit` + `git push origin main`，无需询问**。
- 提交信息用中文，结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 远程：`origin = https://github.com/ronfi/video2md`（**public 仓库**，勿提交任何密钥/隐私/视频文件）。
- 不入库：`ref/BV*.mp4`（版权大文件）、`*_v2md/`、`html/`、`*.swp`、`__pycache__/`。
- 新增/改动转写文档后：跑 `md2html.py` 重建索引再提交。
- **站点发布**（https://ronfi.github.io/video2md/ ，gh-pages 分支）：文档有更新时同步发布：
  `python3 tools/md2html.py -o <临时目录> --bundle-assets && touch <临时目录>/.nojekyll`，
  然后在临时目录 `git init -b gh-pages` + `push -f origin gh-pages`（孤儿分支，覆盖式）。

## 设计语言（md2html 样式）
「QUANT WORKFLOW 信息卡」体系：终端绿 #39E6A8 结构件 + 金黄 #FFC83D 强调 +
等宽眉标/时间戳 + H1 进度线签名；浅色纸面优先、暗色随系统。改样式保持此风格。
