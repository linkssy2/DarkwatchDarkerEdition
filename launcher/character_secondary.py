"""Give only the derived spectral player six bounded secondary-motion joints.

Unused wing slots keep the original 51-bone allocation. The native player pose
still owns every original body joint; runtime motion supplies these six copies.
"""
import math
import struct

try:
    from . import character_boss as boss
except ImportError:
    import character_boss as boss


# Source pose copies are separate from the hierarchy: native animation consumes
# bones in numeric DFS order. The thigh helpers share each hip's spring offset.
PARENTS = (8, 8, 0, 0, 4, 1)
HIERARCHY_PARENTS = (8, 8, 0, 0, 0, 0)
NAMES = ('SpectralChestLeft', 'SpectralChestRight', 'SpectralHipLeft', 'SpectralHipRight',
         'SpectralThighLeft', 'SpectralThighRight')
CENTERS = ((.075, .33, .15), (-.075, .33, .15),
           (.085, -.015, -.105), (-.085, -.015, -.105))
REGION_CENTERS = CENTERS[:2] + ((.10, -.08, -.09), (-.10, -.08, -.09)) * 2
RADII = ((.10, .09, .10),) * 2 + ((.13, .23, .10),) * 4


def influence(point, joint):
    """Keep the sternum, waist and the outside of each region anchored."""
    center, radius = REGION_CENTERS[joint], RADII[joint]
    if point[0] * center[0] <= 0:
        return 0.
    distance = sum(((p-c)/r)**2 for p, c, r in zip(point, center, radius))
    side = min(1., max(0., (abs(point[0])-.012)/.035))
    waist = min(1., max(0., (.065-point[1])/.04)) if joint >= 2 else 1.
    return .65 * max(0., 1.-distance)**2 * side * waist


def joint_names(data):
    lines = data.decode('ascii').splitlines()
    names = [line.strip() for line in lines]
    if len(names) != boss.BONES or tuple(names[22:28]) != ('wingRoot', 'lwing', 'lwing_arm', 'lwing_elbow', 'lwing_wrist', 'lwing_3fing1'):
        raise ValueError('Unexpected spectral secondary joint names')
    parents, stack = [], []
    for bone, line in enumerate(lines):
        indent = len(line)-len(line.lstrip(' '))
        depth = indent//4
        if indent % 4 or depth > len(stack) or ('\t' in line):
            raise ValueError('Invalid spectral joint indentation')
        parents.append(stack[depth-1] if depth else None)
        stack[depth:] = [bone]
    _secondary_parents(parents)
    _flags(parents)
    names[22:28] = NAMES
    depths = []
    for parent in parents:
        depths.append(0 if parent is None else depths[parent]+1)
    return ('\r\n'.join('    '*depth+name for depth, name in zip(depths, names))+'\r\n').encode('ascii')


def _secondary_parents(parents):
    parents[22:28] = HIERARCHY_PARENTS
    parents[29] = parents[32] = 27
    parents[35] = 0
    parents[37] = 0


def _flags(parents):
    children = {bone: [] for bone in range(len(parents))}
    for bone, parent in enumerate(parents):
        if parent is not None:
            children[parent].append(bone)
    order, flags = [], [0] * len(parents)
    def visit(bone):
        order.append(bone)
        siblings = children.get(parents[bone], [bone])
        flags[bone] = (2 if bone != siblings[-1] else 0) | (1 if not children[bone] else 0)
        for child in children[bone]:
            visit(child)
    visit(0)
    if order != list(range(len(parents))):
        raise ValueError('Secondary hierarchy is not in native bone order')
    return flags


def prepare(data):
    """Retain all geometry bytes; transfer only local parent skin weights."""
    rig, _, _ = boss.rig(data, boss.BONES)
    records = list(boss._records(data))
    geometries = [(a, z) for t, a, z, p in records if t == 15]
    if len(geometries) != 2:
        raise ValueError('Expected the derived wingless spectral player')
    result = bytearray(data)
    parents = [rig[i]['parent_bone'] for i in range(boss.BONES)]
    original_flags = _flags(parents)
    _secondary_parents(parents)
    for joint, source in enumerate(PARENTS, 22):
        # Thigh copies need their original local bind pose and inverse bind;
        # copying their weights to the hip joint would pull against walking.
        local = ((1., 0., 0., 0., 1., 0., 0., 0., 1., 0., 0., 0.) if joint < 26
                 else rig[source]['rotation'] + rig[source]['translation'])
        if joint >= 26 and rig[source]['parent_bone'] != 0:
            raise ValueError('Unexpected spectral thigh parent')
        struct.pack_into('<12fi', result, rig[joint]['offset'], *local,
                         rig[HIERARCHY_PARENTS[joint-22]]['frame'])
    # These remaining wing subtrees have no geometry; retain native DFS and
    # physical frame order without reindexing original animation or body bones.
    for joint in (29, 32, 35, 37):
        struct.pack_into('<i', result, rig[joint]['offset']+48, rig[parents[joint]]['frame'])
    flags = _flags(parents)
    hierarchy = [(a, z) for t, a, z, p in records if t == 0x11e and z-a >= 12
                 and struct.unpack_from('<I', data, a+8)[0]]
    if len(hierarchy) != 1:
        raise ValueError('Unexpected spectral hierarchy')
    at, _ = hierarchy[0]
    for bone in range(boss.BONES):
        row = at+20+12*bone
        if struct.unpack_from('<3I', data, row) != (bone, bone, original_flags[bone]):
            raise ValueError('Unexpected spectral hierarchy flags')
        struct.pack_into('<I', result, row+8, flags[bone])
    changed = [0] * len(PARENTS)
    for index, (a, z) in enumerate(geometries):
        rows = list(boss._records(data, a, z, 15))
        ns, ne = next((a, z) for t, a, z, p in rows if t == 0x510)
        native = list(boss.animation._chunks(data, ns, ne))
        if len(native) != 1 or native[0][0] != 1:
            raise ValueError('Unexpected secondary vertex data')
        _, start, end = native[0]
        platform, size = struct.unpack_from('<II', data, start)
        header = start+4
        count, stride = struct.unpack_from('<II', data, header+12)
        vertices = header+size
        if platform != 5 or (count, stride) != ((122, 28) if index == 0 else (2724, 36)) or vertices+count*stride != end:
            raise ValueError('Unexpected secondary vertex layout')
        sa, sz = next((a, z) for t, a, z, p in rows if t == 0x116)
        skin = list(boss.animation._chunks(data, sa, sz))
        if len(skin) != 1 or skin[0][0] != 1:
            raise ValueError('Unexpected secondary skin data')
        _, ss, se = skin[0]
        used, width, _, skin_stride = struct.unpack_from('<4I', data, ss+2056)
        if struct.unpack_from('<II', data, ss) != (5, 51) or (used, width, skin_stride) != ((2, 2, 6) if index == 0 else (22, 4, 12)):
            raise ValueError('Unexpected secondary skin layout')
        skin_at = ss+2072
        inverse = skin_at+count*skin_stride
        if inverse+51*64+12 != se:
            raise ValueError('Unexpected secondary inverse binds')
        for joint, parent in enumerate(PARENTS, 22):
            result[inverse+64*joint:inverse+64*(joint+1)] = data[inverse+64*parent:inverse+64*(parent+1)]
        if index == 0:
            continue
        if struct.unpack_from('<22i', data, ss+8) != tuple(range(22)) or struct.unpack_from('<6i', data, ss+8+22*4) != (-1,)*6:
            raise ValueError('Unexpected secondary bone palette')
        for joint in range(22, 28):
            struct.pack_into('<i', result, ss+8+joint*4, joint)
            struct.pack_into('<i', result, ss+1032+joint*4, joint)
        struct.pack_into('<I', result, ss+2056, 28)
        for vertex in range(count):
            point = struct.unpack_from('<3f', data, vertices+stride*vertex)
            if not all(math.isfinite(v) for v in point):
                raise ValueError('Nonfinite secondary vertex')
            wa = skin_at+vertex*skin_stride
            values = list(data[wa:wa+4])
            ids = list(struct.unpack_from('<4H', data, wa+4))
            if sum(values) != 255 or any(i % 3 or i//3 >= 22 for i, w in zip(ids, values) if w):
                raise ValueError('Invalid original secondary weights')
            transfers = []
            for joint, parent in enumerate(PARENTS):
                if parent*3 not in ids:
                    continue
                source = ids.index(parent*3)
                amount = round(values[source]*influence(point, joint))
                if amount:
                    transfers.append((amount, joint, source))
            # One strongest transfer keeps the shared hip/thigh displacement
            # continuous at their handoff, independent of spare influence slots.
            # Original knee, waist and other-leg weights are never removed.
            transfers.sort(key=lambda row: (-row[0], row[1]))
            if transfers and 0 not in values:
                raise ValueError('Secondary region exceeds native four influences')
            for amount, joint, source in transfers[:1]:
                free = values.index(0)
                values[source] -= amount
                values[free], ids[free] = amount, (22+joint)*3
                changed[joint] += 1
            result[wa:wa+4] = bytes(values)
            struct.pack_into('<4H', result, wa+4, *ids)
    # The low-poly upper thighs have only four posterior vertices per side in
    # this mask; those vertices extend the existing hip region over the thigh.
    if any(count < minimum for count, minimum in zip(changed, (20, 20, 20, 20, 4, 4))):
        raise ValueError(f'Secondary motion regions are missing: {changed}')
    poses = [(a, z) for t, a, z in boss.animation._chunks(data, 0, len(data)) if t == 0x1b]
    if len(poses) != 1:
        raise ValueError('Missing spectral bind animation')
    start, end = poses[0]
    if struct.unpack_from('<4I', data, start) != (0x100, 1, 102, 0) or end-start != 20+102*36:
        raise ValueError('Unexpected spectral bind animation')
    for half in (0, 51):
        for joint, source in enumerate(PARENTS, 22):
            pose = ((0., 0., 0., 1., 0., 0., 0.) if joint < 26 else
                    boss.animation._to_quaternion(tuple(rig[source]['rotation'][i:i+3]
                                                         for i in (0, 3, 6)))
                    + rig[source]['translation'])
            struct.pack_into('<7f', result, start+20+36*(half+joint)+4,
                             *pose)
    return bytes(result)
