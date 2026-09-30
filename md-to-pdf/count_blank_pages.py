#!/usr/bin/env python3
"""统计 PDF 里「几乎空白」的页——用来发现被图挤走、只剩一个孤零零小标题的页面。

判据：整页非白像素占比 < THRESHOLD。图和文字都算 ink，所以只有真正空的页会被抓出来。

用法：
    python3 count_blank_pages.py a.pdf [b.pdf ...]
"""

import subprocess
import sys
import tempfile
from pathlib import Path

THRESHOLD = 0.012   # 非白像素占比低于此值算「几乎空白」
DPI = 50            # 只做统计，低分辨率足够且快


def page_ink_ratios(pdf: Path) -> list[float]:
    """逐页返回非白像素占比。手工解析 PGM 灰度图，避免依赖 PIL。"""
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(
            ["pdftoppm", "-gray", "-r", str(DPI), str(pdf), f"{td}/p"],
            check=True, capture_output=True,
        )
        ratios = []
        for p in sorted(Path(td).glob("p-*.pgm")):
            data = p.read_bytes()
            # PGM (P5) 头：magic / width height / maxval，三行后是原始像素
            pos, fields = 0, []
            while len(fields) < 4:
                nl = data.index(b"\n", pos)
                line = data[pos:nl]
                pos = nl + 1
                if line.startswith(b"#"):
                    continue
                fields.extend(line.split())
            pixels = data[pos:]
            non_white = sum(1 for b in pixels if b < 250)
            ratios.append(non_white / len(pixels) if pixels else 0.0)
        return ratios


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("用法：count_blank_pages.py <file.pdf> [...]")

    worst = 0
    for f in sys.argv[1:]:
        pdf = Path(f)
        ratios = page_ink_ratios(pdf)
        blanks = [(i + 1, r) for i, r in enumerate(ratios) if r < THRESHOLD]
        status = "✅" if not blanks else "⚠️"
        print(f"{status} {pdf.name}：共 {len(ratios)} 页，近乎空白 {len(blanks)} 页")
        for pg, r in blanks:
            print(f"      · 第 {pg} 页  ink={r * 100:.2f}%")
        worst = max(worst, len(blanks))
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
