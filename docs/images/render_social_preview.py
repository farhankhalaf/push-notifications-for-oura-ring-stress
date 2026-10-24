"""Development-only outlined SVG composition; requires fonttools 4.66.1.

Usage: python render_social_preview.py /path/Arial.ttf '/path/Arial Bold.ttf'
The committed SVG can be rendered without these fonts or this dependency.
"""
import base64
import hashlib
import html
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = ROOT / "docs" / "images"
EXPECTED = (
    "525979822591a3447cfc49d943d6f7683508e25543407871c0ed8fed05fd2bd9",
    "d72db21f9242aedd6b917d8549ad5921766b24d5f8d0becfda2ff4c620b3c2e0",
)


def outlined(font, text, x, y, size, color):
    cmap = font.getBestCmap()
    glyphs = font.getGlyphSet()
    metrics = font["hmtx"].metrics
    scale = size / font["head"].unitsPerEm
    cursor = 0
    paths = []
    for char in text:
        name = cmap[ord(char)]
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(pen)
        paths.append('<path transform="translate(%s 0)" d="%s"/>' % (cursor, pen.getCommands()))
        cursor += metrics[name][0]
    return '<g aria-label="%s" fill="%s" transform="translate(%s %s) scale(%s %s)">%s</g>' % (
        html.escape(text, quote=True), color, x, y, scale, -scale, "".join(paths))


def data(path, mime):
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    fonts = []
    for filename, digest in zip(sys.argv[1:], EXPECTED):
        path = Path(filename)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit("Font differs from the documented build. Use the committed outlined SVG instead.")
        fonts.append(TTFont(path))
    regular, bold = fonts
    text = lambda label, x, y, size, color="#f4f4ef", heavy=False: outlined(
        bold if heavy else regular, label, x, y, size, color)
    notice = data(IMAGE_DIR / "walkthrough" / "notification-headline.png", "image/png")
    avatar = data(ROOT / "bot-avatar.jpg", "image/jpeg")
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1280" height="640" viewBox="0 0 1280 640">
<title>Oura Stress Alerts</title>
<desc>Oura Stress Alerts: free and open source Telegram alerts when Oura records more high stress. Unofficial and not affiliated with Oura. The notification is a rendered example of the current alert.</desc>
<defs><clipPath id="avatar"><circle cx="94" cy="99" r="34"/></clipPath><clipPath id="notice"><rect x="700" y="288" width="522" height="100" rx="21"/></clipPath></defs>
<rect width="1280" height="640" fill="#0d171b"/>
<circle cx="1060" cy="325" r="290" fill="#132126"/>
<path d="M666 112V528" stroke="#334249" stroke-width="1"/>
<image x="60" y="65" width="68" height="68" xlink:href="%s" clip-path="url(#avatar)"/>
%s
%s
%s
%s
%s
%s
%s
<image x="700" y="288" width="522" height="100" xlink:href="%s" clip-path="url(#notice)"/>
%s
</svg>''' % (
        avatar,
        text("FREE & OPEN SOURCE", 150, 107, 18, "#b9d5c9", True),
        text("Oura Stress", 60, 235, 72, heavy=True),
        text("Alerts", 60, 316, 72, heavy=True),
        text("A gentle nudge when Oura", 63, 382, 27, "#bac8c8"),
        text("records more high stress.", 63, 421, 27, "#bac8c8"),
        text("UNOFFICIAL · NOT AFFILIATED WITH OURA", 63, 539, 15, "#9bb8ae"),
        text("farhankhalaf/push-notifications-for-oura-ring-stress", 63, 577, 21, "#dce7e1"),
        notice,
        text("DELIVERED THROUGH TELEGRAM", 738, 248, 18, "#b9d5c9", True),
    )
    (IMAGE_DIR / "social-preview.svg").write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
