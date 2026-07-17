# video2md — AI Video-to-Document Toolkit

**[中文](README.md) | English**

Turn **any video** (local files, screen recordings, Bilibili links…) into **searchable, readable, well-structured documents**:
speech transcription (Whisper) + on-screen text (keyframe OCR) → LLM dedup/correction and chaptered write-up → HTML reading site.

**📖 Live demo (document library): https://ronfi.github.io/video2md/**

```
Download (opt.)        Extract                  Organize              Read
bili_dl.py    ──►   video2md.py    ──►   DeepSeek structuring ──►  md2html.py
(Bilibili API)     (any video: ASR+OCR       (body + appendix)     (html/index.html)
                    +word correction)
```

## Quick start

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY=sk-xxx        # for LLM organizing; omit to fall back to raw transcript

# Any local video (screen recording, lecture, meeting…) — two steps
python3 tools/video2md.py your_video.mp4 --auto-crop      # -> <name>-<title>.md
python3 tools/md2html.py                                  # -> html/index.html

# English videos: transcribe and write the document in English
python3 tools/video2md.py talk.mp4 --lang en

# Bilibili videos: one extra download step
python3 tools/bili_dl.py BV1fj5f6iEH5                     # -> ref/ (title recorded automatically)
python3 tools/video2md.py ref/BV1fj5f6iEH5.mp4 --auto-crop
```

> For long videos (>15 min) add `--interval 10` to reduce keyframe density.
> Whole pipeline runs on CPU — no GPU required (≈15 min for a 35-min video).

## Features

- **Title as filename**: video title is recorded on download and used for the document
  H1 and filename, e.g. `BV1fj5f6iEH5-<video title>.md`, with a link back to the source video.
- **ASR word correction**: an LLM fixes mis-recognized words (homophones, proper nouns)
  using *time-aligned on-screen OCR text*; corrections are minimal, auditable replacements.
- **Chinese & English**: `--lang en` transcribes English speech and writes the document in
  English (`--doc-lang` to override); Chinese output is kept in Simplified (OpenCC fallback).
- **Body + appendix**: the LLM produces a chaptered, deduplicated body (overview / takeaways /
  key terms); the raw timestamped transcript and keyframes are kept in a collapsible appendix.
- **HTML reading site**: card-style index and reading layout (light/dark, lazy-loaded keyframes).

## Layout

```
tools/            bili_dl.py · video2md.py · md2html.py (details in tools/README.en.md)
ref/              transcribed documents (.md tracked) and videos (*.mp4 ignored)
html/             generated reading site (temporary, rebuild anytime)
requirements.txt  dependencies
```

## Notes

- Bilibili download uses the **API channel** (video pages often return 412 for server IPs,
  which breaks yt-dlp); anonymous quality caps at 480p — fine for content analysis.
- ⚠️ Copyright: downloaded content is for personal study and content analysis only; do not
  redistribute. Video files are excluded by `.gitignore`.
- 📄 Transcribed documents under `ref/` derive from their source videos (linked inside each
  document) and are provided **for personal study only**; they will be removed upon request
  from the original authors.
