"""Development-only render of the one-line alert used by the social preview.

Usage: python render_notification_headline.py
Needs Pillow and macOS's SF Pro system font (/System/Library/Fonts/SFNS.ttf).
It draws the current alert, "🔴 Oura recorded high stress", as an iOS lock-screen
notification. The avatar, Telegram badge and red circle are cropped from
walkthrough/notification.png; the glass is a blurred crop of
walkthrough/lockscreen-empty.png. The tool itself does not need this script.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WALK = Path(__file__).resolve().parent / "walkthrough"
SS = 4
K = 3.0  # pixels per iOS point
W, H, R = round(377 * K), round(72 * K), round(23 * K)


def rounded(size, radius):
    w, h = size
    mask = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=radius * SS, fill=255)
    return mask.resize(size, Image.LANCZOS)


def font(size, weight):
    face = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", size)
    face.set_variation_by_name(weight)
    return face


def main():
    capture = Image.open(WALK / "notification.png").convert("RGBA")
    lock = Image.open(WALK / "lockscreen-empty.png").convert("RGB")
    avatar = capture.crop((30, 250, 170, 392))
    mask = Image.new("L", avatar.size, 0)
    shape = ImageDraw.Draw(mask)
    shape.ellipse([10, 8, 124, 122], fill=255)
    shape.rounded_rectangle([84, 84, 134, 134], radius=12, fill=255)
    avatar.putalpha(mask.filter(ImageFilter.GaussianBlur(0.6)))
    dot = capture.crop((190, 232, 252, 292))
    dot_mask = Image.new("L", dot.size, 0)
    ImageDraw.Draw(dot_mask).ellipse([3, 4, 58, 58], fill=255)
    dot.putalpha(dot_mask.filter(ImageFilter.GaussianBlur(0.5)))
    scale = W / 594
    glass = lock.crop((13, 590, 607, 590 + round(H / scale))).resize((W, H), Image.LANCZOS)
    glass = glass.filter(ImageFilter.GaussianBlur(30))
    glass = Image.blend(glass, Image.new("RGB", glass.size, (72, 66, 84)), 0.55)
    glass = Image.blend(glass, Image.new("RGB", glass.size, (255, 255, 255)), 0.08).convert("RGBA")
    draw = ImageDraw.Draw(glass)
    side = round(38 * K) + 10
    glass.alpha_composite(avatar.resize((side, side), Image.LANCZOS), (round(13 * K), (H - side) // 2))
    left = round(62 * K)
    draw.text((left, round(15 * K)), "Oura Stress Alerts", font=font(round(15 * K), "Semibold"), fill=(255, 255, 255))
    draw.text((W - round(14 * K), round(15 * K) + 3), "now", font=font(round(13 * K), "Regular"),
              fill=(222, 218, 230), anchor="ra")
    glass.alpha_composite(dot.resize((round(15 * K),) * 2, Image.LANCZOS), (left, round(37 * K) + 4))
    draw.text((left + round(19 * K), round(36 * K)), "Oura recorded high stress",
              font=font(round(15 * K), "Regular"), fill=(244, 242, 248))
    glass.putalpha(rounded(glass.size, R))
    glass.save(WALK / "notification-headline.png", optimize=True)


if __name__ == "__main__":
    main()
