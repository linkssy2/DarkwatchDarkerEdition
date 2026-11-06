"""Body-only starter reload phases driven by the original cartridge hand motion.

The mechanical hands and weapon retain their original animations and events.
Only body rotation keys and their phase duration change; masks and local bone
translations remain byte-identical to the prepared body reload.
"""
import copy
import hashlib
import math
import struct

import character_assets as art
import character_weapon_pose as pose

MODEL = 'characters/player_first/base_pov_chaz.rx1'
LOOP = 'characters/player_first/sanm/med/pov_chaz_reload_pistol.sanm'
PREFIX = 'characters/player_two/reload/starter/'
TIMES = {'PRERELOAD': .6000000238418579, 'RELOAD': .3333333432674408, 'POSTRELOAD': .75}
BLENDS = {'PRERELOAD': ('0.100000', '0.001000'), 'RELOAD': ('0.001000', '0.100000'),
          'POSTRELOAD': ('0.001000', '0.300000')}


def _rotation_mix(first, last, amount):
    q, p = pose.a._to_quaternion(first), pose.a._to_quaternion(last)
    if pose.dot(q, p) < 0: p = pose.scale(p, -1)
    return pose.a._quaternion_matrix(pose.unit(pose.add(pose.scale(q, 1-amount), pose.scale(p, amount))))


class Motion:
    def __init__(self, source, adapted, read_original, target_model, target_locator, basis, offset, ready):
        if basis not in (pose.a.CHAZ, pose.a.STORM) or not math.isfinite(offset) or abs(offset) > .1:
            raise ValueError('Unsupported starter reload rig')
        bones = struct.unpack_from('<I', adapted, 8)[0]
        if bones not in (22, 51): raise ValueError('Unexpected starter body hierarchy')
        locator = basis[:-4] + ('_coop.bllist' if basis == pose.a.STORM else '.bllist')
        self.solver = pose.SupportRetarget(read_original(basis), target_model,
            pose._grip(read_original(locator)), pose._grip(target_locator), bones)
        self.source, self.target = pose.Clip(source, 22), pose.Clip(adapted, bones)
        self.raw, self.offset = adapted, offset
        if self.target.flags & 0x10000000 or set(self.target.parts) - {1, 4, 8} or 4 not in self.target.parts:
            raise ValueError('Starter reload must be an absolute body pose')
        for (_, bit), (_, values) in self.target.tracks.items():
            if bit == 8 and any(pose.length(pose.sub(v, values[0])) > 1e-8 for v in values[1:]):
                raise ValueError('Starter body has animated translation keys')
        loop = read_original(LOOP)
        fp_bones = struct.unpack_from('<I', loop, 8)[0]
        self.fp_bind, self.fp_parents = pose.rig(read_original(MODEL), fp_bones)
        self.fp = pose.Clip(loop, fp_bones)
        self.reference = self.relative_fp(.5)
        if set(ready) != {'STAND', 'CROUCH'}:
            raise ValueError('Missing starter ready stances')
        self.ready = {stance: pose.Clip(data, bones).pose(self.solver.target, .5)
                      for stance, data in ready.items()}
        self.loop_start, self.loop_end = self._insertion(0.), self._insertion(1.)
        self.translations = self.target.pose(self.solver.target, .5)

    def relative_fp(self, phase):
        world = pose.world(self.fp.pose(self.fp_bind, phase), self.fp_parents)
        return pose.mul(world[4], pose.inverse(world[21]))

    def _insertion(self, phase):
        local = self.solver.sample(self.source, self.target, .5, self.offset)
        before = pose.world(local, self.solver.parents)
        grip = self.solver.target_grip
        grip = grip[0], pose.add(grip[1], pose.scale(grip[0][0], self.offset))
        gun = pose.mul(grip, before[16])
        relative = pose.mul(before[20], pose.inverse(gun))
        fp = self.relative_fp(phase)
        rotation = pose.a._multiply(relative[0], pose.a._multiply(pose.a._inverse(self.reference[0]), fp[0]))
        desired = (_rotation_mix(relative[0], rotation, 1.),
            pose.add(relative[1], pose.sub(fp[1], self.reference[1])))
        return self.solver.fit_contacts(before, before, pose.mul(desired, gun))

    def sample(self, action, phase, stance='STAND'):
        if action == 'RELOAD': return self._insertion(phase)
        if action == 'PRERELOAD': first, last = self.ready[stance], self.loop_start
        elif action == 'POSTRELOAD': first, last = self.loop_end, self.ready[stance]
        else: raise ValueError('Unknown starter reload phase')
        # The old approach raised the elbow before bringing the hand inward.
        # Join ready and insertion directly, easing velocity and acceleration
        # to zero at both ends without changing the native phase clocks.
        amount = phase**3 * (10 + phase*(-15 + 6*phase))
        return {bone: (first[bone][0] if phase == 0 else last[bone][0] if phase == 1 else
                       _rotation_mix(first[bone][0], last[bone][0], amount), value[1])
                for bone, value in self.translations.items()}

    def bake(self, action, stance='STAND'):
        section = self.target.parts[4]
        phases = {i/60 for i in range(61)}
        if action == 'RELOAD':
            for times, _ in self.fp.tracks.values(): phases.update(times)
        rounded = lambda value: struct.unpack('<f', struct.pack('<f', value))[0]
        phases = sorted({rounded(value) for value in phases})
        phases = sorted(set(phases) | {rounded((lo+hi)/2) for lo, hi in zip(phases, phases[1:])})
        samples = {phase: self.sample(action, phase, stance) for phase in phases}
        keys, indices = bytearray(), []
        for bone, first in enumerate(section['indices']):
            if first == pose.MISSING: indices.append(first); continue
            indices.append(len(keys)//12)
            previous = None
            for phase, local in samples.items():
                q = pose.a._to_quaternion(local[bone][0])
                if previous is not None and pose.dot(q, previous) < 0: q = pose.scale(q, -1)
                previous = q
                keys += struct.pack('<f4h', phase, *[max(-32768, min(32767, round(v*32768))) for v in q])
        block = struct.pack('<I', len(keys)//12) + struct.pack('<'+'I'*self.solver.bones, *indices) + keys
        output = bytearray(self.raw[:section['start']] + block + self.raw[section['end']:])
        struct.pack_into('<f', output, 12, TIMES[action])
        return bytes(output)


def prepare_table(raw, read, read_original, target_model, target_locator, basis, offset=0.):
    """Split the starter's shared body action into native pre/insert/post phases."""
    tree = art.decode(raw)
    candidates = []
    for group in tree['children']:
        if group['name'] != 'AnimationGroup': continue
        for node in group['children']:
            flags = {child['attributes']['Flag'] for child in node['children'] if child['name'] == 'Modifier'}
            if node['name'] == 'KeyframeAnimation' and 'PISTOL' in flags and node['attributes'].get('AnimationID') in TIMES:
                candidates.append((group, node, flags))
    if len(candidates) != 1: raise ValueError('Unexpected starter body reload routes')
    group, node, flags = candidates[0]
    if flags != {'PISTOL', 'REVOLVER', 'OUT_OF_VEHICLE'} or node['attributes']['AnimationID'] != 'RELOAD':
        raise ValueError('Unsupported shared starter/redeemer reload')
    path = art.norm(node['attributes']['Name']) + '.sanm'
    original = pose._original(path)
    if not original.endswith('/dwagent_pistol_reload_ub.sanm'):
        raise ValueError('Unknown starter source animation')
    ready = {}
    for candidate in tree['children']:
        stance = {'Alert Poses UB': 'STAND', 'Crouch Alert Poses': 'CROUCH'}.get(candidate['attributes'].get('ToolName'))
        if not stance: continue
        rows = [entry for entry in candidate['children'] if entry['name'] == 'KeyframeAnimation' and
                any(child['name'] == 'Modifier' and child['attributes']['Flag'] == 'PISTOL' for child in entry['children'])]
        if len(rows) != 1: raise ValueError('Unexpected starter ready pose')
        ready[stance] = read(art.norm(rows[0]['attributes']['Name']) + '.sanm')
    motion = Motion(read_original(original), read(path), read_original, target_model, target_locator, basis, offset, ready)
    replacements, additions = [], {}
    for action in TIMES:
        for stance in (None,) if action == 'RELOAD' else ('STAND', 'CROUCH'):
            data = motion.bake(action, stance or 'STAND')
            name = PREFIX + hashlib.sha256(data).hexdigest()[:24]
            additions[name + '.sanm'] = data
            replacement = copy.deepcopy(node)
            replacement['attributes'].update(Name=name, AnimationID=action,
                BlendIn=BLENDS[action][0], DecayTime=BLENDS[action][1])
            replacement['children'] = [child for child in replacement['children'] if not
                (child['name'] == 'Modifier' and child['attributes']['Flag'] == 'REVOLVER')]
            lifecycle = ('PoseIn',) if action == 'PRERELOAD' else ('PoseOut', 'SelfBlend') if action == 'RELOAD' else ()
            replacement['children'][1:1] = [dict(name=name, attributes={}, children=[], value=None) for name in lifecycle]
            if stance:
                replacement['children'].append(dict(name='Modifier', attributes={'Flag': stance}, children=[], value=None))
            replacements.append(replacement)
    node['children'] = [child for child in node['children'] if not
        (child['name'] == 'Modifier' and child['attributes']['Flag'] == 'PISTOL')]
    index = next(i for i, value in enumerate(group['children']) if value is node)
    group['children'][index+1:index+1] = replacements
    group['attributes']['KeyedAnimationCount'] = str(sum(row['name'] == 'KeyframeAnimation' for row in group['children']))
    return art.encode(tree), additions
