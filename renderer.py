"""
FIELD NOTES TYPEWRITER — STREAMLIT RENDERER

This is the SAME rendering engine as the working local V6.7 app.
The Streamlit interface is intentionally separate so the desktop version
remains untouched.
"""


import os
import json
import random
import textwrap
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter, ImageOps, ImageChops


# ============================================================
# 1. FROZEN PAGE GEOMETRY
# ============================================================

DPI = 300
PAGE_W_MM = 148.0
PAGE_H_MM = 210.0

CAP_HEIGHT_MM = 2.75
CHAR_PITCH_MM = 2.40
LINE_PITCH_MM = 8.00

LEFT_MM = 5.2
RIGHT_MM = 5.2
TOP_MM = 10.6
BOTTOM_MM = 12.0

PAPER = (248, 247, 241)
INK_RGB = (42, 40, 38)

PAPER_COLOURS = {
    "Ivory": (248, 247, 241),
    "Pale Yellow": (248, 242, 178),
    "Pale Blue": (216, 239, 240),
    "Pale Pink": (236, 181, 212),
    "Pale Green": (219, 238, 174),
}

TEMPLATES = {
    "A5 Field Note": {
        "width_mm": 148.0,
        "height_mm": 210.0,
        "left_mm": 5.2,
        "right_mm": 5.2,
        "top_mm": 10.6,
        "bottom_mm": 12.0,
        "cap_height_mm": 2.75,
        "char_pitch_mm": 2.40,
        "line_pitch_mm": 8.00,
    },
    "Square Note": {
        "width_mm": 100.0,
        "height_mm": 100.0,
        "left_mm": 7.0,
        "right_mm": 7.0,
        "top_mm": 10.0,
        "bottom_mm": 10.0,
        "cap_height_mm": 2.75,
        "char_pitch_mm": 2.40,
        "line_pitch_mm": 8.00,
    },
}


def mm_to_px(mm):
    return int(round(mm / 25.4 * DPI))


def template_geometry(template_name):
    cfg = TEMPLATES[template_name]
    return {
        "PAGE_W": mm_to_px(cfg["width_mm"]),
        "PAGE_H": mm_to_px(cfg["height_mm"]),
        "LEFT": mm_to_px(cfg["left_mm"]),
        "RIGHT": mm_to_px(cfg["right_mm"]),
        "TOP": mm_to_px(cfg["top_mm"]),
        "BOTTOM": mm_to_px(cfg["bottom_mm"]),
        "CAP_HEIGHT": mm_to_px(cfg["cap_height_mm"]),
        "CHAR_PITCH": mm_to_px(cfg["char_pitch_mm"]),
        "LINE_PITCH": mm_to_px(cfg["line_pitch_mm"]),
    }


_DEFAULT = template_geometry("A5 Field Note")
PAGE_W = _DEFAULT["PAGE_W"]
PAGE_H = _DEFAULT["PAGE_H"]
LEFT = _DEFAULT["LEFT"]
RIGHT = _DEFAULT["RIGHT"]
TOP = _DEFAULT["TOP"]
BOTTOM = _DEFAULT["BOTTOM"]
CAP_HEIGHT = _DEFAULT["CAP_HEIGHT"]
CHAR_PITCH = _DEFAULT["CHAR_PITCH"]
LINE_PITCH = _DEFAULT["LINE_PITCH"]


# ============================================================
# 2. LOAD REAL TYPEWRITER GLYPHS
# ============================================================

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
GLYPH_DIR = HERE / "typewriter_glyphs_v6"
MANIFEST_PATH = GLYPH_DIR / "manifest.json"

if not MANIFEST_PATH.exists():
    raise FileNotFoundError(
        "The real glyph library was not found.\n\n"
        "Keep the folder 'typewriter_glyphs_v6' in the same folder as this script."
    )

MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

SOURCE_PITCH = float(MANIFEST["source_pitch_px"])
SOURCE_CAP_HEIGHT = float(MANIFEST["source_cap_height_px"])
SOURCE_CAP_TOP = float(MANIFEST["source_cap_top_px"])

X_SCALE = CHAR_PITCH / SOURCE_PITCH
Y_SCALE = CAP_HEIGHT / SOURCE_CAP_HEIGHT

GLYPH_FILES = {
    ch: [GLYPH_DIR / rel for rel in paths]
    for ch, paths in MANIFEST["glyphs"].items()
}

PUNCTUATION_BASELINES = {
    ch: float(value)
    for ch, value in MANIFEST.get(
        "punctuation_source_baseline_px", {}
    ).items()
}

_GLYPH_CACHE = {}
_VARIANT_METRICS = {}

LOWERCASE_BASELINE_REFS = "abcdefhiklmnorstuvwxz"
UPPERCASE_BASELINE_REFS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGIT_BASELINE_REFS = "0123456789"


def _alpha_bbox(im):
    return im.getchannel("A").getbbox()


def _median(values):
    values = sorted(values)
    if not values:
        return SOURCE_CAP_TOP + SOURCE_CAP_HEIGHT
    n = len(values)
    if n % 2:
        return float(values[n // 2])
    return 0.5 * (values[n // 2 - 1] + values[n // 2])


def _group_for_char(ch):
    if ch.islower():
        return "lower"
    if ch.isupper():
        return "upper"
    if ch.isdigit():
        return "digit"
    return "other"


def _build_variant_metrics():
    """
    V6.2 baseline normalisation.

    Lowercase, uppercase and digits were typed on DIFFERENT calibration rows.
    V6.1 incorrectly allowed their separately-cropped row coordinates to share
    one baseline estimate. That can make mixed-case text look vertically wavy.

    Here each calibration family gets its own baseline for every repetition:
      lower-1 ... lower-5
      upper-1 ... upper-5
      digit-1 ... digit-5

    Every glyph is then placed on one common output carriage baseline.
    """
    groups = {
        "lower": LOWERCASE_BASELINE_REFS,
        "upper": UPPERCASE_BASELINE_REFS,
        "digit": DIGIT_BASELINE_REFS,
    }

    for group, refs in groups.items():
        available = [ch for ch in refs if ch in GLYPH_FILES]
        if not available:
            continue

        max_variants = max(len(GLYPH_FILES[ch]) for ch in available)

        for variant_index in range(max_variants):
            bottoms = []

            for ch in available:
                if variant_index >= len(GLYPH_FILES[ch]):
                    continue

                im = Image.open(GLYPH_FILES[ch][variant_index]).convert("RGBA")
                bbox = _alpha_bbox(im)
                if bbox:
                    bottoms.append(bbox[3] - 1)

            _VARIANT_METRICS[(group, variant_index)] = {
                "baseline": _median(bottoms)
            }


_build_variant_metrics()


def load_real_glyph(ch, variant_index):
    """
    Load one real scanned strike.

    Letters/numbers:
      normalize individual non-descending glyphs to the rigid carriage baseline.

    Real punctuation:
      preserve the punctuation row's physical vertical relationship to the
      baseline. This is important because a comma must descend below a period,
      quotes must sit high, and + / = should remain around mid-height.
    """
    key = (ch, variant_index)
    if key in _GLYPH_CACHE:
        return _GLYPH_CACHE[key]

    path = GLYPH_FILES[ch][variant_index]
    source = Image.open(path).convert("RGBA")
    bbox = _alpha_bbox(source)

    if ch in PUNCTUATION_BASELINES:
        source_baseline = PUNCTUATION_BASELINES[ch]

    else:
        group = _group_for_char(ch)

        if bbox:
            if group == "lower" and ch in "gjpqy":
                metric = _VARIANT_METRICS.get(
                    ("lower", variant_index),
                    {"baseline": SOURCE_CAP_TOP + SOURCE_CAP_HEIGHT}
                )
                source_baseline = metric["baseline"]
            else:
                source_baseline = float(bbox[3] - 1)
        else:
            source_baseline = SOURCE_CAP_TOP + SOURCE_CAP_HEIGHT

    new_w = max(1, int(round(source.width * X_SCALE)))
    new_h = max(1, int(round(source.height * Y_SCALE)))
    glyph = source.resize((new_w, new_h), Image.Resampling.LANCZOS)

    scaled_baseline = source_baseline * Y_SCALE

    _GLYPH_CACHE[key] = (glyph, scaled_baseline)
    return glyph, scaled_baseline


# ============================================================
# 3. DIGITAL FALLBACK ONLY FOR UNCALIBRATED PUNCTUATION
# ============================================================

def find_fallback_font():
    candidates = [
        r"C:\Windows\Fonts\cour.ttf",
        r"C:\Windows\Fonts\lucon.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/Library/Fonts/Courier New.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("No fallback monospaced font found.")


FALLBACK_FONT_PATH = find_fallback_font()


def visible_cap_height(size):
    f = ImageFont.truetype(FALLBACK_FONT_PATH, size)
    box = f.getbbox("H")
    return box[3] - box[1]


def calibrated_fallback_font():
    lo, hi = 8, 200
    while lo < hi:
        mid = (lo + hi) // 2
        if visible_cap_height(mid) < CAP_HEIGHT:
            lo = mid + 1
        else:
            hi = mid
    size = min([max(8, lo - 1), lo], key=lambda s: abs(visible_cap_height(s)-CAP_HEIGHT))
    return ImageFont.truetype(FALLBACK_FONT_PATH, size)


FALLBACK_FONT = calibrated_fallback_font()


# ============================================================
# 4. RIBBON / MACHINE MODEL
# ============================================================

def ribbon_profile(age):
    # Real scanned glyphs already contain genuine strike variation.
    # These values are deliberately gentler than V5.
    if age == "Fresh":
        return {"opacity": 1.06, "variation": 0.035}
    if age == "Used":
        return {"opacity": 0.95, "variation": 0.085}
    return {"opacity": 0.80, "variation": 0.135}


def imperfection_model(value):
    t = max(0.0, min(1.0, value / 100.0))
    soft = t ** 1.25
    strong = t ** 1.65

    return {
        "t": t,
        "line_start_mm": 0.06 + 0.48 * soft,
        "paragraph_extra_mm": 0.10 + 0.78 * strong,
        "extra_space_probability": 0.001 + 0.013 * strong,
        "sentence_space_bonus": 0.002 + 0.014 * strong,
        "major_light_probability": 0.006 + 0.035 * strong,
        "major_dark_probability": 0.004 + 0.026 * strong,
        "line_ink_range": 0.02 + 0.08 * soft,
        "rebound_probability": 0.0005 + 0.010 * strong,
    }


def vary_glyph_opacity(glyph, multiplier):
    if abs(multiplier - 1.0) < 0.001:
        return glyph

    out = glyph.copy()
    a = out.getchannel("A")
    a = a.point(lambda p: max(0, min(255, int(p * multiplier))))
    out.putalpha(a)
    return out


# ============================================================
# 5. TEXT WRAPPING
# ============================================================

def wrap_fixed(text, max_chars):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []

    for raw in text.split("\n"):
        if raw == "":
            lines.append("")
            continue

        wrapped = textwrap.wrap(
            raw,
            width=max_chars,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=True,
        )
        lines.extend(wrapped or [""])

    return lines


# ============================================================
# 6. RENDERING
# ============================================================

def draw_fallback_char(layer, ch, x, y, opacity):
    bbox = FALLBACK_FONT.getbbox(ch)
    pad = 5
    w = max(1, bbox[2]-bbox[0] + pad*2)
    h = max(1, bbox[3]-bbox[1] + pad*2)

    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.text((pad-bbox[0], pad-bbox[1]), ch, font=FALLBACK_FONT, fill=int(255*opacity))

    rgba = Image.new("RGBA", mask.size, (*INK_RGB, 0))
    rgba.putalpha(mask)

    layer.alpha_composite(
        rgba,
        dest=(int(x + bbox[0] - pad), int(y + bbox[1] - pad))
    )


def render_page(lines, ribbon_age, imperfections, seed, template_name="A5 Field Note", paper_name="Ivory", paper_style="Plain"):
    rng = random.Random(seed)
    ribbon = ribbon_profile(ribbon_age)
    model = imperfection_model(imperfections)

    geom = template_geometry(template_name)
    page_w = geom["PAGE_W"]
    page_h = geom["PAGE_H"]
    left = geom["LEFT"]
    top = geom["TOP"]
    char_pitch = geom["CHAR_PITCH"]
    line_pitch = geom["LINE_PITCH"]

    paper_rgb = PAPER_COLOURS.get(paper_name, PAPER_COLOURS["Ivory"])
    page = Image.new("RGB", (page_w, page_h), paper_rgb)

    # very restrained paper texture
    pd = ImageDraw.Draw(page)
    for _ in range(220):
        px = rng.randrange(page_w)
        py = rng.randrange(page_h)
        delta = rng.choice([-2, -1, 1])
        pd.point((px, py), fill=tuple(max(0, min(255, c+delta)) for c in paper_rgb))


    # Optional stationery styles. Kept intentionally faint so the typewriter
    # remains the dominant visual element.
    if paper_style != "Plain":
        pd = ImageDraw.Draw(page)
        if paper_style == "Faint Ruled":
            rule = tuple(max(0, c - 22) for c in paper_rgb)
            step = mm_to_px(8.0)
            y0 = top + mm_to_px(1.6)
            for yy in range(y0, page_h - geom["BOTTOM"], step):
                pd.line((geom["LEFT"], yy, page_w - geom["RIGHT"], yy), fill=rule, width=1)

        elif paper_style == "Graph":
            rule = tuple(max(0, c - 18) for c in paper_rgb)
            step = mm_to_px(5.0)
            for xx in range(geom["LEFT"], page_w - geom["RIGHT"] + 1, step):
                pd.line((xx, geom["TOP"] // 2, xx, page_h - geom["BOTTOM"] // 2), fill=rule, width=1)
            for yy in range(geom["TOP"] // 2, page_h - geom["BOTTOM"] // 2 + 1, step):
                pd.line((geom["LEFT"] // 2, yy, page_w - geom["RIGHT"] // 2, yy), fill=rule, width=1)

        elif paper_style == "Dotted":
            dot = tuple(max(0, c - 26) for c in paper_rgb)
            step = mm_to_px(5.0)
            radius = max(1, mm_to_px(0.10))
            for yy in range(geom["TOP"] // 2, page_h - geom["BOTTOM"] // 2, step):
                for xx in range(geom["LEFT"] // 2, page_w - geom["RIGHT"] // 2, step):
                    pd.ellipse((xx-radius, yy-radius, xx+radius, yy+radius), fill=dot)

    ink = Image.new("RGBA", page.size, (255, 255, 255, 0))
    previous_blank = True

    # Fixed mechanical carriage baseline. Every non-descending glyph is
    # individually normalized to this line; descenders retain their tails.
    target_baseline_offset = 8 + CAP_HEIGHT

    for line_no, line in enumerate(lines):
        y = top + line_no * line_pitch

        paragraph_start = previous_blank and line.strip() != ""
        drift_mm = model["line_start_mm"]
        if paragraph_start:
            drift_mm += model["paragraph_extra_mm"]

        x = left + mm_to_px(rng.uniform(-drift_mm, drift_mm))

        line_multiplier = (
            ribbon["opacity"]
            * rng.uniform(
                1.0 - model["line_ink_range"],
                1.0 + model["line_ink_range"]
            )
        )

        previous_char = ""

        for ch in line:
            if ch != " ":
                strike_multiplier = line_multiplier * rng.gauss(1.0, ribbon["variation"])

                if rng.random() < model["major_light_probability"]:
                    strike_multiplier *= rng.uniform(0.48, 0.72)

                if rng.random() < model["major_dark_probability"]:
                    strike_multiplier *= rng.uniform(1.18, 1.48)

                if ch in GLYPH_FILES:
                    variants = GLYPH_FILES[ch]
                    idx = rng.randrange(len(variants))
                    glyph, glyph_baseline = load_real_glyph(ch, idx)

                    strike_multiplier = max(0.34, min(1.45, strike_multiplier))
                    glyph = vary_glyph_opacity(glyph, strike_multiplier)

                    # Horizontal position still follows the fixed carriage cell.
                    gx = int(round(x + (char_pitch - glyph.width) / 2))

                    # Crucially, vertical position is BASELINE-anchored rather
                    # than top-of-scan-cell anchored.
                    gy = int(round(
                        y + target_baseline_offset - glyph_baseline
                    ))

                    ink.alpha_composite(glyph, dest=(gx, gy))

                    if rng.random() < model["rebound_probability"]:
                        ghost = vary_glyph_opacity(glyph, 0.18)
                        ink.alpha_composite(
                            ghost,
                            dest=(gx + rng.choice([-1, 1]), gy)
                        )
                else:
                    draw_fallback_char(
                        ink,
                        ch,
                        x,
                        y,
                        max(0.35, min(1.0, strike_multiplier))
                    )

            advance = char_pitch

            if ch == " ":
                p = model["extra_space_probability"]
                if previous_char in ".!?":
                    p += model["sentence_space_bonus"]

                if rng.random() < p:
                    advance += int(round(char_pitch * rng.choice([0.35, 0.55, 0.80])))

            x += advance
            previous_char = ch

        previous_blank = line.strip() == ""

    return Image.alpha_composite(page.convert("RGBA"), ink).convert("RGB")

# ============================================================
# 7. OPTIONAL MIXED-MEDIA IMAGE OVERLAYS
# ============================================================

def _soft_grain(image, rng, amount=5, density=0.085):
    """Very light analog-looking grain."""
    img = image.convert("RGB")
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            if rng.random() < density:
                r, g, b = px[x, y]
                delta = rng.randint(-amount, amount)
                px[x, y] = (
                    max(0, min(255, r + delta)),
                    max(0, min(255, g + delta)),
                    max(0, min(255, b + delta)),
                )
    return img


def _square_crop(photo):
    img = ImageOps.exif_transpose(photo.convert("RGB"))
    side = min(img.width, img.height)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    return img.crop((left, top, left + side, top + side))


def _develop_photo(photo, mode, rng):
    """Restrained instant-film treatment."""
    img = _square_crop(photo)

    if mode == "B&W":
        img = ImageOps.grayscale(img).convert("RGB")
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.84, 0.96))
        img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.96, 1.02))
    else:
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.86, 0.96))
        img = ImageEnhance.Color(img).enhance(rng.uniform(0.84, 0.96))
        img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.97, 1.03))
        px = img.load()
        warm = rng.randint(0, 5)
        cool = rng.randint(-4, 1)
        for yy in range(img.height):
            for xx in range(img.width):
                r, g, b = px[xx, yy]
                px[xx, yy] = (
                    max(0, min(255, r + warm)),
                    g,
                    max(0, min(255, b + cool)),
                )

    return _soft_grain(img, rng, amount=5, density=0.10)


def _add_surface_scratches(img, rng, strength=1.0):
    """Fine wear rather than a heavy vintage filter."""
    out = img.convert("RGBA")
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    count = max(3, int(9 * strength))
    for _ in range(count):
        x1 = rng.randrange(out.width)
        y1 = rng.randrange(out.height)
        length = rng.randint(max(8, out.width // 18), max(12, out.width // 5))
        angle = rng.uniform(-0.18, 0.18)
        x2 = max(0, min(out.width - 1, int(x1 + length)))
        y2 = max(0, min(out.height - 1, int(y1 + length * angle)))
        alpha = rng.randint(10, 28)
        d.line((x1, y1, x2, y2), fill=(246, 243, 232, alpha), width=rng.choice([1, 1, 2]))

    return Image.alpha_composite(out, layer)


def make_instant_print(photo_path, mode, width_px, rng):
    """
    A more physical-looking instant print:
    subtle aged frame, edge handling, slight print fade and fine scratches.
    """
    photo = Image.open(photo_path)
    developed = _develop_photo(photo, mode, rng)

    outer_w = max(120, int(width_px))
    outer_h = int(round(outer_w * 107 / 88))
    image_size = int(round(outer_w * 79 / 88))

    side = max(4, (outer_w - image_size) // 2)
    top = side

    frame_base = rng.choice([
        (242, 239, 228, 255),
        (245, 242, 233, 255),
        (239, 237, 229, 255),
    ])
    frame = Image.new("RGBA", (outer_w, outer_h), frame_base)
    fd = ImageDraw.Draw(frame)

    # Paper mottling / handling.
    specks = max(100, outer_w)
    for _ in range(specks):
        x = rng.randrange(outer_w)
        y = rng.randrange(outer_h)
        delta = rng.randint(-8, 5)
        c = tuple(max(0, min(255, v + delta)) for v in frame_base[:3])
        fd.point((x, y), fill=(*c, rng.randint(35, 90)))

    # Slightly dirty edges, especially corners.
    edge = max(3, int(outer_w * 0.012))
    for _ in range(max(20, outer_w // 10)):
        x = rng.choice([rng.randrange(0, edge*2), rng.randrange(max(1, outer_w-edge*2), outer_w)])
        y = rng.randrange(outer_h)
        shade = rng.randint(210, 234)
        fd.ellipse((x, y, x+rng.randint(1,3), y+rng.randint(1,3)), fill=(shade, shade-2, shade-8, rng.randint(20,60)))

    developed = developed.resize((image_size, image_size), Image.Resampling.LANCZOS)
    developed = _add_surface_scratches(developed, rng, 0.8)

    # Soft edge-development fade.
    dev = developed.convert("RGBA")
    fade = Image.new("L", (image_size, image_size), 255)
    fp = fade.load()
    edge_px = max(5, int(image_size * 0.035))
    strength = rng.randint(14, 34)
    for yy in range(image_size):
        for xx in range(image_size):
            dist = min(xx, yy, image_size - 1 - xx, image_size - 1 - yy)
            if dist < edge_px:
                factor = dist / edge_px
                fp[xx, yy] = int(255 - strength * (1.0 - factor))

    faded = Image.composite(dev, Image.new("RGBA", dev.size, frame_base), fade)
    frame.alpha_composite(faded, dest=(side, top))

    # Occasional faint development/wear marks.
    if rng.random() < 0.45:
        marks = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        md = ImageDraw.Draw(marks)
        for _ in range(rng.randint(1, 3)):
            x = rng.randint(side, side + image_size)
            y = rng.randint(top, top + image_size)
            r = rng.randint(3, max(4, image_size // 22))
            md.ellipse((x-r, y-r, x+r, y+r), fill=(236, 230, 213, rng.randint(8, 20)))
        marks = marks.filter(ImageFilter.GaussianBlur(radius=1.8))
        frame = Image.alpha_composite(frame, marks)

    # Tiny softened corners.
    corner = max(2, int(outer_w * 0.009))
    mask = Image.new("L", frame.size, 255)
    md = ImageDraw.Draw(mask)
    # just nick a few outer pixels rather than a perfect rounded rectangle
    if rng.random() < 0.7:
        md.rectangle((0, 0, corner, corner), fill=235)
        md.rectangle((outer_w-corner-1, outer_h-corner-1, outer_w-1, outer_h-1), fill=238)
    frame.putalpha(mask)
    return frame


def _thermal_dither(img, rng):
    img = ImageOps.grayscale(img)
    img = ImageEnhance.Contrast(img).enhance(1.18)
    img = ImageEnhance.Brightness(img).enhance(1.03)
    # Floyd-Steinberg monochrome gives genuine receipt-printer character.
    mono = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    # soften pure black very slightly
    return ImageOps.colorize(mono, black=(42, 42, 40), white=(242, 241, 235)).convert("RGB")


def make_thermal_print(photo_path, mode, width_px, rng):
    """
    Receipt/thermal image strip with slight fade, uneven edge and thermal dots.
    """
    photo = Image.open(photo_path)
    img = _square_crop(photo)
    size = max(100, int(width_px * 0.86))
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    img = _thermal_dither(img, rng)

    margin = max(8, int(width_px * 0.08))
    lower = max(18, int(width_px * 0.15))
    outer_w = size + margin * 2
    outer_h = size + margin + lower
    paper = (244, 243, 237, 255)
    receipt = Image.new("RGBA", (outer_w, outer_h), paper)
    receipt.alpha_composite(img.convert("RGBA"), dest=(margin, margin))

    # Faint horizontal print bands.
    d = ImageDraw.Draw(receipt)
    for yy in range(margin, margin + size, rng.randint(9, 14)):
        if rng.random() < 0.30:
            d.line((margin, yy, margin+size, yy), fill=(255,255,255,rng.randint(12,28)), width=1)

    # Small paper mottling.
    for _ in range(max(50, outer_w // 2)):
        x = rng.randrange(outer_w)
        y = rng.randrange(outer_h)
        shade = rng.randint(228, 248)
        d.point((x, y), fill=(shade, shade, shade-2, rng.randint(25,65)))

    return receipt


def make_dot_matrix_print(photo_path, mode, width_px, rng):
    """
    Dot-matrix/continuous-feed image: coarse ordered dots on a pale paper strip
    with tractor-feed holes.
    """
    photo = Image.open(photo_path)
    img = _square_crop(photo)
    target = max(100, int(width_px * 0.82))
    img = ImageOps.grayscale(img.resize((target, target), Image.Resampling.LANCZOS))
    img = ImageEnhance.Contrast(img).enhance(1.12)

    # Build a dot screen from sampled tonal blocks.
    cell = max(3, target // 115)
    matrix = Image.new("RGBA", (target, target), (229, 236, 234, 255))
    md = ImageDraw.Draw(matrix)
    pix = img.load()
    ink = (67, 82, 84, 225)

    for y in range(0, target, cell):
        for x in range(0, target, cell):
            tone = pix[min(x, target-1), min(y, target-1)]
            darkness = 1.0 - tone / 255.0
            if darkness > rng.uniform(0.16, 0.28):
                r = max(1, int((cell * 0.46) * min(1.0, darkness * 1.35)))
                cx = x + cell // 2
                cy = y + cell // 2
                md.ellipse((cx-r, cy-r, cx+r, cy+r), fill=ink)

    side = max(18, int(width_px * 0.10))
    top = max(10, int(width_px * 0.05))
    outer_w = target + side * 2
    outer_h = target + top * 2
    paper = Image.new("RGBA", (outer_w, outer_h), (222, 232, 232, 255))
    paper.alpha_composite(matrix, dest=(side, top))
    pd = ImageDraw.Draw(paper)

    # Tractor-feed holes.
    hole_r = max(3, int(side * 0.22))
    hole_step = max(hole_r * 4, int(target / 9))
    for yy in range(top, outer_h-top+1, hole_step):
        for xx in (side // 2, outer_w - side // 2):
            pd.ellipse((xx-hole_r, yy-hole_r, xx+hole_r, yy+hole_r), fill=(247,247,242,255), outline=(190,198,198,255))

    # A few faint horizontal feed marks.
    for yy in range(top, top + target, max(12, cell * 6)):
        if rng.random() < 0.25:
            pd.line((side, yy, side+target, yy), fill=(184,199,199,45), width=1)

    return paper


def _photo_position(page_w, page_h, print_w, print_h, position, text_lines, geom, rng):
    margin = mm_to_px(7.0)
    positions = {
        "Top Left": (margin, margin),
        "Top Right": (page_w - print_w - margin, margin),
        "Bottom Left": (margin, page_h - print_h - margin),
        "Bottom Right": (page_w - print_w - margin, page_h - print_h - margin),
    }
    if position != "Auto":
        return positions[position]

    typed_bottom = geom["TOP"] + max(1, len(text_lines)) * geom["LINE_PITCH"]
    bottom_y = page_h - print_h - margin
    if typed_bottom < bottom_y - mm_to_px(4):
        return positions["Bottom Right"]
    if typed_bottom > page_h * 0.58:
        return positions["Top Right"]
    return rng.choice([positions["Bottom Left"], positions["Bottom Right"]])


def add_mixed_media_photo(page, photo_path, mode, style, position, template_name, text_lines, seed):
    if not photo_path:
        return page

    rng = random.Random(seed + 99173)
    geom = template_geometry(template_name)
    width_mm = 58.0 if template_name == "A5 Field Note" else 44.0
    width_px = mm_to_px(width_mm)

    if style == "Thermal":
        obj = make_thermal_print(photo_path, mode, width_px, rng)
        angle = rng.uniform(-1.0, 1.0)
    elif style == "Dot-Matrix":
        obj = make_dot_matrix_print(photo_path, mode, width_px, rng)
        angle = rng.uniform(-0.8, 0.8)
    else:
        obj = make_instant_print(photo_path, mode, width_px, rng)
        angle = rng.uniform(-2.0, 2.0)

    rotated = obj.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

    # Physical contact shadow, lighter for thin printer paper.
    alpha = 24 if style in ("Thermal", "Dot-Matrix") else 38
    shadow_pad = max(5, mm_to_px(1.4))
    shadow = Image.new("RGBA", (rotated.width + shadow_pad*2, rotated.height + shadow_pad*2), (0,0,0,0))
    sd = ImageDraw.Draw(shadow)
    sd.rectangle(
        (shadow_pad+2, shadow_pad+3, shadow_pad+rotated.width+2, shadow_pad+rotated.height+3),
        fill=(0,0,0,alpha)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=3.6))

    x, y = _photo_position(page.width, page.height, rotated.width, rotated.height, position, text_lines, geom, rng)
    out = page.convert("RGBA")
    out.alpha_composite(shadow, dest=(x-shadow_pad, y-shadow_pad))
    out.alpha_composite(rotated, dest=(x, y))
    return out.convert("RGB")


def _trim_transparent_or_white(img):
    """Crop empty/near-white space around a scanned stamp."""
    rgba = ImageOps.exif_transpose(img.convert("RGBA"))
    bg = Image.new("RGBA", rgba.size, (255,255,255,255))
    diff = ImageChops.difference(rgba, bg).convert("L")
    # Include faint stamp ink while ignoring scanner-white.
    diff = diff.point(lambda p: 255 if p > 18 else 0)
    bbox = diff.getbbox()
    return rgba.crop(bbox) if bbox else rgba


def add_stamp_overlay(page, stamp_path, position, template_name, seed):
    """
    Overlay the user's actual scanned stamp. White scanner background is made
    transparent; placement/rotation/opactity vary slightly each generation.
    """
    if not stamp_path:
        return page

    rng = random.Random(seed + 77117)
    raw = Image.open(stamp_path).convert("RGBA")

    # Remove near-white background without changing the real stamp colour.
    data = raw.getdata()
    cleaned = []
    for r, g, b, a in data:
        whiteness = min(r, g, b)
        if whiteness > 235 and max(r,g,b) - min(r,g,b) < 18:
            alpha = int(max(0, 255 - (whiteness - 225) * 8))
            cleaned.append((r,g,b,min(a,alpha)))
        else:
            cleaned.append((r,g,b,a))
    raw.putdata(cleaned)

    bbox = raw.getbbox()
    if bbox:
        raw = raw.crop(bbox)

    geom = template_geometry(template_name)
    target_mm = 40.0 if template_name == "A5 Field Note" else 30.0
    target_w = mm_to_px(target_mm)
    scale = target_w / max(1, raw.width)
    raw = raw.resize((target_w, max(1, int(raw.height * scale))), Image.Resampling.LANCZOS)

    # Mild missing-ink variation using opacity only; keep actual stamp character.
    alpha = raw.getchannel("A")
    alpha = ImageEnhance.Brightness(alpha).enhance(rng.uniform(0.72, 0.92))
    raw.putalpha(alpha)

    angle = rng.uniform(-8.0, 8.0)
    raw = raw.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

    margin = mm_to_px(6.0)
    positions = {
        "Bottom Left": (margin, page.height - raw.height - margin),
        "Bottom Right": (page.width - raw.width - margin, page.height - raw.height - margin),
        "Auto": (
            rng.choice([margin, page.width - raw.width - margin]),
            page.height - raw.height - margin
        )
    }
    x, y = positions.get(position, positions["Auto"])

    # Small haphazard shift.
    x += mm_to_px(rng.uniform(-1.8, 1.8))
    y += mm_to_px(rng.uniform(-1.2, 1.2))

    out = page.convert("RGBA")
    out.alpha_composite(raw, dest=(x, y))
    return out.convert("RGB")





def save_png_robust(image, path, dpi):
    """
    Save PNG defensively on Windows/OneDrive.
    """
    target = os.path.normpath(path)

    try:
        image.save(target, format="PNG", dpi=(dpi, dpi))
        return target
    except OSError as direct_error:
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            image.save(temp_path, format="PNG", dpi=(dpi, dpi))
            shutil.copyfile(temp_path, target)
            return target
        except Exception as fallback_error:
            raise OSError(
                "Could not save to:\n"
                + target
                + "\n\nDirect save error: "
                + str(direct_error)
                + "\nFallback copy error: "
                + str(fallback_error)
                + "\n\nTry saving to Downloads or Desktop instead of a OneDrive-synced folder."
            ) from fallback_error
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


# ============================================================
# 8. GUI
# ============================================================
