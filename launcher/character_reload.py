"""Match third-person reload clocks and the Redeemer's native magazine motion.

These are body-only visual clones. The hands own ammo/event timing; their clips,
weapon clips and the original shared body clips must remain unchanged.
"""
import copy
import hashlib
import math
import struct

import character_assets as art
import character_boss as boss
import character_weapon_pose as pose

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


def _rotation_mix(first, last, amount):
    q, p = pose.a._to_quaternion(first), pose.a._to_quaternion(last)
    if pose.dot(q, p) < 0: p = pose.scale(p, -1)
    return pose.a._quaternion_matrix(pose.unit(pose.add(pose.scale(q, 1-amount), pose.scale(p, amount))))


class RedeemerMotion:
    """Follow the native magazine-hand path without the old overhead sweep."""
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
        part = pose.world(self.weapon.pose(self.weapon_bind, phase), self.weapon_parents)[2]
        # Body fingers are rigid. Transport their measured grasp with the
        # magazine, rather than copying the POV wrist's finger articulation.
        desired = pose.mul(pose.mul(self.grasp, part), pose.mul(self.grip, after[16]))
        # Reloading needs more reach than the bent idle arm, without locking or
        # stretching either elbow. Other action solvers keep their old bounds.
        return self.solver.fit_contacts(before, after, desired, reach_fraction=.95)

    def sample(self, phase):
        lo, hi = REDEEMER_CONTACT_START, REDEEMER_CONTACT_END
        if lo <= phase <= hi: return self.contact(phase)
        if phase < lo: first, last, amount = self.ready, self.start, phase/lo
        else: first, last, amount = self.end, self.ready, (phase-hi)/(1-hi)
        amount = amount**3 * (10 + amount*(-15 + 6*amount))
        return {bone: (_rotation_mix(first[bone][0], last[bone][0], amount), value[1])
                for bone, value in self.ready.items()}

    def bake(self):
        phases = {i/120 for i in range(121)} | {REDEEMER_CONTACT_START, REDEEMER_CONTACT_END}
        for times, _ in self.weapon.tracks.values():
            phases.update(t for t in times if REDEEMER_CONTACT_START <= t <= REDEEMER_CONTACT_END)
        samples = {}
        def sample(phase):
            if phase not in samples: samples[phase] = self.sample(phase)
            return samples[phase]
        self.solver.arm_bones = tuple(range(self.solver.bones))
        return self.solver._encode_rotations(self.target, sample, phases)


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
