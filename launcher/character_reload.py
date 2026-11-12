"""Match third-person reload clocks and the Redeemer's native magazine motion.

These are body-only visual clones. The hands own ammo/event timing; their clips,
weapon clips and the original shared body clips must remain unchanged.
"""
import copy
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re
import struct

import character_assets as art
import character_boss as boss
import character_weapon_pose as pose
import character_spectral_hands as skin
import character_weapon_shoulder as shoulder

# Exact float32 durations from the pinned disc's ChazHands action resources.
# BasicPistol receives separate pre/loop/post body actions in character_starter_reload;
# never shorten its entire original arm swing into each cartridge insertion.
DURATIONS = {
    ('REVOLVER', 'RELOAD'): 1.8833333253860474,
    ('DOUBLEPISTOL', 'RELOAD'): 2.2333333492279053,
    ('CROSSBOW', 'RELOAD'): 3.3333332538604736,
    ('RAILRCKT', 'RELOAD'): 4.5333333015441895,
    ('RIFLE', 'PRERELOAD'): .44999998807907104,
    ('RIFLE', 'RELOAD'): .38333332538604736,
    ('RIFLE', 'POSTRELOAD'): 1.1166666746139526,
    ('SHOTGUN', 'PRERELOAD'): .3166666626930237,
    ('SHOTGUN', 'RELOAD'): .3333333432674408,
    # The weapon's post-reload is .716667 s; preserve that native difference.
    ('SHOTGUN', 'POSTRELOAD'): .6666666865348816,
    ('SNIPERRIFLE', 'RELOAD'): 3.6500000953674316,
}
PHASES = {'PRERELOAD', 'RELOAD', 'POSTRELOAD'}
FAMILIES = {family for family, _ in DURATIONS}
PREFIX = 'characters/player_two/reload/'
REDEEMER_PREFIX = PREFIX + 'redeemer/'
REDEEMER_HANDS = 'characters/player_first/sanm/med/pov_chaz_reload_dwrevolver.sanm'
REDEEMER_MODEL = 'accessories/weapons/dwrevolver/base_pov_dwrevolver.rx1'
REDEEMER_WEAPON = 'accessories/weapons/dwrevolver/sanm/lo/pov_dwrevolver_reload.sanm'
REDEEMER_CONTACT_START = .2654867172241211
REDEEMER_CONTACT_END = .65
REDEEMER_GRASPS = {
    **dict.fromkeys(('TrooperSolo', 'TrooperCoop', 'BlueTrooperSolo', 'BlueTrooperCoop',
                     'RedTrooperSolo', 'RedTrooperCoop'), (0., 0., 0.)),
    **dict.fromkeys(('BossTalaSolo', 'BossTalaCoop'), (.030, -.015, .035)),
    **dict.fromkeys(('Chaz', 'JerichoCoop', 'CivilianJerichoSolo', 'CivilianJerichoCoop',
                     'CassidySolo', 'CassidyPlayerTwo', 'CassidySpectralSolo', 'CassidySpectralPlayerTwo',
                     'TalaSolo', 'TalaCoop', 'VampireTalaSolo', 'VampireTalaCoop'), (.020, -.015, .025)),
}

# Native POV contact intervals: the ejected parts outside these intervals are
# intentionally free. Only the body follows them; their mechanical clips stay intact.
MECHANICAL = {
    'Crossbow': ('CROSSBOW', 8, 1, .175, .75, .4,
        'accessories/weapons/dwcrossbow/base_pov_dwcrossbow.rx1',
        'accessories/weapons/dwcrossbow/sanm/pov_dwcrossbow_reload.sanm',
        'characters/player_first/sanm/lo/pov_chaz_reload_dwcrossbow.sanm'),
    'RocketLauncher': ('RAILRCKT', 5, 2, .25, .44, .35,
        'accessories/weapons/dwrailrocket/base_pov_dwrailrocket.rx1',
        'accessories/weapons/dwrailrocket/sanm/lo/pov_dwrailrocket_reload.sanm',
        'characters/player_first/sanm/lo/pov_chaz_reload_dwrailrocket.sanm'),
    'SniperRifle': ('SNIPERRIFLE', 4, 2, .39, .53, .45,
        'accessories/weapons/dwsniperrifle/base_pov_dwsniperrifle.rx1',
        'accessories/weapons/dwsniperrifle/sanm/pov_dwsniperrifle_reload.sanm',
        'characters/player_first/sanm/med/pov_chaz_reload_dwsniperrifle.sanm'),
}


@lru_cache(maxsize=1)
def mechanical_parts():
    """Read the same compact, third-person-only path contract as the renderer."""
    parts = {}
    for line in Path(__file__).with_name('body_reload_parts.inc').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('//'): continue
        match = re.fullmatch(r'MECHANICAL_RELOAD_PART\("(\w+)",\s*(\d+),\s*(\d+),\s*([^)]*)\)', line)
        if not match: raise ValueError('Invalid mechanical reload part record')
        name, count, bone, numbers = match.groups()
        values = tuple(float(value.strip().removesuffix('f')) for value in numbers.split(','))
        if (name in parts or name not in MECHANICAL or len(values) != 4 or
                not all(math.isfinite(value) for value in values) or not 0 < values[3] <= 1 or
                (int(count), int(bone)) != MECHANICAL[name][1:3]):
            raise ValueError('Unsupported mechanical reload part record')
        parts[name] = values[:3], values[3]
    if parts.keys() != MECHANICAL.keys(): raise ValueError('Incomplete mechanical reload part coverage')
    return parts


def compact_part(weapon, native):
    seated, factor = mechanical_parts()[weapon]
    return native[0], pose.add(seated, pose.scale(pose.sub(native[1], seated), factor))


def _rotation_mix(first, last, amount):
    q, p = pose.a._to_quaternion(first), pose.a._to_quaternion(last)
    if pose.dot(q, p) < 0: p = pose.scale(p, -1)
    return pose.a._quaternion_matrix(pose.unit(pose.add(pose.scale(q, 1-amount), pose.scale(p, amount))))


class RedeemerMotion:
    """Follow the native magazine-hand path without the old overhead sweep."""
    contact_start = REDEEMER_CONTACT_START
    contact_end = REDEEMER_CONTACT_END
    part = 2
    samples = 120
    def __init__(self, adapted, ready, read_original, model, locator, basis, offset, grasp_shift):
        if basis not in (pose.a.CHAZ, pose.a.STORM) or not math.isfinite(offset) or abs(offset) > .1:
            raise ValueError('Unsupported Redeemer reload rig')
        bones = struct.unpack_from('<I', adapted, 8)[0]
        if bones not in (22, 51): raise ValueError('Unexpected Redeemer body hierarchy')
        source_locator = basis[:-4] + ('_coop.bllist' if basis == pose.a.STORM else '.bllist')
        self.solver = pose.SupportRetarget(read_original(basis), model,
            pose._grip(read_original(source_locator)), pose._grip(locator), bones)
        self.target = pose.Clip(adapted, bones)
        if self.target.flags & 0x10000000 or set(self.target.parts) - {1, 4, 8} or 4 not in self.target.parts:
            raise ValueError('Redeemer reload must be an absolute body pose')
        for (_, bit), (_, values) in self.target.tracks.items():
            if bit == 8 and any(pose.length(pose.sub(v, values[0])) > 1e-8 for v in values[1:]):
                raise ValueError('Redeemer body has animated translation keys')
        self.ready = pose.Clip(ready, bones).pose(self.solver.target, .5)
        # The authored settled pose keeps the pistol below the head. Retain its
        # right arm while the left follows the unchanged mechanical animation.
        settled = self.target.pose(self.solver.target, .65)
        self.anchor = dict(self.ready)
        for bone in (12, 13, 14, 15, 16):
            self.anchor[bone] = settled[bone][0], self.anchor[bone][1]
        grip = self.solver.target_grip
        self.grip = grip[0], pose.add(grip[1], pose.scale(grip[0][0], offset))
        self.fp_bind, self.fp_parents = pose.rig(read_original('characters/player_first/base_pov_chaz.rx1'), 22)
        self.fp = pose.Clip(read_original(REDEEMER_HANDS), 22)
        if grasp_shift not in REDEEMER_GRASPS.values(): raise ValueError('Unmeasured Redeemer body grasp')
        self.grasp_shift = grasp_shift
        self.weapon_bind, self.weapon_parents = pose.rig(read_original(REDEEMER_MODEL), 5)
        self.weapon = pose.Clip(read_original(REDEEMER_WEAPON), 5)
        part = pose.world(self.weapon.pose(self.weapon_bind, .4), self.weapon_parents)[2]
        self.grasp = pose.mul(self.relative_hand(.4), pose.inverse(part))
        self.contact_before = pose.world(self.anchor, self.solver.parents)
        self.contact_after = dict(self.contact_before)
        gun = pose.mul(self.grip, self.contact_before[16])
        hand_to_gun = pose.mul(gun, pose.inverse(self.contact_before[15]))
        weapon_to_hand = pose.mul(self.contact_before[16], pose.inverse(self.contact_before[15]))
        # Roll the extraction across the body. A vertical withdrawal makes the
        # shorter body arms pull the receiver through the head to reach it.
        cosine, sine = math.cos(math.radians(60)), math.sin(math.radians(60))
        roll = ((1.,0.,0.),(0.,cosine,sine),(0.,-sine,cosine))
        rotation = pose.a._multiply(roll, gun[0])
        self.contact_after[15] = (pose.a._multiply(pose.a._inverse(hand_to_gun[0]), rotation),
                                 self.contact_before[15][1])
        self.contact_after[16] = pose.mul(weapon_to_hand, self.contact_after[15])
        self.start, self.end = self.contact(REDEEMER_CONTACT_START), self.contact(REDEEMER_CONTACT_END)

    def relative_hand(self, phase):
        world = pose.world(self.fp.pose(self.fp_bind, phase), self.fp_parents)
        hand = pose.mul(world[4], pose.inverse(world[21]))
        # Body fingers extend along +X; the articulated POV fingers use +Z.
        # The measured palm offset aligns the shorter body hand's knuckles.
        mapping = ((0., 0., 1.), (0., 1., 0.), (-1., 0., 0.))
        return (pose.a._multiply(mapping, hand[0]),
                pose.add(hand[1], pose.rotate(self.grasp_shift, hand[0])))

    def contact(self, phase):
        before, after = self.contact_before, self.contact_after
        part = pose.world(self.weapon.pose(self.weapon_bind, phase), self.weapon_parents)[self.part]
        # Body fingers are rigid. Transport their measured grasp with the
        # magazine, rather than copying the POV wrist's finger articulation.
        desired = pose.mul(pose.mul(self.grasp, part), pose.mul(self.grip, after[16]))
        # Reloading needs more reach than the bent idle arm, without locking or
        # stretching either elbow. Other action solvers keep their old bounds.
        return self.solver.fit_contacts(before, after, desired, reach_fraction=.95)

    def sample(self, phase):
        lo, hi = self.contact_start, self.contact_end
        if lo <= phase <= hi: return self.contact(phase)
        if phase < lo: first, last, amount = self.ready, self.start, phase/lo
        else: first, last, amount = self.end, self.ready, (phase-hi)/(1-hi)
        amount = self.transition(amount)
        return {bone: (_rotation_mix(first[bone][0], last[bone][0], amount), value[1])
                for bone, value in self.ready.items()}

    @staticmethod
    def transition(amount):
        return amount**3 * (10 + amount*(-15 + 6*amount))

    def bake(self):
        phases = {i/self.samples for i in range(self.samples+1)} | {self.contact_start, self.contact_end}
        for times, _ in self.weapon.tracks.values():
            phases.update(t for t in times if self.contact_start <= t <= self.contact_end)
        samples = {}
        def sample(phase):
            if phase not in samples: samples[phase] = self.sample(phase)
            return samples[phase]
        self.solver.arm_bones = tuple(range(self.solver.bones))
        return self.solver._encode_rotations(self.target, sample, phases)


class MechanicalMotion(RedeemerMotion):
    """Keep the support hand on each native cartridge through its insertion."""
    samples = 240

    @staticmethod
    def transition(amount):
        # Spread the short ready-to-receiver turn without a sharp midpoint rush.
        return amount*amount*(3 - 2*amount)

    def __init__(self, adapted, ready, read_original, model, locator, basis, actor, weapon, offset):
        if actor not in REDEEMER_GRASPS or weapon not in MECHANICAL or basis not in (pose.a.CHAZ, pose.a.STORM):
            raise ValueError('Unsupported mechanical reload rig')
        if not math.isfinite(offset) or abs(offset) > .1:
            raise ValueError('Invalid mechanical reload grip')
        self.weapon_name = weapon
        bones = struct.unpack_from('<I', adapted, 8)[0]
        if bones not in (22, 51): raise ValueError('Unexpected mechanical reload hierarchy')
        source_locator = basis[:-4] + ('_coop.bllist' if basis == pose.a.STORM else '.bllist')
        self.solver = pose.SupportRetarget(read_original(basis), model,
            pose._grip(read_original(source_locator)), pose._grip(locator), bones)
        self.target = pose.Clip(adapted, bones)
        if self.target.flags & 0x10000000 or set(self.target.parts) - {1, 4, 8} or 4 not in self.target.parts:
            raise ValueError('Mechanical reload must be an absolute body pose')
        for (_, bit), (_, values) in self.target.tracks.items():
            if bit == 8 and any(pose.length(pose.sub(v, values[0])) > 1e-8 for v in values[1:]):
                raise ValueError('Mechanical reload has animated translation keys')
        self.ready = pose.Clip(ready, bones).pose(self.solver.target, .5)
        grip = self.solver.target_grip
        self.grip = grip[0], pose.add(grip[1], pose.scale(grip[0][0], offset))
        _, count, self.part, self.contact_start, self.contact_end, grasp_phase, weapon_model, action, hands = MECHANICAL[weapon]
        self.fp_bind, self.fp_parents = pose.rig(read_original('characters/player_first/base_pov_chaz.rx1'), 22)
        self.fp = pose.Clip(read_original(hands), 22)
        self.grasp_shift = ((.010, -.015, .015) if weapon == 'Crossbow' and actor.startswith('BossTala')
                            else REDEEMER_GRASPS[actor])
        self.weapon_bind, self.weapon_parents = pose.rig(read_original(weapon_model), count)
        self.weapon = pose.Clip(read_original(action), count)
        seated = pose.world(self.weapon_bind, self.weapon_parents)[self.part][1]
        if pose.length(pose.sub(seated, mechanical_parts()[weapon][0])) > 1e-7:
            raise ValueError('Mechanical reload seated reference changed')
        part = pose.world(self.weapon.pose(self.weapon_bind, grasp_phase), self.weapon_parents)[self.part]
        self.grasp = pose.mul(self.relative_hand(grasp_phase), pose.inverse(part))
        # The native reload lowers the receiver before inserting a cartridge.
        # Its settled right arm keeps these larger weapons clear of the head;
        # the pistol-specific roll would swing them through the face or torso.
        anchor = dict(self.ready)
        settled = self.target.pose(self.solver.target, .65)
        for bone in (12, 13, 14, 15, 16): anchor[bone] = settled[bone]
        self.contact_before = pose.world(anchor, self.solver.parents)
        self.contact_after = dict(self.contact_before)
        if weapon == 'Crossbow':
            self.palm_contact = loading_palm_contact(model, bones)
            self.contact_before, self.contact_after = self.crossbow_holding()
            # Grip around the magazine's side instead of folding the body wrist
            # over its top during the native withdrawal turn.
            cosine, sine = math.cos(math.radians(-45)), math.sin(math.radians(-45))
            self.grasp = pose.mul(self.grasp,
                (((1., 0., 0.), (0., cosine, sine), (0., -sine, cosine)), (0., 0., 0.)))
            # Grasp the native cartridge's rear underside so the shorter body
            # arm can reach it without pulling the crossbow back into the neck.
            self.grasp = self.grasp[0], pose.sub((.010, -.075, -.075),
                pose.rotate(self.palm_contact, self.grasp[0]))
        self.start, self.end = self.contact(self.contact_start), self.contact(self.contact_end)

    def crossbow_holding(self):
        # Keep the stock outside the right flank. Standing and crouch have
        # different body-to-aim yaw, so use the actual shoulder line for both.
        before = pose.world(self.ready, self.solver.parents)
        after = dict(before)
        shoulder, elbow, wrist = (before[b][1] for b in (13, 14, 15))
        gun = pose.mul(self.grip, before[16])
        up = (0., 1., 0.)
        right = pose.sub(before[13][1], before[18][1])
        right = pose.unit((right[0], 0., right[2]))
        forward = pose.unit(pose.cross(up, right))
        if pose.dot(forward, gun[0][0]) < 0.: forward = pose.scale(forward, -1.)
        length = pose.length(pose.sub(elbow, shoulder)) + pose.length(pose.sub(wrist, elbow))
        target = pose.add(shoulder, pose.add(pose.scale(forward, length*.15),
            pose.add(pose.scale(up, -length*.65), pose.scale(right, length*.35))))
        bore = pose.unit(pose.sub(forward, right))
        weapon_right = pose.unit(pose.cross(bore, up))
        rotation = (bore, up, weapon_right)
        cosine, sine = math.cos(math.radians(10)), math.sin(math.radians(10))
        rotation = pose.a._multiply(((cosine, sine, 0.), (-sine, cosine, 0.), (0., 0., 1.)), rotation)
        cosine, sine = math.cos(math.radians(15)), math.sin(math.radians(15))
        rotation = pose.a._multiply(((1., 0., 0.), (0., cosine, sine), (0., -sine, cosine)), rotation)
        weapon = pose.mul(before[16], pose.inverse(before[15]))
        wrist_to_gun = pose.mul(self.grip, weapon)
        middle, endpoint = pose.solve(shoulder, elbow, wrist, target)
        after[13] = pose.a._multiply(before[13][0], pose.align(
            pose.sub(elbow, shoulder), pose.sub(middle, shoulder))), shoulder
        after[14] = pose.a._multiply(before[14][0], pose.align(
            pose.sub(wrist, elbow), pose.sub(endpoint, middle))), middle
        after[15] = pose.a._multiply(pose.a._inverse(wrist_to_gun[0]), rotation), endpoint
        after[16] = pose.mul(weapon, after[15])
        after = pose.world(pose.outside_elbow(pose.localize(after, self.solver.parents),
                                            self.solver.parents, 13, side_weight=.5), self.solver.parents)
        return before, after

    def part_pose(self, phase):
        native = pose.world(self.weapon.pose(self.weapon_bind, phase), self.weapon_parents)[self.part]
        return compact_part(self.weapon_name, native)

    def contact(self, phase):
        desired = pose.mul(pose.mul(self.grasp, self.part_pose(phase)),
                           pose.mul(self.grip, self.contact_after[16]))
        result = self.solver.fit_contacts(self.contact_before, self.contact_after, desired, reach_fraction=.95)
        if self.weapon_name == 'Crossbow':
            result = pose.outside_elbow(result, self.solver.parents, 13, side_weight=.5)
            result = pose.outside_elbow(result, self.solver.parents, 18)
            result = soften_loading_wrist(result, self.solver.parents, self.palm_contact)
        return result

    def sample(self, phase):
        local = super().sample(phase)
        if self.weapon_name != 'Crossbow' or self.contact_start <= phase <= self.contact_end:
            return local
        # The cartridge stays seated until .175; use that interval to lower
        # the gun smoothly, then keep its stock outside the neck on return.
        if phase < self.contact_start:
            first, last, amount = self.ready, self.start, phase/self.contact_start
        else:
            first, last, amount = self.end, self.ready, (phase-self.contact_end)/(1-self.contact_end)
        raw_amount = amount
        amount = self.transition(amount)
        before = pose.world(local, self.solver.parents)
        start, finish = (pose.world(value, self.solver.parents) for value in (first, last))
        target = pose.add(pose.scale(start[15][1], 1-amount), pose.scale(finish[15][1], amount))
        right = pose.sub(start[13][1], start[18][1])
        right = pose.unit((right[0], 0., right[2]))
        length = pose.length(pose.sub(start[14][1], start[13][1])) + pose.length(pose.sub(start[15][1], start[14][1]))
        target = pose.add(target, pose.scale(right, .06*length*math.sin(math.pi*raw_amount)**2))
        rotation = _rotation_mix(start[15][0], finish[15][0], amount)
        shoulder, elbow, wrist = (before[bone][1] for bone in (13, 14, 15))
        middles = []
        for endpoint_pose in (start, finish):
            source_elbow = pose.add(shoulder, pose.sub(endpoint_pose[14][1], endpoint_pose[13][1]))
            source_wrist = pose.add(shoulder, pose.sub(endpoint_pose[15][1], endpoint_pose[13][1]))
            middle, endpoint = pose.solve(shoulder, source_elbow, source_wrist, target)
            middles.append(middle)
        axis = pose.unit(pose.sub(endpoint, shoulder))
        upper = pose.sub(middles[0], shoulder)
        center = pose.add(shoulder, pose.scale(axis, pose.dot(upper, axis)))
        first_pole, last_pole = (pose.sub(middle, center) for middle in middles)
        turn = _rotation_mix(pose.a.IDENTITY, pose.align(first_pole, last_pole), amount)
        middle = pose.add(center, pose.rotate(first_pole, turn))
        after = dict(before)
        after[13] = pose.a._multiply(before[13][0], pose.align(pose.sub(elbow, shoulder), pose.sub(middle, shoulder))), shoulder
        after[14] = pose.a._multiply(before[14][0], pose.align(pose.sub(wrist, elbow), pose.sub(endpoint, middle))), middle
        after[15] = rotation, endpoint
        after[16] = pose.mul(pose.mul(before[16], pose.inverse(before[15])), after[15])
        return pose.localize(after, self.solver.parents)


def prepare_mechanical_table(raw, read, read_original, model, locator, basis, actor, offsets):
    """Fit moving reload parts and rifle support without changing weapon clocks."""
    tree = art.decode(raw)
    additions = {}
    for weapon, (flag, *_) in MECHANICAL.items():
        candidates, ready = [], {}
        for group in tree['children']:
            if group['name'] != 'AnimationGroup': continue
            stance = {'Alert Poses UB':'STAND', 'Crouch Alert Poses':'CROUCH'}.get(group['attributes'].get('ToolName'))
            for node in group['children']:
                if node['name'] != 'KeyframeAnimation': continue
                flags = {child['attributes']['Flag'] for child in node['children'] if child['name'] == 'Modifier'}
                if flag not in flags: continue
                if node['attributes'].get('AnimationID') == 'RELOAD': candidates.append((group, node, flags))
                if stance and node['attributes'].get('AnimationID') == 'IDLE':
                    if stance in ready: raise ValueError('Duplicate mechanical reload ready pose')
                    ready[stance] = read(art.norm(node['attributes']['Name']) + '.sanm')
        selectors = [tuple(sorted(flags & {'STAND', 'CROUCH'})) for _, _, flags in candidates]
        if sorted(selectors) not in ([()], [('CROUCH',), ('STAND',)]) or set(ready) != {'STAND', 'CROUCH'}:
            raise ValueError('Incomplete mechanical reload routes: ' + weapon)
        for group, node, flags in candidates:
            selected = flags & {'STAND', 'CROUCH'}
            if flags - selected != {flag, 'OUT_OF_VEHICLE'}:
                raise ValueError('Unsupported mechanical reload selector')
            data = read(art.norm(node['attributes']['Name']) + '.sanm')
            if data[12:16] != struct.pack('<f', DURATIONS[flag, 'RELOAD']):
                raise ValueError('Mechanical reload must use the native hands clock')
            replacements = []
            for stance in sorted(selected) if selected else ('STAND', 'CROUCH'):
                clip = MechanicalMotion(data, ready[stance], read_original, model, locator, basis, actor,
                                        weapon, offsets.get((actor, weapon), (0., 0.))[0]).bake()
                name = PREFIX + 'mechanical/' + hashlib.sha256(clip).hexdigest()[:24]
                additions[name + '.sanm'] = clip
                replacement = copy.deepcopy(node)
                replacement['attributes'].update(Name=name, BlendIn='0.001000')
                pose_ins = [child for child in replacement['children'] if child['name'] == 'PoseIn']
                if len(pose_ins) > 1: raise ValueError('Duplicate mechanical pose-in')
                if not pose_ins: replacement['children'].insert(1, dict(name='PoseIn', attributes={}, children=[], value=None))
                if not selected: replacement['children'].append(dict(name='Modifier', attributes={'Flag':stance}, children=[], value=None))
                replacements.append(replacement)
            index = next(i for i, value in enumerate(group['children']) if value is node)
            group['children'][index:index+1] = replacements
            group['attributes']['KeyedAnimationCount'] = str(sum(row['name'] == 'KeyframeAnimation' for row in group['children']))
    table, rifle_clips = prepare_rifle_support_table(art.encode(tree), read, read_original,
        model, locator, basis, offsets.get((actor, 'Rifle'), (0., 0.))[0],
        bridge_ready=actor in shoulder.SHARED_RIFLE_HOLD)
    additions.update(rifle_clips)
    return table, additions


def fit_loading_hand(before, parents, desired, paired_solver=None):
    """Fit only the loading arm, with bounded shoulder reach and no bone stretch."""
    length = sum(pose.length(pose.sub(before[b][1], before[a][1])) for a, b in ((18,19),(19,20)))
    reach = length * .995
    if pose.length(pose.sub(desired[1], before[18][1])) > reach:
        center = before[17][1]
        offset = pose.sub(before[18][1], center)
        turn = pose.align(offset, pose.sub(desired[1], center))
        angle = math.acos(max(-1., min(1., pose.dot(pose.unit(offset), pose.unit(pose.sub(desired[1], center))))))
        high = min(1., math.radians(8)/max(angle, 1e-9))
        def shifted(amount):
            rotation = _rotation_mix(pose.a.IDENTITY, turn, amount)
            return rotation, pose.add(center, pose.rotate(offset, rotation))
        needs_pair = pose.length(pose.sub(desired[1], shifted(high)[1])) > reach
        if needs_pair and paired_solver is None:
            raise ValueError('Loading hand requires excessive shoulder reach')
        if not needs_pair:
            low = 0.
            for _ in range(30):
                middle = (low+high)*.5
                if pose.length(pose.sub(desired[1], shifted(middle)[1])) > reach: low = middle
                else: high = middle
        rotation, _ = shifted(high)
        before = dict(before)
        for bone in (17, 18, 19, 20, 21):
            value = before[bone]
            before[bone] = (pose.a._multiply(value[0], rotation),
                            pose.add(center, pose.rotate(pose.sub(value[1], center), rotation)))
        if needs_pair:
            # Once the bounded shoulder reach is exhausted, move both contacts
            # together by the smallest feasible displacement. This starts at
            # zero at the reach boundary and preserves the gun's orientation.
            result = paired_solver.fit_contacts(before, before, desired, reach_fraction=.995)
            moved = pose.world(result, parents)
            if pose.length(pose.sub(moved[15][1], before[15][1])) > .10:
                raise ValueError('Loading hand requires excessive paired displacement')
            return result
    shoulder, elbow, wrist = (before[b][1] for b in (18, 19, 20))
    middle, endpoint = pose.solve(shoulder, elbow, wrist, desired[1])
    after = dict(before)
    after[18] = pose.a._multiply(before[18][0], pose.align(pose.sub(elbow, shoulder), pose.sub(middle, shoulder))), shoulder
    after[19] = pose.a._multiply(before[19][0], pose.align(pose.sub(wrist, elbow), pose.sub(endpoint, middle))), middle
    after[20] = desired[0], endpoint
    after[21] = pose.mul(pose.mul(before[21], pose.inverse(before[20])), after[20])
    return pose.localize(after, parents)


def loading_palm_contact(model, bones):
    """Measure the loading palm in wrist space without including forearm skin."""
    points = []
    for index in range(sum(kind == 15 for kind, *_ in pose.b._records(model))):
        geometry = skin._geometry(model, index, allowed_bones=(bones,))
        for position, weights in zip(geometry['positions'], geometry['weights']):
            if weights.get(20, 0.) <= .95:
                continue
            local = skin._point(position, geometry['inverse'][20])
            if .03 < local[0] < .09:
                points.append(local)
    if not points:
        raise ValueError('Loading palm is unavailable')
    return tuple(sum(point[i] for point in points)/len(points) for i in range(3))


def soften_loading_wrist(local, parents, palm_contact, weight=1.):
    """Relax loading-hand flex around its contact, retaining gun and arm lengths."""
    if weight == 0.:
        return local
    before = pose.world(local, parents)
    axis = pose.unit(before[20][0][0])
    forearm = pose.unit(pose.sub(before[20][1], before[19][1]))
    limit = math.radians(20.)
    if pose.dot(axis, forearm) >= math.cos(limit):
        return local
    contact = pose.add(before[20][1], pose.rotate(palm_contact, before[20][0]))
    current = before
    # Rotating around the palm keeps the cartridge contact fixed. Refitting
    # the original-length arm then changes the wrist position slightly;
    # converge against that forearm, without moving the held weapon.
    for _ in range(5):
        forearm = pose.unit(pose.sub(current[20][1], current[19][1]))
        axis = before[20][0][0]
        angle = math.acos(max(-1., min(1., pose.dot(pose.unit(axis), forearm))))
        amount = weight*max(0., 1-limit/angle) if angle > 1e-6 else 0.
        rotation = _rotation_mix(pose.a.IDENTITY, pose.align(axis, forearm), amount)
        rotation = pose.a._multiply(before[20][0], rotation)
        position = pose.sub(contact, pose.rotate(palm_contact, rotation))
        result = fit_loading_hand(before, parents, (rotation, position))
        current = pose.world(result, parents)
    return result


# Actual distal-thumb pads, measured in the prepared body's wrist15 space.
RIFLE_THUMBS = {
    '37bb3be6b4578ce57d3595ac7a2b034952da255949c4322db2ab8259827b3a3b': (0.1374156587449327, 0.032166933926465045, -0.11598649796052057),
    '49481eb60e07c8286d18332cd937a4e55922b7eca23a95e9db417897b6400a10': (0.11810964135135908, 0.011484339359588628, -0.057724504421974604),
    'ab5cd1e6e409eeb650297932503f04eb408ef1ace669b49397f4e07ca36f4eef': (0.11514651156286874, 0.05320408301273153, -0.08992761569123038),
    '08d3c57bc2e28f5a38c26e86f2798b8fa60f47c5552d5ea7cef588ddaddf8ad0': (0.11562428750477005, 0.042307437340749564, -0.06394374276844407),
    '86ae91129740abb0075d4785a114fcbbef6b1f9f690213f243ed4d42f2f11a5b': (0.08586047247804791, 0.04658186686572866, -0.08648275332967754),
    'a1abaac00ac4b1cc24fa16077478defea463791f0475d9f41f6daf989845c657': (0.08600194816228776, 0.07205606427956485, -0.0986631216008691),
    '52f07f4e0568cfde03c28467ccd3e5f73ef06b40fd9327b7a7af5558e65e17ae': (0.1374156587449327, 0.032166933926465045, -0.11598649796052057),
    '61ec2ceac3ebf48f560413492ef566918cc4b6e17ea2348ca8318a5db7899efb': (0.10476014791647331, 0.04792199264701765, -0.06303603876579854),
    '697d68592b6c53ce250f22e298d2770c6a8de8f4c990219b35f4b0128b2aa478': (0.13741489133257664, 0.032167538814466656, -0.11598540628919903),
    '9d1691d4fa15f1939dbd4c64479c28693c9ce701e78b1745868a1dad2cbb8c5f': (0.09246189784853402, 0.03533367759136056, -0.058356052509052826),
    '4b0262b4f9cda044eb915e6d5141e8c666a2a8bf4fb8c8faf21e84bbafd81143': (0.11810964135135908, 0.011484339359588628, -0.057724504421974604),
}
RIFLE_NATIVE_THUMB = (-0.007930847954767768, -0.001732180052801257, -0.01107308506088177)


class RifleSupportMotion:
    """Support the lever rifle with the left hand and load its side gate with the right."""
    def __init__(self, adapted, ready, read_original, model, locator, basis, offset, action, core_ready=None):
        if action not in PHASES or basis not in (pose.a.CHAZ, pose.a.STORM):
            raise ValueError('Unsupported rifle loading phase')
        bones = struct.unpack_from('<I', adapted, 8)[0]
        source_locator = basis[:-4] + ('_coop.bllist' if basis == pose.a.STORM else '.bllist')
        self.solver = pose.SupportRetarget(read_original(basis), model,
            pose._grip(read_original(source_locator)), pose._grip(locator), bones)
        self.target = pose.Clip(adapted, bones)
        if self.target.flags & 0x10000000 or set(self.target.parts)-{1,4,8} or not {4,8} <= self.target.parts.keys():
            raise ValueError('Rifle loading requires an absolute body pose')
        self.solver.arm_bones = tuple(range(7,22))
        self.action = action
        self.parents = self.solver.parents
        self.ready_local = dict(self.solver.target)
        for raw in ((core_ready,ready) if core_ready is not None else (ready,)):
            clip = pose.Clip(raw,bones); local = clip.pose(self.solver.target,.5)
            mask = struct.unpack_from('<'+'I'*bones,raw,clip.parts[1]['keys']) if 1 in clip.parts else (0,)*bones
            self.ready_local.update((bone,value) for bone,value in local.items() if not mask[bone])
        self.ready = pose.world(self.ready_local, self.parents)
        grip = self.solver.target_grip
        self.grip = grip[0], pose.add(grip[1], pose.scale(grip[0][0], offset))
        self.gun = pose.mul(self.grip, self.ready[16])
        inverse = pose.inverse(self.gun)
        self.contacts = {bone:pose.mul(self.ready[bone],inverse) for bone in (15,20)}
        try: self.thumb = RIFLE_THUMBS[hashlib.sha256(model).hexdigest()]
        except KeyError: raise ValueError('Unrecognized rifle loading-hand model') from None
        self.ready_thumb = pose.add(self.contacts[15][1],pose.rotate(self.thumb,self.contacts[15][0]))
        hand = read_original('characters/player_first/base_pov_chaz.rx1')
        if hashlib.sha256(hand).hexdigest() != 'a323481cc83532c746ff5926e3c7f033a455f91309a6161c06569ba4b7759b77':
            raise ValueError('Unrecognized native rifle loading-hand source')
        self.fp_bind,self.fp_parents = pose.rig(hand,22)
        self.native = {phase:pose.Clip(read_original('characters/player_first/sanm/med/pov_chaz_'+phase.lower()+'_dwrifle.sanm'),22) for phase in PHASES}
        side = pose.sub(self.ready[18][1],self.ready[13][1]); side = pose.unit((side[0],0.,side[2]))
        up = (0.,1.,0.); forward = pose.unit(pose.cross(side,up))
        bore = pose.unit(pose.add(pose.add(pose.scale(forward,.55),pose.scale(side,.835)),pose.scale(up,.12)))
        top = pose.unit(pose.sub(up,pose.scale(bore,pose.dot(up,bore))))
        center = pose.scale(pose.add(self.ready[18][1],self.ready[13][1]),.5)
        position = pose.add(center,pose.add(pose.scale(forward,.25),pose.add(pose.scale(side,-.04),pose.scale(up,-.23))))
        self.held = (bore,top,pose.cross(bore,top)),position

    def native_thumb(self, action, phase):
        world = pose.world(self.native[action].pose(self.fp_bind,phase),self.fp_parents)
        thumb = pose.mul(world[20],pose.inverse(world[21]))
        return pose.add(thumb[1],pose.rotate(RIFLE_NATIVE_THUMB,thumb[0]))

    def sample(self, phase):
        smooth = phase**3*(10+phase*(-15+6*phase))
        amount = smooth if self.action=='PRERELOAD' else 1-smooth if self.action=='POSTRELOAD' else 1.
        mount = (_rotation_mix(self.gun[0],self.held[0],amount),
                 pose.add(pose.scale(self.gun[1],1-amount),pose.scale(self.held[1],amount)))
        thumb = self.native_thumb('RELOAD',phase) if self.action=='RELOAD' else pose.add(
            pose.scale(self.ready_thumb,1-amount),pose.scale(self.native_thumb('RELOAD',0. if self.action=='PRERELOAD' else 1.),amount))
        contact = pose.add(pose.rotate(thumb,mount[0]),mount[1])
        original = pose.a._multiply(self.contacts[15][0],mount[0]); hand = original
        shoulder,elbow,wrist = (self.ready[b][1] for b in (13,14,15))
        reach_fraction = 1-.015*amount
        reach = reach_fraction*(pose.length(pose.sub(elbow,shoulder))+pose.length(pose.sub(wrist,elbow)))
        # Rotate around the measured thumb contact instead of folding the wrist
        # to imitate the first-person rig's independently articulated fingers.
        for _ in range(8):
            position = pose.sub(contact,pose.rotate(self.thumb,hand)); offset = pose.sub(position,shoulder)
            end = pose.add(shoulder,pose.scale(pose.unit(offset),min(reach,pose.length(offset))))
            middle,_ = pose.solve(shoulder,elbow,wrist,end)
            forearm = pose.unit(pose.sub(position,middle)); axis = original[0]
            angle = math.acos(max(-1.,min(1.,pose.dot(pose.unit(axis),forearm))))
            turn = _rotation_mix(pose.a.IDENTITY,pose.align(axis,forearm),amount*max(0.,1-math.radians(35)/max(angle,1e-9)))
            hand = pose.a._multiply(original,turn)
        targets = {15:(hand,pose.sub(contact,pose.rotate(self.thumb,hand))),20:pose.mul(self.contacts[20],mount)}
        centers,radii = [],[]
        for first in (13,18):
            shoulder,elbow,wrist = (self.ready[b][1] for b in (first,first+1,first+2))
            centers.append(pose.sub(shoulder,targets[first+2][1]))
            radii.append(reach_fraction*(pose.length(pose.sub(elbow,shoulder))+pose.length(pose.sub(wrist,elbow))))
        displacement = (0.,0.,0.); corrections = [displacement,displacement]
        for _ in range(100):
            previous = displacement
            for i in (0,1):
                trial = pose.add(displacement,corrections[i]); offset = pose.sub(trial,centers[i]); size = pose.length(offset)
                projected = trial if size<=radii[i] else pose.add(centers[i],pose.scale(offset,radii[i]/size))
                corrections[i] = pose.sub(trial,projected); displacement = projected
            if pose.length(pose.sub(previous,displacement))<1e-10: break
        if pose.length(displacement)>.06:
            raise ValueError('Rifle workspace needs excessive reach correction')
        mount = mount[0],pose.add(mount[1],displacement)
        world = dict(self.ready)
        for bone,first in ((15,13),(20,18)):
            target = targets[bone][0],pose.add(targets[bone][1],displacement)
            shoulder,elbow,wrist = (world[b][1] for b in (first,first+1,first+2))
            middle,end = pose.solve(shoulder,elbow,wrist,target[1])
            world[first] = pose.a._multiply(world[first][0],pose.align(pose.sub(elbow,shoulder),pose.sub(middle,shoulder))),shoulder
            world[first+1] = pose.a._multiply(world[first+1][0],pose.align(pose.sub(wrist,elbow),pose.sub(end,middle))),middle
            world[first+2] = target[0],end
        world[16] = pose.mul(self.ready_local[16],world[15]); world[21] = pose.mul(self.ready_local[21],world[20])
        local = pose.localize(world,self.parents)
        for first in (13,18):
            before = pose.world(local,self.parents)
            target = pose.world(pose.outside_elbow(local,self.parents,first,side_weight=.65),self.parents)
            shoulder,elbow,wrist = (before[b][1] for b in (first,first+1,first+2))
            axis = pose.unit(pose.sub(wrist,shoulder)); upper = pose.sub(elbow,shoulder); along = pose.dot(upper,axis)
            old = pose.sub(upper,pose.scale(axis,along)); new = pose.sub(pose.sub(target[first+1][1],shoulder),pose.scale(axis,along))
            radial = pose.unit(pose.add(pose.scale(pose.unit(old),1-amount),pose.scale(pose.unit(new),amount)))
            middle = pose.add(shoulder,pose.add(pose.scale(axis,along),pose.scale(radial,pose.length(old))))
            before[first] = pose.a._multiply(before[first][0],pose.align(upper,pose.sub(middle,shoulder))),shoulder
            before[first+1] = pose.a._multiply(before[first+1][0],pose.align(pose.sub(wrist,elbow),pose.sub(wrist,middle))),middle
            local = pose.localize(before,self.parents)
        world = pose.world(local,self.parents)
        # The common held-attachment path uses this independent gun socket.
        # Spectral's skin publication retains its original finger16 relation.
        local[16] = pose.mul(pose.mul(pose.inverse(self.grip),mount),pose.inverse(world[15]))
        return local

    def bake(self):
        phases = {i/240 for i in range(241)}
        for times,_ in self.target.tracks.values(): phases.update(times)
        cache = {phase:self.sample(phase) for phase in phases}
        data = self.solver._encode_rotations(self.target,cache.__getitem__,phases)
        section = boss.sections(data,self.solver.bones)[1].get(8)
        if section is None: raise ValueError('Missing reload socket translations')
        keys,indices = bytearray(),[]
        for bone,first in enumerate(section['indices']):
            if first == pose.MISSING:
                if bone in (16,21): raise ValueError('Missing rifle socket translation')
                indices.append(first); continue
            indices.append(len(keys)//16)
            stop = min([i for i in section['indices'] if first<i<pose.MISSING]+[section['count']])
            if bone in (16,21):
                for phase in sorted(phases): keys += struct.pack('<f3f',phase,*cache[phase][bone][1])
            else: keys += data[section['keys']+16*first:section['keys']+16*stop]
        block = struct.pack('<I',len(keys)//16)+struct.pack('<'+'I'*self.solver.bones,*indices)+keys
        return data[:section['start']]+block+data[section['end']:]


def prepare_rifle_support_table(raw, read, read_original, model, locator, basis, offset=0., *, bridge_ready=False):
    """Fit loading contact and ready joins; preserve selectors, clocks and events."""
    tree = art.decode(raw)
    ready, candidates = {}, {}
    core_ready = None
    for group in tree['children']:
        if group['name'] != 'AnimationGroup': continue
        stance = {'Alert Poses UB':'STAND', 'Crouch Alert Poses':'CROUCH'}.get(group['attributes'].get('ToolName'))
        for node in group['children']:
            if node['name'] != 'KeyframeAnimation': continue
            flags = {c['attributes']['Flag'] for c in node['children'] if c['name'] == 'Modifier'}
            if 'RIFLE' not in flags: continue
            action = node['attributes'].get('AnimationID')
            if group['attributes'].get('ToolName') == 'Alert Poses' and action == 'IDLE':
                if core_ready is not None: raise ValueError('Duplicate rifle standing core')
                core_ready = read(art.norm(node['attributes']['Name']) + '.sanm')
            if stance and action == 'IDLE': ready[stance] = read(art.norm(node['attributes']['Name']) + '.sanm')
            if action in PHASES:
                selected = flags & {'STAND', 'CROUCH'}
                key = action, next(iter(selected)) if len(selected) == 1 else None
                if key in candidates or len(selected) > 1 or flags - selected != {'RIFLE', 'OUT_OF_VEHICLE'}:
                    raise ValueError('Unsupported rifle reload selector')
                candidates[key] = (group, node)
    if core_ready is None or set(ready) != {'STAND', 'CROUCH'} or any(
            {stance for action, stance in candidates if action == phase} not in ({None}, {'STAND', 'CROUCH'}) for phase in PHASES):
        raise ValueError('Incomplete rifle support routes')
    additions = {}
    for (action, selected), (group, node) in candidates.items():
        source = read(art.norm(node['attributes']['Name']) + '.sanm')
        replacements = []
        stances = (selected,) if selected else ('STAND', 'CROUCH')
        for stance in stances:
            data = RifleSupportMotion(source, ready[stance], read_original, model, locator, basis, offset, action,
                                      core_ready if stance == 'STAND' else None).bake()
            name = PREFIX + 'rifle-support/' + hashlib.sha256(data).hexdigest()[:24]
            additions[name + '.sanm'] = data
            replacement = copy.deepcopy(node)
            replacement['attributes']['Name'] = name
            if bridge_ready and action != 'RELOAD': replacement['attributes']['BlendIn'] = '0.001000'
            if not selected: replacement['children'].append(dict(name='Modifier', attributes={'Flag':stance}, children=[], value=None))
            replacements.append(replacement)
        index = next(i for i, value in enumerate(group['children']) if value is node)
        group['children'][index:index+1] = replacements
        group['attributes']['KeyedAnimationCount'] = str(sum(n['name'] == 'KeyframeAnimation' for n in group['children']))
    return art.encode(tree), additions


def prepare_redeemer_table(raw, read, read_original, model, locator, basis, actor, offset=0.):
    """Replace only the retimed Redeemer body reload; hands and weapon stay native."""
    if actor not in REDEEMER_GRASPS: raise ValueError('Unknown Redeemer body character')
    tree = art.decode(raw)
    candidates, ready = [], {}
    for group in tree['children']:
        if group['name'] != 'AnimationGroup': continue
        stance = {'Alert Poses UB': 'STAND', 'Crouch Alert Poses': 'CROUCH'}.get(group['attributes'].get('ToolName'))
        for node in group['children']:
            if node['name'] != 'KeyframeAnimation': continue
            flags = {child['attributes']['Flag'] for child in node['children'] if child['name'] == 'Modifier'}
            if 'REVOLVER' not in flags: continue
            if node['attributes'].get('AnimationID') == 'RELOAD': candidates.append((group, node, flags))
            if stance and node['attributes'].get('AnimationID') == 'IDLE':
                if stance in ready: raise ValueError('Duplicate Redeemer ready pose')
                ready[stance] = read(art.norm(node['attributes']['Name']) + '.sanm')
    if len(candidates) != 1 or set(ready) != {'STAND', 'CROUCH'}:
        raise ValueError('Incomplete Redeemer reload routes')
    group, node, flags = candidates[0]
    if flags != {'REVOLVER', 'OUT_OF_VEHICLE'}:
        raise ValueError('Unsupported Redeemer body reload selector')
    data = read(art.norm(node['attributes']['Name']) + '.sanm')
    if data[12:16] != struct.pack('<f', DURATIONS['REVOLVER', 'RELOAD']):
        raise ValueError('Redeemer reload must already use the native hands clock')
    additions, replacements = {}, []
    for stance in ('STAND', 'CROUCH'):
        clip = RedeemerMotion(data, ready[stance], read_original, model, locator, basis, offset, REDEEMER_GRASPS[actor]).bake()
        name = REDEEMER_PREFIX + hashlib.sha256(clip).hexdigest()[:24]
        additions[name + '.sanm'] = clip
        replacement = copy.deepcopy(node)
        replacement['attributes'].update(Name=name, BlendIn='0.001000')
        if any(child['name'] == 'PoseIn' for child in replacement['children']):
            raise ValueError('Unexpected existing Redeemer pose-in')
        # Match the weapon's native blend/clock gate. The old body starts up to
        # 8.33 ms early at high FPS, enough to separate the moving magazine.
        replacement['children'].insert(1, dict(name='PoseIn', attributes={}, children=[], value=None))
        replacement['children'].append(dict(name='Modifier', attributes={'Flag': stance}, children=[], value=None))
        replacements.append(replacement)
    index = next(i for i, value in enumerate(group['children']) if value is node)
    group['children'][index:index+1] = replacements
    group['attributes']['KeyedAnimationCount'] = str(sum(row['name'] == 'KeyframeAnimation' for row in group['children']))
    return art.encode(tree), additions


def retime(data, seconds):
    """Change only the seconds header of an absolute, pose-only body clip."""
    if not math.isfinite(seconds) or seconds <= 0 or len(data) < 16:
        raise ValueError('Invalid body reload duration')
    flags, sections = boss.sections(data, struct.unpack_from('<I', data, 8)[0])
    if flags & 0x10000000 or set(sections) - {1, 4, 8}:
        raise ValueError('Body reload must contain absolute pose keys only')
    return data[:12] + struct.pack('<f', seconds) + data[16:]


def prepare_table(raw, read):
    """Return a rewritten full body table and new private visual resources."""
    tree = art.decode(raw)
    if tree['name'] != 'AnimationSystem':
        raise ValueError('Expected a body animation system')
    additions, found = {}, set()
    for group in tree['children']:
        if group['name'] != 'AnimationGroup':
            continue
        rows = []
        for node in group['children']:
            phase = node['attributes'].get('AnimationID')
            modifiers = {c['attributes']['Flag'] for c in node['children']
                         if c['name'] == 'Modifier'}
            families = modifiers & FAMILIES
            if node['name'] != 'KeyframeAnimation' or phase not in PHASES or not families:
                rows.append(node)
                continue
            if len(families) != 1 or 'OUT_OF_VEHICLE' not in modifiers:
                raise ValueError('Ambiguous body reload selector')
            key = next(iter(families)), phase
            if key not in DURATIONS or key in found:
                raise ValueError('Unexpected or duplicate body reload phase')
            found.add(key)
            if 'PISTOL' in modifiers:
                if key != ('REVOLVER', 'RELOAD'):
                    raise ValueError('Unexpected shared pistol reload')
                original = copy.deepcopy(node)
                original['children'] = [c for c in original['children'] if not
                    (c['name'] == 'Modifier' and c['attributes']['Flag'] == 'REVOLVER')]
                rows.append(original)
                node = copy.deepcopy(node)
                node['children'] = [c for c in node['children'] if not
                    (c['name'] == 'Modifier' and c['attributes']['Flag'] == 'PISTOL')]
            path = art.norm(node['attributes']['Name']) + '.sanm'
            clip = retime(read(path), DURATIONS[key])
            # Content identity shares identical clones across matching rigs and
            # tables without overwriting any source animation resource.
            name = PREFIX + hashlib.sha256(clip).hexdigest()[:24]
            additions[name + '.sanm'] = clip
            node['attributes']['Name'] = name
            rows.append(node)
        group['children'] = rows
        group['attributes']['KeyedAnimationCount'] = str(sum(
            node['name'] == 'KeyframeAnimation' for node in rows))
    if found != DURATIONS.keys():
        raise ValueError('Incomplete body reload phase coverage')
    return art.encode(tree), additions
