"""Join skin-chart colors only on locally derived spectral first-person hands.

UVs, geometry, the animated second texture and the original boss stay intact.
The small seam recipe is derived from the user's disc for optional HD aliases.
"""
from collections import defaultdict
import math
import struct

import character_repaint as rw
import character_spectral_hands as hands

OLD = b'BossCassidy_body_X'
NEW = b'DW_SpectralHands_X'
RECIPE = 'characters/player_first/cassidyspectral_hand_seams.bin'
ITERATIONS = 12


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


def _address(x, y, width, height):
    value, bit, target = 0, 1, 1
    while bit < width or bit < height:
        if bit < width:
            if x & bit:
                value |= target
            target <<= 1
        if bit < height:
            if y & bit:
                value |= target
            target <<= 1
        bit <<= 1
    return value


def _texture(value):
    header = value[12:104]
    if (len(header) != 92 or struct.unpack_from('<I', header)[0] != 5 or
            header[8:40].split(b'\0')[0] != OLD or
            struct.unpack_from('<II', header, 72) != (0x2600, 0) or
            (header[84], header[85], header[86], header[87]) != (8, 1, 4, 0)):
        raise ValueError('Unexpected spectral hand texture schema')
    width, height = struct.unpack_from('<HH', header, 80)
    if width not in (128, 512) or width != height or len(value) != 104+1024+width*height:
        raise ValueError('Unexpected spectral hand texture extent')
    palette, indices = value[104:1128], value[1128:]
    if struct.unpack_from('<I', header, 88)[0] != width*height:
        raise ValueError('Unexpected spectral hand texture length')
    pixels = bytearray(width*height*4)
    for y in range(height):
        for x in range(width):
            index = indices[_address(x, y, width, height)]*4
            at = (y*width+x)*4
            pixels[at:at+3] = palette[index:index+3]
            pixels[at+3] = 255
    return header, pixels, width, height


def _sample(pixels, width, height, u, v):
    x, y = u*width-.5, v*height-.5
    ix, iy = math.floor(x), math.floor(y)
    tx, ty = x-ix, y-iy
    indices = (((iy % height)*width+ix % width)*4,
               ((iy % height)*width+(ix+1) % width)*4,
               (((iy+1) % height)*width+ix % width)*4,
               (((iy+1) % height)*width+(ix+1) % width)*4)
    weights = ((1-tx)*(1-ty), tx*(1-ty), (1-tx)*ty, tx*ty)
    return tuple(sum(pixels[p+c]*w for p, w in zip(indices, weights)) for c in range(3))


def _pale(rgb):
    return min(rgb) > 127.5 and max(rgb)-min(rgb) < 40.8


def _pairs(model, pixels, width, height):
    weld, edges = {}, defaultdict(list)
    ids = [weld.setdefault(tuple(round(v, 5) for v in p), len(weld)) for p in model['positions']]
    for tri in model['triangles']:
        for a, b in zip(tri, (*tri[1:], tri[0])):
            if ids[a] > ids[b]:
                a, b = b, a
            edges[ids[a], ids[b]].append((a, b))
    pairs = []
    for sides in edges.values():
        if len(sides) != 2 or all(model['uv'][a] == model['uv'][b] for a, b in zip(*sides)):
            continue
        pair = tuple(tuple(model['uv'][i] for i in side) for side in sides)
        if any(not 0 <= v <= 1 for side in pair for uv in side for v in uv):
            raise ValueError('Spectral hand seam UV outside atlas')
        # Pale nail tips and highlights are authored boundaries, not skin seams.
        if any(_pale(_sample(pixels, width, height,
                             a[0]+(b[0]-a[0])*t/20, a[1]+(b[1]-a[1])*t/20))
               for a, b in pair for t in range(21)):
            continue
        pairs.append(pair)
    if not 1 <= len(pairs) <= 1024:
        raise ValueError('Unexpected spectral hand seam count')
    return pairs


def _protected(model, pixels, width, height):
    # Preserve every pale texel in the hand's UV footprint, including nearby
    # nails reached by the feather around a skin-only seam.
    xs, ys = zip(*model['uv'])
    lo_x, hi_x = max(0, math.floor(min(xs)*width)), min(width, math.ceil(max(xs)*width))
    lo_y, hi_y = max(0, math.floor(min(ys)*height)), min(height, math.ceil(max(ys)*height))
    rectangles = []
    for y in range(lo_y, hi_y):
        start = None
        for x in range(lo_x, hi_x+1):
            pale = x < hi_x and _pale(pixels[(y*width+x)*4:(y*width+x)*4+3])
            if pale and start is None:
                start = x
            elif not pale and start is not None:
                rectangles.append((start/width, y/height, x/width, (y+1)/height))
                start = None
    if not 1 <= len(rectangles) <= 2048:
        raise ValueError('Unexpected spectral hand nail mask')
    return rectangles


def repair(pixels, width, height, pairs, rectangles):
    """Bounded color correction shared with the host's optional HD path."""
    current = list(map(float, pixels))
    regions, totals = [], defaultdict(float)
    radius = max(2., width/64)
    for pair in pairs:
        for side in (0, 1):
            uv_a, uv_b = pair[side]
            ax, ay = uv_a[0]*width-.5, uv_a[1]*height-.5
            dx, dy = (uv_b[0]-uv_a[0])*width, (uv_b[1]-uv_a[1])*height
            length = dx*dx+dy*dy
            if length < 1e-12:
                continue
            for y in range(max(0, math.floor(min(ay, ay+dy)-radius)),
                           min(height-1, math.ceil(max(ay, ay+dy)+radius))+1):
                for x in range(max(0, math.floor(min(ax, ax+dx)-radius)),
                               min(width-1, math.ceil(max(ax, ax+dx)+radius))+1):
                    t = min(1., max(0., ((x-ax)*dx+(y-ay)*dy)/length))
                    distance = math.hypot(x-ax-t*dx, y-ay-t*dy)
                    if distance >= radius:
                        continue
                    weight = .5+.5*math.cos(math.pi*distance/radius)
                    own = tuple(uv_a[k]+t*(uv_b[k]-uv_a[k]) for k in range(2))
                    other = tuple(pair[1-side][0][k]+t*(pair[1-side][1][k]-pair[1-side][0][k]) for k in range(2))
                    at = (y*width+x)*4
                    regions.append((at, weight, own, other))
                    totals[at] += weight
    strength = {}
    for at, total in totals.items():
        x, y = (at//4) % width, (at//4)//width
        u, v = (x+.5)/width, (y+.5)/height
        distance = min(max(x0-u, u-x1, y0-v, v-y1, 0.) for x0, y0, x1, y1 in rectangles)*512
        protection = min(1., max(0., (distance-1)/4))
        strength[at] = .8*protection/max(total, 1.)
    for _ in range(ITERATIONS):
        corrections = {at: [0., 0., 0.] for at in totals}
        for at, weight, own, other in regions:
            a, b = _sample(current, width, height, *own), _sample(current, width, height, *other)
            for c in range(3):
                corrections[at][c] += (b[c]-a[c])*.5*weight
        for at, values in corrections.items():
            for c in range(3):
                current[at+c] = min(255., max(0., current[at+c]+values[c]*strength[at]))
    return bytes(math.floor(v+.5) for v in current)


def _encode(aliases, pairs, rectangles):
    output = bytearray(b'DWHSEAM1'+struct.pack('<6I', 1, len(aliases), len(pairs), len(rectangles), ITERATIONS, 0))
    for alias in aliases:
        output += struct.pack('<6IQQ', *alias)
    for pair in pairs:
        output += struct.pack('<8f', *(v for side in pair for uv in side for v in uv))
    for rectangle in rectangles:
        output += struct.pack('<4f', *rectangle)
    output += struct.pack('<Q', fnv(output))
    return bytes(output)


def bake(raw):
    """Return a hand-only corrected RX1 and its disc-derived HD repair recipe."""
    model = hands._geometry(raw, 0)
    entries = []
    for tag, dictionary in rw.chunks(raw):
        if tag == 0x16:
            for child, native in rw.chunks(dictionary, 12):
                if child == 0x15:
                    for kind, value in rw.chunks(native, 12):
                        if kind == 1 and value[20:52].split(b'\0')[0] == OLD:
                            entries.append((value, _texture(value)))
    if len(entries) != 2 or sorted(row[1][2] for row in entries) != [128, 512]:
        raise ValueError('Missing spectral hand texture dictionaries')
    _, (_, pixels, width, height) = max(entries, key=lambda row: row[1][2])
    pairs, rectangles = _pairs(model, pixels, width, height), _protected(model, pixels, width, height)
    # Serialize/round recipe coordinates before both paths use them.
    pairs = [tuple(tuple(struct.unpack('<2f', struct.pack('<2f', *uv)) for uv in side)
                   for side in pair) for pair in pairs]
    rectangles = [struct.unpack('<4f', struct.pack('<4f', *r)) for r in rectangles]
    replacements, aliases = {}, []
    for value, (header, pixels, width, height) in entries:
        corrected = repair(pixels, width, height, pairs, rectangles)
        swizzled = bytearray(len(corrected))
        for y in range(height):
            for x in range(width):
                old, new = (y*width+x)*4, _address(x, y, width, height)*4
                swizzled[new:new+4] = corrected[old:old+4]
        updated = bytearray(header)
        updated[8:40] = NEW+bytes(32-len(NEW))
        struct.pack_into('<II', updated, 72, 0x0600, 0)
        updated[84] = 32
        struct.pack_into('<I', updated, 88, len(swizzled))
        replacements[value] = rw.rebuild(value, updated+swizzled)
        aliases.append((width, height, 1, 7, len(swizzled), 0, fnv(swizzled), fnv(value[104:])))
    def convert(part, depth=0):
        tag = struct.unpack_from('<I', part)[0]
        if tag in (0x16, 0x15):
            return rw.rebuild(part, b''.join(convert(value, depth+1) for _, value in rw.chunks(part, 12)))
        if part in replacements:
            return replacements[part]
        return part
    result = []
    for tag, part in rw.chunks(raw):
        if tag == 0x10:
            if part.count(OLD+b'\0') != 1 or len(OLD) != len(NEW):
                raise ValueError('Unexpected spectral hand material name')
            part = part.replace(OLD+b'\0', NEW+b'\0')
        result.append(convert(part))
    return b''.join(result), _encode(aliases, pairs, rectangles)
