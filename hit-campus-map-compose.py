#!/usr/bin/env python3
"""Composite HIT 1993 campus map from harvested brush glyphs.

Surgical patches only. Keep native 建议 line 3, ①③⑤, ④ tail, ② 工大.
Never paste a second font over a whole running label.
"""
from pathlib import Path
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import cv2

BACKUP = Path("/media/lius/shep-protected/Videos/web-player/hit-campus-map-1993-before-overlay.png")
OUT = Path("/media/lius/shep-protected/Videos/web-player/hit-campus-map-1993.png")
SHEET = Path("/media/lius/shep-protected/Videos/web-player/hit-notes-hand-labels.png")
DBG = Path("/tmp/hitcrops")
WK = Path("/tmp/hit-fonts/LXGWWenKai-Medium.ttf")
MS = Path("/tmp/hit-fonts/MaShanZheng-Regular.ttf")
DBG.mkdir(exist_ok=True)

RNG = np.random.default_rng(1993)
INK_NOTE = (52, 56, 58)
INK_SHAW = (48, 48, 50)


def load_rgb(path):
    return np.array(Image.open(path).convert("RGB"))


def sprite(src, box, thresh=125, hatch_guard=False):
    x0, y0, x1, y1 = [int(v) for v in box]
    crop = src[y0:y1, x0:x1]
    lum = crop.astype(np.float32).mean(axis=2)
    t = 110 if hatch_guard else thresh
    gain = 10.0 if hatch_guard else 12.0
    alpha = np.clip((t - lum) * gain, 0, 255).astype(np.uint8)
    alpha = np.where(lum < t - 12, 255, alpha)
    if hatch_guard:
        blue = crop[:, :, 2].astype(np.int16)
        red = crop[:, :, 0].astype(np.int16)
        hatch = (blue - red > 16) & (lum > 85)
        alpha = np.where(hatch, 0, alpha).astype(np.uint8)
    ys, xs = np.where(alpha > 28)
    if len(xs) == 0:
        raise RuntimeError(f"no ink in {box}")
    pad = 1
    y0t = max(0, int(ys.min()) - pad)
    y1t = min(alpha.shape[0], int(ys.max()) + 1 + pad)
    x0t = max(0, int(xs.min()) - pad)
    x1t = min(alpha.shape[1], int(xs.max()) + 1 + pad)
    out = np.zeros((y1t - y0t, x1t - x0t, 4), np.uint8)
    out[:, :, :3] = crop[y0t:y1t, x0t:x1t]
    out[:, :, 3] = alpha[y0t:y1t, x0t:x1t]
    return Image.fromarray(out, "RGBA")


def blit_ink(dst, src, src_box, xy, thresh=145):
    """Copy only dark ink pixels so local paper is not stamped as a rectangle."""
    x0, y0, x1, y1 = [int(v) for v in src_box]
    patch = src[y0:y1, x0:x1]
    lum = patch.astype(np.float32).mean(axis=2)
    mask = lum < thresh
    x, y = int(xy[0]), int(xy[1])
    h, w = patch.shape[:2]
    dest = dst[y:y + h, x:x + w]
    dest[mask] = patch[mask]
    dst[y:y + h, x:x + w] = dest
    return w, h


def scale_to_h(spr, h):
    w, hh = spr.size
    if hh == 0:
        return spr
    nw = max(1, int(round(w * h / hh)))
    return spr.resize((nw, int(h)), Image.Resampling.LANCZOS)


def scale_to_w(spr, w):
    ww, h = spr.size
    if ww == 0:
        return spr
    nh = max(1, int(round(h * w / ww)))
    return spr.resize((int(w), nh), Image.Resampling.LANCZOS)


def join_h(parts, gap=2, h=None):
    parts = [scale_to_h(p, h) if h else p for p in parts]
    H = max(p.size[1] for p in parts)
    W = sum(p.size[0] for p in parts) + gap * (len(parts) - 1)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x = 0
    for p in parts:
        canvas.paste(p, (x, (H - p.size[1]) // 2), p)
        x += p.size[0] + gap
    return canvas


def erase_ink(arr, box, thresh=130, inflate=2):
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
    region = arr[y0:y1, x0:x1]
    lum = region.astype(np.float32).mean(axis=2)
    ink = lum < thresh
    if inflate:
        k = np.ones((inflate * 2 + 1, inflate * 2 + 1), np.uint8)
        ink = cv2.dilate(ink.astype(np.uint8), k, iterations=1).astype(bool)
    paper = region[~ink]
    if paper.size == 0:
        return
    fill = np.median(paper.astype(np.float32), axis=0)
    std = np.std(paper.astype(np.float32), axis=0).clip(0, 5)
    noise = RNG.normal(0, 1, region.shape) * std
    out = region.copy()
    out[ink] = np.clip(fill + noise[ink], 0, 255).astype(np.uint8)
    arr[y0:y1, x0:x1] = out


def wipe_to_paper(arr, box, paper_box, src, thresh=170, inflate=4):
    """Erase leftover letters in box. Fill only those pixels from a clean paper
    patch that itself has no ink — never tile a sample taken off existing text."""
    x0, y0, x1, y1 = [int(v) for v in box]
    region = arr[y0:y1, x0:x1]
    lum = region.astype(np.float32).mean(axis=2)
    ink = lum < thresh
    if inflate:
        k = np.ones((inflate * 2 + 1, inflate * 2 + 1), np.uint8)
        ink = cv2.dilate(ink.astype(np.uint8), k, iterations=1).astype(bool)
    sx0, sy0, sx1, sy1 = [int(v) for v in paper_box]
    samp = src[sy0:sy1, sx0:sx1]
    sl = samp.astype(np.float32).mean(axis=2)
    paper = samp[sl > 195]
    if paper.shape[0] < 20:
        raise RuntimeError(f"paper sample still has letters: {paper_box}")
    fill = np.median(paper.astype(np.float32), axis=0)
    std = np.std(paper.astype(np.float32), axis=0).clip(0.8, 3.5)
    noise = RNG.normal(0, 1, region.shape) * std
    out = region.copy()
    out[ink] = np.clip(fill + noise[ink], 0, 255).astype(np.uint8)
    arr[y0:y1, x0:x1] = out


def sheet_line(sheet, y0, y1, thresh=148):
    """Ink-only crop of one row from the handwritten label sheet."""
    band = sheet[y0:y1]
    lum = band.astype(np.float32).mean(axis=2)
    ink = lum < thresh
    xs = np.where(ink.mean(0) > 0.01)[0]
    ys = np.where(ink.mean(1) > 0.01)[0]
    box = (int(xs[0]), y0 + int(ys[0]), int(xs[-1]) + 1, y0 + int(ys[-1]) + 1)
    return sprite(sheet, box, thresh=thresh)


def fill_paper(arr, box, sample):
    """Wipe a rectangle using paper sampled from a nearby clean patch (no white scar)."""
    sx0, sy0, sx1, sy1 = [int(v) for v in sample]
    samp = arr[sy0:sy1, sx0:sx1]
    lum = samp.astype(np.float32).mean(axis=2)
    paper = samp[lum > 190]
    if paper.size == 0:
        paper = samp.reshape(-1, 3)
    fill = np.median(paper.astype(np.float32), axis=0)
    fill_solid(arr, box, fill, std=np.std(paper.astype(np.float32), axis=0).clip(1, 4).mean())


def fill_solid(arr, box, rgb, std=3.0):
    x0, y0, x1, y1 = [int(v) for v in box]
    h, w = y1 - y0, x1 - x0
    fill = np.array(rgb, np.float32)
    noise = RNG.normal(0, std, (h, w, 3))
    arr[y0:y1, x0:x1] = np.clip(fill + noise, 0, 255).astype(np.uint8)


def inpaint_ink(arr, box, thresh=155, inflate=3):
    """Remove dark strokes but keep local paper texture/color."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
    region = arr[y0:y1, x0:x1].copy()
    lum = region.astype(np.float32).mean(axis=2)
    mask = (lum < thresh).astype(np.uint8) * 255
    if inflate:
        k = np.ones((inflate * 2 + 1, inflate * 2 + 1), np.uint8)
        mask = cv2.dilate(mask, k, iterations=1)
    arr[y0:y1, x0:x1] = cv2.inpaint(region, mask, 4, cv2.INPAINT_TELEA)


def paste_center(base, spr, box, y_shift=0):
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    x = x0 + (bw - spr.size[0]) // 2
    y = y0 + (bh - spr.size[1]) // 2 + y_shift
    base.paste(spr, (int(x), int(y)), spr)
    return int(x), int(y)


def save_dbg(spr, name):
    cream = Image.new("RGB", (spr.size[0] + 8, spr.size[1] + 8), (238, 230, 214))
    cream.paste(spr, (4, 4), spr)
    cream.save(DBG / name)


def thicken(spr, iterations=1):
    """Dilate ink so harvested small glyphs match neighboring brush weight."""
    if iterations <= 0:
        return spr
    a = np.array(spr)
    rgb, alpha = a[:, :, :3], a[:, :, 3]
    k = np.ones((3, 3), np.uint8)
    new_a = cv2.dilate(alpha, k, iterations=iterations)
    ink = rgb[alpha > 80]
    fill = np.median(ink, axis=0) if len(ink) else np.array(INK_NOTE)
    out = a.copy()
    grow = (new_a > 80) & (alpha <= 80)
    out[grow, :3] = fill
    out[:, :, 3] = new_a
    return Image.fromarray(out, "RGBA")


def spr_stroke(spr, t=80):
    dark = np.array(spr)[:, :, 3] > t
    widths = []
    for col in range(dark.shape[1]):
        m = c = 0
        for v in dark[:, col]:
            c = c + 1 if v else 0
            m = max(m, c)
        if m:
            widths.append(m)
    return float(np.median(widths)) if widths else 0


def thicken_to(spr, target, max_iter=5):
    """Dilate until median vertical run matches a native brush glyph."""
    best = spr
    for i in range(0, max_iter + 1):
        cur = thicken(spr, i)
        best = cur
        if spr_stroke(cur) >= target:
            return cur
    return best


def cap_w(spr, max_w):
    if spr.size[0] <= max_w:
        return spr
    return spr.resize((int(max_w), spr.size[1]), Image.Resampling.LANCZOS)


def reink(spr, ink=INK_NOTE):
    """Keep harvested alpha, force charcoal so light/ghosted glyphs match neighbors."""
    a = np.array(spr)
    a[:, :, 0] = ink[0]
    a[:, :, 1] = ink[1]
    a[:, :, 2] = ink[2]
    return Image.fromarray(a)


def soften(spr, radius=0.4):
    """Slight alpha blur so synthesized glyphs pick up felt-pen bleed, not print edges."""
    a = np.array(spr)
    a[:, :, 3] = np.array(
        Image.fromarray(a[:, :, 3]).filter(ImageFilter.GaussianBlur(radius))
    )
    return Image.fromarray(a, "RGBA")


def note_sprite(text, h, ink=INK_NOTE, max_w=None):
    """Thin notes-hand stand-in (only for missing/wrong glyphs next to native ink)."""
    spr = font_sprite(text, int(h), ink=ink, up=10, stroke=0, font_path=WK)
    # 一 and other flat strokes must not be scale_to_h'd (height ~2px → huge width).
    if spr.size[1] >= max(6, int(h * 0.55)):
        spr = scale_to_h(spr, int(h))
    cap = max_w if max_w else int(h * max(1, len(text)) * 1.4)
    if spr.size[0] > cap:
        spr = cap_w(spr, cap)
    return soften(crisp_ink(spr, lo=48, hi=145), 0.35)


def font_sprite(text, px, ink=INK_NOTE, up=4, dilate=0, stroke=0, font_path=None):
    """Render Hanzi that do not exist on the sketch. Default MaShan for 邵 only."""
    font = ImageFont.truetype(str(font_path or MS), int(px * up))
    dummy = Image.new("L", (8, 8))
    d = ImageDraw.Draw(dummy)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font, stroke_width=stroke)
    w, h = x1 - x0 + 12, y1 - y0 + 12
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text(
        (6 - x0, 6 - y0), text, font=font, fill=255,
        stroke_width=stroke, stroke_fill=255,
    )
    a = np.array(im)
    if dilate:
        a = cv2.dilate(a, np.ones((3, 3), np.uint8), iterations=dilate)
    ys, xs = np.where(a > 18)
    a = a[int(ys.min()): int(ys.max()) + 1, int(xs.min()): int(xs.max()) + 1]
    tw = max(1, int(round(a.shape[1] / up)))
    th = max(1, int(round(a.shape[0] / up)))
    a = np.array(Image.fromarray(a).resize((tw, th), Image.Resampling.LANCZOS))
    rgba = np.zeros((th, tw, 4), np.uint8)
    rgba[:, :, 0] = ink[0]
    rgba[:, :, 1] = ink[1]
    rgba[:, :, 2] = ink[2]
    rgba[:, :, 3] = a
    return Image.fromarray(rgba, "RGBA")


def crisp_ink(spr, lo=70, hi=130):
    """Drop LANCZOS halo so leftover paper/ink cannot read as a second glyph."""
    a = np.array(spr)
    al = a[:, :, 3].astype(np.int16)
    a[:, :, 3] = np.where(al < lo, 0, np.where(al > hi, 255, al)).astype(np.uint8)
    return Image.fromarray(a)


def fill_from_sample(arr, box, sample, src):
    """Cover a rectangle with tiled paper from a clean patch (keeps texture)."""
    x0, y0, x1, y1 = [int(v) for v in box]
    sx0, sy0, sx1, sy1 = [int(v) for v in sample]
    tile = src[sy0:sy1, sx0:sx1]
    h, w = y1 - y0, x1 - x0
    ny = int(np.ceil(h / tile.shape[0]))
    nx = int(np.ceil(w / tile.shape[1]))
    big = np.tile(tile, (ny, nx, 1))[:h, :w]
    noise = RNG.normal(0, 1.5, big.shape)
    arr[y0:y1, x0:x1] = np.clip(big.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def main():
    shutil.copy(BACKUP, OUT)
    b = load_rgb(BACKUP)

    bath = sprite(b, (400, 492, 485, 552))
    s678 = sprite(b, (74, 582, 162, 600))
    qi = sprite(b, (97, 580, 114, 602))
    shi = sprite(b, (581, 400, 606, 432))
    tang = sprite(b, (608, 400, 633, 432))
    gong = sprite(b, (863, 316, 887, 344), hatch_guard=True)
    di = sprite(b, (888, 316, 912, 344), hatch_guard=True)

    arr = b.copy()
    erase_ink(arr, (392, 488, 492, 558), thresh=140, inflate=2)

    # 11/12: wipe leftover 应用 in the name band. Restore hairlines from
    # the clean gap so we do not recopy ghost tops/bottoms from backup.
    gap_paper = np.median(b[882:898, 828:846].reshape(-1, 3), axis=0)
    fill_solid(arr, (728, 878, 818, 906), gap_paper, std=2)
    fill_solid(arr, (862, 878, 978, 906), gap_paper, std=2)
    def restore_rules(x0, x1):
        for y0, y1 in ((876, 879), (906, 909)):
            tile = b[y0:y1, 820:846]
            w = x1 - x0
            nx = int(np.ceil(w / tile.shape[1]))
            arr[y0:y1, x0:x1] = np.tile(tile, (1, nx, 1))[:, :w]
    restore_rules(728, 818)
    restore_rules(862, 978)

    # ②: keep native 工大 (ends ~1142). Wipe 报… on paper from the empty
    # notes margin — not from the tail that still has 部.
    wipe_to_paper(arr, (1143, 444, 1220, 472), (1194, 448, 1210, 466), b, thresh=175, inflate=4)

    inpaint_ink(arr, (1158, 334, 1188, 370), thresh=155, inflate=3)  # 部 → 邵

    # 建议: wipe L1+L2 all the way to the right rule. Paper from the
    # cream gap between L1 and L2 (no letters). Do not restore backup
    # text into this band — that put 名称/准生活 back under the new ink.
    # Keep native 1. 2., inner rule, L3 (y≥210), and the box rules.
    wipe_to_paper(arr, (738, 154, 876, 208), (748, 177, 762, 183), b, thresh=175, inflate=4)
    arr[150:154, 694:880] = b[150:154, 694:880]
    arr[234:241, 694:880] = b[234:241, 694:880]
    arr[150:241, 693:698] = b[150:241, 693:698]
    arr[210:236, 698:875] = b[210:236, 698:875]  # native line 3 only
    arr[150:241, 877:880] = b[150:241, 877:880]  # right rule only

    # ①: drop 没/设 and close the gap so it reads 主楼有收发室（二楼）
    erase_ink(arr, (1144, 412, 1166, 442), thresh=150, inflate=2)
    you_band = arr[412:442, 1166:1288].copy()
    paper1 = np.median(b[448:468, 1220:1240].reshape(-1, 3), axis=0)
    fill_solid(arr, (1144, 412, 1334, 442), paper1, std=1.4)
    arr[412:442, 1082:1144] = b[412:442, 1082:1144]
    arr[412:442, 1146:1146 + you_band.shape[1]] = you_band
    arr[412:442, 1336:1340] = b[412:442, 1336:1340]
    # ④: wipe the whole garbled line after the circle. Paper from the
    # empty margin before the right border, not from the 债务 tail.
    wipe_to_paper(arr, (1104, 494, 1335, 532), (1322, 508, 1334, 522), b, thresh=175, inflate=4)
    arr[494:532, 1088:1105] = b[494:532, 1088:1105]
    arr[494:532, 1336:1340] = b[494:532, 1336:1340]

    im = Image.fromarray(arr)

    gong_s = scale_to_h(gong, 22)
    di_s = scale_to_h(di, 22)
    im.paste(gong_s, (385, 400), gong_s)
    im.paste(di_s, (434, 400), di_s)

    bath_s = scale_to_h(bath, 48)
    paste_center(im, bath_s, (390, 688, 700, 788))

    d678 = scale_to_w(s678, 92)
    paste_center(im, d678, (386, 480, 498, 564))

    seven = join_h([qi, shi, tang], gap=1, h=17)
    paste_center(im, seven, (532, 446, 651, 466))

    # 11. 应用物理 / 12. 应用数学 — harvest at thresh 128 so 应 isn't gappy,
    # then reink so leftover gray 应用 cannot show through.
    yy = reink(sprite(b, (732, 878, 770, 904), thresh=128))
    sx = reink(sprite(b, (772, 878, 814, 904), thresh=128))
    wl = reink(sprite(b, (916, 878, 962, 904), thresh=128))
    n11 = join_h([yy, wl], gap=2, h=20)
    n12 = join_h([yy, sx], gap=2, h=20)
    im.paste(n11, (730, 881), n11)
    im.paste(n12, (864, 881), n12)
    save_dbg(n11, "f-n11.png")
    save_dbg(n12, "f-n12.png")
    print("11/12", n11.size, n12.size)

    # ② 工大俱乐部 — handwritten 俱乐部 (not WenKai, not ③'s 餐).
    sheet = load_rgb(SHEET)
    club = sheet_line(sheet, 779, 876)
    club = cap_w(scale_to_h(club, 20), 52)
    club = thicken(crisp_ink(club, lo=40, hi=150), 1)
    club = soften(club, 0.35)
    im.paste(club, (1144, 447), club)
    save_dbg(club, "f-club2.png")
    print("② club", club.size)

    # 邵 — MaShan 召+阝, no dilate (dilate → 部), end before 逸 at 1188
    shao = font_sprite("邵", 28, ink=INK_SHAW, up=12, stroke=0)
    shao = shao.resize((22, 31), Image.Resampling.LANCZOS)
    shao = soften(shao, 0.5)
    im.paste(shao, (1164, 336), shao)
    save_dbg(shao, "f-shao.png")
    print("邵", shao.size)

    # 建议: native 1. / 2. stay; both lines from the handwritten sheet.
    sug1 = sheet_line(sheet, 138, 248)
    sug2 = sheet_line(sheet, 352, 454)
    sug1 = cap_w(scale_to_h(sug1, 19), 132)
    sug2 = cap_w(scale_to_h(sug2, 16), 132)
    sug1 = thicken(crisp_ink(sug1, lo=40, hi=150), 1)
    sug2 = thicken(crisp_ink(sug2, lo=40, hi=150), 1)
    sug1 = soften(sug1, 0.35)
    sug2 = soften(sug2, 0.35)
    im.paste(sug1, (742, 155), sug1)
    im.paste(sug2, (742, 181), sug2)
    save_dbg(sug1, "f-sug1.png")
    save_dbg(sug2, "f-sug2.png")
    print("sug1", sug1.size, "sug2", sug2.size)

    # ④ full line after the circle — handwritten, includes 三 and 楼为.
    note4 = sheet_line(sheet, 564, 668)
    note4 = cap_w(scale_to_h(note4, 18), 224)
    note4 = thicken(crisp_ink(note4, lo=40, hi=150), 1)
    note4 = soften(note4, 0.35)
    im.paste(note4, (1106, 504), note4)
    save_dbg(note4, "f-note4.png")
    print("④", note4.size)

    im.save(OUT)
    print("wrote", OUT, im.size)
    r = np.array(im)
    Image.fromarray(r[330:415, 1140:1240]).save(DBG / "out-shaw.png")
    Image.fromarray(r[145:245, 650:890]).save(DBG / "out-sug.png")
    Image.fromarray(r[430:560, 1045:1340]).save(DBG / "out-notes.png")
    Image.fromarray(r[868:912, 690:1020]).save(DBG / "out-1112.png")
    Image.fromarray(r[340:570, 370:670]).save(DBG / "out-gym-cant.png")
    def zoom(src, name, k=3):
        Image.fromarray(src).resize((src.shape[1] * k, src.shape[0] * k), Image.Resampling.NEAREST).save(DBG / name)
    zoom(r[336:372, 1155:1240], "shaw-now.png")
    zoom(r[145:240, 650:890], "sug-now.png")
    zoom(r[412:442, 1080:1340], "n1-now.png")
    zoom(r[445:472, 1080:1210], "n2-now.png")
    zoom(r[498:532, 1084:1335], "n4-now.png")
    zoom(r[872:908, 868:990], "12-now.png")
    zoom(r[872:908, 698:822], "11-now.png")
    print("debug crops saved")


if __name__ == "__main__":
    main()
