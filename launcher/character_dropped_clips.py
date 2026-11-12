"""Derive persistent dropped magazines from the user's original disc."""

import hashlib
import math
import struct
import xml.etree.ElementTree as ET
import character_assets as art
import character_boss as boss
import character_repaint as rw
import character_spectral_hands as skin

SOURCE = 'accessories/weapons/dwrevolver/base_pov_dwrevolver.rx1'

SOURCE_SHA = '5a5c05c437a5d1ed6b2e3ed33724d612a6439a2a532cf179c47c466132dcb788'

MODEL = 'accessories/weapons/darker_private/redeemer_dropped_clip'

ACTOR = 'DarkerPrivateRedeemerDroppedClip'

STATIC = 'accessories/flair/gunslingerhat/gunslinger_hat.rx1'

DUAL_SOURCE = 'accessories/weapons/doublepistol/base_pov_doublepistol.rx1'

DUAL_SOURCE_SHA = '8ca58b473a6a5dd4209983fa66acc61f6d0eca426cc8e9b712e382d542b7179a'

CROSSBOW_SOURCE = 'accessories/weapons/dwcrossbow/base_pov_dwcrossbow.rx1'

CROSSBOW_SOURCE_SHA = 'e7ba4cfda7d83395babf8933136d6d9cb14150137f60b43aad8fe4e6ffe8f5d4'

def chunk(tag, data):
    return struct.pack('<3I', tag, len(data), 402915327) + data

def only(raw, kind):
    return skin._one(raw, kind)

def derive(raw, static, *, dual=False, crossbow=False):
    if dual and crossbow:
        raise ValueError('One source weapon required')
    path, digest, vertices, tri_count, batches, material_index = (DUAL_SOURCE, DUAL_SOURCE_SHA, 34, 24, 2, 1) if dual else (SOURCE, SOURCE_SHA, 40, 32, 3, 0)
    bones, part = (5, 2)
    if crossbow:
        path, digest, vertices, tri_count, batches, material_index = (CROSSBOW_SOURCE, CROSSBOW_SOURCE_SHA, 52, 44, 2, 1)
        bones, part = (8, 1)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Unsupported original magazine model')
    source = skin._geometry(raw, 0, (bones,))
    selected = {i for i, weights in enumerate(source['weights']) if weights == {part: 1.0}}
    triangles = [tri for tri in source['triangles'] if all((i in selected for i in tri))]
    if len(selected) != vertices or len(triangles) != tri_count:
        raise ValueError('Unexpected native magazine island')
    if any((any((i in selected for i in tri)) and (not all((i in selected for i in tri))) for tri in source['triangles'])):
        raise ValueError('Magazine shares faces with the held gun')
    used = sorted({i for tri in triangles for i in tri})
    if set(used) != selected:
        raise ValueError('Unreferenced magazine vertices')
    remap = {old: new for new, old in enumerate(used)}
    points = [skin._point(source['positions'][i], source['inverse'][part]) for i in used]
    center = tuple(((min((p[k] for p in points)) + max((p[k] for p in points))) / 2 for k in range(3)))
    positions = [tuple((p[k] - center[k] for k in range(3))) for p in points]
    half_extents = tuple((max((abs(p[k]) for p in positions)) for k in range(3)))
    radius = max((math.dist((0.0, 0.0, 0.0), p) for p in positions))
    indices = [remap[i] for tri in triangles for i in tri]
    model = {'positions': positions, 'triangles': [tuple((remap[i] for i in tri)) for tri in triangles]}
    normals = skin._normals(model)
    vertex_bytes = b''.join((struct.pack('<3fII2f', *p, n, source['colors'][i], *source['uv'][i]) for i, p, n in zip(used, positions, normals)))
    na, nz = next(((a, z) for t, a, z, _ in boss._records(raw) if t == 1296))
    header_at = na + 16
    if struct.unpack_from('<H', raw, header_at + 6)[0] != batches:
        raise ValueError('Original material batch count changed')
    for batch in range(batches):
        row = struct.unpack_from('<6I', raw, header_at + 36 + batch * 24)
        values = struct.unpack_from('<' + str(row[2]) + 'H', raw, header_at - 24 + row[3])
        if bool(set(values) & selected) != (batch == material_index):
            raise ValueError('Original magazine material batch changed')
    materials = [part for tag, part in rw.chunks(only(source['geometry'], 8), 12) if tag == 7]
    material = chunk(8, chunk(1, struct.pack('<2I', 1, 4294967295)) + materials[material_index])
    align = lambda n: n + 15 & ~15
    index_at = align(24 + 36 + 24) - 24
    header = bytearray(index_at + align(len(indices) * 2))
    struct.pack_into('<IHH7I', header, 0, len(header), 1, 1, 5, len(used), 28, 0, 0, 0, 0)
    struct.pack_into('<6I', header, 36, 0, len(used), len(indices), index_at + 24, 0, 0)
    struct.pack_into('<' + str(len(indices)) + 'H', header, index_at, *indices)
    native = chunk(1296, chunk(1, struct.pack('<I', 5) + header + vertex_bytes))
    mesh = chunk(1294, struct.pack('<5I', 0, 1, len(indices), len(indices), 0))
    extension = chunk(3, mesh + native + chunk(1297, struct.pack('<I', 1349)))
    gs = bytearray(only(source['geometry'], 1)[12:])
    struct.pack_into('<3I', gs, 4, len(triangles), len(used), 1)
    struct.pack_into('<4f', gs, 16, 0.0, 0.0, 0.0, radius)
    geometry = chunk(15, chunk(1, gs) + material + extension)
    native_clump = next((part for tag, part in rw.chunks(static) if tag == 16))
    frames = only(native_clump, 14)
    frame_structure = bytearray(only(frames, 1))
    count = struct.unpack_from('<I', frame_structure, 12)[0]
    if count != 2:
        raise ValueError('Unexpected native static-prop frame contract')
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
    for frame in range(count):
        struct.pack_into('<12f', frame_structure, 16 + frame * 56, *identity)
    frames = rw.rebuild(frames, b''.join((bytes(frame_structure) if tag == 1 else part for tag, part in rw.chunks(frames, 12))))
    pieces = []
    for tag, part in rw.chunks(native_clump, 12):
        if tag == 14:
            part = frames
        elif tag == 26:
            part = chunk(26, chunk(1, struct.pack('<I', 1)) + geometry)
        pieces.append(part)
    clump = rw.rebuild(native_clump, b''.join(pieces))
    platform = next((part for tag, part in rw.chunks(static) if tag == 36))
    dictionaries = [part for tag, part in rw.chunks(raw) if tag == 22]
    result = platform + b''.join(dictionaries) + clump
    metadata = dict(source=path, source_sha256=digest, source_vertices=len(source['positions']), retained_vertices=len(used), retained_triangles=len(triangles), part_bone=1 if crossbow else 2, geometry_center_in_part=list(center), visual_radius=radius, half_extents=list(half_extents), uv_bytes_preserved=True, native_static_template=STATIC, prototype_collision='native enclosing sphere; box refinement needed before final visual acceptance', output_sha256=hashlib.sha256(result).hexdigest())
    return (result, metadata)

def node(name, attributes=None, children=()):
    return dict(name=name, attributes=attributes or {}, children=list(children), value=None)

def param(name, kind, value):
    return node('param', dict(name=name, type=kind, value=str(value)))

def actor(radius):
    return node('actor', {'name': ACTOR, 'category': 'PRIVATE - Clip Physics'}, [node('component', {'name': 'RenderComponent'}, [param('m_modelResourcePath', 'filename', MODEL), param('m_visibleIn', 'menu', 'All'), param('m_boundSphereOverride', 'bool', 'true'), param('m_boundSphereRadius', 'float', radius)]), node('component', {'name': 'HavokMotionComponent'}, [param('m_RigidBodyFileName', 'filename', ''), param('m_defaultRadius', 'float', radius), param('m_mass', 'float', 1), param('m_useGravity', 'bool', 'true'), param('m_elasticity', 'float', 0.15), param('m_dampingRateAir', 'float', 0.01), param('m_dampingRateSpin', 'float', 0.1), param('m_dampingRateContact', 'float', 0.8), param('m_collideAsGib', 'bool', 'true'), param('m_spawnActivated', 'bool', 'true')]), node('component', {'name': 'TimeoutComponent'}, [param('m_minLifetime', 'float', 12), param('m_maxLifetime', 'float', 12), param('m_startCountdownOnPulse', 'bool', 'false'), param('m_startCountdownOnDeath', 'bool', 'false'), param('m_alphaOut', 'bool', 'true'), param('m_alphaOutTime', 'float', 2)])])

TEMPLATE = 'props/pickups/ammobox/box.xml'

def derive_box(raw, half_extents, mass=1.0):
    tree = ET.fromstring(raw)
    if tree.tag != 'hke' or tree.attrib != {'version': 'V_20202_B_20040219'}:
        raise ValueError('Unsupported original Havok XML version')
    shapes = tree.findall("hkobject[@type='hkBoxShape']")
    bodies = tree.findall("hkobject[@type='hkRigidBody']")
    if len(shapes) != 1 or len(bodies) != 1 or len(tree.findall('hkobject')) != 6:
        raise ValueError('Expected one original box body and its world/filter schema')

    def param(node, name, value):
        field = node.find(f"hkparam[@name='{name}']")
        if field is None:
            raise ValueError('Missing original Havok field: ' + name)
        field.text = value
    if len(half_extents) != 3 or not all((0.001 < x < 1 for x in half_extents)):
        raise ValueError('Invalid magazine half extents')
    x, y, z = half_extents
    shape, body = (shapes[0], bodies[0])
    old_shape = shape.attrib['name']
    if body.find("hkparam[@name='shape']").text != old_shape:
        raise ValueError('Original body does not reference the sole native box')
    shape.attrib['name'] = 'darker_clip_box'
    body.attrib['name'] = 'darker_clip_body'
    param(body, 'shape', 'darker_clip_box')
    param(shape, 'halfExtents', f'({x:.9f} {y:.9f} {z:.9f} {min(x, y, z):.9f})')
    param(shape, 'radius', '0.001000000')
    param(body, 'mass', f'{mass:.9f}')
    ix, iy, iz = (mass * (y * y + z * z) / 3, mass * (x * x + z * z) / 3, mass * (x * x + y * y) / 3)
    param(body, 'inertiaTensor', f'({ix:.9f} 0.000000 0.000000)(0.000000 {iy:.9f} 0.000000)(0.000000 0.000000 {iz:.9f})')
    param(body, 'centerOfMass', '(0.000000 0.000000 0.000000 1.000000)')
    result = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
    return (result, dict(source=TEMPLATE, source_sha256=hashlib.sha256(raw).hexdigest(), native_shape='hkBoxShape', half_extents=list(half_extents), mass=mass, convex_margin=0.001, inertia=[ix, iy, iz], live_verified=False))

SOURCES = {'SniperRifle': ('accessories/weapons/dwsniperrifle/base_pov_dwsniperrifle.rx1', 'ce28e0aa0ff619b2cda6567959417df6a10a901e36a498b90bc68cb30718ea86', 4, 77, 64, ((0, 0), (3, 2))), 'RocketLauncher': ('accessories/weapons/dwrailrocket/base_pov_dwrailrocket.rx1', 'd595dd40e1319180ad5bb8e86b92a3ca4cd6294a6d7649819148532116f8fc88', 5, 152, 92, ((0, 1), (2, 2)))}

MODELS = {'SniperRifle': 'accessories/weapons/darker_private/sniper_dropped_cylinder', 'RocketLauncher': 'accessories/weapons/darker_private/rocket_dropped_clip'}

ACTORS = {'SniperRifle': 'DarkerPrivateSniperDroppedCylinder', 'RocketLauncher': 'DarkerPrivateRocketDroppedClip'}

def source_batches(raw):
    at = next((a for t, a, z, _ in boss._records(raw) if t == 1296)) + 16
    count, primitive = struct.unpack_from('<HI', raw, at + 6)
    ma, mz = next(((a, z) for t, a, z, _ in boss._records(raw) if t == 1294))
    flags, meshes, total = struct.unpack_from('<3I', raw, ma)
    if count != meshes or mz - ma != 12 + 8 * meshes or primitive != 6 or (flags != 1):
        raise ValueError('Pinned native mesh table differs')
    output = []
    for batch in range(count):
        row = struct.unpack_from('<6I', raw, at + 36 + 24 * batch)
        n, material = struct.unpack_from('<2I', raw, ma + 12 + batch * 8)
        if n != row[2]:
            raise ValueError('Native material/geometry mesh order differs')
        indices = struct.unpack_from('<' + 'H' * n, raw, at - 24 + row[3])
        tris = []
        for j in range(n - 2):
            tri = tuple(indices[j:j + 3])
            if len(set(tri)) == 3:
                tris.append(tri if j % 2 == 0 else (tri[1], tri[0], tri[2]))
        output.append((material, tris))
    if sum((struct.unpack_from('<I', raw, ma + 12 + i * 8)[0] for i in range(count))) != total:
        raise ValueError('Incomplete native mesh table')
    return output

def derive_holder(raw, static, name):
    path, digest, bones, vcount, tcount, expected = SOURCES[name]
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Unsupported original holder')
    source = skin._geometry(raw, 0, (bones,))
    selected = {i for i, w in enumerate(source['weights']) if w == {2: 1.0}}
    groups = []
    for batch, (material, triangles) in enumerate(source_batches(raw)):
        if any((any((i in selected for i in t)) and (not all((i in selected for i in t))) for t in triangles)):
            raise ValueError('Holder shares a gun face')
        kept = [t for t in triangles if all((i in selected for i in t))]
        if kept:
            groups.append((batch, material, kept))
    if tuple(((b, m) for b, m, _ in groups)) != expected or len(selected) != vcount or sum((len(t) for _, _, t in groups)) != tcount:
        raise ValueError('Native rigid island/material contract changed')
    used = sorted({i for _, _, ts in groups for t in ts for i in t})
    if set(used) != selected:
        raise ValueError('Incomplete holder topology')
    remap = {i: j for j, i in enumerate(used)}
    points = [skin._point(source['positions'][i], source['inverse'][2]) for i in used]
    center = tuple(((min((p[k] for p in points)) + max((p[k] for p in points))) / 2 for k in range(3)))
    points = [tuple((p[k] - center[k] for k in range(3))) for p in points]
    triangles = [tuple((remap[i] for i in t)) for _, _, ts in groups for t in ts]
    normals = skin._normals(dict(positions=points, triangles=triangles))
    vertices = b''.join((struct.pack('<3fII2f', *p, n, source['colors'][i], *source['uv'][i]) for p, n, i in zip(points, normals, used)))
    materials = [v for t, v in rw.chunks(only(source['geometry'], 8), 12) if t == 7]
    material = chunk(8, chunk(1, struct.pack('<3I', 2, 4294967295, 4294967295)) + b''.join((materials[m] for _, m, _ in groups)))
    align = lambda x: x + 15 & ~15
    offsets = []
    size = align(24 + 36 + 2 * 24) - 24
    for _, _, ts in groups:
        offsets.append(size)
        size += align(len(ts) * 3 * 2)
    header = bytearray(size)
    struct.pack_into('<IHH7I', header, 0, size, 1, 2, 5, len(used), 28, 0, 0, 0, 0)
    for g, (_, _, ts) in enumerate(groups):
        values = [remap[i] for t in ts for i in t]
        struct.pack_into('<6I', header, 36 + g * 24, min(values), max(values) - min(values) + 1, len(values), offsets[g] + 24, 0, 0)
        struct.pack_into('<' + 'H' * len(values), header, offsets[g], *values)
    mesh = chunk(1294, struct.pack('<3I', 0, 2, len(triangles) * 3) + b''.join((struct.pack('<2I', len(ts) * 3, g) for g, (_, _, ts) in enumerate(groups))))
    native = chunk(1296, chunk(1, struct.pack('<I', 5) + header + vertices))
    extension = chunk(3, mesh + native + chunk(1297, struct.pack('<I', 1349)))
    radius = max((math.dist((0, 0, 0), p) for p in points))
    gs = bytearray(only(source['geometry'], 1)[12:])
    struct.pack_into('<3I', gs, 4, len(triangles), len(used), 1)
    struct.pack_into('<4f', gs, 16, 0, 0, 0, radius)
    geometry = chunk(15, chunk(1, gs) + material + extension)
    clump = next((p for t, p in rw.chunks(static) if t == 16))
    frames = only(clump, 14)
    fs = bytearray(only(frames, 1))
    if struct.unpack_from('<I', fs, 12)[0] != 2:
        raise ValueError('Native static frames differ')
    for i in range(2):
        struct.pack_into('<12f', fs, 16 + i * 56, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    frames = rw.rebuild(frames, b''.join((bytes(fs) if t == 1 else p for t, p in rw.chunks(frames, 12))))
    clump = rw.rebuild(clump, b''.join((frames if t == 14 else chunk(26, chunk(1, struct.pack('<I', 1)) + geometry) if t == 26 else p for t, p in rw.chunks(clump, 12))))
    out = next((p for t, p in rw.chunks(static) if t == 36)) + b''.join((p for t, p in rw.chunks(raw) if t == 22)) + clump
    metadata = dict(source=path, source_sha256=digest, retained_vertices=vcount, retained_triangles=tcount, part_bone=2, geometry_center_in_part=center, half_extents=[max((abs(p[k]) for p in points)) for k in range(3)], visual_radius=radius, material_batches=[dict(source_batch=b, source_material=m, derived_material=g, triangles=len(ts), material_sha256=hashlib.sha256(materials[m]).hexdigest()) for g, (b, m, ts) in enumerate(groups)], material_mapping='Exact original 0x50e mesh table, not native draw-batch ordinal or material pointer inference.', uv_bytes_preserved=True, output_sha256=hashlib.sha256(out).hexdigest())
    return (out, metadata)

def resources(read):
    result = {}
    actors = []
    variants = [(SOURCE, MODEL, ACTOR, False, False),
        (DUAL_SOURCE, 'accessories/weapons/darker_private/dual_pistol_dropped_clip', 'DarkerPrivateDualPistolDroppedClip', True, False),
        (CROSSBOW_SOURCE, 'accessories/weapons/darker_private/crossbow_dropped_clip', 'DarkerPrivateCrossbowDroppedClip', False, True)]
    meshes = [(model, name, derive(read(source), read(STATIC), dual=dual, crossbow=crossbow))
              for source, model, name, dual, crossbow in variants]
    meshes.extend((MODELS[name], ACTORS[name], derive_holder(read(spec[0]), read(STATIC), name))
                  for name, spec in SOURCES.items())
    for model, name, (mesh, metadata) in meshes:
        box, _ = derive_box(read(TEMPLATE), metadata['half_extents'], mass=30.)
        entry = actor(metadata['visual_radius'])
        entry['attributes']['name'] = name
        entry['children'] = entry['children'][:2]
        entry['children'][1]['children'].append(param('m_RigidBodyName', 'string', 'darker_clip_body'))
        for field in art.walk(entry):
            if field['attributes'].get('name') in ('m_modelResourcePath', 'm_RigidBodyFileName'):
                field['attributes']['value'] = model
            adjustments = {'m_mass': '30.000000', 'm_dampingRateAir': '0.100000', 'm_collideAsGib': 'false'}
            if field['attributes'].get('name') in adjustments:
                field['attributes']['value'] = adjustments[field['attributes']['name']]
        result[model + '.rx1'] = mesh
        result[model + '.xml'] = box
        actors.append(entry)
    return result, actors
