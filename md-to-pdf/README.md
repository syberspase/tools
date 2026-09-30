# md_to_pdf.py

Markdown → PDF 转换工具，**支持 mermaid 图表自动渲染和中文字体**。

底层用 Playwright 控制 Chromium headless 打印 PDF，mermaid 图表通过 CDN 在浏览器里渲染成 SVG。

## 首次安装（只需一次）

```bash
pip install markdown playwright
playwright install chromium
```

## 用法

### 单个文件（PDF 输出到同目录）
```bash
python3 tools/md-to-pdf/md_to_pdf.py report.md
# → report.pdf
```

### 多个文件
```bash
python3 tools/md-to-pdf/md_to_pdf.py a.md b.md c.md
```

### 通配符（bash glob）
```bash
python3 tools/md-to-pdf/md_to_pdf.py 未来家装/*.md
```

### 指定输出路径（单文件）
```bash
python3 tools/md-to-pdf/md_to_pdf.py report.md --out /tmp/report.pdf
```

### 输出到指定目录（多文件）
```bash
python3 tools/md-to-pdf/md_to_pdf.py *.md --outdir ./pdfs/
```

### 切换 mermaid 主题
```bash
python3 tools/md-to-pdf/md_to_pdf.py report.md --theme dark
# 可选：default（默认）| dark | forest | neutral
```

### 排查图表太大／太小
```bash
python3 tools/md-to-pdf/md_to_pdf.py report.md -v
```
逐图打印原始尺寸、缩放比和等效字号：
```
  ⚠️ #1   1337×1137  →  823×700   ×0.62  字≈7.4px  [横向页]
    #2    484×722   →  484×722   ×1.00  字≈12.0px
  ↑ #8    307×518   →  367×620   ×1.20  字≈14.4px
```
`⚠️` = 缩放比 < 0.5，字号掉到 6px 以下。这类图是**源文件本身太宽**，
脚本改不了，得去改 mermaid 方向（`LR` → `TB`）或拆图。

## 选项

| 选项 | 说明 |
| --- | --- |
| `--out PATH` | 指定单个输出 PDF 路径 |
| `--outdir DIR` | 所有 PDF 输出到指定目录 |
| `--theme NAME` | mermaid 主题：`default` \| `dark` \| `forest` \| `neutral` |
| `-v, --verbose` | 逐图打印尺寸与缩放比，排查图太大／太小 |
| `--diagram-width PX` | 图表最大宽度（默认 632 = Letter 竖版可用内容宽） |
| `--diagram-height PX` | 图表最大高度（默认 780） |
| `--no-landscape` | 禁用「超宽图自动转横向页」 |

## 图表排版是怎么处理的

Letter 纸、0.75in 页边距，可用内容区 **632×912px**。

1. **等比缩放**到 632×780 以内。高度上限取 780 而不是 912 是有原因的：
   图一旦撑满整页，`page-break-inside: avoid` 会让它独占一页，把自己的小标题
   孤零零甩在上一页（整页空白）。实测 890→4 个空白页，820→1 个，780→0 个。
2. **小图适度放大**（最多 1.4×），否则窄图在页面上只占一小条。
   但放大后高度不超过 620px，同样是为了能和标题、正文挤在同一页。
3. **超宽图自动转横向页**：竖版缩放比已经低于 0.5、且横向页（内容区 920×700）
   能明显改善（≥1.15×）时，该图单独占一张 landscape 页。
   高瘦图不会被翻——横向页高度更小，翻了只会更糟。

配套脚本：

| 脚本 | 用途 |
| --- | --- |
| `check_mermaid.py` | 校验 mermaid 语法，按真实渲染路径做 DOM 级检查 |
| `count_blank_pages.py` | 统计 PDF 里「几乎空白」的页，用来发现被图挤走的孤儿标题 |

## 常见问题

**图表小得看不清**：先跑 `-v` 看缩放比。低于 0.5 说明图太宽，改 mermaid 方向或拆图；
子图内部想保持横排、整体竖排，用 `direction`：

```
flowchart TB
    subgraph S["资产库"]
        direction LR
        A --- B --- C --- D
    end
    S --> NEXT
```

**某一页几乎全白，只有一个小标题**：跑 `count_blank_pages.py` 确认，
通常是某张图被放大或缩放到接近整页高度。调小 `--diagram-height`。

**subgraph 标题被节点压住**：已通过 `subGraphTitleMargin` 处理。



**中文方块乱码**：`playwright install chromium` 安装的 Chromium 内置字体不含中文，需要安装系统字体：
```bash
apt install fonts-noto-cjk    # Ubuntu/Debian
```

**离线环境 mermaid 不渲染**：脚本用了 CDN，离线时把 mermaid.min.js 下载到本地，修改 `HTML_TEMPLATE` 里的 `<script src>` 为本地路径即可。
