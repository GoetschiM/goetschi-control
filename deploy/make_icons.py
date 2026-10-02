"""Erzeugt das RRM-Icon (SVG + PNG-Groessen + favicon.ico) aus einer gemeinsamen Geometrie.
   python deploy/make_icons.py      -> schreibt nach static/icons/
Minimal: dunkler Grund, ein blauer Kreislauf-Pfeil, drei weisse Server-Einschuebe."""
import math, os
from PIL import Image, ImageDraw

BG, ACCENT, FG = '#0b0e14', '#4f8cff', '#e6ebf2'
OUT = os.path.join(os.path.dirname(__file__), '..', 'static', 'icons')

# Geometrie im 512er-Raster
C, R, RING_W = 256, 160, 30
A_START, A_END = -20, 290          # Grad, im Uhrzeigersinn ab 3 Uhr; Luecke oben rechts
HEAD = 58                          # Laenge der Pfeilspitze
BARS = [(176, 186), (240, 250), (304, 314)]   # y-Bereiche der Einschuebe (Hoehe 46)
BAR_X0, BAR_X1, BAR_H, BAR_R = 168, 344, 46, 12
DOT_X, DOT_R = 196, 8


def pt(a, r=R):
    t = math.radians(a)
    return C + r * math.cos(t), C + r * math.sin(t)


def arrow_head():
    # Spitze am Ende des Bogens, in Richtung der Bewegung (Tangente im Uhrzeigersinn)
    x, y = pt(A_END)
    t = math.radians(A_END)
    dx, dy = -math.sin(t), math.cos(t)          # Tangente
    nx, ny = math.cos(t), math.sin(t)           # Normale (nach aussen)
    tip = (x + dx * HEAD * 0.95, y + dy * HEAD * 0.95)
    w = RING_W * 1.25
    b1 = (x + nx * w - dx * 6, y + ny * w - dy * 6)
    b2 = (x - nx * w - dx * 6, y - ny * w - dy * 6)
    return [b1, tip, b2]


def svg(rounded=True, pad=0):
    s = 512 / (512 - 2 * pad) if pad else 1
    g = f'<g transform="translate({pad} {pad}) scale({(512 - 2 * pad) / 512:.4f})">' if pad else '<g>'
    x0, y0 = pt(A_START); x1, y1 = pt(A_END)
    large = 1 if (A_END - A_START) % 360 > 180 else 0
    head = ' '.join(f'{x:.1f},{y:.1f}' for x, y in arrow_head())
    bars = ''.join(
        f'<rect x="{BAR_X0}" y="{y}" width="{BAR_X1 - BAR_X0}" height="{BAR_H}" rx="{BAR_R}" fill="{FG}"/>'
        f'<circle cx="{DOT_X}" cy="{y + BAR_H / 2}" r="{DOT_R}" fill="{BG}"/>'
        for y, _ in [(176, 0), (233, 0), (290, 0)])
    rect = f'<rect width="512" height="512" rx="{112 if rounded else 0}" fill="{BG}"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{rect}{g}'
            f'<path d="M{x0:.1f} {y0:.1f} A{R} {R} 0 {large} 1 {x1:.1f} {y1:.1f}" fill="none" '
            f'stroke="{ACCENT}" stroke-width="{RING_W}" stroke-linecap="round"/>'
            f'<polygon points="{head}" fill="{ACCENT}" stroke="{ACCENT}" stroke-width="6" stroke-linejoin="round"/>'
            f'{bars}</g></svg>')


def png(size, rounded=True, pad=0, ss=4):
    S = size * ss
    k = S / 512
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if rounded:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(112 * k), fill=BG)
    else:
        d.rectangle([0, 0, S, S], fill=BG)
    q = (512 - 2 * pad) / 512
    def m(x, y): return ((pad + x * q) * k, (pad + y * q) * k)
    # Ring
    cx, cy = m(C, C); rr = R * q * k; w = int(RING_W * q * k)
    d.arc([cx - rr - w / 2, cy - rr - w / 2, cx + rr + w / 2, cy + rr + w / 2], A_START, A_END, fill=ACCENT, width=w)
    for a in (A_START,):           # runde Kappe am Anfang
        x, y = m(*pt(a)); d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=ACCENT)
    d.polygon([m(x, y) for x, y in arrow_head()], fill=ACCENT)
    # Einschuebe
    for y in (176, 233, 290):
        a0 = m(BAR_X0, y); a1 = m(BAR_X1, y + BAR_H)
        d.rounded_rectangle([a0[0], a0[1], a1[0], a1[1]], radius=BAR_R * q * k, fill=FG)
        dx, dy = m(DOT_X, y + BAR_H / 2); dr = DOT_R * q * k
        d.ellipse([dx - dr, dy - dr, dx + dr, dy + dr], fill=BG)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, 'icon.svg'), 'w').write(svg())
    open(os.path.join(OUT, 'icon-maskable.svg'), 'w').write(svg(rounded=False, pad=56))
    for n in (16, 32, 48, 192, 512):
        png(n).save(os.path.join(OUT, f'icon-{n}.png'))
    png(512, rounded=False, pad=56).save(os.path.join(OUT, 'icon-maskable-512.png'))
    png(192, rounded=False, pad=22).save(os.path.join(OUT, 'icon-maskable-192.png'))
    png(180, rounded=False, pad=0).convert('RGB').save(os.path.join(OUT, 'apple-touch-icon.png'))
    png(256).save(os.path.join(OUT, 'favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print('Icons geschrieben nach', os.path.abspath(OUT))
