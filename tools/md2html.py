#!/usr/bin/env python3
"""
Markdown -> HTML 批量转换 + 生成 index.html（本地浏览器阅读用）。

设计语言继承自本仓库视频工程的「QUANT WORKFLOW 信息卡」体系：
终端绿 #39E6A8 结构件 + 金黄 #FFC83D 强调 + 等宽眉标/时间戳 + 进度线签名。
浅色纸面优先，暗色随系统（prefers-color-scheme）。

- 每次运行先清理输出目录中的过期 .html（防止改名后残留旧页面）。
- 图片相对路径自动改写并加 loading=lazy（关键帧多时明显提速）。
- index.html 按目录分组，卡片式索引。

依赖：pip install markdown
用法：
  python tools/md2html.py                 # 全仓库 md -> html/
  python tools/md2html.py ref/x.md        # 只转指定文件（不清理其它）
  python tools/md2html.py -o /tmp/out
"""
import argparse, os, re, html as H, datetime

SKIP_DIRS = {".git", "node_modules", "out", ".remotion", "html"}

EYEBROWS = {
    "ref": "REF · 视频文档 VIDEO DOCS",
    "tools": "TOOLS · 工具说明",
    ".": "DOCS · 项目文档 PROJECT",
}

CSS = """
:root{
  --bg:#F6F9F7; --surface:#FFFFFF; --ink:#1C2622; --dim:#5F6F67;
  --accent:#0E9A68; --accent-soft:rgba(14,154,104,.14); --gold:#8A6400;
  --gold-soft:rgba(255,200,61,.22); --line:#DCE5E0; --code-bg:#EEF3F0;
  --card-shadow:0 1px 2px rgba(28,38,34,.05),0 8px 24px rgba(28,38,34,.06);
}
@media(prefers-color-scheme:dark){:root{
  --bg:#0C120F; --surface:#121A16; --ink:#E6EFEA; --dim:#8FA39A;
  --accent:#39E6A8; --accent-soft:rgba(57,230,168,.13); --gold:#FFC83D;
  --gold-soft:rgba(255,200,61,.14); --line:#233029; --code-bg:#18221D;
  --card-shadow:0 1px 2px rgba(0,0,0,.4),0 8px 28px rgba(0,0,0,.35);
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:18px/1.9 "Noto Serif SC","Source Han Serif SC","Songti SC",Georgia,serif;
  -webkit-font-smoothing:antialiased}
main{max-width:1140px;margin:0 auto;padding:44px 40px 96px}
@media(max-width:720px){main{padding:24px 18px 64px}body{font-size:16.5px}}

/* —— 字体分工：标题黑体 / 元信息等宽 —— */
h1,h2,h3,h4,.sans{font-family:"Noto Sans SC","Source Han Sans SC","PingFang SC",
  -apple-system,"Segoe UI",sans-serif}
.mono,code,pre,.meta,.eyebrow,.pill{font-family:"JetBrains Mono",Menlo,Consolas,
  "Noto Sans Mono CJK SC",monospace}

/* —— 眉标 + 返回 —— */
.topbar{display:flex;align-items:center;gap:14px;margin-bottom:26px;flex-wrap:wrap}
.eyebrow{display:inline-flex;align-items:center;gap:8px;color:var(--dim);
  font-size:12.5px;letter-spacing:2.5px}
.eyebrow::before{content:"";width:8px;height:8px;border-radius:8px;
  background:var(--accent);box-shadow:0 0 8px var(--accent)}
.back{margin-left:auto;font-size:13px;color:var(--accent);text-decoration:none;
  border:1px solid var(--line);border-radius:999px;padding:5px 14px;
  transition:border-color .15s,background .15s}
.back:hover{border-color:var(--accent);background:var(--accent-soft)}

/* —— 标题：签名进度线 —— */
h1{font-size:clamp(27px,3.1vw,38px);font-weight:800;line-height:1.32;
  letter-spacing:.5px;margin:.2em 0 .55em;position:relative;padding-bottom:20px}
h1::after{content:"";position:absolute;left:0;bottom:0;width:100%;height:3px;
  border-radius:3px;background:linear-gradient(90deg,var(--accent) 0%,
  var(--accent) 34%,var(--gold) 35%,var(--gold) 37%,var(--line) 38%)}
h2{font-size:23px;font-weight:800;margin:2.2em 0 .8em;padding-left:16px;
  position:relative;letter-spacing:.5px}
h2::before{content:"";position:absolute;left:0;top:.18em;bottom:.18em;width:5px;
  border-radius:5px;background:linear-gradient(var(--accent),var(--accent-soft))}
h3{font-size:18.5px;font-weight:700;margin:1.7em 0 .5em;color:var(--ink)}
h4{font-size:16.5px;margin:1.4em 0 .4em}

a{color:var(--accent);text-decoration:none;border-bottom:1px solid transparent;
  transition:border-color .15s}
a:hover{border-bottom-color:var(--accent)}
a:focus-visible,.back:focus-visible,summary:focus-visible{outline:2px solid var(--accent);
  outline-offset:3px;border-radius:4px}
strong{color:var(--ink);background:linear-gradient(transparent 62%,var(--gold-soft) 62%);
  padding:0 1px}
p{margin:.9em 0}
ul,ol{padding-left:1.6em}li{margin:.32em 0}
hr{border:none;border-top:1px solid var(--line);margin:2.4em 0}

/* —— 文档头部 meta（首个引用块）—— */
blockquote{margin:1.1em 0;padding:.35em 1.1em;border-left:4px solid var(--line);
  color:var(--dim);background:var(--surface);border-radius:0 10px 10px 0}
h1+blockquote{border-left-color:var(--accent);font-size:14px;
  font-family:"JetBrains Mono",Menlo,monospace;letter-spacing:.3px}

/* —— 代码 / 时间戳 —— */
code{background:var(--code-bg);color:var(--accent);padding:.14em .45em;
  border-radius:6px;font-size:.82em}
pre{background:var(--code-bg);border:1px solid var(--line);padding:16px 18px;
  border-radius:12px;overflow-x:auto;line-height:1.65}
pre code{padding:0;background:none;color:var(--ink);font-size:.85em}

/* —— 表格 —— */
table{border-collapse:collapse;display:block;overflow-x:auto;margin:1.2em 0;
  font-size:.92em;font-family:"Noto Sans SC","PingFang SC",sans-serif}
th,td{border:1px solid var(--line);padding:8px 14px;text-align:left}
th{background:var(--accent-soft);font-weight:700;letter-spacing:.5px;white-space:nowrap}
tbody tr:nth-child(even){background:var(--surface)}

/* —— 关键帧图 —— */
img{max-width:100%;border:1px solid var(--line);border-radius:12px;
  box-shadow:var(--card-shadow);margin:.4em 0}

/* —— 附录折叠面板（终端面板风）—— */
details{border:1px solid var(--line);border-radius:14px;background:var(--surface);
  padding:0;margin:1.2em 0;overflow:hidden}
details>*:not(summary){margin-left:20px;margin-right:20px}
details>p:last-child,details>img:last-child{margin-bottom:18px}
summary{cursor:pointer;font-weight:700;padding:14px 20px;letter-spacing:1px;
  font-family:"Noto Sans SC",sans-serif;font-size:15px;color:var(--dim);
  display:flex;align-items:center;gap:10px;user-select:none;
  transition:color .15s,background .15s}
summary::before{content:"";width:7px;height:7px;border-radius:7px;
  background:var(--accent);flex:none}
summary:hover{color:var(--ink);background:var(--accent-soft)}
details[open]>summary{border-bottom:1px solid var(--line);color:var(--ink)}

/* —— 索引页 —— */
.idx-head{margin-bottom:8px}
.en-sub{font-size:.48em;font-weight:600;color:var(--dim);letter-spacing:2px;
  font-family:"JetBrains Mono",Menlo,monospace;vertical-align:middle;margin-left:10px}
.idx-meta{color:var(--dim);font-size:13px;margin:0 0 34px}
.group{margin:34px 0 10px;display:flex;align-items:baseline;gap:12px}
.group .g-name{font-weight:800;font-size:15px;letter-spacing:2px;
  font-family:"JetBrains Mono",Menlo,monospace;color:var(--dim)}
.group::after{content:"";flex:1;height:1px;background:var(--line)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.card{position:relative;display:block;background:var(--surface);
  border:1px solid var(--line);border-radius:14px;padding:18px 20px 15px;
  text-decoration:none;color:var(--ink);box-shadow:var(--card-shadow);
  transition:transform .16s,border-color .16s;border-bottom:none}
.card:hover{transform:translateY(-2px);border-color:var(--accent)}
.card .no{position:absolute;top:16px;right:18px;font-size:11.5px;color:var(--accent);
  font-family:"JetBrains Mono",Menlo,monospace;letter-spacing:1px;opacity:.85}
.card h3{margin:0 42px .5em 0;font-size:16.5px;line-height:1.5;font-weight:700}
.card .meta{color:var(--dim);font-size:12px;letter-spacing:.3px;margin:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(prefers-reduced-motion:no-preference){
  .card{animation:rise .4s cubic-bezier(.2,.7,.3,1) backwards}
  .cards .card:nth-child(2){animation-delay:.04s}.cards .card:nth-child(3){animation-delay:.08s}
  .cards .card:nth-child(4){animation-delay:.12s}.cards .card:nth-child(5){animation-delay:.16s}
  @keyframes rise{from{opacity:0;transform:translateY(10px)}}
}
footer{margin-top:64px;color:var(--dim);font-size:12px;letter-spacing:1px;
  font-family:"JetBrains Mono",Menlo,monospace;display:flex;gap:10px;align-items:center}
footer::before{content:"";width:26px;height:2px;background:var(--accent);border-radius:2px}
"""

def page(title, body, eyebrow, back=None, lang="zh"):
    back_html = f'<a class="back" href="{back}">← 返回索引 · Index</a>' if back else ""
    return (f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{H.escape(title)}</title><style>{CSS}</style></head><body><main>'
            f'<div class="topbar"><span class="eyebrow">{H.escape(eyebrow)}</span>{back_html}</div>'
            f'{body}'
            f'<footer>md2html · {datetime.date.today().isoformat()}</footer>'
            f'</main></body></html>')

def find_mds(root):
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.endswith("_v2md")]
        for f in fns:
            if f.endswith(".md"):
                out.append(os.path.join(dp, f))
    return sorted(out)

def fix_images(md_text, md_dir, root, out_dir, bundle=False):
    """相对图片路径处理：
    默认 -> 改写为从 out_dir 指向真实文件的相对路径（本地浏览）。
    bundle=True -> 把图片复制进 out_dir/assets/<原目录名>/，用站内相对路径（用于发布，如 GitHub Pages）。
    """
    def repl(m):
        alt, path = m.group(1), m.group(2)
        if re.match(r"^(https?:)?//", path) or path.startswith("data:"):
            return m.group(0)
        for base in (md_dir, root):
            cand = os.path.normpath(os.path.join(base, path))
            if os.path.exists(cand):
                if bundle:
                    import shutil
                    sub = os.path.basename(os.path.dirname(cand)) or "img"
                    parent = os.path.basename(os.path.dirname(os.path.dirname(cand)))
                    adir = os.path.join(out_dir, "assets", parent, sub)
                    os.makedirs(adir, exist_ok=True)
                    dst = os.path.join(adir, os.path.basename(cand))
                    if not os.path.exists(dst):
                        shutil.copy2(cand, dst)
                    return f"![{alt}]({os.path.relpath(dst, out_dir)})"
                return f"![{alt}]({os.path.relpath(cand, out_dir)})"
        return m.group(0)
    return re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", repl, md_text)

def detect_lang(text):
    """按 CJK 字符占比判断文档语言（供 <html lang> 与屏幕阅读器使用）。"""
    cjk = len(re.findall(r"[一-龥]", text))
    letters = len(re.findall(r"[A-Za-z]", text))
    return "zh" if cjk * 3 >= letters else "en"

def first_title(md_text, fallback):
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    return m.group(1).strip() if m else fallback

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="指定 md 文件（缺省=全仓库扫描）")
    ap.add_argument("-o", "--out", default="html", help="输出目录（默认 html/）")
    ap.add_argument("--bundle-assets", action="store_true",
                    help="把引用图片复制进输出目录 assets/（用于发布到 GitHub Pages 等）")
    args = ap.parse_args()

    import markdown
    root = os.getcwd()
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    full_scan = not args.files
    mds = [os.path.abspath(f) for f in args.files] if args.files else find_mds(root)

    # 全量模式：先清过期 .html，防止改名后残留旧页面
    if full_scan:
        for f in os.listdir(out_dir):
            if f.endswith(".html"):
                os.remove(os.path.join(out_dir, f))

    entries = []
    for md_path in mds:
        rel = os.path.relpath(md_path, root)
        text = open(md_path, encoding="utf-8").read()
        title = first_title(text, os.path.basename(md_path))
        text = fix_images(text, os.path.dirname(md_path), root, out_dir, bundle=args.bundle_assets)
        text = re.sub(r"<(details|div)(\s*)>", r'<\1 markdown="1">', text)
        body = markdown.markdown(
            text, extensions=["tables", "fenced_code", "toc", "sane_lists", "md_in_html"])
        body = body.replace("<img ", '<img loading="lazy" ')
        group = os.path.dirname(rel) or "."
        eyebrow = EYEBROWS.get(group, group.upper())
        out_name = rel.replace(os.sep, "__").rsplit(".md", 1)[0] + ".html"
        open(os.path.join(out_dir, out_name), "w", encoding="utf-8").write(
            page(title, body, eyebrow, back="index.html", lang=detect_lang(text)))
        st = os.stat(md_path)
        entries.append((rel, out_name, title,
                        datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        f"{st.st_size/1024:.0f} KB"))
        print(f"  ✓ {rel} -> {out_name}")

    # index.html：按目录分组的卡片索引
    groups = {}
    for e in entries:
        groups.setdefault(os.path.dirname(e[0]) or ".", []).append(e)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    body = ['<div class="idx-head"><h1>文档索引 <span class="en-sub">Document Index</span></h1></div>',
            f'<p class="idx-meta mono">{len(entries)} docs · generated {now}</p>']
    for g in sorted(groups):
        body.append(f'<div class="group"><span class="g-name">{H.escape(g.upper() if g != "." else "ROOT")}/</span></div>')
        body.append('<div class="cards">')
        for i, (rel, out_name, title, mtime, size) in enumerate(groups[g], 1):
            body.append(
                f'<a class="card" href="{out_name}"><span class="no">{i:02d}</span>'
                f'<h3>{H.escape(title)}</h3>'
                f'<p class="meta">{H.escape(rel)} · {mtime} · {size}</p></a>')
        body.append('</div>')
    open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(
        page("文档索引 · Document Index", "\n".join(body), "VIDEO2MD · 文档索引 INDEX"))
    print(f"\n✅ {len(entries)} 篇已转换 -> {out_dir}/index.html")

if __name__ == "__main__":
    main()
