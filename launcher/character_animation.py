"""Adapt player animation poses from the user's verified original disc resources.

Only pose keys change. Native key times, event tracks and animation-table logic
are preserved; this module contains no original animation or model payloads.
"""
import hashlib
import math
import struct


STORM = 'characters/multiplayer/base_dwstormtrooper.rx1'
CHAZ = 'characters/player_third/base_chaz.rx1'
CASSIDY = 'characters/cassidy/base_cassidy.rx1'
KINDS = ('BoneAnimatedResource', 'AnimatedPathResource', 'EventSequenceResource')
TABLES = (
    ('Multi', 'characters/multiplayercoop/multiplayercoopanimation.bxml',
     'characters/player_two/cassidycoopanimation.bxml', STORM,
     'levels/singleplayer/wrongtrain/streaming/wrongtrain_a_resources_coop.bxml', 300),
    ('NotMulti', 'characters/player_third/chazbasicanimation.bxml',
     'characters/player_two/cassidybasicanimation.bxml', CHAZ,
     'levels/singleplayer/wrongtrain/streaming/wrongtrain_a_resources.bxml', 5),
    ('Horse', 'characters/player_third/chazhorseanimation.bxml',
     'characters/player_two/cassidyhorseanimation.bxml', CHAZ,
     'levels/singleplayer/m02_canyonshoot/streaming/hub_a_resources_coop.bxml', 16),
    ('Vehicle', 'characters/player_third/chazvehicleanimation.bxml',
     'characters/player_two/cassidyvehicleanimation.bxml', CHAZ,
     'levels/singleplayer/m08_regulator/streaming/hub_a_resources_coop.bxml', 8),
)
ORDER = ((1, 4), (4, 12), (32, 8), (8, 16), (2, 4), (16, 4))
IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def _chunks(data, start, end):
    while start < end:
        if start + 12 > end:
            raise ValueError('Truncated model chunk')
        tag, size, _ = struct.unpack_from('<III', data, start)
        stop = start + 12 + size
        if stop > end:
            raise ValueError('Model chunk exceeds its parent')
        yield tag, start + 12, stop
        start = stop


def frames(data):
    """Read the original 23-frame, 22-bone player/Cassidy bind hierarchy."""
    lists = [(s, e) for tag, a, z in _chunks(data, 0, len(data)) if tag == 16
             for tag, s, e in _chunks(data, a, z) if tag == 14]
    if len(lists) != 1:
        raise ValueError('Expected one model frame list')
    entries = list(_chunks(data, *lists[0]))
    if not entries or entries[0][0] != 1:
        raise ValueError('Missing model frame structure')
    _, start, end = entries[0]
    if end - start < 4:
        raise ValueError('Truncated model frame count')
    count = struct.unpack_from('<I', data, start)[0]
    if count != 23 or end - start != 4 + 56 * count or len(entries) != count + 1:
        raise ValueError('Unsupported character frame layout')
    result = {}
    for i, (tag, a, z) in enumerate(entries[1:]):
        if tag != 3:
            raise ValueError('Unexpected model frame extension')
        bones = []
        for tag, s, e in _chunks(data, a, z):
            if tag == 0x11e:
                if e - s < 12:
                    raise ValueError('Truncated bone identifier')
                bones.append(struct.unpack_from('<III', data, s)[1])
        if len(bones) > 1:
            raise ValueError('Duplicate frame bone identifier')
        if bones:
            transform = struct.unpack_from('<12f2i', data, start + 4 + i * 56)
            if bones[0] in result or not all(math.isfinite(v) for v in transform[:12]):
                raise ValueError('Invalid bind transform')
            result[bones[0]] = dict(frame=i, parent=transform[12], rotation=transform[:9],
                                    translation=transform[9:12])
    if sorted(result) != list(range(22)):
        raise ValueError('Incomplete character bone hierarchy')
    return result


def sections(data):
    """Validate SANM boundaries before inspecting any keys."""
    if len(data) < 24:
        raise ValueError('Truncated animation header')
    version, magic, bones, duration, _, flags = struct.unpack_from('<IIIfII', data)
    if not (16 <= version <= 40 and magic == 0xf11e0006 and bones == 22 and
            math.isfinite(duration) and duration >= 0 and not flags & 0x20000000):
        raise ValueError('Unsupported animation header')
    pos, result = 24, {}
    for bit, stride in ORDER:
        if not flags & bit:
            continue
        start = pos
        if pos + 4 > len(data):
            raise ValueError('Truncated animation section')
        count = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        indices = ()
        if bit in (4, 8, 32):
            if pos + 88 > len(data):
                raise ValueError('Truncated animation bone index')
            indices = struct.unpack_from('<22I', data, pos)
            pos += 88
            valid = [i for i in indices if i != 0xffffffff]
            if valid != sorted(valid) or any(i >= count for i in valid):
                raise ValueError('Invalid animation bone index')
        end = pos + count * stride
        if end > len(data):
            raise ValueError('Truncated animation keys')
        if bit == 8:
            for key in range(count):
                if not all(math.isfinite(v) for v in struct.unpack_from('<4f', data, pos + key * stride)):
                    raise ValueError('Nonfinite animation translation')
        result[bit] = dict(start=start, end=end, count=count, indices=indices, keys=pos, stride=stride)
        pos = end
    if pos != len(data):
        raise ValueError('Unexpected animation trailing data')
    return flags, result


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def decode_word(word):
    """Expand the original packed quaternion, including its float spill points."""
    if not 0 <= word <= 0xffffffff:
        raise ValueError('Packed rotation must be uint32')
    if word == 0:
        return (0., 0., 0., 1.)
    shell = word & 0x3ffff
    n = int(_f32(math.sqrt(shell)))
    residual = shell - n * n if n else 0
    denominator = 2 * n if n else 1
    w = math.cos(((word >> 18) & 0x7ff) * 0.0007669904152862728)
    sin_angle = math.sqrt(max(0., 1 - w * w))
    stored_sin = _f32(sin_angle)
    theta = _f32(math.sin(n * 0.0030739654321223497))
    phi_full = math.sin(3.1415927410125732 / (2 * denominator) * residual)
    phi = _f32(phi_full)
    x = math.sqrt(max(0., 1 - phi_full * phi_full)) * theta * sin_angle
    y = math.sqrt(max(0., 1 - theta * theta)) * stored_sin
    z = phi * theta * stored_sin
    q = tuple(_f32(v) for v in ((-x if word & 0x80000000 else x),
                               (-y if word & 0x40000000 else y),
                               (-z if word & 0x20000000 else z), w))
    length = math.sqrt(sum(v * v for v in q))
    return tuple(v / length for v in q)


def expand(data):
    flags, parts = sections(data)
    if not flags & 32:
        return data
    if flags & 4:
        raise ValueError('Mixed packed and unpacked rotations are unsupported')
    section = parts[32]
    block = bytearray(data[section['start']:section['keys']])
    for key in range(section['count']):
        at = section['keys'] + 8 * key
        q = decode_word(struct.unpack_from('<I', data, at + 4)[0])
        values = [max(-32768, min(32767, round(v * 32768))) for v in q]
        block += data[at:at + 4] + struct.pack('<4h', *values)
    header = bytearray(data[:24])
    struct.pack_into('<I', header, 20, (flags & ~32) | 4)
    output = bytes(header) + b''.join(block if bit == 4 else data[parts[bit]['start']:parts[bit]['end']]
        for bit, _ in ORDER if bit != 32 and (bit in parts or bit == 4))
    verify_preserved(data, output)
    return output


def _transpose(m):
    return tuple(zip(*m))


def _multiply(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _determinant(m):
    a, b, c = m[0]; d, e, f = m[1]; g, h, i = m[2]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _inverse(m):
    a, b, c = m[0]; d, e, f = m[1]; g, h, i = m[2]
    determinant = _determinant(m)
    return tuple(tuple(v / determinant for v in row) for row in (
        (e*i-f*h, c*h-b*i, b*f-c*e), (f*g-d*i, a*i-c*g, c*d-a*f), (d*h-e*g, b*g-a*h, a*e-b*d)))


def _bind_length(v):
    # Keep the accepted converter's ordered three-term dot product. Python's
    # compensated sum changes tiny cancellation results in translation keys.
    x, y, z = v
    return math.sqrt((x * x + y * y) + z * z)


def parameters(source, target):
    if sorted(source) != list(range(22)) or sorted(target) != list(range(22)):
        raise ValueError('Incomplete retarget hierarchy')
    result = []
    for bone in range(22):
        a, b = source[bone], target[bone]
        if (a['frame'], a['parent']) != (b['frame'], b['parent']):
            raise ValueError('Mismatched character hierarchy')
        old = tuple(tuple(a['rotation'][i:i+3]) for i in (0, 3, 6))
        new = tuple(tuple(b['rotation'][i:i+3]) for i in (0, 3, 6))
        for matrix in (old, new):
            product = _multiply(matrix, _transpose(matrix))
            if not _determinant(matrix) > 0 or any(
                    abs(product[i][j] - IDENTITY[i][j]) > 1e-5 + 1e-5 * IDENTITY[i][j]
                    for i in range(3) for j in range(3)):
                raise ValueError('Non-rigid bind basis')
        old_t, new_t = a['translation'], b['translation']
        length = _bind_length(old_t)
        scale = _bind_length(new_t) / length if length > 1e-5 else 1.
        result.append((_multiply(_inverse(old), new), old_t, new_t, scale))
    return result


def _quaternion_matrix(q):
    x, y, z, w = q
    return ((1-2*(y*y+z*z), 2*(x*y+z*w), 2*(x*z-y*w)),
            (2*(x*y-z*w), 1-2*(x*x+z*z), 2*(y*z+x*w)),
            (2*(x*z+y*w), 2*(y*z-x*w), 1-2*(x*x+y*y)))


def _to_quaternion(row):
    m = _transpose(row)
    q = [0.] * 4
    trace = sum(m[i][i] for i in range(3))
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q[:3] = ((m[2][1]-m[1][2])/s, (m[0][2]-m[2][0])/s, (m[1][0]-m[0][1])/s)
        q[3] = s / 4
    else:
        i = max(range(3), key=lambda k: m[k][k]); j = (i+1) % 3; k = (i+2) % 3
        s = math.sqrt(1+m[i][i]-m[j][j]-m[k][k]) * 2
        q[i] = s/4; q[j] = (m[j][i]+m[i][j])/s; q[k] = (m[k][i]+m[i][k])/s
        q[3] = (m[k][j]-m[j][k])/s
    length = math.sqrt(sum(v * v for v in q))
    return tuple(v / length for v in q)


def retarget(data, params):
    flags, parts = sections(data)
    if flags & 32 or len(params) != 22:
        raise ValueError('Retargeting requires expanded rotations and 22 bones')
    output, changed = bytearray(data), 0
    for bit in (4, 8):
        if bit not in parts:
            continue
        section = parts[bit]
        for bone, index in enumerate(section['indices']):
            if index == 0xffffffff:
                continue
            stop = min([v for v in section['indices'] if index < v < 0xffffffff] + [section['count']])
            offset, old_t, new_t, scale = params[bone]
            for k in range(index, stop):
                key = section['keys'] + k * section['stride']
                if bit == 4:
                    if all(abs(offset[i][j] - IDENTITY[i][j]) <= 1e-10 for i in range(3) for j in range(3)):
                        continue  # Preserve unchanged source keys without requantizing them.
                    q = tuple(v / 32768 for v in struct.unpack_from('<4h', data, key + 4))
                    length = math.sqrt(sum(v * v for v in q))
                    if not .99 < length < 1.01:
                        raise ValueError('Unexpected animation quaternion')
                    q = tuple(v / length for v in q)
                    mapped = _to_quaternion(_multiply(_quaternion_matrix(q), offset))
                    if sum(a * b for a, b in zip(mapped, q)) < 0:
                        mapped = tuple(-v for v in mapped)
                    values = [max(-32768, min(32767, round(v * 32768))) for v in mapped]
                    struct.pack_into('<4h', output, key + 4, *values)
                else:
                    if old_t == new_t and scale == 1:
                        continue
                    values = struct.unpack_from('<3f', data, key + 4)
                    mapped = tuple(b + (v - a) * scale for a, b, v in zip(old_t, new_t, values))
                    if not all(math.isfinite(v) and abs(v) <= 3.4028234663852886e38 for v in mapped):
                        raise ValueError('Invalid retarget translation')
                    struct.pack_into('<3f', output, key + 4, *mapped)
                changed += 1
    verify_preserved(data, output)
    return bytes(output), changed


def verify_preserved(original, adapted):
    old_flags, old = sections(original)
    new_flags, new = sections(adapted)
    expected_flags = (old_flags & ~32) | 4 if old_flags & 32 else old_flags
    if original[:20] != adapted[:20] or new_flags != expected_flags:
        raise ValueError('Animation metadata changed')
    for bit, before in old.items():
        after = new[4 if bit == 32 else bit]
        if before['count'] != after['count'] or before['indices'] != after['indices']:
            raise ValueError('Animation track/index count changed')
        if bit not in (4, 8, 32):
            if original[before['start']:before['end']] != adapted[after['start']:after['end']]:
                raise ValueError('Animation event track changed')
        else:
            for key in range(before['count']):
                a = before['keys'] + key * before['stride']; b = after['keys'] + key * after['stride']
                if original[a:a+4] != adapted[b:b+4]:
                    raise ValueError('Animation key time changed')


def _norm(path):
    value = path.replace('\\', '/').lower()
    if not value or ':' in value or '\0' in value or len(value.encode('ascii')) >= 260 or any(
            p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('Unsafe animation resource path')
    return value


def _walk(node):
    yield node
    for child in node['children']:
        yield from _walk(child)


def _witness(tree):
    rows = [n for n in tree['children'] if n['name'] == 'data']
    if len(rows) != 1:
        raise ValueError('Missing animation resource witnesses')
    result = set()
    for row in rows[0]['children']:
        if row['name'] != 'element' or row['attributes'] or row['value'] is not None:
            raise ValueError('Unexpected animation resource witness')
        fields = {n['name']: n['value'] for n in row['children']}
        if len(fields) != len(row['children']) or any(n['children'] or n['attributes'] for n in row['children']):
            raise ValueError('Invalid animation resource witness fields')
        result.add((_norm(fields['name']), fields['type']))
    return result


def prepare(read, decode, encode):
    """Return 619 adapted clips, five maps and their preload references.

    The importer supplies a source-hash-verifying read(path) function. BXML
    decode/encode are supplied to share the importer's validated format parser.
    """
    models = {path: frames(read(path)) for path in (STORM, CHAZ, CASSIDY)}
    params = {path: parameters(models[path], models[CASSIDY]) for path in (STORM, CHAZ)}
    outputs, tables, reusable = {}, [], {}
    for alias, source, destination, basis, witness, count in TABLES:
        table = decode(read(source))
        witnessed = _witness(decode(read(witness)))
        if (source[:-5], 'AnimatedCharacterResource') not in witnessed:
            raise ValueError('Animation table resource-type witness missing')
        mapping, refs = {}, []
        for node in _walk(table):
            if node['name'] != 'KeyframeAnimation':
                continue
            original = _norm(node['attributes']['Name']) + '.sanm'
            if not original.startswith('characters/'):
                raise ValueError('Unsupported animation resource path')
            if original not in mapping:
                if not all((original[:-5], kind) in witnessed for kind in KINDS):
                    raise ValueError('Animation clip resource-type witness missing')
                raw = read(original)
                data, _ = retarget(expand(raw), params[basis])
                verify_preserved(raw, data)
                key = (original, hashlib.sha256(data).hexdigest())
                target = reusable.get(key)
                if target is None:
                    stem = 'coop' if basis == STORM else 'chaz'
                    target = 'characters/player_two/cassidyanimations/' + stem + '/' + original
                    if target in outputs:
                        raise ValueError('Retarget destination collision')
                    outputs[target] = data
                    reusable[key] = target
                mapping[original] = target
                refs.append(dict(source=original, output=target, source_basis=basis))
            node['attributes']['Name'] = mapping[original][:-5]
        if len(mapping) != count:
            raise ValueError('Unexpected animation-table coverage')
        data = encode(table)
        if decode(data) != table:
            raise ValueError('Animation table roundtrip failed')
        outputs[destination] = data
        tables.append(dict(alias=alias, source=source, output=destination, source_basis=basis,
                           resource_witness=witness, clips=refs, resource_types=list(KINDS)))
    source = 'characters/multiplayer/multiplayeranimation.bxml'
    table = decode(read(source))
    clips = sorted({_norm(n['attributes']['Name']) + '.sanm' for n in _walk(table)
                    if n['name'] == 'KeyframeAnimation'})
    if len(clips) != 291:
        raise ValueError('Unexpected solo animation-table coverage')
    mapping, solo_clips = {}, []
    for original in clips:
        if not original.startswith('characters/'):
            raise ValueError('Unsupported solo animation resource path')
        raw = read(original)
        if sections(raw)[0] & 32:
            raise ValueError('Unsupported solo packed animation')
        data, changed = retarget(raw, params[CHAZ])
        sha = hashlib.sha256(data).hexdigest()
        target = reusable.get((original, sha), 'characters/player_two/cassidyanimations/solo/' + original)
        if target in outputs and outputs[target] != data:
            raise ValueError('Solo animation destination collision')
        outputs[target] = data
        mapping[original] = target
        solo_clips.append(dict(source=original, output=target, sha256=sha, source_basis=CHAZ, pose_keys=changed))
    for node in _walk(table):
        if node['name'] == 'KeyframeAnimation':
            node['attributes']['Name'] = mapping[_norm(node['attributes']['Name']) + '.sanm'][:-5]
    data = encode(table)
    if decode(data) != table:
        raise ValueError('Solo animation table roundtrip failed')
    outputs['characters/player_two/cassidysolomultiplayeranimation.bxml'] = data
    if len(outputs) != 624:
        raise ValueError('Incomplete character animation output')
    return outputs, tables, solo_clips
