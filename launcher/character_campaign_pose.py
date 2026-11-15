"""Authored campaign pose corrections applied to user-supplied resources."""
import math
import struct
import character_assets as art
import character_weapon_pose as p

BONES=(13,14,15,18,19,20)
RELEASE=.4
REPLACEMENT=.525


def flags(node):
    return {n['attributes']['Flag'] for n in node['children'] if n['name'] == 'Modifier'}


def rows(tree):
    return [(g['attributes']['ToolName'], n) for g in tree['children'] if g['name'] == 'AnimationGroup' for n in g['children'] if n['name'] == 'KeyframeAnimation']


class Actor:

    def __init__(self, pack, weapon, stance, actor='CassidySpectralSolo'):
        self.pack, self.weapon, self.stance = (pack, weapon, stance)
        tree = art.decode(pack.read('xml/actortemplates_characters.bxml'))
        node = art.child(tree, actor)
        field = lambda part, key: art.child(art.child(node, part), key)['attributes']['value']
        model = art.norm(field('AlternativeModelsRenderComponent', 'm_modelResourcePath')) + '.rx1'
        locator = art.norm(field('LocatorAttachmentComponent', 'm_locatorFileName')) + '.bllist'
        table = next((n['attributes']['value'] for n in art.child(art.child(node, 'AnimationComponent'), 'm_AnimationFiles')['children'] if n['attributes']['key'] == (pack.animation_key or ('NotMulti' if actor == 'Chaz' else 'Multi'))))
        self.rows = rows(art.decode(pack.read(art.norm(table) + '.bxml')))
        self.stance = stance
        weapon_flag = 'RAILRCKT' if weapon == 'RocketLauncher' else weapon.upper()
        if weapon == "SniperRifle":
            self.rows = [("Reload SniperRifle" if g == "Reload Sniper Rifle" else g, n) for g, n in self.rows]
        self.binding = dict(actor=actor, model=model, locator=locator, table=art.norm(table) + '.bxml')
        self.selected_rows = [(group, n) for group, n in self.rows if weapon_flag in flags(n) and (group == 'Reload ' + weapon or (group in ('Alert Poses', 'Alert Poses UB', 'Crouch Alert Poses') and n['attributes']['AnimationID'] == 'IDLE'))]
        self.actions = {n['attributes']['AnimationID']: n for group, n in self.rows if group == 'Reload ' + weapon and weapon_flag in flags(n) and (stance in flags(n) or not flags(n) & {'STAND', 'CROUCH'})}
        self.data = {key: pack.read(art.norm(n['attributes']['Name']) + '.sanm') for key, n in self.actions.items()}
        self.bones = struct.unpack_from('<I', next(iter(self.data.values())), 8)[0]
        raw = pack.read(model)
        self.bind, self.parents = p.rig(raw, self.bones)
        self.ready = dict(self.bind)
        for group, n in self.rows:
            groups = ('Alert Poses', 'Alert Poses UB') if stance == 'STAND' else ('Crouch Alert Poses',)
            if group in groups and n['attributes']['AnimationID'] == 'IDLE' and (weapon_flag in flags(n)):
                clip = p.Clip(pack.read(art.norm(n['attributes']['Name']) + '.sanm'), self.bones)
                local = clip.pose(self.bind, 0.5)
                mask = self.mask(clip)
                for b in local:
                    if not mask[b]:
                        self.ready[b] = local[b]
        self.clips = {key: p.Clip(data, self.bones) for key, data in self.data.items()}
        self.durations = {key: struct.unpack_from('<f', data, 12)[0] for key, data in self.data.items()}
        self.grip = p._grip(pack.read(locator))
        offset = p.read_grip_offsets().get((actor, weapon), (0.0, 0.0))[0]
        self.grip = (self.grip[0], p.add(self.grip[1], p.scale(self.grip[0][0], offset)))
        
        self.ready_world = p.world(self.ready, self.parents)
        

    def mask(self, clip):
        return struct.unpack_from('<' + 'I' * self.bones, clip.data, clip.parts[1]['keys']) if 1 in clip.parts else (0,) * self.bones

    def sample(self, action, phase):
        if action == 'READY':
            return self.ready_world
        clip = self.clips[action]
        local = clip.pose(self.bind, phase)
        mask = self.mask(clip)
        for b in local:
            if mask[b]:
                local[b] = self.ready[b]
        local[7] = (p.a._multiply(p.a._multiply(local[7][0], self.ready[0][0]), p.a._inverse(local[0][0])), local[7][1])
        return p.world(local, self.parents)


def normal(world):
    return p.unit(p.cross(p.sub(world[14][1], world[13][1]), p.sub(world[15][1], world[14][1])))


def pole_corrected(world, ready, degrees, phase):
    before = dict(world)
    shoulder, elbow, wrist = (before[b][1] for b in (13, 14, 15))
    axis = p.unit(p.sub(wrist, shoulder))
    t = max(0.0, min(1.0, phase / 0.175, (1.0 - phase) / 0.25))
    fade = t * t * (3.0 - 2 * t)
    half = math.radians(degrees * fade) / 2
    rot = p.a._quaternion_matrix((*p.scale(axis, math.sin(half)), math.cos(half)))
    middle = p.add(shoulder, p.rotate(p.sub(elbow, shoulder), rot))
    before[13] = (p.a._multiply(before[13][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder)
    before[14] = (p.a._multiply(before[14][0], p.align(p.sub(wrist, elbow), p.sub(wrist, middle))), middle)
    initial, desired = (normal(ready), normal(before))
    for bone in (13, 14):
        axis = p.unit(p.sub(before[bone + 1][1], before[bone][1]))
        transported = p.rotate(p.rotate(initial, p.a._inverse(ready[bone][0])), before[bone][0])
        transported = p.unit(p.sub(transported, p.scale(axis, p.dot(transported, axis))))
        before[bone] = (p.a._multiply(before[bone][0], p.align(transported, desired)), before[bone][1])
    return before


def assembly_sample(actor, phase, roll_degrees=45.0, yaw_degrees=20.0, pole_degrees=60.0):
    before = actor.sample('RELOAD', phase)
    right = p.sub(before[13][1], before[18][1])
    right = p.unit((right[0], 0.0, right[2]))
    up = (0.0, 1.0, 0.0)
    forward = p.unit(p.cross(up, right))
    gun = p.mul(actor.grip, before[16])
    if p.dot(forward, gun[0][0]) < 0:
        forward = p.scale(forward, -1)
    length = p.length(p.sub(before[14][1], before[13][1])) + p.length(p.sub(before[15][1], before[14][1]))
    t = max(0.0, min(1.0, phase / 0.175, (1.0 - phase) / 0.25))
    fade = t * t * (3.0 - 2 * t)
    half = math.radians(roll_degrees * fade) / 2
    roll = p.a._quaternion_matrix((*p.scale(p.unit(gun[0][0]), math.sin(half)), math.cos(half)))
    bore = p.unit((gun[0][0][0], 0.0, gun[0][0][2]))
    signed = math.atan2(p.dot(p.cross(bore, forward), up), p.dot(bore, forward))
    yaw = math.copysign(1.0, signed) * math.radians(yaw_degrees) * fade
    yaw_rotation = p.a._quaternion_matrix((0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2)))
    roll = p.a._multiply(roll, yaw_rotation)
    pivot = before[15][1]
    targets = {b: p.add(pivot, p.rotate(p.sub(before[b][1], pivot), roll)) for b in (15, 16, 20, 21)}
    offset = p.scale(p.add(p.add(p.scale(right, 0.1), p.scale(up, -0.15)), p.scale(forward, 0.15)), length * fade)
    spheres = []
    for first in (13, 18):
        shoulder, elbow, wrist = (before[b][1] for b in (first, first + 1, first + 2))
        arm = p.length(p.sub(elbow, shoulder)) + p.length(p.sub(wrist, elbow))
        spheres.append((p.sub(shoulder, targets[first + 2]), arm * 0.995))
    corrections = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
    for _ in range(500):
        previous = offset
        for i, (center, radius) in enumerate(spheres):
            trial = p.add(offset, corrections[i])
            radial = p.sub(trial, center)
            distance = p.length(radial)
            projected = trial if distance <= radius else p.add(center, p.scale(radial, radius / distance))
            corrections[i] = p.sub(trial, projected)
            offset = projected
        if p.length(p.sub(offset, previous)) < 1e-10:
            break
    after = dict(before)
    for first in (13, 18):
        shoulder, elbow, wrist = (before[b][1] for b in (first, first + 1, first + 2))
        middle, target = p.solve(shoulder, elbow, wrist, p.add(targets[first + 2], offset))
        after[first] = (p.a._multiply(before[first][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder)
        after[first + 1] = (p.a._multiply(before[first + 1][0], p.align(p.sub(wrist, elbow), p.sub(target, middle))), middle)
        after[first + 2] = (p.a._multiply(before[first + 2][0], roll), target)
        after[first + 3] = (p.a._multiply(before[first + 3][0], roll), p.add(targets[first + 3], offset))
    return (pole_corrected(after, actor.ready_world, pole_degrees, phase), offset)


def final_sample(actor, phase, pronation=90.0, retrieve=False):
    world, offset = assembly_sample(actor, phase, roll_degrees=45.0, yaw_degrees=0.0, pole_degrees=90.0)
    t = max(0.0, min(1.0, phase / 0.175, (1.0 - phase) / 0.25))
    envelope = t * t * (3.0 - 2 * t)
    axis = p.unit(p.sub(world[15][1], world[14][1]))
    half = math.radians(pronation * envelope) / 2
    twist = p.a._quaternion_matrix((*p.scale(axis, math.sin(half)), math.cos(half)))
    world[14] = (p.a._multiply(world[14][0], twist), world[14][1])
    if retrieve and RELEASE < phase < REPLACEMENT:
        t = (phase - RELEASE) / (REPLACEMENT - RELEASE)
        amount = 16 * t * t * (1 - t) * (1 - t)
        shoulder, elbow, wrist = (world[b][1] for b in (18, 19, 20))
        length = p.length(p.sub(elbow, shoulder)) + p.length(p.sub(wrist, elbow))
        left = p.unit(p.sub(world[18][1], world[13][1]))
        up = (0.0, 1.0, 0.0)
        forward = p.unit(p.cross(left, up))
        gun = p.mul(actor.grip, world[16])
        if p.dot(forward, gun[0][0]) < 0.0:
            forward = p.scale(forward, -1.0)
        pickup = p.add(shoulder, p.scale(p.add(p.add(p.scale(left, 0.22), p.scale(up, -0.72)), p.scale(forward, 0.18)), length))
        target = p.add(p.scale(wrist, 1 - amount), p.scale(pickup, amount))
        middle, target = p.solve(shoulder, elbow, wrist, target)
        child = p.mul(world[21], p.inverse(world[20]))
        world[18] = (p.a._multiply(world[18][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder)
        world[19] = (p.a._multiply(world[19][0], p.align(p.sub(wrist, elbow), p.sub(target, middle))), middle)
        world[20] = (world[20][0], target)
        world[21] = p.mul(child, world[20])
    t = max(0.0, min(1.0, phase / 0.175, (1.0 - phase) / 0.25))
    angle = 20 * t * t * (3.0 - 2 * t) + 30 * math.sin(math.pi * t) ** 2
    axis = p.unit(p.sub(world[19][1], world[18][1]))
    half = math.radians(angle) / 2
    twist = p.a._quaternion_matrix((*p.scale(axis, math.sin(half)), math.cos(half)))
    world[18] = (p.a._multiply(world[18][0], twist), world[18][1])
    return (world, offset)


def reroute(world, ready, pole, pronation):
    result = dict(world)
    shoulder, elbow, wrist = (world[b][1] for b in (13, 14, 15))
    axis = p.unit(p.sub(wrist, shoulder))
    center = p.add(shoulder, p.scale(axis, p.dot(p.sub(elbow, shoulder), axis)))
    half = math.radians(pole) / 2
    rotation = p.a._quaternion_matrix((*p.scale(axis, math.sin(half)), math.cos(half)))
    middle = p.add(center, p.rotate(p.sub(elbow, center), rotation))
    result[13] = (p.a._multiply(world[13][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder)
    result[14] = (p.a._multiply(world[14][0], p.align(p.sub(wrist, elbow), p.sub(wrist, middle))), middle)
    initial, desired = (normal(ready), normal(result))
    for bone in (13, 14):
        axis = p.unit(p.sub(result[bone + 1][1], result[bone][1]))
        transported = p.rotate(p.rotate(initial, p.a._inverse(ready[bone][0])), result[bone][0])
        transported = p.unit(p.sub(transported, p.scale(axis, p.dot(transported, axis))))
        result[bone] = (p.a._multiply(result[bone][0], p.align(transported, desired)), result[bone][1])
    axis = p.unit(p.sub(wrist, middle))
    half = math.radians(pronation) / 2
    rotation = p.a._quaternion_matrix((*p.scale(axis, math.sin(half)), math.cos(half)))
    result[14] = (p.a._multiply(result[14][0], rotation), result[14][1])
    return result


def shared_sample(actor, phase, pronation=90.0, retrieve=True, roll=-45.0, pole=-30.0, twist=30.0):
    world, offset = final_sample(actor, phase, pronation, retrieve)
    if 0.175 <= phase <= 0.75 or phase in (0.0, 1.0):
        return (world, offset)
    t = max(0.0, min(1.0, phase / 0.175, (1 - phase) / 0.25))
    amount = math.sin(math.pi * t) ** 2
    gun = p.mul(actor.grip, world[16])
    axis = p.unit(gun[0][0])
    half = math.radians(roll * amount) / 2
    rot = p.a._quaternion_matrix((*p.scale(axis, math.sin(half)), math.cos(half)))
    pivot = world[15][1]
    rolled = dict(world)
    for b in (15, 16, 20, 21):
        rolled[b] = (p.a._multiply(world[b][0], rot), p.add(pivot, p.rotate(p.sub(world[b][1], pivot), rot)))
    spheres = []
    for first in (13, 18):
        shoulder, elbow, wrist = (world[b][1] for b in (first, first + 1, first + 2))
        arm = p.length(p.sub(elbow, shoulder)) + p.length(p.sub(wrist, elbow))
        spheres.append((p.sub(shoulder, rolled[first + 2][1]), arm * 0.995))
    delta = (0.0, 0.0, 0.0)
    corrections = [delta, delta]
    for _ in range(500):
        previous = delta
        for i, (center, radius) in enumerate(spheres):
            trial = p.add(delta, corrections[i])
            radial = p.sub(trial, center)
            distance = p.length(radial)
            projected = trial if distance <= radius else p.add(center, p.scale(radial, radius / distance))
            corrections[i] = p.sub(trial, projected)
            delta = projected
        if p.length(p.sub(delta, previous)) < 1e-10:
            break
    for first in (13, 18):
        shoulder, elbow, wrist = (world[b][1] for b in (first, first + 1, first + 2))
        middle, target = p.solve(shoulder, elbow, wrist, p.add(rolled[first + 2][1], delta))
        rolled[first] = (p.a._multiply(world[first][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder)
        rolled[first + 1] = (p.a._multiply(world[first + 1][0], p.align(p.sub(wrist, elbow), p.sub(target, middle))), middle)
        for bone in (first + 2, first + 3):
            rolled[bone] = (rolled[bone][0], p.add(rolled[bone][1], delta))
    return (reroute(rolled, actor.ready_world, pole * amount, 90 * t * t * (3 - 2 * t) + twist * amount), p.add(offset, delta))


def withdraw_sample(actor, phase, pronation=90.0, retrieve=True, strength=0.35):
    world, offset = shared_sample(actor, phase, pronation, retrieve)
    if 0.175 <= phase <= 0.75 or phase in (0.0, 1.0):
        return (world, offset)
    t = max(0.0, min(1.0, phase / 0.175, (1 - phase) / 0.25))
    amount = math.sin(math.pi * t) ** 2 * strength
    shoulder, elbow, wrist = (world[b][1] for b in (18, 19, 20))
    length = p.length(p.sub(elbow, shoulder)) + p.length(p.sub(wrist, elbow))
    left = p.unit(p.sub(world[18][1], world[13][1]))
    up = (0.0, 1.0, 0.0)
    forward = p.unit(p.cross(left, up))
    gun = p.mul(actor.grip, world[16])
    if p.dot(forward, gun[0][0]) < 0:
        forward = p.scale(forward, -1.0)
    pickup = p.add(shoulder, p.scale(p.add(p.add(p.scale(left, 0.22), p.scale(up, -0.72)), p.scale(forward, 0.18)), length))
    target = p.add(p.scale(wrist, 1 - amount), p.scale(pickup, amount))
    middle, target = p.solve(shoulder, elbow, wrist, target)
    child = p.mul(world[21], p.inverse(world[20]))
    world[18] = (p.a._multiply(world[18][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder)
    world[19] = (p.a._multiply(world[19][0], p.align(p.sub(wrist, elbow), p.sub(target, middle))), middle)
    world[20] = (world[20][0], target)
    world[21] = p.mul(child, world[20])
    return (world, offset)


def cuff_sample(actor, phase, pronation=90.0, retrieve=True):
    world, offset = withdraw_sample(actor, phase, pronation, retrieve)
    if 'Trooper' not in actor.binding['actor'] or actor.stance != 'CROUCH':
        return (world, offset)
    t = max(0.0, min(1.0, (phase - 0.25) / 0.075, (0.475 - phase) / 0.075))
    if not t:
        return (world, offset)
    half = math.radians(15.0 * t * t * (3.0 - 2.0 * t)) / 2.0
    axis = p.unit(p.sub(world[20][1], world[19][1]))
    rotation = p.a._quaternion_matrix((*p.scale(axis, math.sin(half)), math.cos(half)))
    world[19] = (p.a._multiply(world[19][0], rotation), world[19][1])
    return (world, offset)


def crossbow_reload(actor):
    source = actor.clips['RELOAD']
    mask = actor.mask(source)
    cache = {}
    assert not any((mask[b] for b in BONES))

    def sample(phase):
        if phase not in cache:
            result = source.pose(actor.bind, phase)
            adjusted, _ = cuff_sample(actor, phase, 90.0, retrieve=True)
            local = p.localize(adjusted, actor.parents)
            for b in BONES:
                assert p.length(p.sub(result[b][1], local[b][1])) < 1e-07
                result[b] = (local[b][0], result[b][1])
            cache[phase] = result
        return cache[phase]
    encoder = object.__new__(p.SupportRetarget)
    encoder.bones = actor.bones
    encoder.arm_bones = BONES
    return encoder._encode_rotations(source, sample, (), synchronize=False)


class FirstPersonReload:
    """Retarget the original POV wrist paths, preserving body bone lengths."""
    def __init__(self, actor, action='RELOAD'):
        import character_reload as reload
        self.actor, self.action = actor, action
        self.rounds = actor.weapon in ('Rifle', 'Shotgun')
        self.upper_body = actor.weapon in ('Rifle', 'Shotgun', 'RocketLauncher')
        self.mechanical = None if self.rounds else reload.MECHANICAL[actor.weapon]
        self.source = actor.clips[action]
        self.bind, self.parents = p.rig(actor.pack.read('characters/player_first/base_pov_chaz.rx1'), 22)
        if self.rounds:
            self.native = {key: p.Clip(actor.pack.read('characters/player_first/sanm/med/pov_chaz_' +
                key.lower() + '_dw' + actor.weapon.lower() + '.sanm'), 22)
                for key in ('PRERELOAD', 'RELOAD', 'POSTRELOAD')}
            self.clip = self.native[action]
        else:
            self.clip = p.Clip(actor.pack.read(self.mechanical[-1]), 22)
            self.weapon_bind, self.weapon_parents = p.rig(actor.pack.read(self.mechanical[-3]), self.mechanical[1])
            self.weapon = p.Clip(actor.pack.read(self.mechanical[-2]), self.mechanical[1])
        self.fp_grip = p._grip(actor.pack.read('characters/player_first/base_pov_chaz.bllist'))
        self.ready = actor.ready_world
        self.gun = p.mul(actor.grip, self.ready[16])
        self.hand_gun = p.mul(self.gun, p.inverse(self.ready[15]))
        initial = p.world(self.native['PRERELOAD'].pose(self.bind, 0.), self.parents) if self.rounds else self.pov(0.)
        self.reference = p.mul(self.fp_grip, initial[21])
        left = p.mul(initial[4], p.inverse(self.reference))
        self.left_mapping = p.mul(p.mul(self.ready[20], p.inverse(self.gun)), p.inverse(left))
        right = p.mul(initial[14], p.inverse(self.reference))
        self.right_mapping = p.mul(p.mul(self.ready[15], p.inverse(self.gun)), p.inverse(right))
        self.solver = object.__new__(p.SupportRetarget)
        self.solver.parents = actor.parents
        self.solver.bones = actor.bones
        self.solver.arm_bones = tuple(range(7, 22)) if self.upper_body else BONES
        self.cache = {}
        self.poles = None
        if abs(actor.durations[action] - struct.unpack_from('<f', self.clip.data, 12)[0]) > .001:
            raise ValueError(actor.weapon + ' body and POV clocks differ')

    def pov(self, phase):
        local = self.clip.pose(self.bind, phase)
        if self.rounds and self.action != 'RELOAD':
            import character_reload as reload
            amount = max(0., (phase - .9) / .1) if self.action == 'PRERELOAD' else max(0., 1. - phase / .1)
            amount = amount * amount * (3. - 2. * amount)
            if amount:
                # Native hand clips have small join offsets; use the exact insertion seam.
                seam = self.native['RELOAD'].pose(self.bind, 0.)
                local = {b: (reload._rotation_mix(local[b][0], seam[b][0], amount),
                    p.add(p.scale(local[b][1], 1. - amount), p.scale(seam[b][1], amount))) for b in local}
        return p.world(local, self.parents)

    def raw_sample(self, phase):
        import character_reload as reload
        if phase in self.cache:
            return self.cache[phase]
        fp = self.pov(phase)
        fp_gun = p.mul(self.fp_grip, fp[21])
        gun = p.mul(p.mul(fp_gun, p.inverse(self.reference)), self.gun)
        after = dict(self.ready)
        wrist = (p.mul(p.mul(self.right_mapping, p.mul(fp[14], p.inverse(fp_gun))), gun)
                 if self.actor.weapon == 'Rifle' else p.mul(p.inverse(self.hand_gun), gun))
        shoulder, elbow, old_wrist = (self.ready[b][1] for b in (13, 14, 15))
        delta = p.sub(wrist[1], shoulder)
        reach = .95 * (p.length(p.sub(elbow, shoulder)) + p.length(p.sub(old_wrist, elbow)))
        target = p.add(shoulder, p.scale(delta, min(1., reach / p.length(delta))))
        middle, target = p.solve(shoulder, elbow, old_wrist, target)
        after[13] = p.a._multiply(self.ready[13][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder
        after[14] = p.a._multiply(self.ready[14][0], p.align(p.sub(old_wrist, elbow), p.sub(target, middle))), middle
        after[15] = wrist[0], target
        if self.actor.weapon != 'Rifle':
            gun = p.mul(self.hand_gun, after[15])
        after[16] = p.mul(p.inverse(self.actor.grip), gun)
        relative = p.mul(self.left_mapping, p.mul(fp[4], p.inverse(fp_gun)))
        if self.mechanical is not None:
            # Match the renderer's shorter body-only cartridge travel during contact.
            part = p.world(self.weapon.pose(self.weapon_bind, phase), self.weapon_parents)[self.mechanical[2]]
            compact = reload.compact_part(self.actor.weapon, part)
            # The sniper's earlier cylinder is freely ejected; do not pull the hand toward it.
            begin, end = (.125, .8) if self.actor.weapon == 'Crossbow' else (self.mechanical[3], self.mechanical[4] + .05)
            ramp = .1 if self.actor.weapon == 'RocketLauncher' else .05
            if self.actor.weapon == 'RocketLauncher': begin, end = .225, .54
            contact = max(0., min(1., (phase - begin) / ramp, (end - phase) / ramp))
            contact = contact * contact * (3. - 2. * contact)
            relative = relative[0], p.add(relative[1], p.scale(p.sub(compact[1], part[1]), contact))
        desired = p.mul(relative, gun)
        if self.actor.weapon == 'RocketLauncher':
            # Route the loading hand in front of the head rather than through it.
            forward = p.unit((self.gun[0][0][0], 0., self.gun[0][0][2]))
            amount = max(0., min(1., phase / .15, (1. - phase) / .15))
            amount = amount * amount * (3. - 2. * amount)
            gap = .40 - p.dot(p.sub(desired[1], self.ready[10][1]), forward)
            desired = desired[0], p.add(desired[1], p.scale(forward, max(0., gap) * amount))
            drop = max(0., desired[1][1] - (self.ready[10][1][1] - .18))
            desired = desired[0], p.add(desired[1], (0., -drop * amount, 0.))
        local = self.solver.fit_contacts(self.ready, after, desired, reach_fraction=.95)
        # Blend into the accepted standing/crouched pose at the action boundaries.
        amount = (min(1., phase / .1) if self.action == 'PRERELOAD' else
                  min(1., (1. - phase) / .1) if self.action == 'POSTRELOAD' else
                  1.) if self.rounds else min(1., phase / .1, (1. - phase) / .1)
        amount = amount * amount * (3. - 2. * amount)
        result = self.source.pose(self.actor.bind, phase)
        if self.upper_body:
            # Retired reload torso/clavicle poses would offset the new POV arm paths.
            for bone in set(range(7, 22)) - set(BONES):
                result[bone] = self.actor.ready[bone][0], result[bone][1]
        for bone in BONES:
            if p.length(p.sub(result[bone][1], local[bone][1])) > 1e-5:
                raise ValueError('POV retarget changed body arm lengths')
            result[bone] = (reload._rotation_mix(self.actor.ready[bone][0], local[bone][0], amount), result[bone][1])
        if self.actor.weapon == 'Rifle':
            # The existing rifle socket lets the right hand leave the loading gate.
            socket = local[16]
            result[16] = (reload._rotation_mix(self.actor.ready[16][0], socket[0], amount),
                          p.add(p.scale(self.actor.ready[16][1], 1. - amount), p.scale(socket[1], amount)))
        self.cache[phase] = result
        return result

    def sample(self, phase):
        import character_reload as reload
        local = self.raw_sample(phase)
        if self.actor.weapon not in ('SniperRifle', 'RocketLauncher'):
            return local
        # Transport the accepted bend along the wrist path, avoiding fixed-pole flips.
        if self.poles is None:
            initial = p.world(self.raw_sample(0.), self.actor.parents)
            axis = p.unit(p.sub(initial[20][1], initial[18][1]))
            upper = p.sub(initial[19][1], initial[18][1])
            pole = p.unit(p.sub(upper, p.scale(axis, p.dot(upper, axis))))
            self.poles = []
            for i in range(121):
                world = p.world(self.raw_sample(i / 120), self.actor.parents)
                next_axis = p.unit(p.sub(world[20][1], world[18][1]))
                pole = p.rotate(pole, p.align(axis, next_axis))
                axis = next_axis
                self.poles.append((axis, pole))
        world = p.world(local, self.actor.parents)
        shoulder, elbow, wrist = (world[b][1] for b in (18, 19, 20))
        axis = p.unit(p.sub(wrist, shoulder))
        prior_axis, pole = self.poles[min(120, int(phase * 120))]
        pole = p.rotate(pole, p.align(prior_axis, axis))
        if self.actor.weapon == 'RocketLauncher':
            side = p.unit(p.sub(world[18][1], world[13][1]))
            up = p.unit(p.sub(world[10][1], world[8][1]))
            outside = p.sub(side, p.scale(up, .8))
            desired = p.unit(p.sub(outside, p.scale(axis, p.dot(outside, axis))))
            amount = max(0., min(1., phase / .08, (1. - phase) / .15))
            amount = amount * amount * (3. - 2. * amount)
            pole = p.rotate(pole, reload._rotation_mix(p.a.IDENTITY, p.align(pole, desired), amount))
        upper = p.sub(elbow, shoulder)
        along = p.dot(upper, axis)
        radius = p.length(p.sub(upper, p.scale(axis, along)))
        if phase > .9:
            desired = p.unit(p.sub(upper, p.scale(axis, along)))
            amount = (phase - .9) / .1
            amount = amount * amount * (3. - 2. * amount)
            pole = p.rotate(pole, reload._rotation_mix(p.a.IDENTITY, p.align(pole, desired), amount))
        middle = p.add(shoulder, p.add(p.scale(axis, along), p.scale(pole, radius)))
        world[18] = p.a._multiply(world[18][0], p.align(upper, p.sub(middle, shoulder))), shoulder
        world[19] = p.a._multiply(world[19][0], p.align(p.sub(wrist, elbow), p.sub(wrist, middle))), middle
        adjusted = p.localize(world, self.actor.parents)
        result = dict(local)
        for bone in (18, 19, 20):
            result[bone] = adjusted[bone][0], local[bone][1]
        return result

    def bake(self):
        phases = {i / 120 for i in range(121)}
        for times, _ in self.clip.tracks.values():
            phases.update(times)
        samples = {phase: self.sample(phase) for phase in phases}
        data = self.solver._encode_rotations(self.source, samples.__getitem__, phases)
        if self.actor.weapon == 'Rifle':
            import character_boss as boss
            section = boss.sections(data, self.actor.bones)[1][8]
            keys, indices = bytearray(), []
            for bone, first in enumerate(section['indices']):
                if first == p.MISSING:
                    if bone == 16: raise ValueError('Missing rifle reload socket')
                    indices.append(first)
                    continue
                indices.append(len(keys) // 16)
                stop = min([i for i in section['indices'] if first < i < p.MISSING] + [section['count']])
                if bone == 16:
                    for phase in sorted(phases): keys += struct.pack('<f3f', phase, *samples[phase][bone][1])
                else:
                    keys += data[section['keys'] + 16 * first:section['keys'] + 16 * stop]
            block = struct.pack('<I', len(keys) // 16) + struct.pack('<' + 'I' * self.actor.bones, *indices) + keys
            data = data[:section['start']] + block + data[section['end']:]
        return data


def stabilize_head(data, bones, bind, ready):
    clip = p.Clip(data, bones)
    base = p.Clip(ready, bones).pose(bind, 0.5)
    if 32 in clip.parts or clip.flags & 268435456:
        raise ValueError('Expected expanded absolute motion')
    mask = struct.unpack_from('<' + 'I' * bones, data, clip.parts[1]['keys']) if 1 in clip.parts else (0,) * bones
    output = bytearray(data)
    allowed = set()
    for bone in (10, 11):
        first = clip.parts[4]['indices'][bone]
        if mask[bone] or first == p.MISSING:
            raise ValueError(('Missing active head rotation', bone))
        stop = min([x for x in clip.parts[4]['indices'] if first < x < p.MISSING] + [clip.parts[4]['count']])
        q = p.a._to_quaternion(base[bone][0])
        prior = clip.tracks[bone, 4][1][0]
        if p.dot(q, prior) < 0:
            q = p.scale(q, -1.0)
        values = tuple((max(-32768, min(32767, round(x * 32768))) for x in q))
        for index in range(first, stop):
            at = clip.parts[4]['keys'] + 12 * index + 4
            struct.pack_into('<4h', output, at, *values)
            allowed.update(range(at, at + 8))
    changed = {index for index, (a, b) in enumerate(zip(data, output)) if a != b}
    assert changed <= allowed and len(output) == len(data)
    after = p.Clip(bytes(output), bones)
    for key, track in clip.tracks.items():
        if key not in {(bone, 4) for bone in (10, 11)}:
            assert track == after.tracks[key]
        else:
            assert track[0] == after.tracks[key][0]
    for bone in (10, 11):
        expected = p.a._to_quaternion(base[bone][0])
        assert all((abs(p.dot(expected, p.unit(value))) > 0.999999 for value in after.tracks[bone, 4][1]))
    return (bytes(output), len(changed))

def ready(actor, weapon, stance):
    result = dict(actor.bind)
    paths = []
    groups = ('Alert Poses', 'Alert Poses UB') if stance == 'STAND' else ('Crouch Alert Poses',)
    for group, node in actor.rows:
        if group not in groups or node['attributes']['AnimationID'] != 'IDLE' or weapon not in flags(node):
            continue
        path = art.norm(node['attributes']['Name']) + '.sanm'
        paths.append(path)
        clip = p.Clip(actor.pack.read(path), actor.bones)
        local = clip.pose(actor.bind, 0.5)
        mask = actor.mask(clip)
        for b in local:
            if not mask[b]:
                result[b] = local[b]
    assert paths, (actor.binding, weapon, stance)
    return (result, paths)

def head_back(local, parents):
    world = p.world(local, parents)
    side = p.unit(p.sub(world[18][1], world[13][1]))
    forward = p.unit(p.cross(side, (0.0, 1.0, 0.0)))
    neck_to_head = p.sub(world[10][1], world[9][1])
    target = p.sub(neck_to_head, p.scale(forward, 0.02))
    adjusted = dict(world)
    adjusted[9] = (p.a._multiply(world[9][0], p.align(neck_to_head, target)), world[9][1])
    result = dict(local)
    result[9] = (p.localize(adjusted, parents)[9][0], local[9][1])
    return result

def neck_corrected(local, old_ready, new_ready, parents):
    before = p.world(local, parents)
    result = dict(local)
    result[9] = (p.a._multiply(new_ready[9][0], p.a._multiply(p.a._inverse(old_ready[9][0]), local[9][0])), local[9][1])
    changed = p.world(result, parents)
    result[10] = (p.a._multiply(before[10][0], p.a._inverse(changed[9][0])), local[10][1])
    after = p.world(result, parents)
    assert max((p.length(p.sub(after[b][1], before[b][1])) for b in before if b not in (10, 11))) < 1e-07
    return result

def neck_bake(actor, data, old_ready, new_ready):
    clip = p.Clip(data, actor.bones, True)
    mask = actor.mask(clip)
    if mask[9] or mask[10]:
        return data
    additive = bool(clip.flags & 268435456)
    reference = neck_corrected(old_ready, old_ready, new_ready, actor.parents)

    def at(phase):
        local = clip.pose({b: (p.a.IDENTITY, (0.0, 0.0, 0.0)) for b in actor.bind} if additive else actor.bind, phase)
        composed = {b: old_ready[b] if mask[b] else (p.a._multiply(old_ready[b][0], local[b][0]), p.add(old_ready[b][1], local[b][1])) if additive else local[b] for b in actor.bind}
        fixed = neck_corrected(composed, old_ready, new_ready, actor.parents)
        result = dict(local)
        for bone in (9, 10):
            result[bone] = (p.a._multiply(p.a._inverse(reference[bone][0]), fixed[bone][0]) if additive else fixed[bone][0], local[bone][1])
        return result
    encoder = object.__new__(p.SupportRetarget)
    encoder.bones = actor.bones
    encoder.arm_bones = (9, 10)
    return encoder._encode_rotations(clip, at, (), synchronize=False)

def portion(rotation, fraction):
    q = p.unit(p.a._to_quaternion(rotation))
    if q[3] < 0:
        q = p.scale(q, -1)
    half = math.acos(max(-1.0, min(1.0, q[3])))
    if abs(math.sin(half)) < 1e-10:
        return p.a.IDENTITY
    q = (*p.scale(q[:3], math.sin(half * fraction) / math.sin(half)), math.cos(half * fraction))
    return p.a._quaternion_matrix(q)

def envelope(phase):
    t = max(0.0, min(1.0, phase / 0.175, (1.0 - phase) / 0.25))
    return t * t * (3.0 - 2.0 * t)

def frame_correct(local, bind_world, parents, phase):
    before = p.world(local, parents)
    skin = p.a._multiply(p.a._inverse(bind_world[14][0]), before[14][0])
    desired = p.a._multiply(bind_world[13][0], skin)
    desired = p.a._quaternion_matrix(p.unit(p.a._to_quaternion(desired)))
    reference_axis = p.rotate(local[14][1], desired)
    desired = p.a._multiply(desired, p.align(reference_axis, p.sub(before[14][1], before[13][1])))
    delta = p.a._multiply(p.a._inverse(before[13][0]), desired)
    rotation = p.a._multiply(before[13][0], portion(delta, envelope(phase)))
    after = dict(before)
    after[13] = (rotation, before[13][1])
    localized = p.localize(after, parents)
    result = dict(local)
    for bone in (13, 14):
        assert p.length(p.sub(localized[bone][1], local[bone][1])) < 1e-07
        result[bone] = (localized[bone][0], local[bone][1])
    check = p.world(result, parents)
    assert max((p.length(p.sub(check[b][1], before[b][1])) for b in before)) < 1e-07
    return result

def rotation_vector(matrix):
    q = p.a._to_quaternion(matrix)
    if q[3] < 0:
        q = p.scale(q, -1.0)
    length = p.length(q[:3])
    return (0.0, 0.0, 0.0) if length < 1e-10 else p.scale(q[:3], 2 * math.atan2(length, q[3]) / length)

def rotation_exp(vector):
    angle = p.length(vector)
    return p.a.IDENTITY if angle < 1e-10 else p.a._quaternion_matrix((*p.scale(vector, math.sin(angle / 2) / angle), math.cos(angle / 2)))

def smooth_contact(actor, local, phase):
    """Match the native extraction tangent during the preceding free-hand approach."""
    end = 0.39
    window = 0.06
    if not end - window < phase < end:
        return local
    clip = actor.clips['RELOAD']
    h = 0.0005
    first = clip.pose(actor.bind, end)
    last = clip.pose(actor.bind, end + h)
    result = dict(local)
    for bone in (13, 14, 15, 18, 19, 20):
        width = 0.015 if bone < 18 else window
        if phase <= end - width:
            continue
        u = (phase - end + width) / width
        amount = width * u * u * (u - 1.0)
        velocity = p.scale(rotation_vector(p.a._multiply(p.a._inverse(first[bone][0]), last[bone][0])), 1 / h)
        result[bone] = (p.a._multiply(local[bone][0], rotation_exp(p.scale(velocity, amount))), local[bone][1])
    return result

def ring(world, degrees):
    shoulder, elbow, wrist = (world[b][1] for b in (13, 14, 15))
    axis = p.unit(p.sub(wrist, shoulder))
    center = p.add(shoulder, p.scale(axis, p.dot(p.sub(elbow, shoulder), axis)))
    turn = rotation_exp(p.scale(axis, math.radians(degrees)))
    middle = p.add(center, p.rotate(p.sub(elbow, center), turn))
    result = dict(world)
    result[13] = (p.a._multiply(world[13][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder)
    result[14] = (p.a._multiply(world[14][0], p.align(p.sub(wrist, elbow), p.sub(wrist, middle))), middle)
    return result

def crossbow_fit(world, reference, parents, grip, offset=0.0):
    chest_delta = p.mul(p.inverse(reference[8]), world[8])
    ref = {b: p.mul(v, chest_delta) for b, v in reference.items()}
    gun = p.mul(grip, world[16])
    delta = p.scale(p.unit(gun[0][0]), offset)
    source_s, source_e, source_w = (ref[b][1] for b in (13, 14, 15))
    shoulder, elbow, wrist = (world[b][1] for b in (13, 14, 15))
    target = p.add(wrist, delta)
    source_axis = p.unit(p.sub(source_w, source_s))
    axis = p.unit(p.sub(target, shoulder))
    source_upper = p.sub(source_e, source_s)
    pole = p.unit(p.rotate(p.sub(source_upper, p.scale(source_axis, p.dot(source_upper, source_axis))), p.align(source_axis, axis)))
    distance = p.length(p.sub(target, shoulder))
    l1 = p.length(p.sub(elbow, shoulder))
    l2 = p.length(p.sub(wrist, elbow))
    if not abs(l1 - l2) + 1e-06 < distance < l1 + l2 - 1e-06:
        raise ValueError('Unreachable shifted wrist')
    along = (distance * distance + l1 * l1 - l2 * l2) / (2 * distance)
    middle = p.add(shoulder, p.add(p.scale(axis, along), p.scale(pole, math.sqrt(max(0.0, l1 * l1 - along * along)))))
    after = dict(world)
    after[13] = (p.a._multiply(ref[13][0], p.align(source_upper, p.sub(middle, shoulder))), shoulder)
    after[14] = (p.a._multiply(ref[14][0], p.align(p.sub(source_w, source_e), p.sub(target, middle))), middle)
    after[15] = (world[15][0], target)
    left_s, left_e, left_w = (world[b][1] for b in (18, 19, 20))
    left_middle, left_target = p.solve(left_s, left_e, left_w, p.add(left_w, delta))
    after[18] = (p.a._multiply(world[18][0], p.align(p.sub(left_e, left_s), p.sub(left_middle, left_s))), left_s)
    after[19] = (p.a._multiply(world[19][0], p.align(p.sub(left_w, left_e), p.sub(left_target, left_middle))), left_middle)
    after[20] = (world[20][0], left_target)
    before_local = p.localize(world, parents)
    local = p.localize(after, parents)
    for b in (13, 14, 15, 18, 19, 20):
        assert p.length(p.sub(local[b][1], before_local[b][1])) < 0.0001, (b, local[b][1], before_local[b][1])
        before_local[b] = (local[b][0], before_local[b][1])
    return p.world(before_local, parents)


def initial_sniper(actor, clip, phase, reload, preserve_aim, weapon, arcs):
    additive = bool(clip.flags & 268435456)
    local = clip.pose({b: (p.a.IDENTITY, (0.0, 0.0, 0.0)) for b in actor.bind} if additive else actor.bind, phase)
    if reload and weapon == 'Crossbow' and (0.175 <= phase <= 0.75):
        return local
    if reload and weapon == 'SniperRifle':
        return smooth_contact(actor, local, phase)
    mask = actor.mask(clip)
    composed = {b: actor.ready[b] if mask[b] else (p.a._multiply(actor.ready[b][0], local[b][0]), p.add(actor.ready[b][1], local[b][1])) if additive else local[b] for b in actor.bind}
    world = p.world(composed, actor.parents)
    angle = arcs[actor.binding['actor'] + '|' + actor.stance]
    weight = 1.0
    if reload:
        start, end = (0.175, 0.75) if weapon == 'Crossbow' else (0.25, 0.6)
        t = max(0.0, min(1.0, 1.0 - phase / start if phase < start else (phase - end) / (1.0 - end)))
        weight = t * t * (3.0 - 2.0 * t)
    changed = p.localize(world if preserve_aim else ring(world, angle * weight), actor.parents)
    reference = p.localize(ring(actor.ready_world, angle), actor.parents)
    result = dict(local)
    for bone in BONES if reload and weapon == 'SniperRifle' else (13, 14, 15):
        assert not mask[bone]
        value = p.a._multiply(p.a._inverse(reference[bone][0]), changed[bone][0]) if additive else changed[bone][0]
        result[bone] = (value, local[bone][1])
    return result

def sniper_frame(actor, clip, phase, reload, preserve_aim=False):
    additive = bool(clip.flags & 268435456)
    local = clip.pose({b: (p.a.IDENTITY, (0.0, 0.0, 0.0)) for b in actor.bind} if additive else actor.bind, phase)
    if 'Trooper' in actor.binding['actor'] and actor.stance == 'CROUCH' or actor.binding['actor'].startswith('CivilianJericho'):
        return local
    mask = actor.mask(clip)
    composed = {b: actor.ready[b] if mask[b] else (p.a._multiply(actor.ready[b][0], local[b][0]), p.add(actor.ready[b][1], local[b][1])) if additive else local[b] for b in actor.bind}
    bind = p.world(actor.bind, actor.parents)
    adjusted = frame_correct(composed, bind, actor.parents, 0.5)
    reference = frame_correct(actor.ready, bind, actor.parents, 0.5)
    result = dict(local)
    for bone in (13, 14, 15):
        if mask[bone]:
            continue
        rotation = p.a._multiply(p.a._inverse(reference[bone][0]), adjusted[bone][0]) if additive else adjusted[bone][0]
        result[bone] = (rotation, local[bone][1])
    return result


def jericho_rocket_hold(actor, local):
    """Use the Trooper's chest-relative launcher placement with Jericho's hands."""
    if actor.stance != 'STAND':
        return local
    if not hasattr(actor, 'rocket_reference'):
        alias = 'TrooperSolo' if actor.binding['actor'] == 'Chaz' else 'TrooperCoop'
        source = Actor(actor.pack, 'RocketLauncher', actor.stance, alias)
        chest_delta = p.mul(p.inverse(source.ready_world[8]), actor.ready_world[8])
        actor.rocket_reference = p.mul(p.mul(source.grip, source.ready_world[16]), chest_delta)
    before = p.world(local, actor.parents)
    old = p.mul(actor.grip, actor.ready_world[16])
    gun = p.mul(actor.grip, before[16])
    target = p.mul(p.mul(gun, p.inverse(old)), actor.rocket_reference)
    right = p.mul(p.mul(before[15], p.inverse(gun)), target)
    left = p.mul(p.mul(before[20], p.inverse(gun)), target)
    after = dict(before)
    shoulder, elbow, wrist = (before[b][1] for b in (13, 14, 15))
    delta = p.sub(right[1], shoulder)
    reach = .98 * (p.length(p.sub(elbow, shoulder)) + p.length(p.sub(wrist, elbow)))
    endpoint = p.add(shoulder, p.scale(delta, min(1., reach / p.length(delta))))
    middle, endpoint = p.solve(shoulder, elbow, wrist, endpoint)
    after[13] = p.a._multiply(before[13][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder
    after[14] = p.a._multiply(before[14][0], p.align(p.sub(wrist, elbow), p.sub(endpoint, middle))), middle
    after[15] = right[0], endpoint
    after[16] = p.mul(p.mul(before[16], p.inverse(before[15])), after[15])
    solver = object.__new__(p.SupportRetarget)
    solver.parents = actor.parents
    return solver.fit_contacts(before, after, left, reach_fraction=.98)
