#!/usr/bin/env python3
"""Verify the BWork asset contract; optionally retrace the approved reference and render QA.

Default checks use the standard library. --reference additionally needs Pillow, the
already-installed libpotrace and Inkscape. These are authoring tools, never app dependencies.
The source reference is read-only; this tool never modifies any shipped resource.
"""
import argparse
import base64
import ctypes as c
from ctypes.util import find_library
import hashlib
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'app/src/main/res'
JAVA = ROOT / 'app/src/main/java/com/baseer/bwork/legacy'
ANDROID = '{http://schemas.android.com/apk/res/android}'
B_SHA256 = 'd1dd4f7f86a5a682cad47994c5f3351873d5f6c376fb370d1914b2dfdfbfdb6b'
REFERENCE_SHA256 = '93a5ff44e0529f08b93710416f1f98d2cfbc71baed47e222b2192c3fdd82fa05'
B_WIDTH = 99 * 229 / 118
WIDTH, HEIGHT = B_WIDTH + 6 + 659, 233


def validate_contract():
    original = ROOT.parents[1] / 'custom_addons/baseer_basser_workspace/static/description/baseer-mark-b.png'
    png = (RES / 'drawable-nodpi/baseer_mark_b.png').read_bytes()
    assert hashlib.sha256(png).hexdigest() == B_SHA256
    assert original.read_bytes() == png, 'Canonical B bytes have changed'
    vector = ET.parse(RES / 'drawable/bwork_chat_wordmark.xml').getroot()
    assert vector.get(ANDROID + 'viewportWidth') == '659'
    assert vector.get(ANDROID + 'viewportHeight') == '212'
    assert vector.get(ANDROID + 'autoMirrored') == 'false'
    assert len(vector) == 1 and vector[0].tag == 'path'
    path = vector[0]
    assert path.get(ANDROID + 'fillColor') == '#20A9E2'
    assert path.get(ANDROID + 'fillType') == 'evenOdd'
    data = path.get(ANDROID + 'pathData')
    assert data.count('M') == 5 and data.count('Z') == 5, 'Four letters plus single-storey a counter'
    assert set(re.findall('[A-Za-z]', data)) <= set('MLCZ'), 'Keep portable line/cubic path commands'
    assert len(data) < 5000
    view = (JAVA / 'BWorkWordmarkView.java').read_text()
    for contract in ('new Rect(14, 5, 113, 123)', 'B_HEIGHT = 229f',
                     'B_WIDTH = 99f * B_HEIGHT / 118f', 'CHAT_GAP = 6f', 'CHAT_TOP = 21f',
                     'CHAT_WIDTH = 659', 'CHAT_HEIGHT = 212', 'DESIGN_HEIGHT = 233f',
                     'ART_HEIGHT_DP = 32f', 'options.inScaled = false',
                     'setContentDescription("BWork")', 'setLayoutDirection(LAYOUT_DIRECTION_LTR)',
                     'IMPORTANT_FOR_ACCESSIBILITY_YES', 'canvas.scale(scale, scale)',
                     'canvas.drawBitmap(originalB, B_SOURCE, bDestination, bitmapPaint)',
                     'canvas.translate(B_WIDTH + CHAT_GAP, CHAT_TOP)', 'chat.draw(canvas)'):
        assert contract in view, contract
    for forbidden in ('TextView', 'Typeface', 'setTint', 'ColorFilter', 'drawText', 'scaledDensity'):
        assert forbidden not in view, forbidden
    main = (JAVA / 'MainActivity.java').read_text()
    toolbar = main[main.index('private void addMainToolbar()'):main.index('private void addMainSections()')]
    assert toolbar.count('new BWorkWordmarkView(this)') == 1
    assert 'TextView word' not in toolbar and 'ImageView mark' not in toolbar
    assert 'toolbar.addView(brand, p(-2, d(46)))' in toolbar
    assert 'toolbar.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1))' in toolbar
    assert 'new LinearLayout.LayoutParams(0, d(46), 1)' not in toolbar
    assert 'root.addView(toolbar, p(-1, d(56)))' in toolbar
    # Mirror Canvas scaling for narrow/ordinary widths and multiple density scales.
    for density in (1, 1.5, 2, 3, 4):
        for available_dp in (40, 80, 118, 152, 192, 240):
            scale = min(32 * density / HEIGHT, available_dp * density / WIDTH, 46 * density / HEIGHT)
            assert WIDTH * scale <= available_dp * density + 1e-7
            assert HEIGHT * scale <= 32 * density + 1e-7
            assert math.isclose((B_WIDTH * scale) / 99, (229 * scale) / 118)
            assert math.isclose((659 * scale) / (212 * scale), 659 / 212)
    assert math.isclose(WIDTH * 32 / HEIGHT, 117.71702917000073)
    print('PASS original B byte identity; four outlined letters; fixed geometry; accessibility; no font/tint/RTL mirror')
    print(f'PASS unified design {WIDTH:.6f} x {HEIGHT}, at 32dp: {WIDTH * 32 / HEIGHT:.3f} x 32dp')
    return png, data


def trace_mask(mask, width, height):
    # libpotrace's documented C ABI. Parameters are library defaults, version 1.16.
    class Point(c.Structure):
        _fields_ = [('x', c.c_double), ('y', c.c_double)]
    class Curve(c.Structure):
        _fields_ = [('n', c.c_int), ('tag', c.POINTER(c.c_int)), ('c', c.POINTER(Point * 3))]
    class TracePath(c.Structure):
        pass
    TracePath._fields_ = [('area', c.c_int), ('sign', c.c_int), ('curve', Curve),
                         ('next', c.POINTER(TracePath)), ('childlist', c.POINTER(TracePath)),
                         ('sibling', c.POINTER(TracePath)), ('priv', c.c_void_p)]
    class State(c.Structure):
        _fields_ = [('status', c.c_int), ('plist', c.POINTER(TracePath)), ('priv', c.c_void_p)]
    class Bitmap(c.Structure):
        _fields_ = [('w', c.c_int), ('h', c.c_int), ('dy', c.c_int), ('map', c.POINTER(c.c_ulong))]
    library = find_library('potrace')
    assert library, 'libpotrace is needed only for optional reference verification'
    lib = c.CDLL(library)
    lib.potrace_param_default.restype = c.c_void_p
    lib.potrace_trace.argtypes = [c.c_void_p, c.POINTER(Bitmap)]
    lib.potrace_trace.restype = c.POINTER(State)
    lib.potrace_state_free.argtypes = [c.POINTER(State)]
    lib.potrace_param_free.argtypes = [c.c_void_p]
    lib.potrace_version.restype = c.c_char_p
    assert lib.potrace_version().decode() == 'potracelib 1.16', 'Retrace with the recorded authoring version'
    wordbits = 8 * c.sizeof(c.c_ulong)
    stride = (width + wordbits - 1) // wordbits
    bits = (c.c_ulong * (stride * height))()
    for y in range(height):
        for x in range(width):
            if mask[y * width + x]:
                bits[y * stride + x // wordbits] |= 1 << (wordbits - 1 - x % wordbits)
    bitmap = Bitmap(width, height, stride, bits)
    parameters = lib.potrace_param_default()
    state = lib.potrace_trace(parameters, c.byref(bitmap))
    assert state and state.contents.status == 0
    paths = []
    def point(p):
        return f'{p.x:.3f},{p.y:.3f}'
    try:
        path = state.contents.plist
        while path:
            curve = path.contents.curve
            commands = ['M' + point(curve.c[curve.n - 1][2])]
            for i in range(curve.n):
                pts = curve.c[i]
                if curve.tag[i] == 2:
                    commands += ['L' + point(pts[1]), 'L' + point(pts[2])]
                else:
                    commands += ['C' + point(pts[0]) + ' ' + point(pts[1]) + ' ' + point(pts[2])]
            paths.append(' '.join(commands + ['Z']))
            path = path.contents.next
    finally:
        lib.potrace_state_free(state)
        lib.potrace_param_free(parameters)
    return ' '.join(paths)


def render(svg_path, png_path):
    assert shutil.which('inkscape'), 'Inkscape is needed only for optional static QA'
    subprocess.run(['inkscape', str(svg_path), '--export-filename=' + str(png_path)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def validate_reference(reference, data):
    from PIL import Image
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == REFERENCE_SHA256, 'Wrong selected reference'
    with Image.open(reference) as image:
        assert image.size == (1254, 1254)
        crop = image.convert('RGB').crop((410, 457, 1069, 669))
    pixels = list(crop.get_flattened_data() if hasattr(crop, 'get_flattened_data') else crop.getdata())
    mask = [b - r > 100 and g - r > 70 and b > 180 for r, g, b in pixels]
    assert sum(mask) == 75264
    assert trace_mask(mask, 659, 212) == data, 'Shipped outlines do not reproduce the selected reference trace'
    with tempfile.TemporaryDirectory(prefix='bwork-wordmark-') as directory:
        svg = Path(directory) / 'chat.svg'
        png = Path(directory) / 'chat.png'
        svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="659" height="212"><path fill="#20A9E2" fill-rule="evenodd" d="{data}"/></svg>')
        render(svg, png)
        with Image.open(png) as image:
            alpha = image.convert('RGBA').getchannel('A')
            rendered = [a > 127 for a in (alpha.get_flattened_data() if hasattr(alpha, 'get_flattened_data') else alpha.getdata())]
        union = sum(a or b for a, b in zip(mask, rendered))
        intersection = sum(a and b for a, b in zip(mask, rendered))
        overlap = intersection / union
        assert overlap > .99, f'Silhouette overlap {overlap:.4%} below 99%'
    print(f'PASS selected reference SHA; reproducible trace; full-size silhouette IoU {overlap:.4%}')
    return overlap


def make_proof(output, reference, png, data):
    # A clearly labeled, offline SVG rendering. It is not an Android screenshot.
    output.mkdir(parents=True, exist_ok=True)
    encoded_b = base64.b64encode(png).decode()
    scale_b = 229 / 118
    mark = (f'<g id="wordmark"><image x="{-14 * scale_b}" y="{-5 * scale_b}" '
            f'width="{128 * scale_b}" height="{128 * scale_b}" href="data:image/png;base64,{encoded_b}"/>'
            f'<path transform="translate({B_WIDTH + 6},21)" fill="#20A9E2" fill-rule="evenodd" d="{data}"/></g>')
    ref = ''
    if reference:
        encoded_ref = base64.b64encode(reference.read_bytes()).decode()
        ref_scale = 520 / 920
        ref = ('<text x="40" y="118">Selected concept, read-only reference</text>'
               '<defs><clipPath id="reference-clip"><rect x="40" y="137" width="520" height="160"/></clipPath></defs>'
               '<g clip-path="url(#reference-clip)">'
               f'<image x="{40 - 180 * ref_scale}" y="{137 - 420 * ref_scale}" '
               f'width="{1254 * ref_scale}" height="{1254 * ref_scale}" href="data:image/png;base64,{encoded_ref}"/></g>')
    proof = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1200" height="540">
<rect width="1200" height="540" fill="white"/>
<defs>{mark}</defs>
<g font-family="sans-serif" font-size="19" fill="#234657">
<text x="40" y="42" font-size="26" font-weight="bold">Internal static asset QA only</text>
<text x="40" y="77">This is an SVG render, not an Android screenshot. Native device validation remains open.</text>
{ref}
<text x="620" y="118">Canonical B + selected Chat outlines</text>
<use xlink:href="#wordmark" transform="translate(620,150) scale({520 / WIDTH})"/>
<text x="40" y="350">32dp artwork / 56dp toolbar at 1x</text>
<rect x="40" y="367" width="360" height="56" fill="#F4F8FE"/>
<use xlink:href="#wordmark" transform="translate(52,379) scale({32 / HEIGHT})"/>
<text x="470" y="350">Same geometry at 2x for inspection</text>
<rect x="470" y="367" width="690" height="112" fill="#F4F8FE"/>
<use xlink:href="#wordmark" transform="translate(494,391) scale({64 / HEIGHT})"/>
<text x="40" y="513">Original B pixels unchanged. Solid sky blue #20A9E2. Transparent artwork; one uniform scale.</text>
</g></svg>'''
    svg = output / 'wordmark-static-proof.svg'
    svg.write_text(proof)
    render(svg, output / 'wordmark-static-proof.png')
    print('Static QA proof:', output / 'wordmark-static-proof.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, help='Exact selected BWork-logo-concept.png, read only')
    parser.add_argument('--proof', type=Path, help='Write clearly labeled SVG/PNG static QA to this directory')
    args = parser.parse_args()
    png, data = validate_contract()
    if args.reference:
        validate_reference(args.reference, data)
    if args.proof:
        make_proof(args.proof, args.reference, png, data)


if __name__ == '__main__':
    main()
