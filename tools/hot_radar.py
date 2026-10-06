#!/usr/bin/env python3
"""
hot_radar.py — 选题雷达：抖音热榜（发现热点）× B 站（可下载的内容源）

分工来自实测的平台能力边界：
  抖音：热榜列表可取，但【搜索/下钻/下载全被签名墙挡住】→ 只当"大众在关注什么"的雷达
  B 站：搜索/排行/热门/下载都可用 → 当内容源，热词拿到这里换成可转写的视频

典型用法：
  python3 tools/hot_radar.py                      # 抖音热榜 + B站爆款，按选题关键词筛
  python3 tools/hot_radar.py --all                # 不筛，全看
  python3 tools/hot_radar.py --topic "黄金|美联储|芯片"
  python3 tools/hot_radar.py --cross              # 抖音热词 → 自动去B站搜可转写视频
  python3 tools/hot_radar.py --search "华为 芯片"  # 直接按词搜B站候选
  python3 tools/hot_radar.py --ups                # 看关注 UP 主的最新投稿（内置名单）
  python3 tools/hot_radar.py --ups "极客湾Geekerwan,小Lin说" --days 7 --all
  python3 tools/hot_radar.py --cross -o radar.md  # 同时输出 Markdown 报告

命中的 BV 号可直接喂给流水线：
  python3 tools/bili_dl.py <BV号> && python3 tools/video2md.py ref/<BV号>.mp4 --auto-crop
"""
import argparse, datetime, html, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# 本仓库的选题方向（AI / 科技 / 财经）；--topic 可覆盖，--all 可关闭
DEFAULT_TOPIC = (r"AI|人工智能|智能|芯片|算力|模型|大模型|机器人|半导体|英伟达|GPU|显卡|"
                 r"黄金|美联储|经济|股市|A股|港股|美股|市场|货币|汇率|财报|投资|基金|量化|"
                 r"关税|楼市|房价|债|通胀|特斯拉|华为|苹果|自动驾驶|新能源|锂电|存储|光模块")

LABELS = {1: "新", 2: "荐", 3: "热", 8: "爆"}

# 关注的 UP 主（本库转写过的垂类头部）。--ups 缺省用这组，也可逗号分隔自定义。
DEFAULT_UPS = ["开卷有财", "野生量化员", "B站金融大学", "科技狐", "极客湾Geekerwan", "小Lin说"]


# ---------------- 通用 ----------------
def clean(s):
    return re.sub(r"<[^>]+>", "", html.unescape(s or ""))


def fmt_ts(ts, fmt="%m-%d"):
    return datetime.datetime.fromtimestamp(ts).strftime(fmt) if ts else "--"


def fmt_dur(sec):
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return str(sec or "?")
    return f"{sec // 60}:{sec % 60:02d}"


# ---------------- 抖音：只取热榜 ----------------
def douyin_hot(limit=50):
    """抖音热搜榜。实测：仅此接口免签名可用；搜索(2483)/下钻(404,403)/下载全被挡。"""
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://www.douyin.com/"})
    try:
        s.get("https://www.douyin.com/", timeout=20)          # 取匿名 cookie
        d = s.get("https://www.douyin.com/aweme/v1/web/hot/search/list/",
                  params={"device_platform": "webapp", "aid": "6383"}, timeout=20).json()
    except Exception as e:
        print(f"  ⚠ 抖音热榜不可用：{type(e).__name__}")
        return []
    if d.get("status_code") != 0:
        print(f"  ⚠ 抖音热榜 status_code={d.get('status_code')}")
        return []
    out = []
    for w in ((d.get("data") or {}).get("word_list") or [])[:limit]:
        out.append({
            "word": w.get("word", ""),
            "hot": w.get("hot_value", 0),
            "label": LABELS.get(w.get("label"), " "),
            "rank": w.get("position", 0),
            "videos": w.get("video_count", 0),
        })
    return out


# ---------------- B 站：排行/热门/搜索 ----------------
def _bili_session():
    import bili_dl as b
    s = b.new_session()
    time.sleep(1.5)
    return s


def bili_hot(sess, pages=2):
    """全站排行榜 + 综合热门。实测：rid=0 可用；分区排行(-352)与 pubdate 排序被风控。"""
    seen, out = set(), []

    def take(url, params, src):
        try:
            d = sess.get(url, params=params, timeout=30).json()
        except Exception as e:
            print(f"  ⚠ B站{src}不可用：{type(e).__name__}")
            return
        if d.get("code") != 0:
            print(f"  ⚠ B站{src} code={d.get('code')}")
            return
        data = d.get("data")
        lst = data["list"] if isinstance(data, dict) else data
        for it in lst or []:
            bv = it.get("bvid")
            if not bv or bv in seen:
                continue
            seen.add(bv)
            st = it.get("stat", {})
            out.append({
                "bv": bv, "title": clean(it.get("title")),
                "up": (it.get("owner") or {}).get("name", "?"),
                "play": st.get("view", 0), "like": st.get("like", 0),
                "dur": it.get("duration", 0), "pub": it.get("pubdate", 0), "src": src,
            })

    take("https://api.bilibili.com/x/web-interface/ranking/v2", {"rid": 0, "type": "all"}, "排行榜")
    time.sleep(3)
    for pn in range(1, pages + 1):
        take("https://api.bilibili.com/x/web-interface/popular", {"ps": 50, "pn": pn}, "热门")
        time.sleep(3)
    return out


def bili_search(sess, keyword, limit=5):
    """按词搜 B 站。实测：order=click 稳定（按历史播放排序），默认/pubdate 排序易被限流。"""
    try:
        d = sess.get("https://api.bilibili.com/x/web-interface/search/type",
                     params={"search_type": "video", "keyword": keyword,
                             "order": "click", "page": 1}, timeout=30).json()
    except Exception:
        return []
    if d.get("code") != 0:
        return []
    out = []
    for it in ((d.get("data") or {}).get("result") or [])[:limit]:
        out.append({
            "bv": it.get("bvid"), "title": clean(it.get("title")),
            "up": it.get("author", "?"), "play": it.get("play", 0),
            "dur": it.get("duration", "?"), "pub": it.get("pubdate", 0),
        })
    return out


def bili_up_latest(sess, up_name, limit=5, days=None):
    """某 UP 主的最新投稿。

    注意：B 站 space/ 系接口（含 wbi 签名版）对本机 IP 整体返回 412 边缘拦截，不可用。
    这里改走唯一稳定的搜索接口：按 UP 名搜 + order=pubdate（时间倒序）+ 作者精确过滤。
    代价是只能拿到搜索可见的投稿，但对「看关注的人更新了什么」足够。
    """
    d = None
    for attempt in range(3):                      # 搜索接口密集调用易被限流，退避重试
        if attempt:
            time.sleep(6 * attempt)
        try:
            d = sess.get("https://api.bilibili.com/x/web-interface/search/type",
                         params={"search_type": "video", "keyword": up_name,
                                 "order": "pubdate", "page": 1}, timeout=30).json()
        except Exception:
            d = None
            continue
        if d.get("code") == 0:
            break
    if not d:
        return None, "限流/无响应（已重试3次）"
    if d.get("code") != 0:
        return None, f"code={d.get('code')}"
    cut = time.time() - days * 86400 if days else 0
    out = []
    for it in (d.get("data") or {}).get("result") or []:
        if it.get("author") != up_name:          # 只要本人投稿，滤掉"提到他"的视频
            continue
        if it.get("pubdate", 0) < cut:
            continue
        out.append({"bv": it.get("bvid"), "title": clean(it.get("title")),
                    "up": up_name, "play": it.get("play", 0),
                    "dur": it.get("duration", "?"), "pub": it.get("pubdate", 0)})
        if len(out) >= limit:
            break
    return out, None


# ---------------- 渲染 ----------------
def render(dy, bili, cross, topic_src, args, feeds=None):
    L = []
    w = L.append
    w(f"# 选题雷达 · {datetime.datetime.now():%Y-%m-%d %H:%M}\n")
    w(f"> 过滤：{topic_src}\n")

    if dy is not None:
        w(f"\n## 抖音热榜（{len(dy)} 条）\n")
        w("> 抖音仅开放热榜列表；搜索/下钻/下载均被签名墙拦截，故只作选题雷达。\n")
        if dy:
            w("| # | 热词 | 热度 | 标签 |")
            w("|---|---|---|---|")
            for it in dy:
                w(f"| {it['rank']} | {it['word']} | {it['hot']:,} | {it['label']} |")
        else:
            w("（无命中）")

    if bili is not None:
        w(f"\n## B 站爆款（{len(bili)} 条）\n")
        if bili:
            for it in bili:
                w(f"\n**{it['title']}**  ")
                w(f"`{it['bv']}` · {it['up']} · {fmt_ts(it['pub'])} · {fmt_dur(it['dur'])} · "
                  f"播放 {it['play']:,} · 点赞 {it['like']:,} · [{it['src']}]")
        else:
            w("（无命中）")

    if cross:
        w("\n## 跨平台：抖音热词 → B 站可转写候选\n")
        for word, vids in cross:
            w(f"\n### {word}")
            if not vids:
                w("（B 站无相关结果）")
                continue
            for v in vids:
                w(f"- `{v['bv']}` {v['title']}  ")
                w(f"  {v['up']} · {fmt_ts(v['pub'])} · {v['dur']} · 播放 {v['play']:,}")

    if feeds:
        w(f"\n## UP 主最新投稿（{sum(len(v) for _, v in feeds)} 条 / {len(feeds)} 位）\n")
        for name, vids in feeds:
            w(f"\n### {name}")
            if not vids:
                w("（无新投稿或未命中过滤）")
                continue
            for v in vids:
                w(f"- `{v['bv']}` {v['title']}  ")
                w(f"  {fmt_ts(v['pub'])} · {v['dur']} · 播放 {v['play']:,}")

    w("\n---\n")
    w("转写任一候选：\n")
    w("```bash\npython3 tools/bili_dl.py <BV号>\n"
      "python3 tools/video2md.py ref/<BV号>.mp4 --auto-crop\n```")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="选题雷达：抖音热榜 × B 站内容源")
    ap.add_argument("--topic", default=None, help="过滤正则（默认：本仓库 AI/科技/财经 选题）")
    ap.add_argument("--all", action="store_true", help="不过滤，全部列出")
    ap.add_argument("--douyin-only", action="store_true", help="只看抖音热榜")
    ap.add_argument("--bili-only", action="store_true", help="只看 B 站爆款")
    ap.add_argument("--cross", action="store_true", help="抖音命中热词 → 去 B 站搜可转写视频")
    ap.add_argument("--search", default=None, help="直接按词搜 B 站候选（不拉热榜）")
    ap.add_argument("--ups", nargs="?", const="", default=None,
                    help="看关注 UP 主的最新投稿；缺省用内置名单，或逗号分隔自定义")
    ap.add_argument("--days", type=int, default=None, help="--ups 只看最近 N 天")
    ap.add_argument("-n", "--limit", type=int, default=12, help="各榜最多展示条数")
    ap.add_argument("--cross-top", type=int, default=5, help="最多为几个热词做跨平台搜索")
    ap.add_argument("-o", "--out", default=None, help="同时输出 Markdown 报告路径")
    args = ap.parse_args()

    pat = None if args.all else re.compile(args.topic or DEFAULT_TOPIC, re.I)
    topic_src = "（无，全部列出）" if args.all else (args.topic or "仓库默认选题（AI/科技/财经）")

    # UP 主订阅模式
    if args.ups is not None:
        ups = [u.strip() for u in args.ups.split(",") if u.strip()] or DEFAULT_UPS
        rng = f"最近 {args.days} 天" if args.days else "最新"
        print(f"[UP订阅] {len(ups)} 位 · {rng}\n")
        sess = _bili_session()
        feeds = []
        for name in ups:
            vids, err = bili_up_latest(sess, name, limit=args.limit, days=args.days)
            if err:
                print(f"  ⚠ {name}: {err}")
                feeds.append((name, []))
            else:
                hit = [v for v in vids if not pat or pat.search(v["title"])]
                feeds.append((name, hit))
                print(f"▸ {name}  （{len(hit)} 条）")
                for v in hit:
                    print(f"    {v['bv']} | {fmt_ts(v['pub'])} | {v['dur']:>6} | "
                          f"播放 {v['play']:>9,} | {v['title'][:40]}")
                if not hit:
                    print("    （无）")
            time.sleep(4)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(
                render(None, None, None, topic_src, args, feeds=feeds))
            print(f"\n报告 -> {args.out}")
        return

    # 直接搜索模式
    if args.search:
        print(f"B 站搜索：{args.search}\n")
        sess = _bili_session()
        vids = bili_search(sess, args.search, limit=args.limit)
        for v in vids:
            print(f"  {v['bv']} | {v['title'][:50]}")
            print(f"    {v['up']} · {fmt_ts(v['pub'])} · {v['dur']} · 播放 {v['play']:,}")
        if args.out:
            open(args.out, "w", encoding="utf-8").write(
                render(None, None, [(args.search, vids)], topic_src, args))
            print(f"\n报告 -> {args.out}")
        return

    want_dy = not args.bili_only
    want_bl = not args.douyin_only
    dy = bl = None
    cross = []

    if want_dy:
        print("[抖音] 拉热搜榜…")
        words = douyin_hot()
        dy = [w for w in words if not pat or pat.search(w["word"])][:args.limit]
        print(f"  共 {len(words)} 条，命中 {len(dy)} 条")
        for it in dy:
            print(f"  {it['rank']:>2}. [{it['label']}] {it['word']}  热度 {it['hot']:,}")

    if want_bl:
        print("\n[B站] 拉排行榜 + 热门…")
        sess = _bili_session()
        items = bili_hot(sess)
        bl = sorted([v for v in items if not pat or pat.search(v["title"])],
                    key=lambda v: -v["play"])[:args.limit]
        print(f"  共 {len(items)} 条，命中 {len(bl)} 条")
        for v in bl:
            print(f"  {v['play']:>9,} | {fmt_ts(v['pub'])} | {fmt_dur(v['dur']):>6} | "
                  f"{v['bv']} | {v['title'][:40]}")
            print(f"{'':>11}UP: {v['up']}  [{v['src']}]")

    if args.cross and dy:
        print(f"\n[跨平台] 抖音热词 → B 站搜索（最多 {args.cross_top} 个词）…")
        sess = locals().get("sess") or _bili_session()
        for it in dy[:args.cross_top]:
            vids = bili_search(sess, it["word"], limit=3)
            cross.append((it["word"], vids))
            print(f"\n  ▸ {it['word']}  → {len(vids)} 条")
            for v in vids:
                print(f"      {v['bv']} | {v['title'][:44]}")
                print(f"        {v['up']} · {fmt_ts(v['pub'])} · 播放 {v['play']:,}")
            time.sleep(3)

    if args.out:
        open(args.out, "w", encoding="utf-8").write(render(dy, bl, cross, topic_src, args))
        print(f"\n报告 -> {args.out}")


if __name__ == "__main__":
    main()
