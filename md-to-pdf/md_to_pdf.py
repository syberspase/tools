#!/usr/bin/env python3
"""
md_to_pdf.py — Markdown → PDF，支持 mermaid 图表与中文

依赖（首次使用）：
    pip install markdown playwright
    playwright install chromium

用法：
    python3 md_to_pdf.py <file.md> [file2.md ...]
    python3 md_to_pdf.py report.md --out /tmp/report.pdf
    python3 md_to_pdf.py *.md --outdir ./pdfs/
    python3 md_to_pdf.py report.md --theme dark
"""

import argparse
import re
import sys
import time
from pathlib import Path
import html as html_mod

# ── 依赖检查 ──────────────────────────────────────────────────────────────────

try:
    import markdown
except ImportError:
    sys.exit("❌ 缺少依赖：pip install markdown")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("❌ 缺少依赖：pip install playwright && playwright install chromium")


# ── 版面常量 ──────────────────────────────────────────────────────────────────
# Letter @96dpi = 816×1056px。减去 0.75in×2 页边距，再减 body 的 padding 0 20px：
#   可用宽 = 816 - 2*72 - 2*20 = 632px
#   可用高 = 1056 - 2*72 = 912px
# 但高度上限不能贴着 912：图一旦撑满整页，page-break-inside:avoid 就会让它独占一页，
# 把自己的小标题孤零零甩在上一页（整页空白）。780 是实测出来的临界值——
# 用 count_blank_pages.py 扫 tech-design.md：890→4 个空白页，820→1 个，780→0 个。
# 再往下压只会让图更小，不再减少空白页。
PAGE_CONTENT_W = 632
PAGE_CONTENT_H = 780

# 横向页（Letter landscape 1056×816px，页边距 0.5in）：内容区 960×720，减 body padding
# 宽扁的架构图在竖版里会被压到看不清，丢到横向页能多拿 45% 宽度。
# 但高瘦的图千万别翻——横向页高度更小，只会更糟。所以按「哪个方向缩放比大」来选。
LANDSCAPE_W = 920
LANDSCAPE_H = 700
# 翻页是有代价的（强制分页 + 阅读时要转屏），收益不够大就不翻
LANDSCAPE_MIN_GAIN = 1.15

# 允许把小图放大，但别放太狠：mermaid 是矢量图不会糊，可字号会大得不协调
MAX_UPSCALE = 1.4
# 放大后的高度上限，必须明显小于整页：一旦放大到接近 PAGE_CONTENT_H，
# page-break-inside:avoid 就会让这张图独占一页，把它自己的小标题孤零零留在上一页。
# 缩小时不受这条限制——那种图本来就大，独占一页是合理的。
UPSCALE_MAX_H = 620

# mermaid.initialize 里设的 fontSize，用来估算缩放后的等效字号
MERMAID_FONT_PX = 12
# 缩放比低于这个值，等效字号 < 6px，打印出来基本看不清 → 报警
LEGIBLE_SCALE = 0.5


# ── HTML 模板 ─────────────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap');

  *, *::before, *::after {{ box-sizing: border-box; }}

  body {{
    font-family: 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei',
                 'WenQuanYi Micro Hei', 'Hiragino Sans GB', sans-serif;
    font-size: 14px;
    line-height: 1.75;
    color: #1a1a1a;
    margin: 0;
    padding: 0 20px;
    width: 100%;
  }}

  h1 {{ font-size: 2em;   border-bottom: 2px solid #222; padding-bottom: .35em; margin: 1.4em 0 .6em; }}
  h2 {{ font-size: 1.5em; border-bottom: 1px solid #bbb; padding-bottom: .25em; margin: 1.2em 0 .5em; }}
  h3 {{ font-size: 1.2em; margin: 1em 0 .4em; }}
  h4, h5, h6 {{ margin: .8em 0 .3em; }}

  pre {{
    background: #f6f6f6;
    border: 1px solid #ddd;
    border-radius: 5px;
    padding: 12px 16px;
    overflow-x: auto;
    font-size: 0.85em;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  code {{
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    font-size: 0.88em;
    background: #efefef;
    padding: 1px 5px;
    border-radius: 3px;
  }}
  pre code {{ background: none; padding: 0; font-size: inherit; }}

  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.9em; }}
  th, td {{ border: 1px solid #ccc; padding: 7px 12px; vertical-align: top; }}
  th {{ background: #f0f0f0; font-weight: 600; }}
  tr:nth-child(even) td {{ background: #fafafa; }}

  blockquote {{
    border-left: 4px solid #ccc;
    margin: 1em 0;
    padding: .5em 1em;
    color: #555;
    background: #fafafa;
    border-radius: 0 4px 4px 0;
  }}
  blockquote p {{ margin: .3em 0; }}

  ul, ol {{ padding-left: 2em; margin: .5em 0; }}
  li {{ margin: .3em 0; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 1.8em 0; }}
  img {{ max-width: 100%; height: auto; border-radius: 4px; }}

  .mermaid {{
    display: block;
    text-align: center;
    margin: 1.2em auto;
    overflow: visible;
    page-break-inside: avoid;   /* 尽量不跨页 */
    break-inside: avoid;
  }}
  .mermaid svg {{
    display: block;
    margin: 0 auto;
    /* 不在 CSS 里限制尺寸：由 JS 直接写入精确的 width/height attribute */
  }}

  /* 页面尺寸由 CSS 定义（配合 prefer_css_page_size），这样才能混排横竖页 */
  @page {{ size: Letter portrait; margin: 0.75in; }}
  @page wide {{ size: Letter landscape; margin: 0.5in; }}

  /* 由 JS 打标：竖版放不下、横版明显更清楚的图，单独占一张横向页 */
  .mermaid.landscape {{
    page: wide;
    break-before: page;
    break-after: page;
  }}

  @media print {{
    h1, h2, h3 {{ page-break-after: avoid; }}
    pre, table, .mermaid {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>
{body}
<script>
// mermaid 块已由 Python 预处理为 <div class="mermaid">，直接初始化即可
mermaid.initialize({{
  startOnLoad: true,
  theme: {theme!r},
  securityLevel: 'loose',
  fontFamily: 'Noto Sans SC, Microsoft YaHei, sans-serif',
  fontSize: 12,
  // 注意：键名必须用 mermaid 自己的 config key。曾误写 stateDiagram（正确是 state），
  // 导致状态图带着 width="100%" 输出、逃过下面的等比缩放。
  // nodeSpacing/rankSpacing 调紧：默认各 50，对多层级的图会白白撑出几百 px 高度，
  // 而高度撑大 → 等比缩放比变小 → 字反而更看不清。
  // subGraphTitleMargin：不给的话 subgraph 标题会被里面第一排节点压住
  flowchart:  {{ useMaxWidth: false, htmlLabels: true, curve: 'basis',
                 padding: 6, nodeSpacing: 34, rankSpacing: 38,
                 subGraphTitleMargin: {{ top: 6, bottom: 10 }} }},
  // actorMargin 默认 50，participant 一多就横向爆掉
  sequence:   {{ useMaxWidth: false, boxMargin: 6, messageMargin: 28,
                 actorMargin: 26, width: 110 }},
  gantt:      {{ useMaxWidth: false, fontSize: 11 }},
  state:      {{ useMaxWidth: false }},
  class:      {{ useMaxWidth: false }},
  er:         {{ useMaxWidth: false }},
  pie:        {{ useMaxWidth: false }},
  journey:    {{ useMaxWidth: false }},
  mindmap:    {{ useMaxWidth: false }},
  timeline:   {{ useMaxWidth: false }},
  gitGraph:   {{ useMaxWidth: false }},
}});
</script>
</body>
</html>
"""


# ── Mermaid 预处理 ────────────────────────────────────────────────────────────

# 必须在送进 markdown 之前替换：
#   1. fenced_code 会把内容 HTML 转义（--> 变成 --&gt;），mermaid 解析不了
#   2. codehilite 会改掉类名，JavaScript 找不到正确的 code 块
# 替换成原始 <div class="mermaid">，markdown 会当作 raw HTML 原样透传
_MERMAID_RE = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def _extract_mermaid(md_text: str) -> str:
    """把所有 ```mermaid 块替换成 <div class="mermaid">，在 markdown 解析前调用。"""
    def _repl(m: re.Match) -> str:
        diagram = m.group(1).rstrip("\n")
        return f'\n<div class="mermaid">\n{diagram}\n</div>\n'
    return _MERMAID_RE.sub(_repl, md_text)


def md_to_html(md_text: str, title: str, theme: str = "default",
               max_diagram_px: int = PAGE_CONTENT_W) -> str:
    """把 Markdown 文本转成可由 Chrome 打印的 HTML。"""
    # ① 先把 mermaid 块提取成原始 HTML div（避免 markdown 转义箭头等特殊字符）
    md_text = _extract_mermaid(md_text)

    md = markdown.Markdown(
        extensions=[
            "tables",        # | 表格 |
            "fenced_code",   # ``` 代码块（非 mermaid 的继续走这里）
            "toc",           # [TOC]
            "sane_lists",    # 更智能的列表处理
            "attr_list",     # {.class} 语法
        ],
    )
    body = md.convert(md_text)
    return HTML_TEMPLATE.format(
        title=html_mod.escape(title),
        body=body,
        theme=theme,
        max_diagram_px=max_diagram_px,
    )


# ── 转换单个文件 ──────────────────────────────────────────────────────────────

def convert_one(input_path: Path, output_path: Path, theme: str, page,
                max_diagram_px: int = PAGE_CONTENT_W,
                max_diagram_h: int = PAGE_CONTENT_H,
                verbose: bool = False,
                landscape_wide: bool = True) -> None:
    """用已打开的 Playwright page 对象转换一个文件。"""
    input_path = input_path.resolve()   # 必须是绝对路径才能转成 file:// URI
    output_path = output_path.resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"文件不存在：{input_path}")

    print(f"\n📄 {input_path}")
    print(f"   → {output_path}")

    md_text = input_path.read_text(encoding="utf-8")
    title = input_path.stem
    html_content = md_to_html(md_text, title, theme, max_diagram_px)

    # 临时 HTML 写到源文件旁边，保证 file:// 路径无跨盘符问题
    tmp_html = input_path.with_name(f"__tmp_pdf_{title}__.html")
    tmp_html.write_text(html_content, encoding="utf-8")

    try:
        page.goto(tmp_html.as_uri(), wait_until="networkidle", timeout=60_000)

        # 等待 mermaid 渲染完毕（所有 .mermaid 获得 data-processed 属性）
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('.mermaid:not([data-processed])').length === 0",
                timeout=30_000,
            )
        except Exception:
            print("   ⚠️  mermaid 渲染超时，继续输出（部分图表可能未完成）")

        time.sleep(1.5)  # 额外 buffer

        # 等比缩放：同时满足 MAX_W 和 MAX_H，不管图多高都不跨页
        report = page.evaluate(f"""() => {{
            var MAX_W = {max_diagram_px};
            var MAX_H = {max_diagram_h};
            var MAX_UPSCALE = {MAX_UPSCALE};
            var UPSCALE_MAX_H = {UPSCALE_MAX_H};
            var LEGIBLE_SCALE = {LEGIBLE_SCALE};
            var LANDSCAPE = {str(landscape_wide).lower()};
            var LAND_W = {LANDSCAPE_W};
            var LAND_H = {LANDSCAPE_H};
            var LANDSCAPE_MIN_GAIN = {LANDSCAPE_MIN_GAIN};
            var report = [];

            document.querySelectorAll('.mermaid svg').forEach(function(svg, i) {{
                // ① 取真实尺寸。width/height 可能是 "100%" 这类相对值（parseFloat 会得出
                //    垃圾值或 0），所以优先信 viewBox，再退回属性，最后用 getBBox 兜底。
                var natW = 0, natH = 0;

                var vb = svg.getAttribute('viewBox');
                if (vb) {{
                    var p = vb.trim().split(/[\\s,]+/).map(parseFloat);
                    if (p.length === 4 && p[2] > 0 && p[3] > 0) {{ natW = p[2]; natH = p[3]; }}
                }}
                if (natW <= 0 || natH <= 0) {{
                    var wa = svg.getAttribute('width')  || '';
                    var ha = svg.getAttribute('height') || '';
                    if (wa.indexOf('%') === -1) natW = parseFloat(wa) || 0;
                    if (ha.indexOf('%') === -1) natH = parseFloat(ha) || 0;
                }}
                if (natW <= 0 || natH <= 0) {{
                    try {{
                        var bb = svg.getBBox();
                        if (bb.width > 0 && bb.height > 0) {{
                            natW = bb.width; natH = bb.height;
                            svg.setAttribute('viewBox',
                                bb.x + ' ' + bb.y + ' ' + natW + ' ' + natH);
                        }}
                    }} catch (e) {{ /* getBBox 在极少数情况下会抛 */ }}
                }}
                if (natW <= 0 || natH <= 0) {{
                    report.push({{i: i + 1, skipped: true}});
                    return;
                }}

                // ② viewBox 是等比缩放的前提，保留内部坐标系
                if (!svg.getAttribute('viewBox')) {{
                    svg.setAttribute('viewBox', '0 0 ' + natW + ' ' + natH);
                }}
                // mermaid 在 useMaxWidth 生效时会塞 inline max-width，会干扰下面的宽度设定
                svg.style.maxWidth = 'none';

                // ③ 按最严的一边等比缩放
                var fit = Math.min(MAX_W / natW, MAX_H / natH);
                var scale, landscape = false;

                if (fit < 1) {{
                    scale = fit;                      // 放不下 → 必须缩小

                    // 竖版已经压到看不清了，看看翻成横向页是否明显更好。
                    // 只有宽扁图会受益：高瘦图在横版里高度更吃紧，fitL 反而更小。
                    if (LANDSCAPE && scale < LEGIBLE_SCALE) {{
                        var fitL = Math.min(LAND_W / natW, LAND_H / natH);
                        if (fitL > scale * LANDSCAPE_MIN_GAIN) {{
                            scale = fitL;
                            landscape = true;
                            svg.closest('.mermaid').classList.add('landscape');
                        }}
                    }}
                }} else {{
                    // 放得下 → 可以适度放大填满宽度，但要留出和标题、正文同页的余地
                    scale = Math.min(fit, MAX_UPSCALE, UPSCALE_MAX_H / natH);
                    if (scale < 1) scale = 1;         // 别把本来放得下的图缩小
                }}
                svg.setAttribute('width',  String(Math.round(natW * scale)));
                svg.setAttribute('height', String(Math.round(natH * scale)));

                report.push({{
                    i: i + 1, skipped: false, landscape: landscape,
                    natW: Math.round(natW), natH: Math.round(natH), scale: scale,
                }});
            }});
            return report;
        }}""")

        if verbose:
            print(f"   📐 {len(report)} 个图表：")
            for r in report:
                if r["skipped"]:
                    print(f"      · #{r['i']:<2} 尺寸未知，已跳过缩放")
                    continue
                s = r["scale"]
                w, h = round(r["natW"] * s), round(r["natH"] * s)
                mark = "⚠️" if s < LEGIBLE_SCALE else ("↑" if s > 1.01 else " ")
                tag = "  [横向页]" if r.get("landscape") else ""
                print(f"      {mark} #{r['i']:<2} {r['natW']:>5}×{r['natH']:<5}"
                      f" → {w:>4}×{h:<4}  ×{s:.2f}"
                      f"  字≈{MERMAID_FONT_PX * s:.1f}px{tag}")

        # 缩放比过小 = 图太宽，字号会掉到看不清。这是图本身的问题（该换 LR→TB），
        # 脚本没法替它换方向，只能报出来。
        tiny = [r for r in report
                if not r["skipped"] and r["scale"] < LEGIBLE_SCALE]
        if tiny and not verbose:
            print(f"   ⚠️  {len(tiny)} 个图过宽，缩放后字号偏小（建议源文件改 LR→TB 或拆图）：")
            for r in tiny:
                eff = round(MERMAID_FONT_PX * r["scale"], 1)
                print(f"      · 图 #{r['i']}  {r['natW']}×{r['natH']}px"
                      f"  → scale {r['scale']:.2f}，等效字号 ≈ {eff}px")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        # prefer_css_page_size：让上面的 @page 规则生效，横竖页才能混排。
        # 用了它就不能再传 format / margin，否则会覆盖 CSS。
        page.pdf(
            path=str(output_path),
            prefer_css_page_size=True,
            print_background=True,
        )

        kb = output_path.stat().st_size / 1024
        print(f"   ✅ 完成 ({kb:.1f} KB)")

    finally:
        tmp_html.unlink(missing_ok=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="md_to_pdf.py",
        description="Markdown → PDF，支持 mermaid 图表与中文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python3 md_to_pdf.py report.md
  python3 md_to_pdf.py a.md b.md c.md
  python3 md_to_pdf.py report.md --out /tmp/report.pdf
  python3 md_to_pdf.py *.md --outdir ./pdfs/
  python3 md_to_pdf.py report.md --theme dark
        """,
    )
    parser.add_argument("files", nargs="+", metavar="file.md", help=".md 文件路径，支持多个")
    parser.add_argument("--out", metavar="PATH", help="指定输出 PDF 路径（仅单文件有效）")
    parser.add_argument("--outdir", metavar="DIR", help="所有 PDF 输出到此目录（默认与源文件同目录）")
    parser.add_argument(
        "--theme",
        default="default",
        choices=["default", "dark", "forest", "neutral"],
        help="mermaid 主题（默认 default）",
    )
    parser.add_argument(
        "--diagram-width", type=int, default=PAGE_CONTENT_W, metavar="PX",
        help=f"mermaid 图表最大宽度，单位 px（默认 {PAGE_CONTENT_W} = Letter 可用内容宽度）",
    )
    parser.add_argument(
        "--diagram-height", type=int, default=PAGE_CONTENT_H, metavar="PX",
        help=f"mermaid 图表最大高度，单位 px（默认 {PAGE_CONTENT_H}，防止图跨页）",
    )
    parser.add_argument(
        "--no-landscape", action="store_true",
        help="禁用「超宽图自动转横向页」。默认开启：竖版放不下且横版明显更清楚的图会独占一张横页",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="逐图打印原始尺寸、缩放比与等效字号，用于排查图太大/太小",
    )
    args = parser.parse_args()

    if args.out and len(args.files) > 1:
        parser.error("--out 仅支持单个文件输入，多文件请使用 --outdir")

    input_paths = [Path(f) for f in args.files]

    print(f"🎨 Mermaid 主题：{args.theme}  "
          f"📐 图表上限：{args.diagram_width}×{args.diagram_height}px  "
          f"（小图最多放大 {MAX_UPSCALE}×）")
    print(f"📁 文件数：{len(input_paths)}")

    errors = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--font-render-hinting=none",
            ],
        )
        # Letter @ 96dpi = 816×1056px；content area（去 0.75in×2 边距）≈ 672px
        page = browser.new_page(viewport={"width": 816, "height": 1056})

        for md_path in input_paths:
            try:
                if args.out:
                    out_path = Path(args.out)
                elif args.outdir:
                    out_path = Path(args.outdir) / (md_path.stem + ".pdf")
                else:
                    out_path = md_path.with_suffix(".pdf")

                convert_one(md_path, out_path, args.theme, page,
                            args.diagram_width, args.diagram_height,
                            args.verbose, not args.no_landscape)

            except Exception as e:
                print(f"   ❌ 错误：{e}")
                errors += 1

        browser.close()

    print(f"\n{'─' * 48}")
    print(f"完成：{len(input_paths) - errors} 成功，{errors} 失败。")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
