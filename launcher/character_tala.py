"""Derive the wingless playable Tala boss from the user's original disc."""
import hashlib
import struct

import character_animation as animation
import character_assets as art
import character_boss as boss
import character_repaint as rw
import character_spectral_hands as skin
import character_secondary as secondary
import character_tala_shape as shape

VAMPIRE = 'characters/tala/base_cine_tala'
ORIGINAL_BOSS = 'characters/tala_boss/base_tala_boss'
MODEL = 'characters/player_roster/base_tala_boss'


def without_wings(raw):
    """Remove both the large wings and the wing-root material on the body."""
    clumps = [part for tag, part in rw.chunks(raw) if tag == 16]
    if len(clumps) != 1:
        raise ValueError('Unexpected Tala boss clump')
    clump = clumps[0]
    geolist = skin._one(clump, 26)
    geos = [part for tag, part in rw.chunks(geolist, 12) if tag == 15]
    atomics = [part for tag, part in rw.chunks(clump, 12) if tag == 20]
    if len(geos) != 2 or len(atomics) != 2:
        raise ValueError('Unexpected Tala boss geometry count')
    wing_names = [geos[1][a:z].rstrip(b'\0') for t,a,z,p in boss._records(geos[1])
                  if t == 2 and p == 6 and geos[1][a:z].rstrip(b'\0')]
    materials = [part for tag, part in rw.chunks(skin._one(geos[0], 8), 12) if tag == 7]
    if wing_names != [b'Tala_wings_B_clr_X'] or len(materials) != 5 or b'Tala_wings_B_clr_X\0' not in materials[-1]:
        raise ValueError('Unexpected Tala boss wing materials')
    extension = skin._one(geos[0], 3)
    native = skin._one(extension, 0x510)
    native_struct = bytearray(skin._one(native, 1))
    header = 16
    size = struct.unpack_from('<I', native_struct, header)[0]
    serial, count, primitive, vertices, stride = struct.unpack_from('<HHIII', native_struct, header+4)
    if (count, primitive, vertices, stride) != (5, 6, 2696, 28):
        raise ValueError('Unexpected Tala boss body vertex layout')
    batches = [struct.unpack_from('<6I', native_struct, header+36+i*24) for i in range(count)]
    pointers = sorted({row[4] for row in batches})
    if len(pointers) != 5 or [pointers.index(row[4]) for row in batches] != [0,2,3,1,4]:
        raise ValueError('Unexpected Tala boss body material order')
    triangles = 0
    for row in batches[:-1]:
        at = header-24+row[3]
        if at < header+36+count*24 or at+2*row[2] > header+size:
            raise ValueError('Invalid Tala boss body indices')
        ids = struct.unpack_from('<' + str(row[2]) + 'H', native_struct, at)
        if any(i >= vertices for i in ids):
            raise ValueError('Invalid Tala boss body vertex')
        triangles += sum(len(set(ids[i:i+3])) == 3 for i in range(len(ids)-2))
    struct.pack_into('<H', native_struct, header+6, 4)
    mesh = skin._one(extension, 0x50e)
    values = struct.unpack_from('<13I', mesh, 12)
    if values[:3] != (1, 5, sum(row[2] for row in batches)) or values[-2:] != (23, 4):
        raise ValueError('Unexpected Tala boss native mesh map')
    new_mesh = skin._chunk(0x50e, struct.pack('<11I', 1, 4, values[2]-23, *values[3:-2]))
    new_extension = rw.rebuild(extension, b''.join(
        new_mesh if tag == 0x50e else rw.rebuild(native, bytes(native_struct)) if tag == 0x510 else part
        for tag, part in rw.chunks(extension, 12)))
    structure = bytearray(skin._one(geos[0], 1))
    struct.pack_into('<I', structure, 16, triangles)
    new_materials = skin._chunk(8, skin._chunk(1, struct.pack('<5I', 4, *([0xffffffff]*4))) + b''.join(materials[:-1]))
    body = rw.rebuild(geos[0], b''.join(
        bytes(structure) if tag == 1 else new_materials if tag == 8 else new_extension if tag == 3 else part
        for tag, part in rw.chunks(geos[0], 12)))
    for i, atomic in enumerate(atomics):
        if struct.unpack_from('<4I', skin._one(atomic, 1), 12) != (1,i,5,0):
            raise ValueError('Unexpected Tala boss atomic')
    first = True
    parts = []
    for tag, part in rw.chunks(clump, 12):
        if tag == 1:
            part = skin._chunk(1, struct.pack('<3I', 1, 0, 0))
        elif tag == 26:
            part = skin._chunk(26, skin._chunk(1, struct.pack('<I', 1)) + body)
        elif tag == 20:
            if not first:
                continue
            first = False
        parts.append(part)
    rebuilt = rw.rebuild(clump, b''.join(parts))
    return b''.join(rebuilt if tag == 16 else part for tag, part in rw.chunks(raw))


def model(read):
    original, regular = read(ORIGINAL_BOSS+'.rx1'), read(VAMPIRE+'.rx1')
    if hashlib.sha256(original).hexdigest() != '775d6bbd677ee25b07cdc6194b35b5e5df18eecf12ffacd694ded4357ace11ef':
        raise ValueError('Unexpected original Tala boss')
    return secondary.prepare_tala(without_wings(boss.scaled_model(original, regular, geometry_count=2)))


def presentation(prepared, reference):
    """Finish the visible body after native hand and animation derivation."""
    return shape.upper_motion(shape.reshape(prepared, reference))


def _arm_maps(read, derived, *, dual=False):
    delta = boss.body_parameters(read(VAMPIRE+'.rx1'), derived)
    old = animation.frames(read(VAMPIRE+'.rx1'))
    target, _, _ = boss.rig(derived, 51)
    # The existing final Vampire-to-Boss conversion remains in place. Compose
    # its right-side bind correction out of the intermediate arm mapping.
    target = {bone: dict(target[bone], frame=old[bone]['frame'], parent=old[bone]['parent'])
              for bone in range(22)}
    locators = {basis: art.encode(adapt(art.decode(read(path)), art.decode(read(VAMPIRE+'.bllist'))))
        for basis, path, adapt in ((animation.CHAZ, 'characters/player_third/base_chaz.bllist', art.solo_locators),
                                  (animation.STORM, 'characters/multiplayer/base_dwstormtrooper_coop.bllist', art.adapt_locators))} if dual else None
    arms = animation.player_arm_parameters(read, art.decode, target, VAMPIRE+'.bllist', dual=dual, dual_locators=locators)
    for basis in arms:
        arms[basis] = {bone: (left, animation._multiply(delta[bone][0], parent))
                       for bone, (left, parent) in arms[basis].items()}
    return arms


def animations(read, derived, cancel=lambda: None, progress=lambda message: None):
    outputs, _, _ = animation.prepare(read, art.decode, art.encode,
        VAMPIRE+'.rx1', 'bosstala', cancel=cancel, progress=progress, arm_maps=_arm_maps(read, derived),
        dual_arm_maps=_arm_maps(read, derived, dual=True))
    delta = boss.body_parameters(read(VAMPIRE+'.rx1'), derived)
    for path in outputs:
        if path.endswith('.sanm'):
            cancel()
            retargeted, _ = animation.retarget(outputs[path], delta)
            outputs[path] = boss.expand_player(retargeted)
    return outputs
