from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from config import BASE_DIR, INCENTIVE_REWARD

ROOT = Path(__file__).resolve().parent

LEAGUE_NAMES = {
    1: "Rookie",
    2: "Rookie",
    3: "Pro",
    4: "Pro",
    5: "All Star",
    6: "All Star",
    7: "Elite",
    8: "Elite",
    9: "Elite",
    10: "Elite",
}

LEAGUE_COLORS = {
    1: "#22C55E",
    2: "#4ADE80",
    3: "#38BDF8",
    4: "#2563EB",
    5: "#FACC15",
    6: "#F59E0B",
    7: "#EA580C",
    8: "#A78BFA",
    9: "#8B5CF6",
    10: "#6D28D9",
}

COLORS = {
    "bg": "#050607",
    "panel": "#111315",
    "panel_alt": "#0C0E10",
    "border": "#22262A",
    "muted": "#77808A",
    "text": "#F8FAFC",
    "subtext": "#B8C2CC",
    "gold": "#F4C430",
    "green": "#24D366",
    "yellow": "#FFB020",
    "red": "#FF4D5E",
    "blue": "#257BFF",
    "cyan": "#00B8D9",
    "purple": "#8B5CF6",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        str(ROOT / "assets" / "fonts" / ("Inter-Bold.ttf" if bold else "Inter-Regular.ttf")),
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def canvas(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    scale = 2
    image = Image.new("RGB", (width * scale, height * scale), COLORS["bg"])
    return image, ImageDraw.Draw(image)


def downsample(image: Image.Image) -> Image.Image:
    return image.resize((image.width // 2, image.height // 2), Image.Resampling.LANCZOS)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: str, outline: str | None = None, width: int = 1) -> None:
    box = tuple(v * 2 for v in box)
    draw.rounded_rectangle(box, radius=radius * 2, fill=fill, outline=outline, width=width * 2)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int, fill: str, bold: bool = False, anchor: str | None = None) -> None:
    draw.text((xy[0] * 2, xy[1] * 2), value, font=font(size * 2, bold), fill=fill, anchor=anchor)


def line(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], fill: str, width: int = 1) -> None:
    draw.line(tuple(v * 2 for v in xy), fill=fill, width=width * 2)


def fasttrack_logo_path() -> Path | None:
    for logo_path in (ROOT / "assets" / "fasttrack_logo.png", ROOT / "assets" / "logo.png"):
        if not logo_path.exists():
            continue
        try:
            with Image.open(logo_path) as source:
                if source.width > 1 and source.height > 1:
                    return logo_path
        except OSError:
            continue
    return None


def draw_fasttrack_logo(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    framed: bool = True,
) -> None:
    if framed:
        rounded(draw, (x, y, x + w, y + h), 10, "#080A0D", COLORS["border"])

    logo_path = fasttrack_logo_path()
    if logo_path:
        with Image.open(logo_path) as source:
            padding = 10 if min(w, h) <= 90 else 14
            logo = ImageOps.contain(source.convert("RGBA"), (w * 2 - padding * 2, h * 2 - padding * 2), Image.Resampling.LANCZOS)
        paste_x = (x * 2) + ((w * 2 - logo.width) // 2)
        paste_y = (y * 2) + ((h * 2 - logo.height) // 2)
        image.paste(logo, (paste_x, paste_y), logo)
        return

    title_size = 17 if w >= 140 else 12
    sub_size = 11 if w >= 140 else 8
    text(draw, (x + w // 2, y + h // 2 - 8), "FASTTRACK", title_size, COLORS["gold"], True, "ma")
    text(draw, (x + w // 2, y + h // 2 + 14), "AGENCY", sub_size, COLORS["subtext"], True, "ma")


def text_width(value: str, size: int, bold: bool = False) -> int:
    bbox = font(size * 2, bold).getbbox(value)
    return (bbox[2] - bbox[0]) // 2


def league_name(tier: int) -> str:
    return LEAGUE_NAMES.get(tier, LEAGUE_NAMES[10])


def league_color(tier: int) -> str:
    return LEAGUE_COLORS.get(tier, LEAGUE_COLORS[10])


def format_int(value: int | float) -> str:
    return f"{int(round(value)):,}"


def format_hours(value: float) -> str:
    hours = int(value)
    minutes = int(round((value - hours) * 60))
    if minutes == 60:
        hours += 1
        minutes = 0
    return f"{hours}h {minutes}m"


def _legacy_incentive_label(status: str) -> tuple[str, str]:
    if status == "ACHIEVED":
        return "Achieved £80", COLORS["green"]
    if status == "NOT_ACHIEVABLE":
        return "Not Achievable", COLORS["red"]
    return "In Progress", COLORS["yellow"]


def incentive_label(status: str) -> tuple[str, str]:
    if status == "ACHIEVED":
        return f"Achieved £{INCENTIVE_REWARD}", COLORS["green"]
    if status == "NOT_ACHIEVABLE":
        return "Not Achievable", COLORS["red"]
    return "In Progress", COLORS["yellow"]


def incentive_label(status: str) -> tuple[str, str]:
    if status == "ACHIEVED":
        return f"Achieved GBP {INCENTIVE_REWARD}", COLORS["green"]
    if status == "NOT_ACHIEVABLE":
        return "Not Achievable", COLORS["red"]
    return "In Progress", COLORS["yellow"]


def resolve_image_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path if path.exists() else None


def circular_avatar(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    name: str,
    rank: int,
    avatar_path: str = "",
    accent_color: str | None = None,
    badge_text: str | None = None,
) -> None:
    accents = [COLORS["gold"], COLORS["subtext"], "#D97706", COLORS["blue"], COLORS["green"], COLORS["purple"]]
    accent = accent_color or accents[(rank - 1) % len(accents)]
    scale = 2
    box = (x * scale, y * scale, (x + size) * scale, (y + size) * scale)
    glow_box = ((x - 3) * scale, (y - 3) * scale, (x + size + 3) * scale, (y + size + 3) * scale)
    draw.ellipse(glow_box, fill="#0B0D0F", outline=accent, width=1 * scale)
    draw.ellipse(box, fill="#171A1F", outline=accent, width=3 * scale)

    path = resolve_image_path(avatar_path)
    if path:
        try:
            with Image.open(path) as source:
                avatar = ImageOps.fit(source.convert("RGB"), (size * scale, size * scale), Image.Resampling.LANCZOS)
            mask = Image.new("L", (size * scale, size * scale), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, size * scale, size * scale), fill=255)
            image.paste(avatar, (x * scale, y * scale), mask)
            draw.ellipse(box, outline=accent, width=3 * scale)
            if badge_text:
                _avatar_badge(draw, x, y, size, badge_text, accent)
            return
        except OSError:
            pass

    initials = "".join(part[:1] for part in name.replace(".", " ").replace("_", " ").split()[:2]).upper()
    draw.ellipse(box, fill="#171A1F", outline=accent, width=3 * scale)
    text(draw, (x + size // 2, y + size // 2 - 6), initials[:2] or "TV", max(12, size // 3), COLORS["text"], True, "ma")
    if badge_text:
        _avatar_badge(draw, x, y, size, badge_text, accent)


def _avatar_badge(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, value: str, accent: str) -> None:
    badge_w = max(22, text_width(value, 8, True) + 10)
    badge_x = x + size // 2 - badge_w // 2
    badge_y = y + size - 11
    rounded(draw, (badge_x, badge_y, badge_x + badge_w, badge_y + 16), 8, "#050607", accent, 1)
    text(draw, (x + size // 2, badge_y + 3), value, 8, accent, True, "ma")
