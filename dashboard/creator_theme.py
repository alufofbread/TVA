"""Visual primitives scoped to the creator card; other dashboards keep their theme."""
import math
from PIL import Image, ImageDraw, ImageFilter, ImageColor
from dashboard.style import rounded as base_rounded, text as base_text, text_width

COLORS = dict(bg='#060914', panel='#10162B', panel_alt='#0C1123', border='#27304C',
              muted='#97A3C0', text='#F5F4FF', subtext='#BFCAE2', gold='#B7A2FF',
              green='#73DDB5', blue='#669CFF', purple='#B29AFF', red='#FF8398', yellow='#E8BF79')

def canvas(width, height):
    # Small smooth light field, upscaled before the normal 2x typography pass.
    field = Image.new('RGB', (385, 180))
    pixels = field.load()
    for y in range(180):
        for x in range(385):
            purple = math.exp(-(((x-345)/130)**2 + ((y-30)/95)**2))
            blue = math.exp(-(((x-30)/100)**2 + ((y-170)/75)**2))
            pixels[x,y] = (int(6+44*purple+2*blue), int(9+11*purple+23*blue), int(20+65*purple+44*blue))
    image = field.resize((width*2, height*2), Image.Resampling.BICUBIC)
    draw = ImageDraw.Draw(image)
    for offset in (0, 34, 68):
        draw.arc((int((710+offset)*2), -680, int((1600+offset)*2), 820), 35, 255, fill='#211E38', width=2)
    # Fixed positions keep previews deterministic; these sit beneath every panel.
    for x,y in ((1012,16),(1049,303),(23,433),(664,294),(804,23),(1052,617),(21,697)):
        diamond(draw, x, y, 2, '#3B365A')
    return image, draw

def rounded(draw, box, radius, fill, outline=None, width=1):
    if fill in (COLORS['panel'], COLORS['panel_alt']):
        x,y,r,b = box
        base_rounded(draw, (x,y+5,r,b+5), 20, '#070B18')
        base_rounded(draw, box, 20, fill, outline, width)
        # A restrained light wash gives panels depth without bright borders.
        wash = Image.new('RGBA', ((r-x)*2, (b-y)*2))
        wd = ImageDraw.Draw(wash)
        for row in range(wash.height):
            alpha = int(16 * (1-row/max(1,wash.height-1))**2)
            wd.line((0,row,wash.width,row), fill=(112,104,211,alpha))
        mask = Image.new('L', wash.size)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,wash.width-1,wash.height-1), radius=40, fill=255)
        from PIL import ImageChops
        wash.putalpha(ImageChops.multiply(wash.getchannel('A'), mask))
        draw._image.paste(wash, (x*2,y*2), wash)
        draw.line(((x+22)*2,(y+1)*2,(r-22)*2,(y+1)*2), fill='#333755', width=2)
    else:
        base_rounded(draw, box, radius, fill, outline, width)

def text(draw, xy, value, size, fill, bold=False, anchor=None):
    if size <= 13 and value.isupper() and anchor is None:
        x,y = xy
        for char in value:
            base_text(draw, (x,y), char, size, fill, bold)
            x += text_width(char, size, bold) + 1
    else:
        base_text(draw, xy, value, size, fill, bold, anchor)

def rail(draw, x, y, width, height, pct, hero=False, accent=None):
    if hero and pct > 0:
        bloom(draw, (x-6,y-7,x+int(width*min(100,pct)/100)+6,y+height+7), '#826AFF', 70, 12)
    base_rounded(draw, (x,y,x+width,y+height), height//2, '#090F23', '#29314C')
    filled = max(0, min(width, int(width*pct/100)))
    if filled <= 0:
        return
    # Rounded mask keeps zero and very small progress values safe to render.
    strip = Image.new('RGB', (filled*2,height*2))
    sd = ImageDraw.Draw(strip)
    for i in range(filled*2):
        t = i / max(1, width*2-1)
        sd.line((i,0,i,height*2), fill=ImageColor.getrgb(accent) if accent else (int(91+78*t),int(132-6*t),255))
    mask = Image.new('L', strip.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,filled*2-1,height*2-1), radius=height, fill=255)
    draw._image.paste(strip, (x*2,y*2), mask)

    if hero:
        for fraction in (.25,.5,.75):
            mx = x + int(width*fraction)
            draw.line((mx*2,(y+height+5)*2,mx*2,(y+height+8)*2), fill='#646082', width=2)
        endpoint = x + filled - min(4, filled//2)
        diamond(draw, endpoint, y+height//2, 5, '#EEE7FF')
        diamond(draw, x+width, y+height//2, 5, '#BEB0FF', outline=True)


def bloom(draw, box, color, opacity=45, blur=16):
    """Local blurred light; callers place it before their foreground content."""
    x,y,r,b = box
    pad=blur*3
    layer=Image.new('RGBA', ((r-x+pad*2)*2,(b-y+pad*2)*2))
    ld=ImageDraw.Draw(layer)
    ld.ellipse((pad*2,pad*2,(r-x+pad)*2,(b-y+pad)*2), fill=(*ImageColor.getrgb(color),opacity))
    layer=layer.filter(ImageFilter.GaussianBlur(blur*2))
    draw._image.paste(layer, ((x-pad)*2,(y-pad)*2), layer)


def diamond(draw, x, y, size, color, outline=False):
    vertices=[(x*2,(y-size)*2),((x+size)*2,y*2),(x*2,(y+size)*2),((x-size)*2,y*2)]
    if outline:
        draw.line(vertices+[vertices[0]], fill=color, width=2)
    else:
        draw.polygon(vertices, fill=color)
