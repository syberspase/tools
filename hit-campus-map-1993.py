#!/usr/bin/env python3
"""Redraw the 1993 HIT campus sketch with Gemini layout + corrected labels."""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math

# Original scan is 832 x 570. Draw at 4x for a sharp print.
S = 4
W, H = 832 * S, 570 * S

# Palette — cream paper, grey roads, function-colored blocks (Gemini look)
PAPER = (246, 239, 217)
INK = (36, 32, 28)
ROAD = (198, 198, 196)
ROAD_EDGE = (120, 118, 112)
ACAD = (210, 154, 114)       # teaching / admin
DORM = (158, 196, 176)       # dormitories, bath
FOOD = (226, 186, 96)        # canteens
SITE = (196, 208, 216)       # construction
SITE_LINE = (150, 164, 176)
MED = (226, 168, 160)        # hospital, school
STAD = (196, 186, 112)       # sports field
MKT = (168, 186, 196)        # market / post / north row
SCI = (176, 204, 196)        # science hall
NOTE = (252, 248, 236)       # text panels
WHITE = (255, 252, 245)

SANS_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_R = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
SERIF_B = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
SERIF_R = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
KAI = "/usr/share/fonts/truetype/arphic/ukai.ttc"
SC, KAI_CN = 2, 2


def font(path, size, idx=SC):
    return ImageFont.truetype(path, int(size * S / 4), index=idx)


def F(px):
    return int(px * S)


def box(x, y, w, h):
    return (F(x), F(y), F(x + w), F(y + h))


def fill_rect(d, b, color, outline=INK, width=2):
    d.rectangle(b, fill=color, outline=outline, width=max(1, width * S // 4))


def hatch(im, b, bg, line=SITE_LINE, step=7):
    """Diagonal hatch clipped to the rectangle — never draws outside it."""
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = b
    w, h = x1 - x0, y1 - y0
    tile = Image.new("RGB", (w, h), bg)
    td = ImageDraw.Draw(tile)
    step_px = max(5, F(step))
    for i in range(-h, w + h, step_px):
        td.line([(i, 0), (i + h, h)], fill=line, width=max(1, S // 4))
    im.paste(tile, (x0, y0))
    d.rectangle(b, outline=INK, width=max(1, 2 * S // 4))


def text_size(draw, text, fnt):
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=fnt)
    return x1 - x0, y1 - y0


def draw_htext(draw, cx, cy, text, fnt, fill=INK, anchor="mm"):
    draw.text((cx, cy), text, font=fnt, fill=fill, anchor=anchor)


def draw_vtext(draw, cx, top, text, fnt, fill=INK, gap=1):
    """Vertical column of characters, centered on cx, starting at top."""
    sizes = [text_size(draw, ch, fnt) for ch in text]
    total_h = sum(h for _, h in sizes) + gap * S * (len(text) - 1)
    y = top
    for ch, (w, h) in zip(text, sizes):
        draw.text((cx, y + h // 2), ch, font=fnt, fill=fill, anchor="mm")
        y += h + gap * S
    return total_h


def fit_label(draw, b, text, fnt, fill=INK, vertical=False, pad=4):
    x0, y0, x1, y1 = b
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    if vertical:
        h = y1 - y0 - F(pad) * 2
        draw_vtext(draw, cx, y0 + F(pad), text, fnt, fill)
    else:
        draw_htext(draw, cx, cy, text, fnt, fill)


def wrapped_center(draw, b, lines, fnt, fill=INK, leading=1.15):
    x0, y0, x1, y1 = b
    cx = (x0 + x1) // 2
    heights = []
    for line in lines:
        _, h = text_size(draw, line, fnt)
        heights.append(h)
    total = int(sum(heights) * leading)
    y = (y0 + y1) // 2 - total // 2
    for line, h in zip(lines, heights):
        draw_htext(draw, cx, y + h // 2, line, fnt, fill)
        y += int(h * leading)


def split_dorm(d, x, y, w, h, name, lines, fill=DORM, name_w=28):
    b = box(x, y, w, h)
    fill_rect(d, b, fill)
    nb = box(x, y, name_w, h)
    d.line([(F(x + name_w), F(y)), (F(x + name_w), F(y + h))], fill=INK, width=max(1, 2 * S // 4))
    fit_label(d, nb, name, font(SANS_B, 11), vertical=True)
    rb = box(x + name_w, y, w - name_w, h)
    wrapped_center(d, rb, lines, font(SANS_R, 10))


def circle_num(d, x, y, n, r=7):
    cx, cy = F(x), F(y)
    rr = F(r)
    d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=INK, fill=WHITE, width=max(1, 2 * S // 4))
    draw_htext(d, cx, cy, str(n), font(SANS_B, 9))


def arrow(d, x0, y0, x1, y1):
    d.line([(F(x0), F(y0)), (F(x1), F(y1))], fill=INK, width=max(1, 2 * S // 4))
    ang = math.atan2(y1 - y0, x1 - x0)
    for da in (2.5, -2.5):
        d.line(
            [
                (F(x1), F(y1)),
                (F(x1 - 6 * math.cos(ang + da * 0.25)), F(y1 - 6 * math.sin(ang + da * 0.25))),
            ],
            fill=INK,
            width=max(1, 2 * S // 4),
        )


def compass(d, cx, cy):
    cx, cy = F(cx), F(cy)
    r = F(16)
    d.line((cx - r, cy, cx + r, cy), fill=INK, width=max(1, 2 * S // 4))
    d.line((cx, cy - r, cx, cy + r), fill=INK, width=max(1, 2 * S // 4))
    # north-east tick like the original (北 toward upper-left of page, arrow up)
    d.polygon(
        [(cx, cy - r - F(4)), (cx - F(4), cy - r + F(6)), (cx + F(4), cy - r + F(6))],
        fill=INK,
    )
    draw_htext(d, cx, cy - r - F(10), "北", font(SANS_B, 9))


def main():
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)

    # Outer double frame
    d.rectangle(box(10, 8, 812, 554), outline=INK, width=max(2, 3 * S // 4))
    d.rectangle(box(14, 12, 804, 546), outline=INK, width=max(1, S // 4))
    # corner ticks
    for x, y, dx, dy in ((14, 12, 12, 12), (818, 12, -12, 12), (14, 558, 12, -12), (818, 558, -12, -12)):
        d.line([(F(x), F(y)), (F(x + dx), F(y))], fill=INK, width=max(1, 2 * S // 4))
        d.line([(F(x), F(y)), (F(x), F(y + dy))], fill=INK, width=max(1, 2 * S // 4))

    compass(d, 36, 32)

    title_f = font(SERIF_B, 17)
    draw_htext(d, F(280), F(24), "哈尔滨工业大学校园简图", title_f)
    tw, _ = text_size(d, "哈尔滨工业大学校园简图", title_f)
    d.line([(F(280) - tw // 2, F(35)), (F(280) + tw // 2, F(35))], fill=INK, width=max(1, S // 4))
    draw_htext(d, F(280), F(46), "五系学生会宣传部绘测  93.9", font(SANS_R, 9))

    # Gemini-style grey streets as the campus ground
    fill_rect(d, box(20, 90, 798, 362), ROAD, ROAD_EDGE, 1)

    # ── North of 西大直街 ──────────────────────────────────────────
    fill_rect(d, box(548, 18, 78, 46), MKT)
    fit_label(d, box(548, 18, 78, 46), "教化商场", font(SANS_B, 11))

    north = [("邮局", 628), ("化学楼", 672), ("图书馆", 722), ("物理楼", 772)]
    for name, x in north:
        fill_rect(d, box(x, 32, 42 if name != "图书馆" else 48, 32), ACAD if name != "邮局" else MKT)
        fit_label(d, box(x, 32, 42 if name != "图书馆" else 48, 32), name, font(SANS_B, 10))

    # 西大直街
    fill_rect(d, box(198, 66, 348, 22), ROAD, ROAD_EDGE, 1)
    fit_label(d, box(198, 66, 348, 22), "西大直街", font(SANS_B, 11))
    fill_rect(d, box(546, 66, 272, 22), ROAD, ROAD_EDGE, 1)
    fit_label(d, box(546, 66, 272, 22), "哈市内环路（西端）", font(SANS_B, 10))

    # ── Left column ────────────────────────────────────────────────
    fill_rect(d, box(24, 96, 168, 34), ACAD)
    fit_label(d, box(24, 96, 168, 34), "西苑宾馆", font(SANS_B, 12))

    # classroom numbering legend
    lb = box(24, 134, 168, 148)
    fill_rect(d, lb, NOTE)
    draw_htext(d, F(24 + 84), F(146), "各楼教室标号", font(SANS_B, 10))
    d.line([(F(32), F(154)), (F(184), F(154))], fill=INK, width=max(1, S // 4))
    rows = [
        ("管理学院", "G"),
        ("新教学楼", "X"),
        ("节能楼", "J"),
        ("主楼", "三位数字"),
        ("电机楼", "五位数字"),
        ("机械楼", "四位数字"),
    ]
    y = 160
    for a, b_ in rows:
        draw_htext(d, F(36), F(y), a, font(SANS_R, 9), anchor="lm")
        draw_htext(d, F(182), F(y), b_, font(SANS_B, 9), anchor="rm")
        y += 16
    wrapped_center(
        d,
        box(24, 254, 168, 24),
        ["例  G001  X421  J201", "416  30030  1031"],
        font(SANS_R, 8),
    )

    fill_rect(d, box(24, 286, 168, 52), DORM)
    wrapped_center(
        d,
        box(24, 286, 168, 52),
        ["六七八舍", "住研究生、留学生"],
        font(SANS_B, 11),
    )

    split_dorm(
        d, 24, 344, 168, 72, "一宿舍",
        ["住 6、7、8、9 系本科生", "及各系专科生"],
    )

    fill_rect(d, box(24, 424, 168, 70), STAD)
    fit_label(d, box(24, 424, 168, 70), "体育场", font(SANS_B, 16))

    # ── Management / new teaching ─────────────────────────────────
    fill_rect(d, box(200, 96, 84, 50), ACAD)
    fit_label(d, box(200, 96, 84, 50), "管理学院", font(SANS_B, 12))
    fill_rect(d, box(288, 96, 84, 50), ACAD)
    wrapped_center(d, box(288, 96, 84, 50), ["新教学楼"], font(SANS_B, 12))

    # 建议
    fill_rect(d, box(380, 96, 150, 58), NOTE)
    draw_htext(d, F(396), F(108), "建议", font(SANS_B, 10), anchor="lm")
    d.line([(F(388), F(116)), (F(522), F(116))], fill=INK, width=1)
    tips = [
        "1. 安置寝室明锁",
        "2. 暂缓购买非生活必需品",
        "3. 谨防推销者",
    ]
    ty = 124
    for t in tips:
        draw_htext(d, F(388), F(ty), t, font(SANS_R, 8), anchor="lm")
        ty += 10

    # ── Gym + canteens ────────────────────────────────────────────
    # outer compound
    fill_rect(d, box(200, 154, 172, 154), PAPER)
    fill_rect(d, box(206, 200, 50, 72), SITE)
    fit_label(d, box(206, 200, 50, 72), "体育馆工地", font(SANS_B, 10), vertical=True)

    fill_rect(d, box(260, 160, 104, 28), FOOD)
    fit_label(d, box(260, 160, 104, 28), "教工食堂", font(SANS_B, 11))
    circle_num(d, 378, 174, 3)
    arrow(d, 364, 174, 370, 174)

    fill_rect(d, box(260, 192, 52, 72), FOOD)
    fit_label(d, box(260, 192, 52, 72), "六食堂", font(SANS_B, 11), vertical=True)
    circle_num(d, 330, 228, 4)
    arrow(d, 314, 228, 322, 228)

    fill_rect(d, box(260, 268, 104, 16), WHITE)
    fill_rect(d, box(260, 286, 104, 16), WHITE)

    fill_rect(d, box(200, 300, 172, 18), FOOD)
    fit_label(d, box(200, 300, 172, 18), "二食堂", font(SANS_B, 11))
    fill_rect(d, box(200, 320, 172, 18), FOOD)
    fit_label(d, box(200, 320, 172, 18), "七食堂", font(SANS_B, 11))
    fill_rect(d, box(200, 340, 172, 18), FOOD)
    fit_label(d, box(200, 340, 172, 18), "方便食堂", font(SANS_B, 11))

    fill_rect(d, box(200, 362, 172, 36), DORM)
    fit_label(d, box(200, 362, 172, 36), "六七八宿舍", font(SANS_B, 12))

    # labs / gym / bath
    fill_rect(d, box(200, 402, 52, 36), ACAD)
    fit_label(d, box(200, 402, 52, 36), "体育馆", font(SANS_B, 10), vertical=True)
    fill_rect(d, box(256, 402, 70, 36), ACAD)
    wrapped_center(d, box(256, 402, 70, 36), ["综合实验楼"], font(SANS_B, 10))
    fill_rect(d, box(330, 402, 42, 36), ACAD)
    wrapped_center(d, box(330, 402, 42, 36), ["计算机中心"], font(SANS_B, 9))
    fill_rect(d, box(200, 442, 172, 48), DORM)
    fit_label(d, box(200, 442, 172, 48), "浴池", font(SANS_B, 14))

    # ── Library site / hospital / dorms 2 & 3 ─────────────────────
    hatch(im, box(380, 158, 154, 118), SITE)
    wrapped_center(d, box(380, 158, 154, 118), ["图书馆工地"], font(SANS_B, 14))

    fill_rect(d, box(380, 280, 46, 40), MED)
    fit_label(d, box(380, 280, 46, 40), "医院", font(SANS_B, 11))
    circle_num(d, 372, 300, 5)
    arrow(d, 372, 300, 378, 300)

    fill_rect(d, box(430, 280, 48, 40), MKT)
    fit_label(d, box(430, 280, 48, 40), "派出所", font(SANS_B, 10), vertical=True)
    fill_rect(d, box(482, 280, 52, 40), MKT)
    fit_label(d, box(482, 280, 52, 40), "商店", font(SANS_B, 11))

    split_dorm(d, 380, 326, 154, 48, "三宿舍", ["住本科女生"])
    split_dorm(
        d, 380, 380, 154, 72, "二宿舍",
        ["住 1～5、10～19 系", "本科生、部分专科生"],
    )

    # ── Vertical inner-ring construction road ─────────────────────
    hatch(im, box(538, 92, 22, 360), SITE, step=5)
    draw_vtext(d, F(549), F(150), "哈市内环路工地", font(SANS_B, 9))

    # ── Main building U ───────────────────────────────────────────
    fill_rect(d, box(566, 96, 148, 36), ACAD)          # 主楼 bar
    fit_label(d, box(566, 96, 148, 36), "主楼  ①", font(SANS_B, 12))
    fill_rect(d, box(566, 132, 52, 72), ACAD)          # 电机楼
    fit_label(d, box(566, 132, 52, 72), "电机楼", font(SANS_B, 11), vertical=True)
    fill_rect(d, box(662, 132, 52, 72), ACAD)          # 机械楼
    fit_label(d, box(662, 132, 52, 72), "机械楼", font(SANS_B, 11), vertical=True)
    # club protrusion ②
    fill_rect(d, box(618, 132, 40, 28), ACAD)
    circle_num(d, 638, 146, 2)

    fill_rect(d, box(566, 210, 100, 36), SCI)
    fit_label(d, box(566, 210, 100, 36), "邵逸夫科学馆", font(SANS_B, 11))
    fill_rect(d, box(670, 210, 44, 36), ACAD)
    fit_label(d, box(670, 210, 44, 36), "节能楼", font(SANS_B, 10), vertical=True)

    hatch(im, box(722, 96, 92, 48), SITE)
    wrapped_center(d, box(722, 96, 92, 48), ["科技城工地"], font(SANS_B, 11))
    fill_rect(d, box(722, 148, 92, 48), MKT)
    fit_label(d, box(722, 148, 92, 48), "校办工厂", font(SANS_B, 12))
    fill_rect(d, box(722, 200, 92, 46), MED)
    fit_label(d, box(722, 200, 92, 46), "复华小学", font(SANS_B, 12))

    # numbered notes
    nb = box(566, 254, 148, 98)
    fill_rect(d, nb, NOTE)
    notes = [
        "①  主楼有收发室（一楼，可取汇款）",
        "②  工大俱乐部",
        "③  俱乐部售票处",
        "④  六食堂三四楼为学生阅览室",
        "⑤  哈工大出版社读者服务部",
    ]
    ny = 264
    for line in notes:
        draw_htext(d, F(574), F(ny), line, font(SANS_R, 8), anchor="lm")
        ny += 16

    # welcome letter
    lb = box(566, 356, 248, 100)
    fill_rect(d, lb, NOTE)
    lf = font(SERIF_R, 8)
    lfb = font(SERIF_B, 9)
    draw_htext(d, F(578), F(368), "五系九三级同学：", lfb, anchor="lm")
    letter = [
        "你们好！首先祝贺你们以优异的成绩来到了哈工大，来到了五系！",
        "新学期开始，为了使新同学们尽早熟悉校园环境、适应紧张充实",
        "的大一生活，我们绘制了这份工大地图，希望对你们有所帮助。",
        "祝九三级同学在新学期里学习进步、生活愉快！",
    ]
    ly = 382
    for line in letter:
        draw_htext(d, F(578), F(ly), line, lf, anchor="lm")
        ly += 13
    draw_htext(d, F(798), F(440), "五系学生会　宣传部　仲继松", lfb, anchor="rm")

    # ── Department codes ──────────────────────────────────────────
    db = box(200, 460, 614, 90)
    fill_rect(d, db, NOTE)
    draw_vtext(d, F(214), F(472), "各系代号", font(SANS_B, 10))
    d.line([(F(226), F(468)), (F(226), F(542))], fill=INK, width=max(1, S // 4))
    depts = [
        (1, "精密仪器"), (2, "动力工程"), (3, "计算机"), (4, "自动控制"),
        (5, "无线电工程"), (6, "电气工程"), (7, "应用化学"), (8, "机械工程"),
        (9, "金属工艺"), (10, "管理学院"), (11, "应用物理"), (12, "应用数学"),
        (14, "建筑工程"), (15, "外语"), (18, "航天工程与力学"), (19, "汽车学院"),
    ]
    cols, rows_n = 4, 4
    cell_w, cell_h = 145, 18
    ox, oy = 236, 472
    for i, (num, name) in enumerate(depts):
        r, c = divmod(i, cols)
        # 4x4: i 0-3 row0, 4-7 row1...
        r, c = i // cols, i % cols
        draw_htext(
            d, F(ox + c * cell_w), F(oy + r * cell_h),
            f"{num}. {name}", font(SANS_R, 9), anchor="lm",
        )
        if r < 3:
            yline = oy + r * cell_h + 10
            d.line(
                [(F(ox), F(yline)), (F(ox + 4 * cell_w - 8), F(yline))],
                fill=(210, 200, 180), width=1,
            )

    # Color legend — left column under 体育场, does not overlap 各系代号
    legend_items = [
        (ACAD, "教学行政"),
        (DORM, "宿舍浴池"),
        (FOOD, "食堂"),
        (SITE, "工地"),
        (MED, "医院小学"),
        (STAD, "运动场"),
    ]
    fill_rect(d, box(24, 500, 168, 48), NOTE)
    draw_htext(d, F(32), F(512), "图例", font(SANS_B, 9), anchor="lm")
    for i, (col, name) in enumerate(legend_items):
        r, c = i // 3, i % 3
        lx = 28 + c * 54
        ly = 524 + r * 12
        fill_rect(d, box(lx, ly - 5, 8, 8), col, width=1)
        draw_htext(d, F(lx + 12), F(ly), name, font(SANS_R, 7), anchor="lm")

    out = "/media/lius/shep-protected/Videos/web-player/hit-campus-map-1993-vector.png"
    im.save(out, "PNG", optimize=True)
    preview = im.resize((1248, 855), Image.Resampling.LANCZOS)
    preview.save("/tmp/hit-campus-map-preview.png", "PNG")
    print("wrote", out, im.size)


if __name__ == "__main__":
    main()
