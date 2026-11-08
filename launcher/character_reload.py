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
    'Crossbow': ('CROSSBOW', 8, 1, .08, .75, .4,
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
        self.start, self.end = self.contact(self.contact_start), self.contact(self.contact_end)

    def part_pose(self, phase):
        native = pose.world(self.weapon.pose(self.weapon_bind, phase), self.weapon_parents)[self.part]
        return compact_part(self.weapon_name, native)

    def contact(self, phase):
        desired = pose.mul(pose.mul(self.grasp, self.part_pose(phase)),
                           pose.mul(self.grip, self.contact_after[16]))
        return self.solver.fit_contacts(self.contact_before, self.contact_after, desired, reach_fraction=.95)


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


class RifleSupportMotion:
    """Keep the rifle supported during its native pre/post reload phases."""
    def __init__(self, adapted, insertion, ready, read_original, model, locator, basis, offset, action, bridge_ready=False):
        if action not in ('PRERELOAD', 'POSTRELOAD') or basis not in (pose.a.CHAZ, pose.a.STORM):
            raise ValueError('Unsupported rifle support phase')
        bones = struct.unpack_from('<I', adapted, 8)[0]
        source_locator = basis[:-4] + ('_coop.bllist' if basis == pose.a.STORM else '.bllist')
        self.solver = pose.SupportRetarget(read_original(basis), model,
            pose._grip(read_original(source_locator)), pose._grip(locator), bones)
        self.solver.arm_bones = (17, 18, 19, 20, 21)
        self.target = pose.Clip(adapted, bones)
        if self.target.flags & 0x10000000 or set(self.target.parts) - {1, 4, 8} or 4 not in self.target.parts:
            raise ValueError('Rifle support requires an absolute body pose')
        self.bridge_ready = bridge_ready
        self.action = action
        # Among the admitted shared holds, only Spectral Cassidy uses 51 bones.
        # Her two prepared rigs need an earlier return to the clear authored
        # path so the stock does not sweep through the torso during entry.
        self.ready_window = (.1875 if basis == pose.a.STORM else .25) if bones == 51 else .5
        if bridge_ready:
            held_pose = pose.Clip(ready, bones).pose(self.solver.target, .5)
            insert_pose = pose.Clip(insertion, bones).pose(self.solver.target, 0. if action == 'PRERELOAD' else 1.)
            self.pose_first, self.pose_last = ((held_pose, insert_pose) if action == 'PRERELOAD' else (insert_pose, held_pose))
        grip = self.solver.target_grip
        self.grip = grip[0], pose.add(grip[1], pose.scale(grip[0][0], offset))
        def contact(raw, phase):
            world = pose.world(pose.Clip(raw, bones).pose(self.solver.target, phase), self.solver.parents)
            return pose.mul(world[20], pose.inverse(pose.mul(self.grip, world[16])))
        held = contact(ready, .5)
        if action == 'PRERELOAD': self.first, self.last = held, contact(insertion, 0.)
        else: self.first, self.last = contact(insertion, 1.), held
        self.fp_bind, self.fp_parents = pose.rig(read_original('characters/player_first/base_pov_chaz.rx1'), 22)
        self.fp = pose.Clip(read_original('characters/player_first/sanm/med/pov_chaz_' + action.lower() + '_dwrifle.sanm'), 22)
        self.fp_first, self.fp_last = self.native_contact(0.), self.native_contact(1.)

    def native_contact(self, phase):
        world = pose.world(self.fp.pose(self.fp_bind, phase), self.fp_parents)
        return pose.mul(world[4], pose.inverse(world[21]))

    def sample(self, phase):
        local = self.target.pose(self.solver.target, phase)
        # The old source swept an empty hand above the rifle. Keep it on a
        # continuous path between the actual support grip and cartridge handoff.
        amount = phase**3 * (10 + phase*(-15 + 6*phase))
        if self.bridge_ready:
            # The shared ready chain must also be the reload's real endpoint.
            # Ease into/out of the authored path, retaining its clear middle
            # trajectory rather than cutting straight through the torso.
            start_window, end_window = ((self.ready_window, .25) if self.action == 'PRERELOAD' else (.25, .5))
            anchor, blend = None, 0.
            if phase < start_window:
                t = phase/start_window
                anchor, blend = self.pose_first, 1-t**3*(10+t*(-15+6*t))
            elif phase > 1-end_window:
                t = (phase-(1-end_window))/end_window
                anchor, blend = self.pose_last, t**3*(10+t*(-15+6*t))
            for bone in range(7, 22):
                if anchor is not None:
                    local[bone] = _rotation_mix(local[bone][0], anchor[bone][0], blend), local[bone][1]
            if anchor is not None:
                for bone in (16, 21):
                    local[bone] = local[bone][0], pose.add(pose.scale(local[bone][1], 1-blend), pose.scale(anchor[bone][1], blend))
        before = pose.world(local, self.solver.parents)
        relative = (_rotation_mix(self.first[0], self.last[0], amount),
                    pose.add(pose.scale(self.first[1], 1-amount), pose.scale(self.last[1], amount)))
        # Preserve the original POV hand's small settling motion. Its endpoints
        # are rebased onto the body grip/handoff so neither transition snaps.
        native = self.native_contact(phase)
        baseline = (_rotation_mix(self.fp_first[0], self.fp_last[0], phase),
                    pose.add(pose.scale(self.fp_first[1], 1-phase), pose.scale(self.fp_last[1], phase)))
        relative = (pose.a._multiply(relative[0], pose.a._multiply(pose.a._inverse(baseline[0]), native[0])),
                    pose.add(relative[1], pose.sub(native[1], baseline[1])))
        desired = pose.mul(relative, pose.mul(self.grip, before[16]))
        return fit_loading_hand(before, self.solver.parents, desired, self.solver)

    def bake(self):
        phases = {i/240 for i in range(241)}
        for times, _ in self.target.tracks.values(): phases.update(times)
        cache = {}
        def sample(phase):
            if phase not in cache: cache[phase] = self.sample(phase)
            return cache[phase]
        for phase in phases: sample(phase)
        if self.bridge_ready:
            self.solver.arm_bones = tuple(range(7, 22))
        elif any(pose.length(pose.sub(pose.world(value, self.solver.parents)[15][1],
                pose.world(self.target.pose(self.solver.target, phase), self.solver.parents)[15][1])) > 1e-8
                for phase, value in cache.items()):
            self.solver.arm_bones = tuple(range(13, 22))
        data = self.solver._encode_rotations(self.target, sample, phases)
        if not self.bridge_ready: return data
        section = boss.sections(data, self.solver.bones)[1].get(8)
        if section is None: raise ValueError('Missing reload socket translations')
        keys, indices = bytearray(), []
        for bone, first in enumerate(section['indices']):
            if first == pose.MISSING:
                if bone in (16, 21): raise ValueError('Missing reload socket translation')
                indices.append(first)
                continue
            indices.append(len(keys)//16)
            stop = min([i for i in section['indices'] if first < i < pose.MISSING] + [section['count']])
            if bone in (16, 21):
                for phase in sorted(phases): keys += struct.pack('<f3f', phase, *sample(phase)[bone][1])
            else: keys += data[section['keys']+16*first:section['keys']+16*stop]
        block = struct.pack('<I', len(keys)//16) + struct.pack('<'+'I'*self.solver.bones, *indices) + keys
        return data[:section['start']] + block + data[section['end']:]


def prepare_rifle_support_table(raw, read, read_original, model, locator, basis, offset=0., *, bridge_ready=False):
    """Fit pre/post contact and optional ready joins; preserve loop and events."""
    tree = art.decode(raw)
    ready, candidates = {}, {}
    for group in tree['children']:
        if group['name'] != 'AnimationGroup': continue
        stance = {'Alert Poses UB':'STAND', 'Crouch Alert Poses':'CROUCH'}.get(group['attributes'].get('ToolName'))
        for node in group['children']:
            if node['name'] != 'KeyframeAnimation': continue
            flags = {c['attributes']['Flag'] for c in node['children'] if c['name'] == 'Modifier'}
            if 'RIFLE' not in flags: continue
            action = node['attributes'].get('AnimationID')
            if stance and action == 'IDLE': ready[stance] = read(art.norm(node['attributes']['Name']) + '.sanm')
            if action in PHASES:
                selected = flags & {'STAND', 'CROUCH'}
                key = action, next(iter(selected)) if len(selected) == 1 else None
                if key in candidates or len(selected) > 1 or flags - selected != {'RIFLE', 'OUT_OF_VEHICLE'}:
                    raise ValueError('Unsupported rifle reload selector')
                candidates[key] = (group, node)
    if set(ready) != {'STAND', 'CROUCH'} or any(
            {stance for action, stance in candidates if action == phase} not in ({None}, {'STAND', 'CROUCH'}) for phase in PHASES):
        raise ValueError('Incomplete rifle support routes')
    additions = {}
    for (action, selected), (group, node) in candidates.items():
        if action == 'RELOAD': continue
        source = read(art.norm(node['attributes']['Name']) + '.sanm')
        replacements = []
        for stance in (selected,) if selected else ('STAND', 'CROUCH'):
            insertion_node = candidates['RELOAD', stance if ('RELOAD', stance) in candidates else None][1]
            insertion = read(art.norm(insertion_node['attributes']['Name']) + '.sanm')
            data = RifleSupportMotion(source, insertion, ready[stance], read_original, model, locator, basis, offset, action, bridge_ready).bake()
            name = PREFIX + 'rifle-support/' + hashlib.sha256(data).hexdigest()[:24]
            additions[name + '.sanm'] = data
            replacement = copy.deepcopy(node)
            replacement['attributes']['Name'] = name
            if bridge_ready: replacement['attributes']['BlendIn'] = '0.001000'
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
