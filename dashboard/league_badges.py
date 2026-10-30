"""Supplied league artwork; rendering never changes qualification thresholds."""
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageOps

ASSETS = Path(__file__).resolve().parent / 'assets' / 'leagues'
BADGES = ('rising', 'star', 'premier', 'elite', 'millionaire', 'icon')


@lru_cache(maxsize=6)
def _badge(name):
    if name not in BADGES:
        raise ValueError('Unknown league badge')
    with Image.open(ASSETS / (name + '.png')) as source:
        image = source.convert('RGBA')
        bounds = image.getchannel('A').getbbox()
        return image.crop(bounds) if bounds else image


def badge_name(league_name):
    return league_name.lower()


def draw_badge(image, name, box):
    """Fit original transparent artwork into a logical 1x box on the 2x card."""
    x,y,right,bottom=box
    badge=ImageOps.contain(_badge(name),((right-x)*2,(bottom-y)*2),Image.Resampling.LANCZOS)
    image.paste(badge,(x*2+((right-x)*2-badge.width)//2,y*2+((bottom-y)*2-badge.height)//2),badge)
