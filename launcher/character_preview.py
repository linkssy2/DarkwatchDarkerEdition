"""Build private menu previews from the installed, verified original disc.

The distributed code contains no mesh, texture or animation payload. Thirty
samples of an original idle are baked locally; the menu supplies its rotation.
All integers/floats are little endian. Colors are RGBA bytes (R in the low byte).
"""
import hashlib
import math
import os
from pathlib import Path
import struct
import tempfile

import character_animation as animation
import character_archive as archive
import character_boss as boss
import character_content
import character_spectral_hands as skin

VERSION = 3
NAME = 'character-previews.pack'
MAGIC = b'DWCP0003'
FRAMES = 30
IDLE = 'characters/player_third/sanm/lo/jericho_idle.sanm'
IDLE_SHA = 'ed5897a5f771b88176e0f1dba0674776650b89563bacd2ded87451be25c9ac7e'
MAX_BYTES = 64 * 1024 * 1024
IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
MODELS = (
    animation.CHAZ, animation.CASSIDY, boss.MODEL+'.rx1',
    'characters/player_third/base_jerichociv.rx1',
    'characters/multiplayer/base_dwstormtrooper.rx1',
    'characters/multiplayer/base_dwstormtrooper_blue.rx1',
    'characters/multiplayer/base_dwstormtrooper_red.rx1',
    'characters/talaagent/base_agenttala.rx1',
    'characters/tala/base_cine_tala.rx1',
    'characters/player_roster/base_tala_boss.rx1',
)


def fnv(raw):
    value = 14695981039346656037
    for byte in raw:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def _normal(values):
    length = math.sqrt(sum(x*x for x in values))
    if not math.isfinite(length) or length < 1e-12:
        raise ValueError('Invalid preview normal')
    return tuple(x/length for x in values)


def _matrix(values):
    return tuple(values[:3])+(0.,)+tuple(values[3:6])+(0.,)+tuple(values[6:9])+(0.,)+tuple(values[9:12])+(1.,)


def _multiply(a, b):
    return tuple(sum(a[i*4+k]*b[k*4+j] for k in range(4)) for i in range(4) for j in range(4))


def _rgba(argb):
    return (argb & 0xff00ff00) | ((argb >> 16) & 255) | ((argb & 255) << 16)


def _textures(raw):
    """Use the largest authored dictionary and retain native HD identities."""
    output = {}
    for tag, a, z in animation._chunks(raw, 0, len(raw)):
        if tag != 0x16:
            continue
        for kind, p, end in animation._chunks(raw, a, z):
            if kind != 0x15:
                continue
            parts = list(animation._chunks(raw, p, end))
            if not parts or parts[0][0] != 1:
                raise ValueError('Missing preview texture structure')
            _, at, stop = parts[0]
            if stop-at < 92 or struct.unpack_from('<I', raw, at)[0] != 5:
                raise ValueError('Unsupported preview texture platform')
            name = raw[at+8:at+40].split(b'\0')[0].decode('ascii')
            w, h, depth, levels, _, compression, reported = struct.unpack_from('<HH4BI', raw, at+80)
            fmt = compression if compression in (12, 15) else 0 if compression == 0 and depth == 8 else -1
            if (not name or fmt < 0 or not 1 <= w <= 2048 or not 1 <= h <= 2048 or
                    w & (w-1) or h & (h-1) or not 1 <= levels <= max(w, h).bit_length()):
                raise ValueError('Unsupported preview texture layout')
            sizes = [(max(1, w >> i)*max(1, h >> i) if fmt == 0 else
                      ((max(1, w >> i)+3)//4)*((max(1, h >> i)+3)//4)*(8 if fmt == 12 else 16))
                     for i in range(levels)]
            palette_size = 1024 if fmt == 0 else 0
            count = sum(sizes)
            if reported < count or reported-count > 3 or at+92+palette_size+reported > stop:
                raise ValueError('Truncated preview texture payload')
            pixels = raw[at+92:at+92+palette_size+count]
            row = (w, h, fmt, pixels[:palette_size], pixels[palette_size:palette_size+sizes[0]], fnv(pixels))
            if name not in output or w*h > output[name][0]*output[name][1]:
                output[name] = row
    return output


def _mesh(raw):
    """Reuse the proven native skin decoder; preserve each batch's material."""
    textures = _textures(raw)
    output = dict(vertices=[], triangles=[], textures=[], parts=[])
    texture_ids = {}
    for geo, (a, z) in enumerate((a, z) for t, a, z, _ in boss._records(raw) if t == 15):
        data = skin._geometry(raw, geo)
        records = list(boss._records(raw, a, z, 15))
        materials = []
        for t, start, stop, _ in records:
            if t != 7:
                continue
            rows = list(boss._records(raw, start, stop, 7))
            names = [raw[p:e].rstrip(b'\0').decode('ascii') for k, p, e, parent in rows
                     if k == 2 and parent == 6 and raw[p:e].rstrip(b'\0')]
            structs = [(p, e) for k, p, e, parent in rows if k == 1 and parent == 7]
            if len(names) != 1 or len(structs) != 1 or structs[0][1]-structs[0][0] < 16:
                raise ValueError('Unsupported preview material')
            name = names[0]
            if name not in textures:
                raise ValueError('Missing preview material texture')
            if name not in texture_ids:
                texture_ids[name] = len(output['textures']); output['textures'].append(textures[name])
            tint = struct.unpack_from('<I', raw, structs[0][0]+4)[0]
            materials.append((texture_ids[name], tint))
        start, end = next((p, e) for t, p, e, _ in records if t == 0x510)
        header = start+16
        size = struct.unpack_from('<I', raw, header)[0]
        _, count, primitive, vertices, stride = struct.unpack_from('<HHIII', raw, header+4)
        vb = header+size
        batches = [struct.unpack_from('<6I', raw, header+36+i*24) for i in range(count)]
        pointers = sorted({row[4] for row in batches})
        if len(pointers) != len(materials) or any(b-a != 192 for a, b in zip(pointers, pointers[1:])):
            raise ValueError('Unsupported preview material pointer order')
        first = len(output['vertices'])
        for i, (position, uv, color, weights) in enumerate(zip(data['positions'], data['uv'], data['colors'], data['weights'])):
            packed = struct.unpack_from('<I', raw, vb+i*stride+12)[0]
            values = [(packed & 2047), ((packed >> 11) & 2047), ((packed >> 22) & 1023)]
            normal = _normal(tuple((v-(limit*2) if v & limit else v)/(limit-1)
                                   for v, limit in zip(values, (1024, 1024, 512))))
            output['vertices'].append((position, normal, uv, _rgba(color), weights))
        for _, _, n, relative, pointer, _ in batches:
            at = header-24+relative
            if at < header+36+count*24 or at+2*n > vb:
                raise ValueError('Invalid preview batch indices')
            indices = struct.unpack_from('<'+str(n)+'H', raw, at)
            if any(i >= vertices for i in indices) or primitive == 5 and n % 3:
                raise ValueError('Invalid preview triangle')
            texture, tint = materials[pointers.index(pointer)]
            for j in range(0, n-2, 3 if primitive == 5 else 1):
                tri = indices[j:j+3]
                if primitive == 6 and j % 2:
                    tri = (tri[1], tri[0], tri[2])
                if len(set(tri)) == 3:
                    output['triangles'].append(tuple(first+i for i in tri)+(texture, tint))
        output['parts'].append((first, len(output['vertices']), data['inverse']))
    if not output['vertices'] or not output['triangles'] or len(output['textures']) > 16:
        raise ValueError('Empty or oversized preview model')
    return output


def _tracks(raw, bones):
    _, parts = boss.sections(raw, bones)
    output = {}
    if 32 in parts:
        raise ValueError('Preview requires expanded rotation tracks')
    for bit in (4, 8):
        part = parts.get(bit)
        if not part:
            continue
        for bone, begin in enumerate(part['indices']):
            if begin == 0xffffffff:
                continue
            end = min([i for i in part['indices'] if i > begin and i != 0xffffffff]+[part['count']])
            keys = []
            for index in range(begin, end):
                at = part['keys']+index*part['stride']
                values = struct.unpack_from('<f4h' if bit == 4 else '<4f', raw, at)
                values = (values[0], *(_normal(values[1:]) if bit == 4 else values[1:]))
                if any(not math.isfinite(v) for v in values) or keys and values[0] < keys[-1][0]:
                    raise ValueError('Invalid preview animation key')
                keys.append(values)
            output[bone, bit] = keys
    return output


def _sample(keys, time, rotation):
    a = keys[0]
    for b in keys[1:]:
        if time <= b[0]:
            f = max(0., min(1., (time-a[0])/(b[0]-a[0]))) if b[0] > a[0] else 0.
            sign = -1 if rotation and sum(x*y for x, y in zip(a[1:], b[1:])) < 0 else 1
            result = tuple(x*(1-f)+y*sign*f for x, y in zip(a[1:], b[1:]))
            return _normal(result) if rotation else result
        a = b
    return a[1:]


def _poses(raw, clip, mesh, cancel):
    bones = len(mesh['parts'][0][2])
    rig, frames, _ = boss.rig(raw, bones)
    by_frame = {row['frame']: bone for bone, row in rig.items()}
    tracks = _tracks(clip, bones)
    duration = struct.unpack_from('<f', clip, 12)[0]
    if not .1 <= duration <= 10:
        raise ValueError('Invalid preview idle duration')
    output = []
    for frame in range(FRAMES):
        cancel(); time = duration*frame/FRAMES
        world = []
        for index, values in enumerate(frames):
            local = list(_matrix(values)) if index else list(IDENTITY)
            bone = by_frame.get(index)
            if (bone, 4) in tracks:
                matrix = animation._quaternion_matrix(_sample(tracks[bone, 4], time, True))
                for i in range(3):
                    local[i*4:i*4+3] = matrix[i]
            if (bone, 8) in tracks:
                local[12:15] = _sample(tracks[bone, 8], time, False)
            world.append(_multiply(local, world[values[12]]) if values[12] >= 0 else local)
        positions = []
        for first, last, inverses in mesh['parts']:
            # RenderWare's fourth column holds flags/padding, not affine values.
            matrices = [_multiply(_matrix(inv[:3]+inv[4:7]+inv[8:11]+inv[12:15]),
                                  world[rig[i]['frame']]) for i, inv in enumerate(inverses)]
            for position, normal, _, _, weights in mesh['vertices'][first:last]:
                point, direction = [0.]*3, [0.]*3
                for bone, weight in weights.items():
                    m = matrices[bone]
                    for j in range(3):
                        point[j] += (sum(position[i]*m[i*4+j] for i in range(3))+m[12+j])*weight
                        direction[j] += sum(normal[i]*m[i*4+j] for i in range(3))*weight
                positions.append(tuple(point)+_normal(direction))
        output.append(positions)
    return duration, output


def _clip(poly, axis, bound, positive):
    result = []
    for a, b in zip(poly, poly[1:]+poly[:1]):
        ain = a[axis] >= bound if positive else a[axis] <= bound
        bin = b[axis] >= bound if positive else b[axis] <= bound
        if ain:
            result.append(a)
        if ain != bin:
            t = (bound-a[axis])/(b[axis]-a[axis])
            result.append(tuple(x+t*(y-x) for x, y in zip(a, b)))
    return result


def _wrap(mesh):
    """Split wrapping UVs at tile edges before placing textures in an atlas."""
    vertices, triangles, seen = [], [], {}
    for a, b, c, texture, tint in mesh['triangles']:
        ids = (a, b, c)
        uv = [mesh['vertices'][i][2] for i in ids]
        if any(not math.isfinite(v) or abs(v) > 8 for p in uv for v in p):
            raise ValueError('Unsupported preview UV extent')
        for x in range(math.floor(min(p[0] for p in uv)), math.floor(max(p[0] for p in uv))+1):
            for y in range(math.floor(min(p[1] for p in uv)), math.floor(max(p[1] for p in uv))+1):
                poly = [(*p, float(i == 0), float(i == 1), float(i == 2)) for i, p in enumerate(uv)]
                for axis, edge, positive in ((0, x, True), (0, x+1, False), (1, y, True), (1, y+1, False)):
                    poly = _clip(poly, axis, edge, positive)
                    if not poly:
                        break
                if len(poly) < 3:
                    continue
                for i in range(1, len(poly)-1):
                    corners = [poly[0], poly[i], poly[i+1]]
                    p, q, r = corners
                    # A flat-color triangle can have zero UV area but real geometry.
                    if abs((q[3]-p[3])*(r[4]-p[4])-(q[4]-p[4])*(r[3]-p[3])) < 1e-12:
                        continue
                    tri = []
                    for p in corners:
                        refs = tuple(sorted((index, round(weight, 10)) for index, weight in zip(ids, p[2:]) if weight > 1e-10))
                        u, v = max(0., min(1., p[0]-x)), max(0., min(1., p[1]-y))
                        key = (refs, round(u, 8), round(v, 8))
                        if key not in seen:
                            color = sum(max(0, min(255, round(sum(((mesh['vertices'][index][3] >> shift) & 255)*w
                                                        for index, w in refs)))) << shift for shift in (0, 8, 16, 24))
                            seen[key] = len(vertices); vertices.append((u, v, color, refs))
                        tri.append(seen[key])
                    triangles.append((*tri, texture, tint))
    if not 0 < len(vertices) <= 12000 or not 0 < len(triangles) <= 24000:
        raise ValueError('Preview mesh exceeds bounds after UV wrapping')
    return vertices, triangles


def build(read, cancel=lambda: None):
    idle = read(IDLE)
    if hashlib.sha256(idle).hexdigest() != IDLE_SHA:
        raise ValueError('Unsupported character preview idle')
    chaz = read(MODELS[0])
    reference = animation.frames(chaz)
    output = bytearray(struct.pack('<8sII', MAGIC, VERSION, len(MODELS)))
    for identity, name in enumerate(MODELS):
        raw = chaz if identity == 0 else read(name)
        clip = idle
        if identity in (2, 9):
            clip, _ = animation.retarget(idle, boss.body_parameters(chaz, raw))
            clip = boss.expand_player(clip)
        elif identity:
            clip, _ = animation.retarget(idle, animation.parameters(reference, animation.frames(raw)))
        cancel(); mesh = _mesh(raw)
        duration, poses = _poses(raw, clip, mesh, cancel)
        vertices, triangles = _wrap(mesh)
        output += struct.pack('<5If', identity, len(vertices), len(triangles), len(mesh['textures']), FRAMES, duration)
        for w, h, fmt, palette, pixels, native_hash in mesh['textures']:
            output += struct.pack('<5IQ', w, h, fmt, len(palette), len(pixels), native_hash)+palette+pixels
        for u, v, color, _ in vertices:
            output += struct.pack('<2fI', u, v, color)
        for tri in triangles:
            output += struct.pack('<5I', *tri)
        for pose in poses:
            cancel()
            for _, _, _, refs in vertices:
                value = tuple(sum(pose[index][i]*weight for index, weight in refs) for i in range(6))
                value = value[:3]+_normal(value[3:])
                if any(not math.isfinite(v) or abs(v) > 1000 for v in value):
                    raise ValueError('Invalid preview pose')
                output += struct.pack('<6f', *value)
    if len(output) > MAX_BYTES-8:
        raise ValueError('Preview pack exceeds bounds')
    output += struct.pack('<Q', fnv(output))
    return bytes(output)


def prepare(assets, output, cancel=lambda: None):
    """Atomically create the cache from a complete admitted local installation."""
    source = Path(assets)/'packfile.pck'
    size, expected = character_content.INSTALLED['packfile.pck']
    if source.stat().st_size != size:
        raise ValueError('Character preview archive size differs')
    raw = source.read_bytes(); cancel()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Character preview archive identity differs')
    table = archive.read(raw)
    entries = {row['name']: row for row in table['entries']}
    def read(name):
        cancel()
        row = entries.get(name)
        if not row:
            raise ValueError('Missing character preview resource: '+name)
        return raw[row['offset']:row['offset']+row['size']]
    payload = build(read, cancel)
    output = Path(output)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.character-preview-', dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name); stream.write(payload)
        cancel(); os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return dict(version=VERSION, size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
