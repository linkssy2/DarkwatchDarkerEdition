"""Derive a player-sized, wingless spectral Cassidy from the verified disc.

The original player clips keep their event bytes, timing and body-track masks.
Only presentation resources are produced here; this module supplies no boss AI,
attacks, collision, original mesh data or original animation payloads.
"""
import copy
import hashlib
import math
import struct

try:
    from . import character_animation as animation
    from . import character_assets as assets
except ImportError:
    import character_animation as animation
    import character_assets as assets


BOSS = 'characters/cassidyboss/base_cassidy_boss'
MODEL = 'characters/player_two/base_cassidy_spectral'
LOCATOR = 'characters/player_two/cassidyspectralplayertwo'
SOLO_LOCATOR = 'characters/player_two/cassidyspectralsolo'
SOLO_TABLE = 'characters/player_two/cassidyspectralsolomultiplayeranimation.bxml'
SCALE = .4  # Original boss body bind lengths are 2.5 times regular Cassidy.
BONES = 51
BODY_BONES = 22
MISSING = 0xffffffff
CONTAINERS = (16, 14, 26, 15, 20, 3, 8, 7, 6)


def _records(data, start=0, end=None, parent=0):
    for tag, a, z in animation._chunks(data, start, len(data) if end is None else end):
        yield tag, a, z, parent
        if tag in CONTAINERS:
            yield from _records(data, a, z, tag)


def rig(data, bones):
    """Read bone IDs independently of the serialized frame order."""
    lists = [(a, z) for t, a, z, p in _records(data) if t == 14]
    if len(lists) != 1:
        raise ValueError('Expected one character frame list')
    chunks = list(animation._chunks(data, *lists[0]))
    if not chunks or chunks[0][0] != 1:
        raise ValueError('Missing character frame structure')
    _, start, end = chunks[0]
    if end-start < 4:
        raise ValueError('Truncated character frame count')
    count = struct.unpack_from('<I', data, start)[0]
    if count != bones+1 or end-start != 4+56*count or len(chunks) != count+1:
        raise ValueError('Unexpected character frame count')
    result, transforms, frame_bones = {}, [], {}
    for frame, (tag, a, z) in enumerate(chunks[1:]):
        if tag != 3:
            raise ValueError('Unexpected frame extension')
        at = start+4+56*frame
        values = struct.unpack_from('<12f2i', data, at)
        if not all(math.isfinite(x) for x in values[:12]) or not -1 <= values[12] < frame:
            raise ValueError('Invalid character transform')
        transforms.append(values)
        for t, x, e in animation._chunks(data, a, z):
            if t != 0x11e:
                continue
            if e-x < 12:
                raise ValueError('Truncated bone identifier')
            _, bone, nodes = struct.unpack_from('<3I', data, x)
            if bone in result or frame in frame_bones:
                raise ValueError('Duplicate bone identifier')
            if nodes:
                if nodes != bones or e-x != 20+12*bones:
                    raise ValueError('Unexpected HAnim hierarchy')
                if any(struct.unpack_from('<II', data, x+20+12*i) != (i, i) for i in range(bones)):
                    raise ValueError('HAnim bone index mismatch')
            result[bone] = dict(frame=frame, parent=values[12], rotation=values[:9],
                                translation=values[9:12], offset=at)
            frame_bones[frame] = bone
    if sorted(result) != list(range(bones)):
        raise ValueError('Incomplete character skeleton')
    for row in result.values():
        row['parent_bone'] = frame_bones.get(row['parent'])
    return result, transforms, start+4


def body_parameters(source, target):
    """The shared body uses matching bone IDs, even when frame order differs."""
    old, _, _ = rig(source, BODY_BONES)
    new, _, _ = rig(target, BONES)
    for bone in range(BODY_BONES):
        if old[bone]['parent_bone'] != new[bone]['parent_bone']:
            raise ValueError('Spectral body hierarchy differs from the player')
    normalized = {bone: dict(new[bone], frame=old[bone]['frame'], parent=old[bone]['parent'])
                  for bone in range(BODY_BONES)}
    return animation.parameters(old, normalized)


def scaled_model(original, regular, geometry_count=3):
    """Scale positions, binds and bounds together; retain materials and UVs."""
    boss, frames, frame_at = rig(original, BONES)
    normal, normal_frames, _ = rig(regular, BODY_BONES)
    for bone in range(BODY_BONES):
        a, b = boss[bone], normal[bone]
        # Boss knees are slightly straighter in the bind pose. The existing
        # rest-rotation retargeter handles those four leg deltas explicitly.
        if a['parent_bone'] != b['parent_bone'] or (bone not in (1,2,4,5) and any(
                abs(x-y) > 3e-5 for x, y in zip(a['rotation'], b['rotation']))) or any(
                abs(x*SCALE-y) > 3e-5 for x, y in zip(a['translation'], b['translation'])):
            raise ValueError('Boss body is not the witnessed 2.5x Cassidy skeleton')
    output = bytearray(original)
    def scale(at, count):
        values = struct.unpack_from('<'+'f'*count, original, at)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Nonfinite model coordinate')
        struct.pack_into('<'+'f'*count, output, at, *(v*SCALE for v in values))
    for i in range(len(frames)):
        scale(frame_at+56*i+36, 3)
    # The non-bone scene root has an authoring offset, not a body proportion.
    struct.pack_into('<12f', output, frame_at, *normal_frames[0][:12])
    geometries = [(a,z) for t,a,z,p in _records(original) if t == 15]
    if len(geometries) != geometry_count:
        raise ValueError('Expected boss eyes, wings and body geometries')
    for a, z in geometries:
        rows = list(_records(original, a, z, 15))
        structs = [(s,e) for t,s,e,p in rows if t == 1 and p == 15]
        if len(structs) != 1 or structs[0][1]-structs[0][0] != 40:
            raise ValueError('Unexpected native geometry structure')
        ga, _ = structs[0]
        _, _, vertices, morphs = struct.unpack_from('<4I', original, ga)
        if morphs != 1:
            raise ValueError('Unexpected model morph count')
        scale(ga+16, 4)  # Morph sphere centre and radius.
        na, nz = next((s,e) for t,s,e,p in rows if t == 0x510)
        native = list(animation._chunks(original, na, nz))
        if len(native) != 1 or native[0][0] != 1:
            raise ValueError('Unexpected native vertex structure')
        _, ns, ne = native[0]
        platform, size = struct.unpack_from('<II', original, ns)
        header = ns+4
        _, _, primitive, count, stride = struct.unpack_from('<HHIII', original, header+4)
        vb = header+size
        if platform != 5 or count != vertices or primitive not in (5,6) or stride not in (28,36) or vb+vertices*stride != ne:
            raise ValueError('Unexpected native vertex layout')
        for i in range(vertices):
            scale(vb+i*stride, 3)
        sa, sz = next((s,e) for t,s,e,p in rows if t == 0x116)
        skin = list(animation._chunks(original, sa, sz))
        if len(skin) != 1 or skin[0][0] != 1:
            raise ValueError('Unexpected native skin structure')
        _, ss, se = skin[0]
        if struct.unpack_from('<II', original, ss) != (5,BONES):
            raise ValueError('Unexpected native skin skeleton')
        used, weights, _, stride = struct.unpack_from('<4I', original, ss+2056)
        inverse = ss+2072+vertices*stride
        if not 1 <= weights <= 4 or stride != 3*weights or used > BONES or inverse+BONES*64+12 != se or original[se-12:se] != bytes(12):
            raise ValueError('Unexpected native skin weights')
        for bone in range(BONES):
            scale(inverse+bone*64+48, 3)
    poses = [(a,z) for t,a,z in animation._chunks(original,0,len(original)) if t == 0x1b]
    if len(poses) != 1:
        raise ValueError('Missing native bind animation')
    start, end = poses[0]
    version, kind, keys, flags = struct.unpack_from('<4I', original, start)
    if (version,kind,keys,flags) != (0x100,1,2*BONES,0) or end-start != 20+keys*36:
        raise ValueError('Unexpected native bind animation layout')
    for key in range(keys):
        scale(start+20+36*key+24, 3)
    body_parameters(regular, output)
    return bytes(output)


def without_wings(data):
    """Remove the witnessed wing geometry/atomic, preserving body skin indices.

    The 51-bone layout remains intact for the native skin and ragdoll readers.
    Player animations explicitly mask its unused wing bones; no wing clip runs.
    """
    roots = list(animation._chunks(data,0,len(data)))
    clumps = [(a,z) for t,a,z in roots if t == 16]
    if len(clumps) != 1:
        raise ValueError('Expected one spectral model clump')
    start,end = clumps[0]
    children = list(animation._chunks(data,start,end))
    def chunk(a,z,payload=None):
        if payload is None:
            return data[a-12:z]
        header = bytearray(data[a-12:a]);struct.pack_into('<I',header,4,len(payload))
        return header+payload
    structures = [(a,z) for t,a,z in children if t == 1]
    lists = [(a,z) for t,a,z in children if t == 26]
    atomics = [(a,z) for t,a,z in children if t == 20]
    if len(structures) != 1 or len(lists) != 1 or len(atomics) != 3:
        raise ValueError('Unexpected spectral geometry containers')
    a,z = structures[0]
    if z-a != 12 or struct.unpack_from('<3I',data,a) != (3,0,0):
        raise ValueError('Unexpected spectral atomic count')
    la,lz = lists[0]; geometry = list(animation._chunks(data,la,lz))
    if [t for t,_,_ in geometry] != [1,15,15,15] or geometry[0][2]-geometry[0][1] != 4 or struct.unpack_from('<I',data,geometry[0][1])[0] != 3:
        raise ValueError('Unexpected spectral geometry list')
    _,wa,wz = geometry[2]
    wing = list(_records(data,wa,wz,15))
    names = [data[a:z].rstrip(b'\0') for t,a,z,p in wing if t == 2 and p == 6 and data[a:z].rstrip(b'\0')]
    structs = [(a,z) for t,a,z,p in wing if t == 1 and p == 15]
    if names != [b'Cassidy_wings'] or len(structs) != 1 or struct.unpack_from('<I',data,structs[0][0]+8)[0] != 704:
        raise ValueError('Wing geometry identity differs')
    rebuilt = bytearray(); atomic_index = 0
    for t,a,z in children:
        if t == 1:
            rebuilt += chunk(a,z,struct.pack('<3I',2,0,0))
        elif t == 26:
            _,s,e = geometry[0]
            payload = chunk(s,e,struct.pack('<I',2))
            for _,s,e in (geometry[1],geometry[3]):payload += chunk(s,e)
            rebuilt += chunk(a,z,payload)
        elif t == 20:
            parts = list(animation._chunks(data,a,z))
            if not parts or parts[0][0] != 1 or parts[0][2]-parts[0][1] != 16:
                raise ValueError('Unexpected spectral atomic structure')
            _,s,e = parts[0]
            if struct.unpack_from('<4I',data,s) != (1,atomic_index,5,0):
                raise ValueError('Spectral atomic geometry index differs')
            if atomic_index != 1:
                payload = chunk(s,e,struct.pack('<4I',1,0 if atomic_index == 0 else 1,5,0))
                for _,s,e in parts[1:]:payload += chunk(s,e)
                rebuilt += chunk(a,z,payload)
            atomic_index += 1
        else:
            rebuilt += chunk(a,z)
    return b''.join(chunk(a,z,rebuilt) if t == 16 else chunk(a,z) for t,a,z in roots)


def player_eye_shading(data):
    """Give the player eye mesh a pale-blue prelight instead of authored black."""
    geometry = [(a, z) for t, a, z, p in _records(data) if t == 15]
    if len(geometry) != 2:
        raise ValueError('Expected wingless spectral body')
    rows = list(_records(data, *geometry[0], 15))
    names = [data[a:z].rstrip(b'\0') for t, a, z, p in rows
             if t == 2 and p == 6 and data[a:z].rstrip(b'\0')]
    native = [(a, z) for t, a, z, p in rows if t == 0x510]
    if names != [b'Ghost cassidy_eyeball_X'] or len(native) != 1:
        raise ValueError('Unexpected spectral eye geometry')
    chunks = list(animation._chunks(data, *native[0]))
    if len(chunks) != 1 or chunks[0][0] != 1:
        raise ValueError('Unexpected spectral eye vertex data')
    _, start, end = chunks[0]
    platform, size = struct.unpack_from('<II', data, start)
    header = start+4
    count, stride = struct.unpack_from('<II', data, header+12)
    vertices = header+size
    if platform != 5 or count != 122 or stride != 28 or vertices+count*stride != end:
        raise ValueError('Unexpected spectral eye vertex layout')
    result = bytearray(data)
    for vertex in range(count):
        color = vertices+vertex*stride+16
        if struct.unpack_from('<I', data, color)[0] != 0xff000000:
            raise ValueError('Unexpected spectral eye prelight')
        # Keep the authored iris and pupils; brighten only their player shading.
        struct.pack_into('<I', result, color, 0xff9cceff)
    return bytes(result)


def sections(data, bones):
    """Validate variable-bone SANM; retain the existing pose codec conventions."""
    if len(data) < 24:
        raise ValueError('Truncated animation header')
    version, magic, count, duration, _, flags = struct.unpack_from('<IIIfII', data)
    if not (16 <= version <= 40 and magic == 0xf11e0006 and count == bones and
            math.isfinite(duration) and duration >= 0 and not flags & 0x20000000):
        raise ValueError('Unsupported spectral animation header')
    pos, result = 24, {}
    for bit, stride in animation.ORDER:
        if not flags & bit:
            continue
        start = pos
        if pos+4 > len(data):
            raise ValueError('Truncated animation section')
        count = struct.unpack_from('<I', data, pos)[0]; pos += 4
        indices = ()
        if bit in (4,8,32):
            if pos+4*bones > len(data):
                raise ValueError('Truncated animation bone index')
            indices = struct.unpack_from('<'+'I'*bones, data, pos); pos += 4*bones
            valid = [i for i in indices if i != MISSING]
            if valid != sorted(valid) or any(i >= count for i in valid):
                raise ValueError('Invalid animation bone index')
        end = pos+count*stride
        if end > len(data):
            raise ValueError('Truncated animation keys')
        if bit == 1 and count != bones:
            raise ValueError('Invalid animation bone mask length')
        result[bit] = dict(start=start,end=end,count=count,indices=indices,keys=pos,stride=stride)
        pos = end
    if pos != len(data):
        raise ValueError('Unexpected animation trailing data')
    return flags, result


def expand_player(data):
    """Keep player tracks and explicitly exclude wings from the native bone map."""
    flags, parts = animation.sections(data)
    output = bytearray(data[:24]); struct.pack_into('<I',output,8,BONES)
    struct.pack_into('<I',output,20,flags | 1)
    mask = parts.get(1)
    if mask and mask['count'] != BODY_BONES:
        raise ValueError('Invalid player animation bone mask length')
    body_mask = data[mask['keys']:mask['end']] if mask else bytes(4*BODY_BONES)
    # Native 241AA6 tests bit0 of each u32: one excludes that bone. Missing pose
    # indices alone do not exclude a bone from an independently blended group.
    output += struct.pack('<I',BONES)+body_mask+struct.pack('<29I',*([1]*29))
    for bit, _ in animation.ORDER:
        if bit not in parts or bit == 1:
            continue
        row = parts[bit]
        if bit in (4,8,32):
            output += data[row['start']:row['keys']]+struct.pack('<29I',*([MISSING]*29))
            output += data[row['keys']:row['end']]
        else:
            output += data[row['start']:row['end']]
    new_flags, new = sections(output,BONES)
    if new_flags != flags | 1:
        raise ValueError('Player animation flags changed')
    for bit, row in parts.items():
        if bit == 1:
            continue
        after = new[bit]
        if data[row['keys']:row['end']] != output[after['keys']:after['end']] or row['indices'] != after['indices'][:BODY_BONES]:
            raise ValueError('Player animation content changed')
    return bytes(output)


def locators(player, boss, regular):
    """Retain player attachments and add scaled boss visual-effect anchors."""
    original = assets.decode(player); extra = assets.decode(boss)
    if original['name'] != 'locator_list' or extra['name'] != 'locator_list':
        raise ValueError('Unexpected locator list')
    mapped = {n['attributes']['name']:n for n in original['children']}
    if len(mapped) != len(original['children']):
        raise ValueError('Duplicate player locator')
    for item in extra['children']:
        name = item['attributes']['name']
        if name not in ('loc_Head','loc_RightHand','loc_LeftHand','loc_bossQuaternary'):
            continue
        row = copy.deepcopy(item)
        values = [float(x.strip()) for x in row['attributes']['pos'].split(',')]
        if len(values) != 3 or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid boss locator position')
        row['attributes']['pos'] = ', '.join(f'{v*SCALE:.9f}' for v in values)
        if name in mapped:
            original['children'][original['children'].index(mapped[name])] = row
        else:
            original['children'].append(row)
    # Use Cassidy's authored gun grip instead of the boss's offset hand marker.
    grip = assets.child(assets.decode(regular), 'loc_RightHand')
    if grip['attributes']['parent'] != 'weaponJoint_RightHand':
        raise ValueError('Unexpected Cassidy weapon attachment parent')
    original['children'][original['children'].index(
        assets.child(original, 'loc_RightHand'))] = copy.deepcopy(grip)
    return assets.encode(original)


def prepare(read):
    """Return private derived assets and typed animation references for import."""
    try:
        from . import character_secondary as secondary
    except ImportError:
        import character_secondary as secondary
    model = player_eye_shading(without_wings(scaled_model(read(BOSS+'.rx1'),read(animation.CASSIDY))))
    joints = read(BOSS+'.jlist')
    names = [s.strip() for s in joints.decode('ascii').splitlines() if s.strip()]
    regular_names = [s.strip() for s in read(animation.CASSIDY[:-4]+'.jlist').decode('ascii').splitlines() if s.strip()]
    if len(names) != BONES or len(regular_names) != BODY_BONES or names[:BODY_BONES] != regular_names:
        raise ValueError('Spectral joint-name mapping differs from Cassidy')
    model = secondary.prepare(model)
    outputs = {MODEL+'.rx1':model,MODEL+'.jlist':secondary.joint_names(joints)}
    regular_locators = read('characters/cassidy/base_cassidy.bllist')
    outputs[LOCATOR+'.bllist'] = locators(read('characters/multiplayer/base_dwstormtrooper_coop.bllist'),read(BOSS+'.bllist'),regular_locators)
    outputs[SOLO_LOCATOR+'.bllist'] = locators(read('characters/player_third/base_chaz.bllist'),read(BOSS+'.bllist'),regular_locators)
    # Model and attachment resource names are distinct in the existing importer.
    outputs[MODEL+'.bllist'] = outputs[LOCATOR+'.bllist']
    parameters = {p:body_parameters(read(p),model) for p in (animation.STORM,animation.CHAZ)}
    refs, reusable = [], {}
    for alias,source,destination,basis,witness,expected in animation.TABLES:
        table = assets.decode(read(source)); witnessed = animation._witness(assets.decode(read(witness)))
        if (source[:-5],'AnimatedCharacterResource') not in witnessed:
            raise ValueError('Missing player animation table witness')
        mapping, clips = {}, []
        for node in assets.walk(table):
            if node['name'] != 'KeyframeAnimation':
                continue
            original = assets.norm(node['attributes']['Name'])+'.sanm'
            if original not in mapping:
                if not all((original[:-5],kind) in witnessed for kind in animation.KINDS):
                    raise ValueError('Missing player animation clip witnesses')
                data,_ = animation.retarget(animation.expand(read(original)),parameters[basis])
                data = expand_player(data)
                key = (original,hashlib.sha256(data).hexdigest())
                target = reusable.get(key)
                if target is None:
                    target = 'characters/player_two/cassidyspectralanimations/'+('coop/' if basis==animation.STORM else 'chaz/')+original
                    if target in outputs:
                        raise ValueError('Spectral animation destination collision')
                    outputs[target] = data; reusable[key] = target
                mapping[original] = target
                clips.append(dict(source=original,output=target))
            node['attributes']['Name'] = mapping[original][:-5]
        if len(mapping) != expected:
            raise ValueError('Unexpected player animation coverage')
        destination = destination.replace('/cassidy','/cassidyspectral')
        outputs[destination] = assets.encode(table)
        refs.append(dict(alias=alias,source=source,output=destination,clips=clips,resource_types=list(animation.KINDS)))
    source = 'characters/multiplayer/multiplayeranimation.bxml'
    table = assets.decode(read(source)); mapping, clips = {}, []
    for node in assets.walk(table):
        if node['name'] != 'KeyframeAnimation':
            continue
        original = assets.norm(node['attributes']['Name'])+'.sanm'
        if original not in mapping:
            data,_ = animation.retarget(animation.expand(read(original)),parameters[animation.CHAZ])
            data = expand_player(data)
            key = (original,hashlib.sha256(data).hexdigest())
            target = reusable.get(key)
            if target is None:
                target = 'characters/player_two/cassidyspectralanimations/solo/'+original
                if target in outputs:
                    raise ValueError('Spectral solo animation destination collision')
                outputs[target] = data; reusable[key] = target
            mapping[original] = target; clips.append(dict(source=original,output=target))
        node['attributes']['Name'] = mapping[original][:-5]
    if len(mapping) != 291:
        raise ValueError('Unexpected spectral solo animation coverage')
    outputs[SOLO_TABLE] = assets.encode(table)
    refs.append(dict(alias='SoloMulti',source=source,output=SOLO_TABLE,clips=clips,resource_types=list(animation.KINDS)))
    return outputs, refs
