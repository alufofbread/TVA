"""Aether identity. Drop an official logo into assets without changing renderers."""
from pathlib import Path
from PIL import Image, ImageOps
BASE_DIR = Path(__file__).resolve().parent

BRAND_NAME = "Aether Creator Network"
BRAND_SHORT = "AETHER"
BLUE = "#257BFF"
PINK = "#FF4FA3"
LOGO_PATH = BASE_DIR / "dashboard" / "assets" / "aether-logo.png"


def draw_brand(image, draw, x, y, w, h, framed=True):
    from dashboard.style import rounded, text
    if framed:
        rounded(draw, (x, y, x+w, y+h), 10, "#080A0D", BLUE)
    if LOGO_PATH.exists():
        with Image.open(LOGO_PATH) as source:
            logo = ImageOps.contain(source.convert("RGBA"), (w*2-16, h*2-16), Image.Resampling.LANCZOS)
        image.paste(logo, (x*2+(w*2-logo.width)//2, y*2+(h*2-logo.height)//2), logo)
    else:
        text(draw, (x+w//2, y+h//2-12), BRAND_SHORT, 13 if w < 110 else 18, BLUE, True, "ma")
        text(draw, (x+w//2, y+h//2+10), "ACN", 10, PINK, True, "ma")
