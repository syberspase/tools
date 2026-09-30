#!/usr/bin/env python3
"""
check_mermaid.py — 校验 Markdown 里的 mermaid 图表是否有语法错误。

mermaid 出错时会把错误画成红色 "Syntax error in graph" 图片嵌在页面里，
PDF 照样生成成功，所以必须显式调用 parse()/render() 并检查结果。

用法:
    python3 check_mermaid.py a.md b.md
"""

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MERMAID_RE = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)

# 故意写坏的负对照，用来确认检测逻辑真的能抓到错误
NEGATIVE_CONTROLS = [
    ("NEGCTRL-1 unquoted-ascii-paren", 'flowchart TB\n    A[label (paren) here] --> B[end节点]'),
    ("NEGCTRL-2 bogus-tokens", 'flowchart TB\n    A --> B\n    thisIsNotValid ]][[ C'),
    ("NEGCTRL-3 unclosed-bracket", 'flowchart TB\n    A[未闭合的标签 --> B'),
    ("NEGCTRL-4 bad-direction", 'flowchart QQ\n    A --> B'),
    ("NEGCTRL-5 unknown-diagram", 'flowchartt TB\n    A --> B'),
    ("NEGCTRL-6 bad-gantt-date", 'gantt\n    title X\n    dateFormat YYYY-MM-DD\n    section S\n    t1 :a1, notadate, 3d'),
]

PAGE_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
</head><body><div id="sink"></div>
<script>
mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'loose',
  fontFamily: 'Noto Sans SC, Microsoft YaHei, sans-serif',
  fontSize: 12,
  flowchart:    { useMaxWidth: false, htmlLabels: true, curve: 'basis', padding: 8 },
  sequence:     { useMaxWidth: false },
  gantt:        { useMaxWidth: false, fontSize: 11 },
  stateDiagram: { useMaxWidth: false },
});
window.__check = async function (code, idx) {
  const out = { parse: null, render: null, svgLen: 0, errText: null };
  try {
    await mermaid.parse(code);
  } catch (e) {
    out.parse = (e && (e.str || e.message)) ? String(e.str || e.message) : String(e);
  }
  try {
    const res = await mermaid.render('chk' + idx, code);
    const svg = res.svg || '';
    out.svgLen = svg.length;
    // mermaid 画出来的错误图里有 "Syntax error in graph" / aria-roledescription="error"
    if (/Syntax error in (graph|text)/i.test(svg) ||
        /aria-roledescription="error"/i.test(svg) ||
        /class="error-icon"/i.test(svg)) {
      out.errText = 'rendered error-graph SVG';
    }
    if (!/<svg/i.test(svg)) out.errText = 'no <svg> produced';
  } catch (e) {
    out.render = (e && (e.str || e.message)) ? String(e.str || e.message) : String(e);
  }
  return out;
};
</script></body></html>
"""


def collect(paths):
    items = []
    for p in paths:
        text = Path(p).read_text(encoding="utf-8")
        for m in MERMAID_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            items.append({"file": str(p), "line": line, "code": m.group(1).rstrip("\n")})
    return items


DOM_PROBE = """
() => {
  const out = [];
  document.querySelectorAll('.mermaid').forEach((el, i) => {
    const svg = el.querySelector('svg');
    const txt = el.textContent || '';
    out.push({
      idx: i,
      processed: el.hasAttribute('data-processed'),
      hasSvg: !!svg,
      svgW: svg ? (svg.getAttribute('width') || '') : '',
      svgH: svg ? (svg.getAttribute('height') || '') : '',
      // 各图种的「内容元素」选择器不一样：时序图没有 .node，只有 .actor 和 .messageText，
      // 状态图用 .statediagram-state，饼图用 .pieCircle。只数 .node 会把它们全判成失败。
      nodes: svg ? svg.querySelectorAll(
        '.node, .nodeLabel, .taskText, .task, .actor, .messageText, .labelText,'
        + ' .statediagram-state, .pieCircle, .classGroup, .entityBox, .commit'
      ).length : 0,
      errorIcon: !!el.querySelector('.error-icon, [aria-roledescription="error"], .error-text'),
      errorText: /Syntax error|mermaid version|Parse error|Error:/i.test(txt),
      snippet: txt.replace(/\\s+/g, ' ').trim().slice(0, 120),
    });
  });
  return out;
}
"""


def dom_check(page, md_path: Path) -> int:
    """按 md_to_pdf.py 的真实渲染路径（startOnLoad）建页面，再检查 DOM。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from md_to_pdf import md_to_html

    html = md_to_html(md_path.read_text(encoding="utf-8"), md_path.stem, "default", 380)
    tmp = md_path.resolve().with_name(f"__domcheck_{md_path.stem}__.html")
    tmp.write_text(html, encoding="utf-8")
    bad = 0
    try:
        page.goto(tmp.as_uri(), wait_until="networkidle", timeout=60_000)
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('.mermaid:not([data-processed])').length === 0",
                timeout=30_000,
            )
        except Exception:
            print("      ⚠️ 渲染超时")
        page.wait_for_timeout(1500)
        for r in page.evaluate(DOM_PROBE):
            ok = r["processed"] and r["hasSvg"] and not r["errorIcon"] and not r["errorText"] and r["nodes"] > 0
            flag = "✅" if ok else "❌"
            print(f"      {flag} div#{r['idx'] + 1}  svg={r['hasSvg']} {r['svgW']}x{r['svgH']} "
                  f"nodes={r['nodes']} errIcon={r['errorIcon']} errText={r['errorText']}")
            if not ok:
                print(f"         文本: {r['snippet']}")
                bad += 1
    finally:
        tmp.unlink(missing_ok=True)
    return bad


def main():
    files = sys.argv[1:]
    if not files:
        sys.exit("用法: python3 check_mermaid.py <file.md> ...")

    items = collect(files)
    print(f"共提取 {len(items)} 个 mermaid 块\n")

    console = []
    failures = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.on("console", lambda msg: console.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: console.append(f"[pageerror] {err}"))

        tmp = Path(files[0]).resolve().with_name("__mermaid_check__.html")
        tmp.write_text(PAGE_HTML, encoding="utf-8")
        try:
            page.goto(tmp.as_uri(), wait_until="networkidle", timeout=60_000)
            page.wait_for_function("() => typeof window.__check === 'function'", timeout=30_000)

            print("=== 负对照（必须全部 FAIL，否则检测逻辑本身无效）===")
            neg_ok = True
            for i, (name, code) in enumerate(NEGATIVE_CONTROLS):
                r = page.evaluate("([c, i]) => window.__check(c, i)", [code, f"neg{i}"])
                bad = r["parse"] or r["render"] or r["errText"]
                print(f"  {name}: {'FAIL(符合预期)' if bad else 'PASS(!! 检测器失效 !!)'}"
                      f"  {(r['parse'] or r['render'] or r['errText'] or '')[:90]}")
                if not bad:
                    neg_ok = False
            print(f"  → 负对照结论：{'检测器有效' if neg_ok else '检测器无效，结果不可信'}\n")

            print("=== 实际图表 ===")
            cur = None
            n = 0
            for it in items:
                if it["file"] != cur:
                    cur = it["file"]
                    n = 0
                    print(f"\n-- {cur}")
                n += 1
                r = page.evaluate("([c, i]) => window.__check(c, i)", [it["code"], f"d{items.index(it)}"])
                bad = r["parse"] or r["render"] or r["errText"]
                first = it["code"].splitlines()[0][:40]
                if bad:
                    failures += 1
                    print(f"   #{n} L{it['line']:<5} [{first}]  ❌ FAIL")
                    print(f"        parse : {r['parse']}")
                    print(f"        render: {r['render']}")
                    print(f"        dom   : {r['errText']}  svgLen={r['svgLen']}")
                else:
                    print(f"   #{n} L{it['line']:<5} [{first}]  ✅ OK  svgLen={r['svgLen']}")
            print("\n=== DOM 级检查（按 md_to_pdf.py 的真实渲染路径）===")
            for f in files:
                print(f"\n-- {f}")
                failures += dom_check(page, Path(f))
        finally:
            tmp.unlink(missing_ok=True)
            browser.close()

    print("\n=== 浏览器控制台输出 ===")
    if console:
        for c in console:
            print("  " + c)
    else:
        print("  (无)")

    print(f"\n结果：{len(items) - failures}/{len(items)} 通过")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
