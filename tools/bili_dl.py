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
  - 下载支持断点续传：中断后保留 .m4s 分片，重跑即接着下；--fresh 可强制重下。
  - 请尊重版权：仅用于个人学习/内容分析，勿传播。大文件建议加入 .gitignore。
"""
import argparse, json, os, re, subprocess, sys, time

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

def _progress(label, done, total):
    if total:
        pct = done * 100 // total
        print(f"\r  下载{label}… {done/1e6:6.1f}/{total/1e6:.1f} MB ({pct:3d}%)",
              end="", flush=True)
    else:
        print(f"\r  下载{label}… {done/1e6:6.1f} MB", end="", flush=True)


CHUNK = 64 * 1024   # 64KB：B站 CDN 常在几百 KB 处断流，chunk 过大会导致整段进度丢失


def download(s, urls, path, label, retries=8, fresh=False):
    """带断点续传 + CDN 轮换的下载。

    B 站 CDN 流偶发中途断开(ChunkedEncodingError)，且常固定在某个偏移处断。对策：
      1) HTTP Range 从已落盘字节续传，失败按指数退避重试；
      2) chunk 取 64KB —— 若用 1MB，断点早于 1MB 时 iter_content 尚未吐出数据，
         落盘为 0、每次从头再来，续传等于失效（实测踩过）；
      3) 连续失败则轮换到 backupUrl 镜像站；
      4) 416(分片越界/不匹配) 与 200(不支持 Range) 自动丢弃分片重下。
    中断时保留 .m4s 分片，重跑脚本可接着下；--fresh 强制重来。
    """
    urls = [u for u in (urls if isinstance(urls, (list, tuple)) else [urls]) if u]
    if fresh and os.path.exists(path):
        os.remove(path)
    done = os.path.getsize(path) if os.path.exists(path) else 0
    if done:
        print(f"  发现分片 {done/1e6:.1f} MB，尝试续传…")
    total, attempt, ui = None, 0, 0

    while True:
        url = urls[ui % len(urls)]
        headers = {"Range": f"bytes={done}-"} if done else {}
        try:
            with s.get(url, headers=headers, stream=True, timeout=(15, 60)) as r:
                if r.status_code == 416:               # 分片越界：比当前流还大/已不匹配
                    print("\n  ⚠ 已有分片与当前流不匹配(416)，丢弃重下")
                    done, total = 0, None
                    open(path, "wb").close()
                    continue
                if done and r.status_code == 200:      # 不支持 Range，只能重来
                    print("\n  ⚠ 服务端不支持续传，从头下载")
                    done = 0
                    open(path, "wb").close()
                elif r.status_code not in (200, 206):
                    r.raise_for_status()

                if total is None:                       # 解析总大小
                    cr = r.headers.get("Content-Range", "")
                    if "/" in cr:
                        total = int(cr.rsplit("/", 1)[1])
                    elif r.headers.get("Content-Length"):
                        total = done + int(r.headers["Content-Length"])
                    if total and done > total:          # 分片比总长还大 = 不是同一路流
                        print("\n  ⚠ 已有分片与当前流不匹配，重新下载")
                        done, total = 0, None
                        open(path, "wb").close()
                        continue

                with open(path, "ab" if done else "wb") as f:
                    for chunk in r.iter_content(CHUNK):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            _progress(label, done, total)

            if total is None or done >= total:
                _progress(label, done, total)
                print()
                return
            raise IOError(f"提前结束 {done}/{total}")

        except Exception as e:
            attempt += 1
            if attempt > retries:
                print()
                raise
            prev, done = done, (os.path.getsize(path) if os.path.exists(path) else 0)
            if done <= prev and len(urls) > 1:      # 本轮毫无进展 -> 换个 CDN 镜像
                ui += 1
            wait = min(2 ** attempt, 30)
            mirror = f"，切镜像 {urls[ui % len(urls)].split('/')[2]}" if len(urls) > 1 and done <= prev else ""
            print(f"\n  ⚠ {label}中断({type(e).__name__})，{wait}s 后从 {done/1e6:.1f} MB 续传"
                  f" [{attempt}/{retries}]{mirror}", flush=True)
            time.sleep(wait)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="BV 号或 B 站视频链接")
    ap.add_argument("-d", "--dir", default="ref", help="输出目录（默认 ref/）")
    ap.add_argument("-o", "--out", default=None, help="输出文件名（默认 <BV号>.mp4）")
    ap.add_argument("--page", type=int, default=1, help="多 P 视频的分 P 序号（从 1 起）")
    ap.add_argument("--cookies", default=None, help="登录 cookies.txt（解锁高清晰度）")
    ap.add_argument("--fresh", action="store_true", help="忽略已有分片，从头下载")
    ap.add_argument("--qn", type=int, default=64, help="期望清晰度 qn（64=720p 80=1080p）")
    args = ap.parse_args()

    bvid = parse_bvid(args.video)
    os.makedirs(args.dir, exist_ok=True)
    out = os.path.join(args.dir, args.out or f"{bvid}.mp4")

    print(f"[1/4] 会话与元数据 ({bvid})")
    s = new_session(args.cookies)
    # view 接口偶发被针对性限流(412)，回退到 pagelist（只给分P/cid，标题用 P1 分P名）
    title = owner = None
    try:
        info = api(s, "https://api.bilibili.com/x/web-interface/view", bvid=bvid)
        pages = info["pages"]
        title, owner = info["title"], info["owner"]["name"]
    except SystemExit:
        raise
    except Exception:
        print("  ⚠ view 接口不可用(限流)，回退 pagelist")
        pages = api(s, "https://api.bilibili.com/x/player/pagelist", bvid=bvid)
        title, owner = pages[0]["part"], "?"
    if not 1 <= args.page <= len(pages):
        sys.exit(f"分 P 超范围：共 {len(pages)} P")
    pg = pages[args.page - 1]
    cid = pg["cid"]
    print(f"  标题: {title}")
    print(f"  UP主: {owner} | 时长: {pg['duration']}s | cid: {cid} | 共 {len(pages)}P")
    # 写 sidecar 标题文件，供 video2md 自动用作文档标题与文件名后缀
    title_file = os.path.splitext(out)[0] + ".title.txt"
    open(title_file, "w", encoding="utf-8").write(title + "\n")

    print("[2/4] 取播放地址 (DASH)")
    play = api(s, "https://api.bilibili.com/x/player/playurl",
               bvid=bvid, cid=cid, qn=args.qn, fnval=16)
    if "dash" not in play or not play["dash"]:
        sys.exit("未返回 DASH 流（可能需要登录/大会员）")
    v, a = pick_streams(play["dash"])
    print(f"  视频: {v['width']}x{v['height']} {v['codecs'][:12]} | 音频 bw: {a['bandwidth']}")

    print("[3/4] 下载流")
    tmp_v, tmp_a = out + ".v.m4s", out + ".a.m4s"
    def _urls(st):
        return [st["baseUrl"]] + list(st.get("backupUrl") or st.get("backup_url") or [])
    download(s, _urls(v), tmp_v, "视频流", fresh=args.fresh)
    download(s, _urls(a), tmp_a, "音频流", fresh=args.fresh)

    print("[4/4] ffmpeg 合并")
    subprocess.run([ffmpeg_exe(), "-y", "-i", tmp_v, "-i", tmp_a, "-c", "copy", out],
                   check=True, stderr=subprocess.DEVNULL)
    os.remove(tmp_v); os.remove(tmp_a)
    print(f"\n✅ 完成: {out} ({os.path.getsize(out)/1e6:.1f} MB)")
    print("   提示: 第三方版权内容请勿入库/传播；可配合 tools/video2md.py 转文档。")

if __name__ == "__main__":
    main()
