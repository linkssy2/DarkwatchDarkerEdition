"""Give derived playable bosses six bounded secondary-motion joints.

Unused wing slots keep the original 51-bone allocation. The native player pose
still owns every original body joint; runtime motion supplies these six copies.
"""
import hashlib
import math
import struct

try:
    from . import character_boss as boss
    from . import character_repaint as rw
except ImportError:
    import character_boss as boss
    import character_repaint as rw


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


def repair_player_hips(data):
    """Repair the witnessed boss skin for player locomotion, before helpers.

    The boss's positive hip contains copied negative-thigh donors. They are
    harmless in its flying pose but pull opposite ways in player walk/turn
    clips. Preserve the mesh and its bind matrices; correct just the derived
    player's pelvis weights. Original NPC resources never enter this path.
    """
    geometries = [(a, z) for t, a, z, p in boss._records(data) if t == 15]
    if len(geometries) != 2:
        raise ValueError('Expected the derived wingless spectral player')
    rows = list(boss._records(data, *geometries[1], 15))
    na, nz = next((a, z) for t, a, z, p in rows if t == 0x510)
    sa, sz = next((a, z) for t, a, z, p in rows if t == 0x116)
    native = list(boss.animation._chunks(data, na, nz))
    skin = list(boss.animation._chunks(data, sa, sz))
    if len(native) != 1 or len(skin) != 1 or native[0][0] != 1 or skin[0][0] != 1:
        raise ValueError('Unexpected spectral hip structures')
    _, start, end = native[0]
    platform, size = struct.unpack_from('<II', data, start)
    count, stride = struct.unpack_from('<II', data, start+16)
    vertices = start+4+size
    _, ss, se = skin[0]
    skin_at = ss+2072
    if (platform, count, stride) != (5, 2724, 36) or vertices+count*stride != end or (
            struct.unpack_from('<II', data, ss) != (5, 51) or
            struct.unpack_from('<22i', data, ss+8) != tuple(range(22)) or
            struct.unpack_from('<4I', data, ss+2056)[:2] != (22, 4) or
            struct.unpack_from('<I', data, ss+2068)[0] != 12 or
            skin_at+count*12+51*64+12 != se):
        raise ValueError('Unexpected spectral hip layout')
    # Pin both positions/UVs and original donors. An unrelated mesh or already
    # prepared model must never receive this anatomy-specific correction.
    if (hashlib.sha256(data[vertices:end]).hexdigest() !=
            'd90b53f2b095c0ede33c3012e87075cf998446686c91888fcfecd0ebbcc1a6fb' or
            hashlib.sha256(data[skin_at:skin_at+count*12]).hexdigest() !=
            '0e954a2688628f973126844cc1c77e9749d837d31e0c3928dd4c971ffc996e44'):
        raise ValueError('Unrecognized original spectral hip geometry or weights')
    points = [struct.unpack_from('<3f', data, vertices+i*stride) for i in range(count)]
    result = bytearray(data)
    changed = 0
    for vertex, point in enumerate(points):
        at = skin_at+vertex*12
        values = data[at:at+4]
        ids = struct.unpack_from('<4H', data, at+4)
        weights = {bone//3: value for bone, value in zip(ids, values) if value}
        original = dict(weights)
        total = weights.get(1, 0)+weights.get(4, 0)
        if total and -.12 < point[1] < .12:
            # A hard side swap moves the tear to the center seam. Blend only
            # that narrow seam; keep total thigh, pelvis/spine/knee weights.
            t = min(1., max(0., (point[0]+.035)/.070))
            positive = round(total*t*t*(3.-2.*t))
            weights.pop(1, None); weights.pop(4, None)
            if positive:
                weights[4] = positive
            if total-positive:
                weights[1] = total-positive
        # These four surface points and their exact duplicates were entirely
        # thigh-bound next to a 70%-pelvis rear surface. The regular Cassidy
        # points within 8 mm supply the native transition (627/961, 614/963).
        if vertex in (640, 641, 1808, 1809):
            weights = {0: 128, 4 if point[0] > 0 else 1: 127}
        elif vertex in (643, 644, 1811, 1812):
            weights = {0: 77, 4 if point[0] > 0 else 1: 178}
        if weights == original:
            continue
        if sum(weights.values()) != 255 or len(weights) > 4:
            raise ValueError('Invalid repaired spectral hip weights')
        ordered = sorted(weights.items(), key=lambda row: (-row[1], row[0]))
        ordered += [(0, 0)]*(4-len(ordered))
        result[at:at+4] = bytes(value for bone, value in ordered)
        struct.pack_into('<4H', result, at+4, *(bone*3 for bone, value in ordered))
        changed += 1
    if changed != 106:
        raise ValueError('Unexpected spectral hip repair coverage')
    return bytes(result)


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


def prepare_tala(data):
    """Expand Tala's two-weight skin so the same helpers can retain its donors."""
    if hashlib.sha256(data).hexdigest() != '69d692a1ade3726ff3725748ca6b0496c379cab5cf4bf9cdb479ce259be37793':
        raise ValueError('Unexpected wingless playable Boss Tala model')
    replacements = 0
    def rebuild(raw):
        nonlocal replacements
        parts = []
        for tag, part in rw.chunks(raw):
            if tag in boss.CONTAINERS:
                part = rw.rebuild(part, rebuild(part[12:]))
            elif tag == 0x116:
                rows = rw.chunks(part, 12)
                if len(rows) != 1 or rows[0][0] != 1:
                    raise ValueError('Unexpected Boss Tala skin structure')
                original = rows[0][1]
                header = bytearray(original[12:2084])
                palette = struct.unpack_from('<256i', header, 8)
                if (struct.unpack_from('<II', header) != (5, 51) or
                        struct.unpack_from('<4I', header, 2056)[:2] != (20, 2) or
                        struct.unpack_from('<I', header, 2068)[0] != 6 or
                        len(original) != 2084+2696*6+51*64+12):
                    raise ValueError('Unexpected Boss Tala two-weight skin')
                for offset in (8, 1032):
                    struct.pack_into('<256i', header, offset, *range(22), *([-1]*234))
                struct.pack_into('<II', header, 2056, 22, 4)
                struct.pack_into('<I', header, 2068, 12)
                weights = bytearray()
                for vertex in range(2696):
                    at = 2084+vertex*6
                    values = original[at:at+2]
                    ids = struct.unpack_from('<2H', original, at+2)
                    if sum(values) != 255 or any(i % 3 or i//3 >= 20 for i in ids):
                        raise ValueError('Invalid Boss Tala skin donor')
                    bones = [palette[i//3] for i in ids]
                    if any(not 0 <= b < 22 for b in bones):
                        raise ValueError('Invalid Boss Tala body bone')
                    weights.extend(values+bytes(2)+struct.pack('<4H', bones[0]*3, bones[1]*3, 0, 0))
                tail = original[2084+2696*6:]
                part = rw.rebuild(part, rw.rebuild(original, bytes(header)+weights+tail))
                replacements += 1
            parts.append(part)
        return b''.join(parts)
    expanded = rebuild(data)
    if replacements != 1:
        raise ValueError('Expected one Boss Tala body skin')
    # Tala has a different chest and inner-thigh topology. These mirrored
    # transfers smooth its original falloff across native player poses while
    # retaining the shared spring limits and all original animation donors.
    # Keep the lower chest fold anchored; pinning the source hash above prevents
    # these vertex indices from ever applying to another mesh or an NPC.
    secondary_weights = {vertex: weight for weight, vertices in (
        (0, (1427, 1428, 1754, 1755)),
        (6, (1345, 1673, 1330, 1331, 1658, 1659)),
        (8, (1415, 1743)),
        (9, (1366, 1367, 1694, 1695)),
        (10, (1264, 1265, 1354, 1592, 1593, 1682)),
        (11, (1447, 1774)),
        (12, (1399, 1400, 1448, 1727, 1728, 1775)),
        (13, (1361, 1385, 1396, 1689, 1713, 1724)),
        (14, (1284, 1612)),
        (15, (1365, 1693)),
        (16, (1353, 1414, 1681, 1742)),
        (17, (1349, 1677)),
        (18, (1314, 1642)),
        (19, (1309, 1310, 1637, 1638)),
        (21, (1344, 1672)),
        (22, (1398, 1726)),
        (24, (1408, 1736)),
        (26, (1342, 1445, 1670, 1772)),
        (27, (1386, 1714)),
        (28, (1446, 1773)),
        (30, (1452, 1779)),
        (31, (1360, 1688)),
        (33, (1453, 1780)),
        (36, (1397, 1425, 1725, 1753)),
        (37, (1355, 1451, 1683, 1778)),
        (39, (1279, 1607)),
        (43, (1424, 1752)),
        (44, (1329, 1409, 1657, 1737)),
        (45, (1449, 1776)),
        (48, (1420, 1748)),
        (49, (1450, 1777)),
        (50, (1419, 1747)),
        (52, (1421, 1749)),
        (55, (1418, 1746)),
        (56, (1433, 1760)),
        (57, (1432, 1759)),
        (58, (1373, 1701, 1422, 1750)),
        (59, (1417, 1431, 1434, 1745, 1758, 1761)),
        (60, (1443, 1770)),
        (61, (1435, 1444, 1762, 1771)),
        (62, (1416, 1423, 1430, 1437, 1442, 1744, 1751, 1757, 1764, 1769)),
        (63, (1377, 1441, 1705, 1768)),
        (64, (1438, 1765)),
        (65, (1429, 1436, 1440, 1756, 1763, 1767)),
        (66, (1439, 1766)),
        (77, (1374, 1702)),
        (86, (1356, 1684)),
        (111, (1276, 1604)),
    ) for vertex in vertices}
    return _prepare(expanded, ((2696, 28, True),), (20, 20, 18, 18, 4, 4), secondary_weights)


def prepare(data):
    """Retain all geometry bytes; transfer only local parent skin weights."""
    return _prepare(repair_player_hips(data), ((122, 28, False), (2724, 36, True)),
                    (20, 20, 20, 20, 4, 4))


def _prepare(data, layouts, minimum_coverage, secondary_weights=None):
    rig, _, _ = boss.rig(data, boss.BONES)
    records = list(boss._records(data))
    geometries = [(a, z) for t, a, z, p in records if t == 15]
    if len(geometries) != len(layouts):
        raise ValueError('Unexpected derived secondary player geometry count')
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
        expected_count, expected_stride, body = layouts[index]
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
        if platform != 5 or (count, stride) != (expected_count, expected_stride) or vertices+count*stride != end:
            raise ValueError('Unexpected secondary vertex layout')
        sa, sz = next((a, z) for t, a, z, p in rows if t == 0x116)
        skin = list(boss.animation._chunks(data, sa, sz))
        if len(skin) != 1 or skin[0][0] != 1:
            raise ValueError('Unexpected secondary skin data')
        _, ss, se = skin[0]
        used, width, _, skin_stride = struct.unpack_from('<4I', data, ss+2056)
        if struct.unpack_from('<II', data, ss) != (5, 51) or (used, width, skin_stride) != ((22, 4, 12) if body else (2, 2, 6)):
            raise ValueError('Unexpected secondary skin layout')
        skin_at = ss+2072
        inverse = skin_at+count*skin_stride
        if inverse+51*64+12 != se:
            raise ValueError('Unexpected secondary inverse binds')
        for joint, parent in enumerate(PARENTS, 22):
            result[inverse+64*joint:inverse+64*(joint+1)] = data[inverse+64*parent:inverse+64*(parent+1)]
        if not body:
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
                if secondary_weights is not None:
                    amount = secondary_weights.get(vertex, amount)
                if not amount:
                    continue
                if not 0 < amount <= values[source]:
                    raise ValueError('Invalid secondary donor transfer')
                free = values.index(0)
                values[source] -= amount
                values[free], ids[free] = amount, (22+joint)*3
                changed[joint] += 1
            result[wa:wa+4] = bytes(values)
            struct.pack_into('<4H', result, wa+4, *ids)
    # The low-poly upper thighs have only four posterior vertices per side in
    # this mask; those vertices extend the existing hip region over the thigh.
    if any(count < minimum for count, minimum in zip(changed, minimum_coverage)):
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
