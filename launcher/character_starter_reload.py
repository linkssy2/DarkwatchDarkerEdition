"""Body-only starter reload phases driven by the original cartridge hand motion.

The mechanical hands and weapon retain their original animations and events.
Only body rotation keys change. Native phase clocks, masks, local translations,
and weapon events remain unchanged.
"""
import copy
import hashlib
import math
import struct

import character_assets as art
import character_reload as reloads
import character_weapon_pose as pose

MODEL = 'characters/player_first/base_pov_chaz.rx1'
LOOP = 'characters/player_first/sanm/med/pov_chaz_reload_pistol.sanm'
PREFIX = 'characters/player_two/reload/starter/'
TIMES = {'PRERELOAD': .6000000238418579, 'RELOAD': .3333333432674408, 'POSTRELOAD': .75}
BLENDS = {'PRERELOAD': ('0.100000', '0.001000'), 'RELOAD': ('0.001000', '0.100000'),
          'POSTRELOAD': ('0.001000', '0.300000')}

# Distal loading-finger centers measured in each body hand's bind coordinates.
# The rigid body fingers differ from the articulated POV fingers; copying the
# POV wrist alone leaves them working on the holding arm instead of the cylinder.
FINGERTIPS = {
    **dict.fromkeys(('Chaz', 'JerichoCoop'), (.173426, .037032, .075800)),
    **dict.fromkeys(('CassidySolo', 'CassidyPlayerTwo'), (.161025, .010752, .032525)),
    **dict.fromkeys(('CassidySpectralSolo', 'CassidySpectralPlayerTwo'), (.164239, .003334, .027183)),
    **dict.fromkeys(('CivilianJerichoSolo', 'CivilianJerichoCoop'), (.174764, .060615, .070862)),
    **dict.fromkeys(('TrooperSolo', 'TrooperCoop', 'BlueTrooperSolo', 'BlueTrooperCoop',
                     'RedTrooperSolo', 'RedTrooperCoop'), (.226026, .030254, .064241)),
    **dict.fromkeys(('TalaSolo', 'TalaCoop'), (.153157, .004856, .020338)),
    **dict.fromkeys(('VampireTalaSolo', 'VampireTalaCoop'), (.145242, .015003, .032850)),
    **dict.fromkeys(('BossTalaSolo', 'BossTalaCoop'), (.154462, .015799, .022734)),
}
LOADING_GATE = (-.015, .085, .040)
LOADING_CLEARANCE = {
    **dict.fromkeys(('Chaz', 'JerichoCoop'), (.045, .120, .090)),
    **dict.fromkeys(('CivilianJerichoSolo', 'CivilianJerichoCoop'), (.035, .125, .100)),
    **dict.fromkeys(('TrooperSolo', 'TrooperCoop', 'BlueTrooperSolo', 'BlueTrooperCoop',
                     'RedTrooperSolo', 'RedTrooperCoop'), (.015, .105, .080)),
}
BODY_FROM_POV = ((0., 0., 1.), (0., 1., 0.), (-1., 0., 0.))


def _rotation_mix(first, last, amount):
    q, p = pose.a._to_quaternion(first), pose.a._to_quaternion(last)
    if pose.dot(q, p) < 0: p = pose.scale(p, -1)
    return pose.a._quaternion_matrix(pose.unit(pose.add(pose.scale(q, 1-amount), pose.scale(p, amount))))


def _outside_elbow(local, parents, first):
    """Keep the wrist fixed while bending the elbow below/outside the chest."""
    before = pose.world(local, parents)
    shoulder, elbow, wrist = (before[b][1] for b in (first, first+1, first+2))
    axis = pose.unit(pose.sub(wrist, shoulder))
    up = (0., 1., 0.)
    side = pose.unit(pose.sub(before[18][1], before[13][1]))
    forward = pose.unit(pose.cross(side, up))
    pole = pose.add(pose.sub(pose.scale(side, 2.0 if first == 18 else -2.0), up), pose.scale(forward, .3))
    pole = pose.unit(pose.sub(pole, pose.scale(axis, pose.dot(pole, axis))))
    upper = pose.sub(elbow, shoulder)
    along = pose.dot(upper, axis)
    radius = pose.length(pose.sub(upper, pose.scale(axis, along)))
    middle = pose.add(shoulder, pose.add(pose.scale(axis, along), pose.scale(pole, radius)))
    after = dict(before)
    after[first] = pose.a._multiply(before[first][0], pose.align(upper, pose.sub(middle, shoulder))), shoulder
    after[first+1] = pose.a._multiply(before[first+1][0], pose.align(pose.sub(wrist, elbow), pose.sub(wrist, middle))), middle
    return pose.localize(after, parents)

class Motion:
    def __init__(self, source, adapted, read_original, target_model, target_locator, basis, offset, ready, *, actor):
        if basis not in (pose.a.CHAZ, pose.a.STORM) or not math.isfinite(offset) or abs(offset) > .1:
            raise ValueError('Unsupported starter reload rig')
        if actor not in FINGERTIPS: raise ValueError('Unmeasured starter loading hand')
        bones = struct.unpack_from('<I', adapted, 8)[0]
        if bones not in (22, 51): raise ValueError('Unexpected starter body hierarchy')
        locator = basis[:-4] + ('_coop.bllist' if basis == pose.a.STORM else '.bllist')
        self.solver = pose.SupportRetarget(read_original(basis), target_model,
            pose._grip(read_original(locator)), pose._grip(target_locator), bones)
        # Validate the original shared reload layout before replacing its body motion.
        pose.Clip(source, 22)
        self.target = pose.Clip(adapted, bones)
        self.raw, self.offset = adapted, offset
        # The Trooper's broader upper arm needs about 4 cm of shoulder-side
        # clearance; moving the whole workspace preserves the cylinder contact.
        self.holding_lateral = .06 if actor in ('TrooperSolo', 'TrooperCoop', 'BlueTrooperSolo',
            'BlueTrooperCoop', 'RedTrooperSolo', 'RedTrooperCoop') else 0.
        self.glove_clearance = actor in LOADING_CLEARANCE
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
        self.contact = pose.sub(LOADING_CLEARANCE.get(actor, LOADING_GATE), pose.rotate(FINGERTIPS[actor],
            pose.a._multiply(BODY_FROM_POV, self.reference[0])))
        if set(ready) != {'STAND', 'CROUCH'}:
            raise ValueError('Missing starter ready stances')
        self.ready = {stance: pose.Clip(data, bones).pose(self.solver.target, .5)
                      for stance, data in ready.items()}
        self.holding, self.gun = self._holding_pose()
        self.loop_start, self.loop_end = self._insertion(0.), self._insertion(1.)
        self.translations = self.target.pose(self.solver.target, .5)

    def relative_fp(self, phase):
        world = pose.world(self.fp.pose(self.fp_bind, phase), self.fp_parents)
        return pose.mul(world[4], pose.inverse(world[21]))

    def _holding_pose(self):
        # Present the revolver ahead of the torso, with its right-side loading
        # gate rolled upward. Preserve the hand-to-grip transform and arm lengths.
        local = dict(self.ready['STAND'])
        before = pose.world(local, self.solver.parents)
        rs, re, rw = (before[b][1] for b in (13, 14, 15))
        ls = before[18][1]
        side = pose.unit(pose.sub(ls, rs))
        up = (0., 1., 0.)
        forward = pose.unit(pose.cross(side, up))
        angle = math.radians(30)
        bore = pose.add(pose.scale(forward, math.cos(angle)), pose.scale(up, math.sin(angle)))
        top = pose.sub(pose.scale(up, math.cos(angle)), pose.scale(forward, math.sin(angle)))
        gun_rotation = (bore, top, pose.unit(pose.cross(bore, top)))
        roll = math.radians(-60)
        gun_rotation = pose.a._multiply(((1.,0.,0.),(0.,math.cos(roll),math.sin(roll)),(0.,-math.sin(roll),math.cos(roll))), gun_rotation)
        length = pose.length(pose.sub(re, rs)) + pose.length(pose.sub(rw, re))
        target = pose.add(pose.scale(pose.add(rs, ls), .5),
            pose.sub(pose.scale(forward, length*.78), pose.scale(up, length*.3)))
        target = pose.add(target, pose.scale(side, -length*self.holding_lateral))
        grip = self.solver.target_grip
        grip = grip[0], pose.add(grip[1], pose.scale(grip[0][0], self.offset))
        weapon = pose.mul(before[16], pose.inverse(before[15]))
        wrist_to_gun = pose.mul(grip, weapon)
        wrist_rotation = pose.a._multiply(pose.a._inverse(wrist_to_gun[0]), gun_rotation)
        elbow, wrist = pose.solve(rs, re, rw, target)
        before[13] = pose.a._multiply(before[13][0], pose.align(pose.sub(re, rs), pose.sub(elbow, rs))), rs
        before[14] = pose.a._multiply(before[14][0], pose.align(pose.sub(rw, re), pose.sub(wrist, elbow))), elbow
        before[15] = wrist_rotation, wrist
        before[16] = pose.mul(weapon, before[15])
        before = pose.world(_outside_elbow(pose.localize(before, self.solver.parents), self.solver.parents, 13), self.solver.parents)
        return before, pose.mul(grip, before[16])

    def _insertion(self, phase):
        fp = self.relative_fp(phase)
        delta = pose.sub(fp[1], self.reference[1])
        # The POV hand withdraws 30 cm along the barrel. A body-sized cartridge
        # stroke instead retreats beside the open gate, clear of the chest.
        stroke = (delta[0]*.1, delta[1]*.25, delta[2]*.25 - delta[0]*.2)
        desired = (pose.a._multiply(BODY_FROM_POV, fp[0]),
            pose.add(self.contact, stroke))
        if self.glove_clearance and .6 < phase < 1.:
            outward = .02 * math.sin(math.pi*(phase-.6)/.4)**2
            desired = desired[0], pose.add(desired[1], (0., 0., outward))
        fitted = reloads.fit_loading_hand(self.holding, self.solver.parents,
                                          pose.mul(desired, self.gun))
        return _outside_elbow(fitted, self.solver.parents, 18)

    def sample(self, action, phase, stance='STAND'):
        if action == 'RELOAD': return self._insertion(phase)
        if action == 'PRERELOAD': first, last = self.ready[stance], self.loop_start
        elif action == 'POSTRELOAD': first, last = self.loop_end, self.ready[stance]
        else: raise ValueError('Unknown starter reload phase')
        # The old approach raised the elbow before bringing the hand inward.
        # Join ready and insertion directly. A cubic ease spreads the longer
        # loading-hand turn instead of rushing through its midpoint, while
        # retaining zero endpoint velocity and the native phase clocks.
        amount = phase*phase*(3 - 2*phase)
        # Leading the loading hand clears the holding glove in crouched joins.
        loading_phase = min(1., phase/.85) if action == 'PRERELOAD' else max(0., (phase-.15)/.85)
        loading_amount = loading_phase*loading_phase*(3 - 2*loading_phase)
        return {bone: (first[bone][0] if phase == 0 else last[bone][0] if phase == 1 else
                       _rotation_mix(first[bone][0], last[bone][0],
                                     loading_amount if 17 <= bone <= 21 else amount), value[1])
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


def prepare_table(raw, read, read_original, target_model, target_locator, basis, offset=0., *, actor):
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
    motion = Motion(read_original(original), read(path), read_original, target_model, target_locator,
                    basis, offset, ready, actor=actor)
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


