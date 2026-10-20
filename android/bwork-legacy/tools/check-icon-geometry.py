#!/usr/bin/env python3
"""Original-PNG/safe-zone geometry checks, not an Android launcher screenshot test."""
from pathlib import Path
import math
import struct
import zlib
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
a = '{http://schemas.android.com/apk/res/android}'
xml = ET.parse(root / 'app/src/main/res/drawable/ic_foreground.xml').getroot()
assert xml.tag == 'inset', 'The foreground must have a viewport-relative inset'
insets = [xml.get(a + 'inset' + side) for side in ('Left', 'Top', 'Right', 'Bottom')]
assert insets == ['31%'] * 4, 'Use a symmetric square frame, not unequal fixed width/height'
bitmap = xml.find('bitmap')
assert bitmap is not None and bitmap.get(a + 'src') == '@drawable/baseer_mark_b'
assert bitmap.get(a + 'tint') == '#FFFFFF' and bitmap.get(a + 'gravity') == 'fill'
assert not xml.findall('.//item'), 'Do not restore the old non-square layer item'

# Decode only the known original 8-bit RGBA PNG to inspect alpha bounds, using stdlib.
png = (root / 'app/src/main/res/drawable-nodpi/baseer_mark_b.png').read_bytes()
assert png[:8] == b'\x89PNG\r\n\x1a\n'
pos, payload = 8, bytearray()
while pos < len(png):
    length = struct.unpack('>I', png[pos:pos + 4])[0]
    kind, data = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + length]
    if kind == b'IHDR':
        width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', data)
        assert (width, height, depth, color, compression, filtering, interlace) == (128, 128, 8, 6, 0, 0, 0)
    if kind == b'IDAT':
        payload.extend(data)
    pos += length + 12
raw = zlib.decompress(payload)
stride, previous, pixels, offset = width * 4, bytearray(width * 4), [], 0
for y in range(height):
    method = raw[offset]
    row = bytearray(raw[offset + 1:offset + 1 + stride])
    offset += stride + 1
    for x in range(stride):
        left = row[x - 4] if x >= 4 else 0
        up = previous[x]
        corner = previous[x - 4] if x >= 4 else 0
        if method == 0:
            predictor = 0
        elif method == 1:
            predictor = left
        elif method == 2:
            predictor = up
        elif method == 3:
            predictor = (left + up) // 2
        elif method == 4:
            p = left + up - corner
            distances = [abs(p - left), abs(p - up), abs(p - corner)]
            predictor = [left, up, corner][distances.index(min(distances))]
        else:
            raise AssertionError('Unknown PNG filter')
        row[x] = (row[x] + predictor) & 255
    pixels.extend((x, y) for x in range(width) if row[x * 4 + 3] > 0)
    previous = row
assert pixels
bounds = (min(x for x, y in pixels), min(y for x, y in pixels), max(x for x, y in pixels) + 1, max(y for x, y in pixels) + 1)
# Android uses a 108-unit expanded layer with a 72-unit masked viewport and a 66-unit safe zone.
# Equal 31% insets produce a 41.04x41.04 frame, so scale X == scale Y for this square PNG.
scale_x = 108 * (1 - .31 - .31) / width
scale_y = 108 * (1 - .31 - .31) / height
assert scale_x == scale_y
radius = max(math.hypot((x + .5 - width / 2) * scale_x, (y + .5 - height / 2) * scale_y) for x, y in pixels)
assert radius <= 33, 'Nontransparent artwork escapes the centered circular 66-unit safe zone'
for viewport in (24, 48, 72, 96, 192, 512):
    assert viewport * .38 / width == viewport * .38 / height
print(f'PASS original 128x128 B, alpha bounds {bounds}, equal-axis scaling, safe-zone radius {radius:.2f}/33')

assert abs((1-.31-.31)/(1-.28-.28)-(19/22)) < 1e-9
print('PASS launcher artwork extent is 13.64% smaller than 0.4.2 without changing source/aspect')
