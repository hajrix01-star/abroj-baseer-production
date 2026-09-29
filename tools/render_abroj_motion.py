"""Render a self-contained Saudi-villa construction motion graphic as MP4."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.video_runtime'))

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT, FPS, SECONDS = 1280, 720, 24, 12
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'custom_addons' / 'abroj_website' / 'static' / 'src' / 'video' / 'abroj-foundation-to-handover.mp4'
FONT_DIR = ROOT / 'odoo' / 'addons' / 'web' / 'static' / 'fonts' / 'google' / 'Open_Sans'


def clamp(value): return max(0.0, min(1.0, value))
def ease(value):
    value = clamp(value)
    return value * value * (3 - 2 * value)
def font(size, bold=False):
    return ImageFont.truetype(str(FONT_DIR / ('Open_Sans-Bold.ttf' if bold else 'Open_Sans-SemiBold.ttf')), size)
def line(draw, points, fill, width=2): draw.line(points, fill=fill, width=width, joint='curve')
def polygon(draw, pts, fill, outline=None, width=1):
    draw.polygon(pts, fill=fill)
    if outline: line(draw, pts + [pts[0]], outline, width)


def worker(draw, x, y, phase, scale=1.0, working=False):
    """A small illustrated worker with a moving body and long morning shadow."""
    walk = math.sin(phase) * (2.5 if working else 1.2)
    shadow_x, shadow_y = x - 52 * scale, y + 29 * scale
    draw.ellipse((shadow_x - 36 * scale, shadow_y - 6 * scale, shadow_x + 25 * scale, shadow_y + 7 * scale), fill=(4, 36, 53, 64))
    draw.ellipse((x - 7 * scale, y - 45 * scale + walk, x + 7 * scale, y - 31 * scale + walk), fill=(249, 193, 42, 255))
    draw.ellipse((x - 6 * scale, y - 33 * scale + walk, x + 6 * scale, y - 20 * scale + walk), fill=(190, 133, 78, 255))
    draw.rounded_rectangle((x - 9 * scale, y - 20 * scale + walk, x + 9 * scale, y + 8 * scale + walk), radius=3, fill=(239, 117, 42, 255))
    line(draw, [(x - 7 * scale, y - 17 * scale + walk), (x + 7 * scale, y + 5 * scale + walk)], (254, 231, 159, 255), max(1, int(scale)))
    line(draw, [(x + 7 * scale, y - 17 * scale + walk), (x - 7 * scale, y + 5 * scale + walk)], (254, 231, 159, 255), max(1, int(scale)))
    arm_y = y - 12 * scale + walk
    line(draw, [(x + 7 * scale, arm_y), (x + 18 * scale, arm_y + math.sin(phase * 1.6) * 4)], (190, 133, 78, 255), max(2, int(3 * scale)))
    line(draw, [(x - 4 * scale, y + 8 * scale + walk), (x - 7 * scale, y + 26 * scale)], (23, 47, 59, 255), max(2, int(3 * scale)))
    line(draw, [(x + 4 * scale, y + 8 * scale + walk), (x + 8 * scale, y + 26 * scale)], (23, 47, 59, 255), max(2, int(3 * scale)))


def palm(draw, x, y, reveal):
    if not reveal: return
    trunk_h = int(105 * reveal)
    line(draw, [(x, y), (x - 5, y - trunk_h)], (111, 78, 42, int(255 * reveal)), 9)
    top = (x - 5, y - trunk_h)
    for angle in (-2.6, -2.1, -1.55, -1.0, -.45):
        end = (top[0] + math.cos(angle) * 43 * reveal, top[1] + math.sin(angle) * 34 * reveal)
        line(draw, [top, end], (48, 126, 94, int(255 * reveal)), 8)


def frame_at(t):
    image = Image.new('RGB', (WIDTH, HEIGHT), '#07395e')
    draw = ImageDraw.Draw(image, 'RGBA')
    for x in range(0, WIDTH + 1, 64): line(draw, [(x, 0), (x, HEIGHT)], (178, 224, 236, 21 if x % 128 else 36), 1)
    for y in range(0, HEIGHT + 1, 64): line(draw, [(0, y), (WIDTH, y)], (178, 224, 236, 21 if y % 128 else 36), 1)
    sun_x = -420 + (t / SECONDS) * 1780
    polygon(draw, [(sun_x, -70), (sun_x + 290, -70), (sun_x + 660, 790), (sun_x + 370, 790)], (201, 238, 248, 18))
    draw.text((66, 48), 'ABROJ', font=font(42, True), fill=(255, 255, 255, 255))
    draw.text((69, 101), 'INTEGRATED CONSTRUCTION', font=font(14, True), fill=(170, 218, 233, 255))
    draw.text((981, 57), 'SAUDI VILLA · BUILD STORY', font=font(14, True), fill=(188, 225, 237, 255))
    line(draw, [(66, 142), (1212, 142)], (178, 224, 236, 105), 1)

    polygon(draw, [(92, 571), (788, 399), (1184, 590), (426, 704)], (215, 227, 224, 255), (146, 187, 199, 180), 2)
    for n in range(1, 7): line(draw, [(92, 571 + n * 24), (1184, 590 + n * 18)], (49, 108, 132, 35), 1)
    for n in range(1, 10): line(draw, [(90 + n * 78, 571), (425 + n * 78, 704)], (49, 108, 132, 33), 1)

    foundation = ease((t - .4) / 1.3)
    walls = ease((t - 2.0) / 1.55)
    facade = ease((t - 4.1) / 1.9)
    landscaping = ease((t - 6.4) / 1.45)
    handover = ease((t - 8.3) / 1.3)
    villa_front = [(532, 538), (884, 470), (1053, 551), (690, 628)]
    if foundation:
        line(draw, villa_front + [villa_front[0]], (22, 101, 131, int(255 * foundation)), 8)
        line(draw, [(493, 560), (884, 482), (1093, 566)], (242, 250, 248, int(255 * foundation)), 4)
        line(draw, [(503, 580), (867, 509), (1078, 577)], (28, 104, 135, int(255 * foundation)), 3)
        polygon(draw, [(438, 589), (515, 574), (545, 589), (468, 604)], (230, 221, 199, int(240 * foundation)))
        polygon(draw, [(1018, 566), (1098, 550), (1128, 565), (1046, 582)], (230, 221, 199, int(240 * foundation)))

    if walls:
        left_height, right_height = int(110 * walls), int(118 * walls)
        left = [(532, 538), (690, 628), (690, 628 - left_height), (532, 538 - left_height)]
        right = [(690, 628), (1053, 551), (1053, 551 - right_height), (690, 628 - left_height)]
        polygon(draw, left, (193, 180, 148, int(255 * walls)), (248, 242, 220, int(220 * walls)), 2)
        polygon(draw, right, (235, 229, 209, int(255 * walls)), (255, 251, 235, int(235 * walls)), 2)
        polygon(draw, [(532, 538 - left_height), (690, 628 - left_height), (1053, 551 - right_height), (892, 465 - right_height)], (250, 245, 226, int(255 * walls)), (255, 255, 246, int(220 * walls)), 2)
        line(draw, [(532, 538-left_height), (532, 524-left_height), (607, 540-left_height), (607, 526-left_height), (690, 628-left_height)], (252, 247, 231, int(255 * walls)), 8)
        line(draw, [(690, 628-left_height), (690, 612-right_height), (795, 590-right_height), (795, 575-right_height), (1053, 551-right_height)], (255, 252, 237, int(255 * walls)), 8)

    if facade:
        for xx, yy in ((756, 560), (837, 543), (918, 526)):
            reveal = ease((facade * 3) - ((xx - 756) / 82))
            polygon(draw, [(xx, yy), (xx + 52, yy - 11), (xx + 52, yy - 49), (xx, yy - 38)], (31, 85, 103, int(255 * reveal)), (249, 241, 214, int(220 * reveal)), 2)
            for bar in range(1, 4): line(draw, [(xx + bar * 12, yy - 3), (xx + bar * 12, yy - 36)], (206, 181, 124, int(235 * reveal)), 2)
        arch_x, arch_y = 648, 591
        draw.rounded_rectangle((arch_x, arch_y - 89, arch_x + 63, arch_y + 2), radius=30, fill=(182, 160, 117, int(255 * facade)))
        draw.rounded_rectangle((arch_x + 10, arch_y - 77, arch_x + 52, arch_y + 2), radius=20, fill=(37, 82, 91, int(255 * facade)))
        line(draw, [(arch_x + 31, arch_y - 77), (arch_x + 31, arch_y - 4)], (201, 172, 112, int(245 * facade)), 2)
        polygon(draw, [(574, 549), (615, 572), (615, 526), (574, 503)], (197, 177, 128, int(245 * facade)))
        for gap in range(3): line(draw, [(580 + gap * 10, 543), (580 + gap * 10, 511)], (242, 232, 204, int(230 * facade)), 2)

    palm(draw, 470, 596, landscaping)
    palm(draw, 1090, 578, landscaping * .9)
    if landscaping:
        for x, y in ((510, 602), (545, 586), (1002, 575), (1033, 569)):
            draw.ellipse((x - 14, y - 10, x + 14, y + 8), fill=(64, 135, 91, int(255 * landscaping)))

    team = ((300, 611, 1.05, False), (372, 588, .93, True), (447, 566, .84, True), (1030, 600, .82, False), (1120, 580, .7, True))
    for index, (x, y, scale, working) in enumerate(team):
        drift = math.sin(t * .9 + index) * (6 if not working else 2)
        worker(draw, x + drift, y, t * 1.3 + index * .9, scale, working)

    stage = 'FOUNDATION' if t < 2 else 'STRUCTURE' if t < 4.1 else 'SAUDI VILLA' if t < 6.4 else 'FINISHING' if t < 8.3 else 'HANDOVER'
    stage_no = '01' if t < 2 else '02' if t < 4.1 else '03' if t < 6.4 else '04' if t < 8.3 else '05'
    draw.rectangle((66, 180, 300, 226), fill=(255, 255, 255, 238))
    draw.text((83, 192), f'{stage_no}  {stage}', font=font(16, True), fill=(6, 54, 93, 255))
    if handover:
        draw.rectangle((859, 195, 1112, 242), fill=(255, 255, 255, int(240 * handover)))
        draw.text((883, 207), 'READY FOR HOME', font=font(16, True), fill=(6, 54, 93, int(255 * handover)))
    fade = clamp(t / .45) * clamp((SECONDS - t) / .6)
    if fade < 1:
        image = Image.alpha_composite(image.convert('RGBA'), Image.new('RGBA', image.size, (7, 57, 94, int((1 - fade) * 255)))).convert('RGB')
    return image


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio_ffmpeg.write_frames(str(OUT), (WIDTH, HEIGHT), pix_fmt_in='rgb24', pix_fmt_out='yuv420p', fps=FPS, codec='libx264', quality=8)
    writer.send(None)
    try:
        for index in range(FPS * SECONDS): writer.send(frame_at(index / FPS).tobytes())
    finally:
        writer.close()
    print(OUT)


if __name__ == '__main__': main()
