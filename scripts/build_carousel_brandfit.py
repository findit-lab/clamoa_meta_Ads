"""clamoa '브랜드 맞춤 협찬' 포지셔닝 캐러셀 빌더.

기존 비주얼 시스템 재현: 928x1152(4:5), 흑백 하이패션 배경 + 하단 다크 그라데이션,
좌상단 clamoa 로고(흰색), 우상단 라임 번호 배지, 볼드 고딕 헤드라인 + 서브카피,
라임 CTA 칩. 배경(흑백)은 그대로 두고 텍스트만 오버레이하므로 카피 수정 = 재실행만 하면 됨.

usage: python3 scripts/build_carousel_brandfit.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
BG = ROOT / "data/ad_creatives/bg2"
OUT = ROOT / "data/ad_creatives"
LOGO = ROOT / "data/logo/clamoa.png"

W, H = 928, 1152
LIME = (219, 250, 28)
WHITE = (255, 255, 255)
SUBGRAY = (216, 216, 216)
DARK = (17, 17, 17)
MARGIN = 64

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
def f(size, weight="bold"):
    idx = {"regular": 0, "medium": 2, "semibold": 4, "bold": 6}[weight]
    return ImageFont.truetype(FONT, size, index=idx)


def white_logo(target_w):
    logo = Image.open(LOGO).convert("RGBA")
    a = logo.split()[3]
    solid = Image.new("RGBA", logo.size, WHITE + (0,))
    solid.putalpha(a)
    r = target_w / logo.width
    return solid.resize((target_w, int(logo.height * r)), Image.LANCZOS)


def bg_canvas(name, top_crop=0.0, pre_top=0.0):
    """Crop source to 4:5, grayscale, add bottom + top gradients for legibility.

    pre_top: fraction of source height to drop from the top BEFORE the 4:5 crop
    (used to remove AI watermark-like text in the logo zone, e.g. s4 'VOGU').
    """
    im = Image.open(BG / name).convert("RGB")
    im = ImageOps.grayscale(im).convert("RGB")
    if pre_top:
        im = im.crop((0, int(im.height * pre_top), im.width, im.height))
    # crop to 4:5 (W/H = 0.8056). source 1536x2048 -> 0.75, so crop width.
    tw = int(im.height * W / H)
    if tw <= im.width:
        x0 = (im.width - tw) // 2
        im = im.crop((x0, 0, x0 + tw, im.height))
    else:
        th = int(im.width * H / W)
        y0 = int((im.height - th) * (0.5 + top_crop))
        im = im.crop((0, y0, im.width, y0 + th))
    im = im.resize((W, H), Image.LANCZOS)

    # bottom gradient (transparent top -> near black bottom)
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        t = max(0.0, (y - H * 0.40) / (H * 0.60))
        grad.putpixel((0, y), int(245 * (t ** 1.25)))
    grad = grad.resize((W, H))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    im = Image.composite(black, im, grad)

    # subtle top scrim for logo/number legibility
    top = Image.new("L", (1, H), 0)
    for y in range(H):
        t = max(0.0, 1 - y / (H * 0.22))
        top.putpixel((0, y), int(110 * t))
    top = top.resize((W, H))
    im = Image.composite(black, im, top)
    return im


def draw_lines(d, lines, font, x, y, fill, lh, tracking=0, stroke=0, anchor_bottom=False):
    """Draw multiline text. Returns total height. If anchor_bottom, y is bottom edge."""
    asc, desc = font.getmetrics()
    line_h = int((asc + desc) * lh)
    total = line_h * len(lines)
    yy = y - total if anchor_bottom else y
    for ln in lines:
        if tracking:
            cx = x
            for ch in ln:
                d.text((cx, yy), ch, font=font, fill=fill,
                       stroke_width=stroke, stroke_fill=fill)
                w = d.textlength(ch, font=font)
                cx += w + tracking
        else:
            d.text((cx := x, yy), ln, font=font, fill=fill,
                   stroke_width=stroke, stroke_fill=fill)
        yy += line_h
    return total


def chip(d, text, font, x, y, anchor_right=False):
    """Filled lime rounded CTA chip with dark text."""
    pad_x, pad_y = 26, 16
    tw = int(d.textlength(text, font=font))
    asc, desc = font.getmetrics()
    th = asc + desc
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    bx = x - bw if anchor_right else x
    d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=bh // 2, fill=LIME)
    d.text((bx + pad_x, y + pad_y - 2), text, font=font, fill=DARK)
    return bw, bh


SLIDES = [
    dict(out="bf_0_cover.png", bg="s0.png", num=None,
         eyebrow="패션 브랜드 협찬 마케팅",
         head=["아무 셀럽에게나", "협찬하고 계신가요?"],
         sub=None, cta="넘겨보기  →"),
    dict(out="bf_1_problem.png", bg="s4.png", num="01", pre_top=0.16,
         eyebrow=None,
         head=["유명하다고", "다 어울리진 않습니다"],
         sub=["브랜드와 맞지 않는 셀럽은", "노출만 남기고 매출은 남기지 못합니다"], cta=None),
    dict(out="bf_2_fit.png", bg="s2.png", num="02",
         eyebrow=None,
         head=["셀럽보다 중요한 건", "브랜드와의 ‘결’입니다"],
         sub=["무드 · 타깃 · 가격대까지 맞아야", "소비자가 ‘내 취향 브랜드’로 기억합니다"], cta=None),
    dict(out="bf_3_match.png", bg="s1.png", num="03",
         eyebrow=None,
         head=["clamoa는 브랜드에 맞는", "셀럽을 찾아냅니다"],
         sub=["수많은 셀럽 데이터를 분석해", "우리 브랜드와 어울리는 셀럽만 매칭합니다"], cta=None),
    dict(out="bf_4_cta.png", bg="s3.png", num=None,
         eyebrow="단순 협찬이 아닌, 브랜드 맞춤 협찬",
         head=["우리 브랜드에 어울리는", "셀럽을 찾아드립니다"],
         sub=["지금 무료로 셀럽 추천을 받아보세요"], cta="무료 상담 받기  →"),
]


def build(s):
    im = bg_canvas(s["bg"], s.get("top_crop", 0.0), s.get("pre_top", 0.0)).convert("RGBA")
    d = ImageDraw.Draw(im)

    # logo top-left
    logo = white_logo(168)
    im.alpha_composite(logo, (MARGIN, 52))

    # number badge top-right
    if s["num"]:
        nf = f(150, "bold")
        pf = f(26, "semibold")
        d.text((W - MARGIN, 66), "POINT", font=pf, fill=WHITE, anchor="ra")
        d.text((W - MARGIN + 6, 96), s["num"], font=nf, fill=LIME,
               anchor="ra", stroke_width=1, stroke_fill=LIME)

    d = ImageDraw.Draw(im)
    bottom = H - 92

    # CTA (cover: lime text bottom-right ; close: filled chip bottom-left)
    if s["cta"] and s["num"] is None and s["out"].endswith("cover.png"):
        cf = f(30, "bold")
        d.text((W - MARGIN, bottom), s["cta"], font=cf, fill=LIME, anchor="rs")

    # build bottom stack: [sub], head, [eyebrow]  (bottom-anchored, upward)
    y = bottom
    cta_chip_h = 0
    if s["cta"] and not s["out"].endswith("cover.png"):
        # reserve chip at very bottom; draw later
        cta_chip_h = 64
        y -= cta_chip_h + 18

    if s["sub"]:
        sf = f(31, "medium")
        h = draw_lines(d, s["sub"], sf, MARGIN, y, SUBGRAY, 1.32, anchor_bottom=True)
        y -= h + 22

    hf = f(64, "bold")
    h = draw_lines(d, s["head"], hf, MARGIN, y, WHITE, 1.20, stroke=1, anchor_bottom=True)
    y -= h + 18

    if s["eyebrow"]:
        ef = f(27, "semibold")
        sq = 20
        ey = y - (ef.getmetrics()[0] + ef.getmetrics()[1])
        d.rectangle([MARGIN, ey + 6, MARGIN + sq, ey + 6 + sq], fill=LIME)
        d.text((MARGIN + sq + 14, ey), s["eyebrow"], font=ef, fill=WHITE)

    # close CTA chip at bottom-left
    if s["cta"] and not s["out"].endswith("cover.png"):
        chip(d, s["cta"], f(29, "bold"), MARGIN, H - 92 - 60)

    im.convert("RGB").save(OUT / s["out"], quality=95)
    print("wrote", s["out"])


if __name__ == "__main__":
    for s in SLIDES:
        build(s)
