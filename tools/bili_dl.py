#!/usr/bin/env python3
"""
B 站视频下载（API 通道版）。

背景：本机数据中心 IP 访问 B 站【视频页】会被 412 风控拦截（yt-dlp 也因此失败），
但【API 通道】是通的。本脚本固化这条路：
  首页拿匿名 cookies(buvid3) -> view API 拿标题/cid -> playurl API 拿 DASH 流
  -> 分别下载视频/音频流 -> ffmpeg 合并 mp4

依赖：pip install requests imageio-ffmpeg
用法：
  python tools/bili_dl.py BV1GPTH6vErg                    # 下到 ./ref/<BV号>.mp4
  python tools/bili_dl.py https://www.bilibili.com/video/BV1GPTH6vErg -d ref
  python tools/bili_dl.py BVxxxx --cookies my_bili.txt    # 登录 cookies 可解锁 >480p
注意：
  - 未登录清晰度上限 480p；1080p 需提供登录 cookies(Netscape 格式)。
  - 仅下载单 P 视频的 P1；多 P 可用 --page 指定。
  - 请尊重版权：仅用于个人学习/内容分析，勿传播。大文件建议加入 .gitignore。
"""
import argparse, json, os, re, subprocess, sys

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def parse_bvid(s):
    m = re.search(r"(BV[0-9A-Za-z]{10})", s)
    if not m:
        sys.exit(f"无法从 '{s}' 解析 BV 号")
    return m.group(1)

def new_session(cookies_file=None):
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    if cookies_file:
        from http.cookiejar import MozillaCookieJar
        jar = MozillaCookieJar(cookies_file); jar.load(ignore_discard=True, ignore_expires=True)
        s.cookies = jar
        print(f"  已加载登录 cookies: {cookies_file}")
    else:
        s.get("https://www.bilibili.com/", timeout=30)   # 拿匿名 buvid3
    return s

def api(s, url, **params):
    r = s.get(url, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        sys.exit(f"API 错误 code={d.get('code')} msg={d.get('message')} ({url})")
    return d["data"]

def pick_streams(dash, prefer_codec="avc1"):
    vids = [v for v in dash["video"] if v["codecs"].startswith(prefer_codec)] or dash["video"]
    v = max(vids, key=lambda x: (x["width"] * x["height"], x["bandwidth"]))
    a = max(dash["audio"], key=lambda x: x["bandwidth"])
    return v, a

def download(s, url, path, label):
    print(f"  下载{label}…", end="", flush=True)
    with s.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    print(f" {os.path.getsize(path)/1e6:.1f} MB")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="BV 号或 B 站视频链接")
    ap.add_argument("-d", "--dir", default="ref", help="输出目录（默认 ref/）")
    ap.add_argument("-o", "--out", default=None, help="输出文件名（默认 <BV号>.mp4）")
    ap.add_argument("--page", type=int, default=1, help="多 P 视频的分 P 序号（从 1 起）")
    ap.add_argument("--cookies", default=None, help="登录 cookies.txt（解锁高清晰度）")
    ap.add_argument("--qn", type=int, default=64, help="期望清晰度 qn（64=720p 80=1080p）")
    args = ap.parse_args()

    bvid = parse_bvid(args.video)
    os.makedirs(args.dir, exist_ok=True)
    out = os.path.join(args.dir, args.out or f"{bvid}.mp4")

    print(f"[1/4] 会话与元数据 ({bvid})")
    s = new_session(args.cookies)
    info = api(s, "https://api.bilibili.com/x/web-interface/view", bvid=bvid)
    pages = info["pages"]
    if not 1 <= args.page <= len(pages):
        sys.exit(f"分 P 超范围：共 {len(pages)} P")
    cid = pages[args.page - 1]["cid"]
    print(f"  标题: {info['title']}")
    print(f"  UP主: {info['owner']['name']} | 时长: {pages[args.page-1]['duration']}s | cid: {cid}")
    # 写 sidecar 标题文件，供 video2md 自动用作文档标题与文件名后缀
    title_file = os.path.splitext(out)[0] + ".title.txt"
    open(title_file, "w", encoding="utf-8").write(info["title"] + "\n")

    print("[2/4] 取播放地址 (DASH)")
    play = api(s, "https://api.bilibili.com/x/player/playurl",
               bvid=bvid, cid=cid, qn=args.qn, fnval=16)
    if "dash" not in play or not play["dash"]:
        sys.exit("未返回 DASH 流（可能需要登录/大会员）")
    v, a = pick_streams(play["dash"])
    print(f"  视频: {v['width']}x{v['height']} {v['codecs'][:12]} | 音频 bw: {a['bandwidth']}")

    print("[3/4] 下载流")
    tmp_v, tmp_a = out + ".v.m4s", out + ".a.m4s"
    download(s, v["baseUrl"], tmp_v, "视频流")
    download(s, a["baseUrl"], tmp_a, "音频流")

    print("[4/4] ffmpeg 合并")
    subprocess.run([ffmpeg_exe(), "-y", "-i", tmp_v, "-i", tmp_a, "-c", "copy", out],
                   check=True, stderr=subprocess.DEVNULL)
    os.remove(tmp_v); os.remove(tmp_a)
    print(f"\n✅ 完成: {out} ({os.path.getsize(out)/1e6:.1f} MB)")
    print("   提示: 第三方版权内容请勿入库/传播；可配合 tools/video2md.py 转文档。")

if __name__ == "__main__":
    main()
