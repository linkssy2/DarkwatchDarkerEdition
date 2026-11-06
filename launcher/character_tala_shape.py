"""Derive Tala's presentation mesh from verified, locally prepared disc models.

Original Tala textures, skin donors, rig and materials remain authoritative.
"""
import hashlib
import math
import struct

import character_repaint as rw
import character_spectral_hands as skin


SOURCE_SHA256 = '4b0262b4f9cda044eb915e6d5141e8c666a2a8bf4fb8c8faf21e84bbafd81143'
REFERENCE_SHA256 = '08d3c57bc2e28f5a38c26e86f2798b8fa60f47c5552d5ea7cef588ddaddf8ad0'
CHEEK_FULLNESS = .065


def _sub(a, b): return tuple(x-y for x, y in zip(a, b))
def _dot(a, b): return sum(x*y for x, y in zip(a, b))
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _mix(a, b, t): return tuple(x+(y-x)*t for x, y in zip(a, b))
def _key(point): return tuple(round(v, 6) for v in point)


def _smooth(low, high, value):
    t = min(1., max(0., (value-low)/(high-low)))
    return t*t*(3.-2.*t)


def _influence(point):
    x, y, z = point
    return (_smooth(-.25, -.16, y)*(1.-_smooth(.075, .16, y))
            *(1.-_smooth(.18, .25, abs(x)))*_smooth(-.03, .015, -z))


def _radial(point, triangle):
    """Intersect the reference at the same height and horizontal polar angle."""
    a, b, c = triangle
    direction = (point[0]-.09, 0., point[2])
    origin = (.09, point[1], 0.)
    ab, ac = _sub(b, a), _sub(c, a)
    h = _cross(direction, ac)
    determinant = _dot(ab, h)
    if abs(determinant) < 1e-12: return None
    s = _sub(origin, a)
    u = _dot(s, h)/determinant
    q = _cross(s, ab)
    v = _dot(direction, q)/determinant
    distance = _dot(ac, q)/determinant
    if u < -1e-7 or v < -1e-7 or u+v > 1+1e-7 or distance <= 0.: return None
    return distance, u, v


def _decode_normal(value):
    pieces = value & 2047, (value >> 11) & 2047, (value >> 22) & 1023
    return tuple((v-2*s if v & s else v)/(s-1) for v, s in zip(pieces, (1024, 1024, 512)))


def _pack_normal(normal):
    length = math.sqrt(_dot(normal, normal))
    if length < 1e-12: raise ValueError('Degenerate Tala surface normal')
    x, y, z = (v/length for v in normal)
    return (round(x*1023)&2047)|((round(y*1023)&2047)<<11)|((round(z*511)&1023)<<22)


def _sections(model):
    native = skin._one(skin._one(skin._one(model['geometry'], 3), 0x510), 1)
    size = struct.unpack_from('<I', native, 16)[0]
    count, stride = struct.unpack_from('<2I', native, 28)
    if count != len(model['positions']) or stride not in (28, 36) or 16+size+count*stride != len(native):
        raise ValueError('Invalid radial-reference vertex buffer')
    normals = [_decode_normal(struct.unpack_from('<I', native, 16+size+i*stride+12)[0]) for i in range(count)]
    result = []
    for tri in model['triangles']:
        points = [model['positions'][i] for i in tri]
        normal = _cross(_sub(points[1], points[0]), _sub(points[2], points[0]))
        if (min(p[0] for p in points) >= -1e-5 and max(p[0] for p in points) <= .28
                and min(p[1] for p in points) >= -.35 and max(p[1] for p in points) <= .22
                and _dot(normal, normal) > 1e-16):
            result.append((points, [normals[i] for i in tri]))
    return result


def _section_hit(point, sections):
    best = None
    for triangle, normals in sections:
        hit = _radial(point, triangle)
        if hit is not None and (best is None or hit[0] > best[0]):
            distance, u, v = hit
            normal = tuple(normals[0][i]*(1-u-v)+normals[1][i]*u+normals[2][i]*v for i in range(3))
            best = distance, normal
    return best


def _fullness_weight(point):
    x, y, z = point
    return (_smooth(-.145, -.075, y)*(1.-_smooth(.025, .10, y))
            *_smooth(.015, .05, abs(x))*(1.-_smooth(.15, .215, abs(x)))
            *_smooth(.005, .05, -z))


def _rounded_section_hit(point, sections):
    """Small neighboring section samples soften the reference's planar ridges."""
    hit = _section_hit(point, sections)
    weight = _fullness_weight(point)
    if hit is None or weight == 0.: return hit
    radius = math.hypot(point[0]-.09, point[2])
    angle = math.atan2(point[0]-.09, -point[2])
    center_radius = radius*hit[0]
    total_radius = 2*center_radius
    total_normal = [2*v for v in hit[1]]
    for dy, da in ((-.006, 0.), (.006, 0.), (0., -.055), (0., .055)):
        query = (.09+math.sin(angle+da), point[1]+dy, -math.cos(angle+da))
        sample = _section_hit(query, sections)
        sample_radius, normal = sample if sample is not None else (center_radius, hit[1])
        total_radius += sample_radius
        for i in range(3): total_normal[i] += normal[i]
    return ((center_radius+(total_radius/6-center_radius)*weight)/radius,
            _mix(hit[1], tuple(v/6 for v in total_normal), weight))


def _fuller_point(point):
    factor = 1.+CHEEK_FULLNESS*_fullness_weight(point)
    return (.09+(point[0]-.09)*factor, point[1], point[2]*factor)


def _fuller_normal(point, normal):
    # Inverse-transpose transport preserves lighting through the soft bulge edge.
    step = 1e-5
    columns = []
    for axis in range(3):
        lo, hi = list(point), list(point)
        lo[axis] -= step;hi[axis] += step
        columns.append(tuple(v/(2*step) for v in _sub(_fuller_point(hi), _fuller_point(lo))))
    cofactors = (_cross(columns[1], columns[2]), _cross(columns[2], columns[0]), _cross(columns[0], columns[1]))
    if _dot(columns[0], cofactors[0]) <= 0.: raise ValueError('Inverted cheek fullness field')
    return tuple(sum(cofactors[j][i]*normal[j] for j in range(3)) for i in range(3))


def _rotate_normal(normal, old, new):
    old, new = [tuple(v/math.sqrt(_dot(n, n)) for v in n) for n in (old, new)]
    axis, cosine = _cross(old, new), max(-1., min(1., _dot(old, new)))
    if cosine < -.999: raise ValueError('Opposed radial-reference normals')
    first = _cross(axis, normal);second = _cross(axis, first)
    return tuple(normal[j]+first[j]+second[j]/(1+cosine) for j in range(3))


def _weights(weights):
    if len(weights) > 4: raise ValueError('Tala subdivision exceeds four skin donors')
    order = sorted(weights, key=lambda bone: (-weights[bone], bone))
    values = [math.floor(weights[bone]*255) for bone in order]
    for i in sorted(range(len(order)), key=lambda i: (-(weights[order[i]]*255-values[i]), order[i]))[:255-sum(values)]:
        values[i] += 1
    return dict(zip(order, values))


def _build(data, reference):
    """Return native bytes and original-vertex/triangle provenance for verification."""
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256 or hashlib.sha256(reference).hexdigest() != REFERENCE_SHA256:
        raise ValueError('Expected the pinned prepared Tala and Spectral Cassidy bodies')
    model, target = skin._geometry(data, 0), skin._geometry(reference, 1)
    geometry = model['geometry']
    extension = skin._one(geometry, 3)
    native = skin._one(skin._one(extension, 0x510), 1)
    header = 16
    size = struct.unpack_from('<I', native, header)[0]
    serial, count, primitive, original_count, stride = struct.unpack_from('<HHIII', native, header+4)
    if (count, primitive, original_count, stride) != (4, 6, 2696, 28):
        raise ValueError('Unexpected Tala native mesh')
    batches = [struct.unpack_from('<6I', native, header+36+i*24) for i in range(count)]
    positions = list(model['positions'])
    vertices = [native[header+size+i*stride:header+size+(i+1)*stride] for i in range(original_count)]
    weights = list(model['weights'])
    sources = [{i: 1.} for i in range(original_count)]
    triangles, materials = [], []
    for material, row in enumerate(batches):
        indices = struct.unpack_from('<'+'H'*row[2], native, header-24+row[3])
        for i in range(len(indices)-2):
            tri = indices[i:i+3]
            if len(set(tri)) == 3:
                triangles.append(tri if i % 2 == 0 else (tri[1], tri[0], tri[2]))
                materials.append(material)
    if triangles != model['triangles']: raise ValueError('Tala strip decode disagrees')
    parents = list(range(len(triangles)))
    for iteration in range(3):
        edges = {}
        for tri in triangles:
            for a, b in zip(tri, (*tri[1:], tri[0])):
                edge = tuple(sorted((a, b)))
                key = tuple(sorted((_key(positions[a]), _key(positions[b]))))
                edges.setdefault(key, set()).add(edge)
        selected = set()
        for variants in edges.values():
            a, b = min(variants)
            middle = _mix(positions[a], positions[b], .5)
            if (_influence(middle) > .001 and math.dist(positions[a], positions[b]) > .018
                    and all(len(weights[i].keys() | weights[j].keys()) <= 4 for i, j in variants)):
                selected.update(variants)
        midpoints = {}
        for a, b in sorted(selected):
            midpoints[a, b] = len(positions)
            positions.append(_mix(positions[a], positions[b], .5))
            weights.append({bone: (weights[a].get(bone, 0.)+weights[b].get(bone, 0.))*.5
                            for bone in weights[a].keys() | weights[b].keys()})
            sources.append({i: (sources[a].get(i, 0.)+sources[b].get(i, 0.))*.5
                            for i in sources[a].keys() | sources[b].keys()})
            na, nb = (_decode_normal(struct.unpack_from('<I', vertices[i], 12)[0]) for i in (a, b))
            ca, cb = (struct.unpack_from('<I', vertices[i], 16)[0] for i in (a, b))
            color = sum(round((((ca >> shift)&255)+((cb >> shift)&255))*.5) << shift for shift in (0, 8, 16, 24))
            ua, ub = (struct.unpack_from('<2f', vertices[i], 20) for i in (a, b))
            vertices.append(struct.pack('<3fII2f', *positions[-1], _pack_normal(_mix(na, nb, .5)), color, *_mix(ua, ub, .5)))
        expanded, new_materials, new_parents = [], [], []
        for tri, material, parent in zip(triangles, materials, parents):
            a, b, c = tri
            ab, bc, ca = (midpoints.get(tuple(sorted(edge))) for edge in ((a, b), (b, c), (c, a)))
            mask = (ab is not None)+2*(bc is not None)+4*(ca is not None)
            parts = {0: [tri], 1: [(a, ab, c), (ab, b, c)], 2: [(b, bc, a), (bc, c, a)],
                     4: [(c, ca, b), (ca, a, b)], 3: [(b, bc, ab), (ab, bc, c), (a, ab, c)],
                     6: [(c, ca, bc), (bc, ca, a), (b, bc, a)],
                     5: [(a, ab, ca), (ca, ab, b), (c, ca, b)],
                     7: [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]}[mask]
            expanded.extend(parts);new_materials.extend([material]*len(parts));new_parents.extend([parent]*len(parts))
        triangles, materials, parents = expanded, new_materials, new_parents
    if len(positions) >= 65536: raise ValueError('Tala local subdivision exceeds native indices')
    # Center seam records share X ~= 0, but can belong to opposite cheek faces.
    # Their incident triangles, not floating-point coordinate sign, define which
    # reference normal frame to use. Shared center records use both frames.
    center_sides = {i: set() for i, p in enumerate(positions)
                    if abs(p[0]) < 1e-7 and -.09 < p[1] < .16 and p[2] < -.035}
    for triangle in triangles:
        x = sum(positions[i][0] for i in triangle)
        if abs(x) > 1e-7:
            for i in triangle:
                if i in center_sides: center_sides[i].add(-1 if x < 0 else 1)
    target_sections, source_sections = _sections(target), _sections(model)
    if len(target_sections) < 100: raise ValueError('Missing Cassidy rear reference surface')
    moved, transferred_normals = [], []
    for i, (point, vertex) in enumerate(zip(positions, vertices)):
        normal = _decode_normal(struct.unpack_from('<I', vertex, 12)[0])
        transferred_normals.append(normal)
        amount = _influence(point)
        # Keep the original crotch/thigh junction while matching the outer cheeks.
        amount *= 1.-(1.-_smooth(.01, .045, abs(point[0])))*(1.-_smooth(-.095, -.055, point[1]))
        if not amount:
            moved.append(point);continue
        query = (abs(point[0]), point[1], point[2])
        fitted, original = _rounded_section_hit(query, target_sections), _section_hit(query, source_sections)
        if fitted is None or original is None:
            moved.append(point);continue
        ratio = fitted[0]/original[0]
        closest = (.09+(query[0]-.09)*ratio, query[1], query[2]*ratio)
        new_normal = _fuller_normal(closest, fitted[1])
        closest = _fuller_point(closest)
        closest = (query[0]+(closest[0]-query[0])*_smooth(0., .035, query[0]), closest[1], closest[2])
        closest = (math.copysign(closest[0], point[0]), closest[1], closest[2])
        moved.append(_mix(point, closest, amount))
        sides = center_sides.get(i) or {-1 if point[0] < 0 else 1}
        rotated = []
        for side in sorted(sides):
            old_frame = (original[1][0]*side, *original[1][1:])
            new_frame = (new_normal[0]*side, *new_normal[1:])
            rotated.append(_rotate_normal(normal, old_frame, new_frame))
        fitted_normal = tuple(sum(n[axis] for n in rotated)/len(rotated) for axis in range(3))
        transferred_normals[-1] = _mix(normal, fitted_normal, amount)
    for i in range(len(positions)):
        vertex = bytearray(vertices[i])
        struct.pack_into('<3f', vertex, 0, *moved[i])
        if positions[i] != moved[i]: struct.pack_into('<I', vertex, 12, _pack_normal(transferred_normals[i]))
        vertices[i] = bytes(vertex)
    grouped = [[tri for tri, m in zip(triangles, materials) if m == material] for material in range(count)]
    output_parents = [parent for material in range(count) for parent, m in zip(parents, materials) if m == material]
    indices = [[i for tri in group for i in tri] for group in grouped]
    align = lambda n: (n+15)&~15
    offset = align(24+36+24*count)-24
    rebuilt = bytearray(offset)
    for material, (row, ids) in enumerate(zip(batches, indices)):
        struct.pack_into('<6I', rebuilt, 36+24*material, min(ids), max(ids)-min(ids)+1,
                         len(ids), len(rebuilt)+24, row[4], row[5])
        rebuilt.extend(struct.pack('<'+'H'*len(ids), *ids))
        rebuilt.extend(bytes(align(len(rebuilt))-len(rebuilt)))
    # Serialized native pointers are cleared; vertexAlpha is an actual flag.
    vertex_alpha = struct.unpack_from('<I', native, header+24)[0]
    struct.pack_into('<IHH7I', rebuilt, 0, len(rebuilt), serial, count, 5, len(vertices), stride, 0, vertex_alpha, 0, 0)
    new_native = skin._chunk(0x510, skin._chunk(1, struct.pack('<I', 5)+rebuilt+b''.join(vertices)))
    old_skin = skin._one(skin._one(extension, 0x116), 1)
    prefix = old_skin[12:12+2072]
    palette, reverse = struct.unpack_from('<256i', prefix, 8), struct.unpack_from('<256i', prefix, 1032)
    skin_rows = bytearray(old_skin[12+2072:12+2072+original_count*12])
    for row in weights[original_count:]:
        quantized = _weights(row)
        bones = list(quantized)+[0]*(4-len(quantized));values = list(quantized.values())+[0]*(4-len(quantized))
        if any(value and (reverse[bone] < 0 or palette[reverse[bone]] != bone) for bone, value in zip(bones, values)):
            raise ValueError('Unmapped Tala midpoint skin donor')
        skin_rows.extend(bytes(values)+struct.pack('<4H', *(max(0, reverse[bone])*3 for bone in bones)))
    new_skin = skin._chunk(0x116, skin._chunk(1, prefix+skin_rows+model['inverse_bytes']+bytes(12)))
    pointers = sorted({row[4] for row in batches})
    mesh_values = [0, count, sum(len(row) for row in indices)]
    for row, ids in zip(batches, indices): mesh_values.extend((len(ids), pointers.index(row[4])))
    replacements = {0x510: new_native, 0x116: new_skin,
                    0x50e: skin._chunk(0x50e, struct.pack('<'+'I'*len(mesh_values), *mesh_values))}
    new_extension = rw.rebuild(extension, b''.join(replacements.get(tag, part) for tag, part in rw.chunks(extension, 12)))
    structure = bytearray(skin._one(geometry, 1))
    struct.pack_into('<2I', structure, 16, len(triangles), len(vertices))
    center, radius = struct.unpack_from('<3f', structure, 28), struct.unpack_from('<f', structure, 40)[0]
    radius = max(radius, max(math.dist(p, center) for p in moved)+1e-6)
    struct.pack_into('<f', structure, 40, radius)
    new_geometry = rw.rebuild(geometry, b''.join(bytes(structure) if tag == 1 else new_extension if tag == 3 else part
                                               for tag, part in rw.chunks(geometry, 12)))
    clump = next(part for tag, part in rw.chunks(data) if tag == 16)
    geolist = skin._one(clump, 26)
    geolist = rw.rebuild(geolist, b''.join(new_geometry if tag == 15 else part for tag, part in rw.chunks(geolist, 12)))
    clump = rw.rebuild(clump, b''.join(geolist if tag == 26 else part for tag, part in rw.chunks(clump, 12)))
    output = b''.join(clump if tag == 16 else part for tag, part in rw.chunks(data))
    return output, dict(candidate_sha256=hashlib.sha256(output).hexdigest(),
                        vertex_sources=[sorted(row.items()) for row in sources], triangle_parents=output_parents,
                        original_vertices=original_count, vertices=len(vertices), triangles=len(triangles),
                        reference_triangles=len(target_sections), maximum_edge_length=.018, subdivision_passes=3)


def reshape(data, reference):
    return _build(data, reference)[0]


def upper_motion(data):
    """Extend the accepted remesh's upper cheek motion without reshaping."""
    if hashlib.sha256(data).hexdigest() != '935dd3a48c61b79e31d4deb836a374d92f493993765eb61d63cd564258d85d3f':
        raise ValueError('Expected the accepted Boss Tala remesh')
    model = skin._geometry(data, 0)
    extension = skin._one(model['geometry'], 3)
    chunk = skin._one(skin._one(extension, 0x116), 1)
    prefix = chunk[12:12+2072]
    palette, reverse = struct.unpack_from('<256i', prefix, 8), struct.unpack_from('<256i', prefix, 1032)
    rows = bytearray(chunk[12+2072:12+2072+len(model['positions'])*12])
    for i, (x, y, z) in enumerate(model['positions']):
        # The remesh reaches above the original 6.5 cm waist cutoff. Blend
        # its upper cheeks to the unchanged lower-back anchor at 15 cm.
        height = _smooth(.015, .055, y)*(1.-_smooth(.075, .15, y))
        radius = ((abs(x)-.10)/.13)**2+((z+.09)/.12)**2
        cap = .20*max(0., 1.-radius)**2*_smooth(.012, .045, abs(x))*_smooth(.02, .06, -z)
        at = i*12
        ids = struct.unpack_from('<4H', rows, at+4)
        weights = {palette[j//3]: value for j, value in zip(ids, rows[at:at+4]) if value}
        helper = 24 if x > 0 else 25
        old = weights.get(helper, 0)
        transfer = min(weights.get(0, 0), max(0, round((cap*255-old)*height)))
        if not transfer:
            continue
        weights[0] -= transfer
        weights[helper] = old+transfer
        ordered = sorted(((bone, value) for bone, value in weights.items() if value),
                         key=lambda row: (-row[1], row[0]))
        if len(ordered) > 4 or sum(value for _, value in ordered) != 255:
            raise ValueError('Invalid upper-cheek skin transfer')
        ordered += [(0, 0)]*(4-len(ordered))
        rows[at:at+4] = bytes(value for _, value in ordered)
        struct.pack_into('<4H', rows, at+4, *(max(0, reverse[bone])*3 for bone, _ in ordered))
    replacement = rw.rebuild(chunk, prefix+rows+chunk[12+2072+len(rows):])
    old = skin._one(extension, 0x116)
    replacement = rw.rebuild(old, replacement)
    # Equal-length skin-only replacement leaves every original asset byte else intact.
    if data.count(old) != 1 or len(old) != len(replacement):
        raise ValueError('Ambiguous Tala skin chunk')
    return data.replace(old, replacement, 1)
