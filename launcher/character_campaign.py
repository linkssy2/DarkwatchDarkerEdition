"""Reproduce the accepted campaign animations using user-supplied resources."""
import copy
import hashlib
import json
import math
import struct
import mmap
from contextlib import ExitStack
from pathlib import Path

import character_assets as art
import character_archive as archive
import character_dropped_clips
import third_person_animation
import character_campaign_pose as pose
import character_weapon_pose as p
import character_weapon_hold as hold

SNIPER_GROUPS = {'Alert Poses UB', 'Crouch Alert Poses', 'Rifle Aim', 'Weapon Shoot',
    'Reload Sniper Rifle', 'Movement UB Rifle', 'Crouch Movement Rifle', 'Jump Rifle',
    'Vampire Jump Rifle'}
DUAL_GROUPS = {'Alert Poses UB', 'Crouch Alert Poses', 'Double Pistol Aim', 'Weapon Shoot',
    'Reload Double Pistol', 'Movement UB Double Pistol', 'Crouch Movement Double Pistol',
    'Jump Double Pistol', 'Vampire Jump Double Pistol'}


def composed(actor, clip, phase):
    additive = bool(clip.flags & 0x10000000)
    local = clip.pose({b: (p.a.IDENTITY, (0., 0., 0.)) for b in actor.bind}
                      if additive else actor.bind, phase)
    mask = actor.mask(clip)
    return local, {b: actor.ready[b] if mask[b] else
        (p.a._multiply(actor.ready[b][0], local[b][0]), p.add(actor.ready[b][1], local[b][1]))
        if additive else local[b] for b in actor.bind}


def bake(actor, data, transform, reload=False, dense=False):
    clip = p.Clip(data, actor.bones, True)
    cache = {}
    def at(phase):
        if phase not in cache:
            cache[phase] = transform(actor, clip, phase)
        return cache[phase]
    phases = set()
    if dense:
        duration = struct.unpack_from('<f', data, 12)[0]
        if not 0 < duration < 10:
            raise ValueError('Unsupported campaign clip duration')
        count = max(1, math.ceil(duration * 60))
        phases = {i / count for i in range(count + 1)}
        phases.update(t for times, _ in clip.tracks.values() for t in times)
    encoder = object.__new__(p.SupportRetarget)
    encoder.bones = actor.bones
    encoder.arm_bones = pose.BONES if reload or dense else (13, 14, 15)
    return encoder._encode_rotations(clip, at, phases, synchronize=dense)


def weapon_stage(pack, weapon, groups, prefix, convert, *, aliases=None, animation_key=None):
    """Split shared weapon/stance routes before replacing only the requested motion."""
    pack.animation_key = animation_key
    changes = {}
    for alias in sorted(p.GRIP_ACTORS if aliases is None else aliases):
        actors = {stance: pose.Actor(pack, 'SniperRifle' if weapon == 'SNIPERRIFLE' else 'Crossbow', stance, alias)
                  for stance in ('STAND', 'CROUCH')}
        path = actors['STAND'].binding['table']
        tree = art.decode(pack.read(path))
        for group in tree['children']:
            name = group['attributes'].get('ToolName')
            if name not in groups:
                continue
            nodes = []
            for node in group['children']:
                flags = pose.flags(node)
                if node['name'] != 'KeyframeAnimation' or weapon not in flags:
                    nodes.append(node)
                    continue
                source = art.norm(node['attributes']['Name']) + '.sanm'
                raw = pack.read(source)
                if flags & (p.WEAPONS - {weapon}):
                    other = copy.deepcopy(node)
                    other['children'] = [c for c in other['children'] if not
                        (c['name'] == 'Modifier' and c['attributes']['Flag'] == weapon)]
                    nodes.append(other)
                stances = ('CROUCH',) if 'CROUCH' in flags else ('STAND',) if 'STAND' in flags else ('STAND', 'CROUCH')
                for stance in stances:
                    result = convert(actors[stance], raw, name)
                    resource = 'characters/player_two/' + prefix + '/' + hashlib.sha256(result).hexdigest()[:24]
                    if resource + '.sanm' in changes and changes[resource + '.sanm'] != result:
                        raise ValueError('Campaign resource collision')
                    changes[resource + '.sanm'] = result
                    item = copy.deepcopy(node)
                    item['attributes']['Name'] = resource
                    item['children'] = [c for c in item['children'] if not
                        (c['name'] == 'Modifier' and c['attributes']['Flag'] in p.WEAPONS - {weapon})]
                    if not flags & {'STAND', 'CROUCH'}:
                        item['children'].append(dict(name='Modifier', attributes={'Flag': stance}, value=None, children=[]))
                    nodes.append(item)
            group['children'] = nodes
            group['attributes']['KeyedAnimationCount'] = str(sum(n['name'] == 'KeyframeAnimation' for n in nodes))
        raw = art.encode(tree)
        if path in changes and changes[path] != raw:
            raise ValueError('Conflicting shared animation table')
        changes[path] = raw
    return changes


def head_stage(pack):
    changes = {}
    pack.animation_key = None
    for alias in sorted(p.GRIP_ACTORS):
        actor = pose.Actor(pack, 'Crossbow', 'STAND', alias)
        references = {}
        for group, node in actor.rows:
            if group in ('Alert Poses UB', 'Crouch Alert Poses') and node['attributes']['AnimationID'] == 'IDLE':
                stance = 'CROUCH' if group == 'Crouch Alert Poses' else 'STAND'
                for flag in pose.flags(node) & p.WEAPONS:
                    if (flag, stance) in references:
                        raise ValueError('Ambiguous ready pose')
                    references[flag, stance] = art.norm(node['attributes']['Name']) + '.sanm'
        if set(references) != {(flag, stance) for flag in p.WEAPONS for stance in ('STAND', 'CROUCH')}:
            raise ValueError('Incomplete ready poses')
        tree = art.decode(pack.read(actor.binding['table']))
        cache = {}
        for group in tree['children']:
            name = group['attributes'].get('ToolName', '')
            if not name.startswith(('Jump ', 'Vampire Jump ', 'Movement UB ', 'Crouch Movement ')) or name.endswith((' Flag', ' Core')):
                continue
            for node in group['children']:
                flags = pose.flags(node)
                weapons = flags & p.WEAPONS
                if node['name'] != 'KeyframeAnimation' or len(weapons) != 1 or 'OUT_OF_VEHICLE' not in flags:
                    raise ValueError('Expected prepared weapon-specific motion')
                source = art.norm(node['attributes']['Name']) + '.sanm'
                reference = references[next(iter(weapons)), 'CROUCH' if 'CROUCH' in flags else 'STAND']
                if (source, reference) not in cache:
                    raw, _ = pose.stabilize_head(pack.read(source), actor.bones, actor.bind, pack.read(reference))
                    resource = 'characters/player_two/private_aimed_head/' + hashlib.sha256(raw).hexdigest()[:24]
                    changes[resource + '.sanm'] = raw
                    cache[source, reference] = resource
                node['attributes']['Name'] = cache[source, reference]
        path = actor.binding['table']
        raw = art.encode(tree)
        if path in changes and changes[path] != raw:
            raise ValueError('Conflicting shared head table')
        changes[path] = raw
    return changes


def sniper_stage(pack, mode, angles, *, animation_key=None):
    ready_cache = {}
    references = {}
    choices = {(x['actor'], x['stance'], x.get('source_sha256', x.get('source'))): x['degrees']
               for x in angles.get('aim' if mode == 'aim' else 'crossbow', [])}
    def fitted(actor, clip, phase):
        _, local = composed(actor, clip, phase)
        world = p.world(local, actor.parents)
        key = actor.binding['actor'], actor.stance, hashlib.sha256(clip.data).hexdigest()
        if key not in choices:
            raise ValueError('Unreviewed sniper animation')
        degrees = choices[key]
        if degrees is None:
            return world
        pair = key[:2]
        if pair not in references:
            references[pair] = pose.Actor(pack, 'Crossbow', actor.stance, pair[0]).ready_world
        return pose.ring(pose.crossbow_fit(world, references[pair], actor.parents, actor.grip, 0.), degrees)
    def new_ready(actor):
        key = actor.binding['actor'], actor.stance
        if key not in ready_cache:
            result = dict(actor.bind)
            groups = ('Alert Poses', 'Alert Poses UB') if actor.stance == 'STAND' else ('Crouch Alert Poses',)
            for group, node in actor.rows:
                if group not in groups or node['attributes']['AnimationID'] != 'IDLE' or 'SNIPERRIFLE' not in pose.flags(node):
                    continue
                clip = p.Clip(pack.read(art.norm(node['attributes']['Name']) + '.sanm'), actor.bones, True)
                local = clip.pose(actor.bind, .5)
                mask = actor.mask(clip)
                if group in SNIPER_GROUPS:
                    changed = p.localize(fitted(actor, clip, .5), actor.parents)
                    for bone in (13, 14, 15):
                        local[bone] = changed[bone][0], local[bone][1]
                for bone in local:
                    if not mask[bone]:
                        result[bone] = local[bone]
            ready_cache[key] = result
        return ready_cache[key]
    def convert(actor, data, group):
        reload = group == 'Reload Sniper Rifle'
        def transform(actor, clip, phase):
            if mode == 'initial':
                return pose.initial_sniper(actor, clip, phase, reload, group == 'Rifle Aim', 'SniperRifle', angles['initial_arcs'])
            if mode == 'frame':
                return pose.sniper_frame(actor, clip, phase, reload)
            local, base = composed(actor, clip, phase)
            if mode == 'aim':
                key = actor.binding['actor'], actor.stance, hashlib.sha256(clip.data).hexdigest()
                if key not in choices:
                    raise ValueError('Unreviewed aim animation')
                after = pose.ring(p.world(base, actor.parents), choices[key])
                reference = actor.ready
            else:
                after = fitted(actor, clip, phase)
                reference = new_ready(actor) if clip.flags & 0x10000000 else actor.ready
            changed = p.localize(after, actor.parents)
            result = dict(local)
            mask = actor.mask(clip)
            for bone in (13, 14, 15):
                if not mask[bone]:
                    result[bone] = (p.a._multiply(p.a._inverse(reference[bone][0]), changed[bone][0])
                                    if clip.flags & 0x10000000 else changed[bone][0]), local[bone][1]
            return result
        return bake(actor, data, transform, reload=reload and mode == 'initial', dense=mode == 'crossbow')
    aliases = p.GRIP_ACTORS if animation_key is None else p.GRIP_ACTORS - {'Chaz'}
    if mode == 'crossbow':
        aliases = {'CassidySpectralSolo', 'CassidySpectralPlayerTwo'}
    prefixes = {'initial': 'private_sniper_arm', 'frame': 'private_sniper_frame',
                'aim': 'private_sniper_aim', 'crossbow': 'private_sniper_crossbow_basis'}
    return weapon_stage(pack, 'SNIPERRIFLE', {'Rifle Aim'} if mode == 'aim' else SNIPER_GROUPS,
                        prefixes[mode], convert, aliases=aliases, animation_key=animation_key)


def neck_stage(pack, *, animation_key=None, back=False):
    references = {}
    def convert(actor, data, group):
        key = actor.binding['actor'], actor.stance
        if key not in references:
            old = pose.ready(actor, 'DOUBLEPISTOL', actor.stance)[0]
            new = pose.head_back(old, actor.parents) if back else pose.ready(actor, 'PISTOL', actor.stance)[0]
            references[key] = old, new
        return pose.neck_bake(actor, data, *references[key])
    return weapon_stage(pack, 'DOUBLEPISTOL', DUAL_GROUPS, 'private_dual_neck', convert,
                        aliases=p.GRIP_ACTORS if animation_key is None else p.GRIP_ACTORS - {'Chaz'},
                        animation_key=animation_key)


def gait_stage(pack):
    actors = art.decode(pack.read('xml/actortemplates_characters.bxml'))
    owners, models, changes, cache = {}, {}, {}, {}
    for alias in sorted(p.GRIP_ACTORS):
        actor = art.child(actors, alias)
        models[alias] = art.norm(art.child(art.child(actor, 'AlternativeModelsRenderComponent'),
                                         'm_modelResourcePath')['attributes']['value']) + '.rx1'
        for row in art.child(art.child(actor, 'AnimationComponent'), 'm_AnimationFiles')['children']:
            if row['attributes']['key'] in ('Multi', 'NotMulti'):
                table = art.norm(row['attributes']['value']) + '.bxml'
                owners.setdefault(table, set()).add(alias)
    for table, aliases in sorted(owners.items()):
        if not aliases & hold.MASCULINE_GAIT_ACTORS:
            continue
        if not aliases <= hold.MASCULINE_GAIT_ACTORS:
            raise ValueError('Unexpected shared male movement table')
        tree = art.decode(pack.read(table))
        changed = False
        for group in tree['children']:
            if group['attributes'].get('ToolName') != 'Movement UB Pistol':
                continue
            for node in group['children']:
                if node['name'] != 'KeyframeAnimation':
                    continue
                if not pose.flags(node) & p.WEAPONS <= {'PISTOL', 'REVOLVER'}:
                    raise ValueError('Unexpected weapon in male movement table')
                source = art.norm(node['attributes']['Name']) + '.sanm'
                model_names = tuple(sorted({models[a] for a in aliases}))
                key = source, model_names
                if key not in cache:
                    raw = pack.read(source)
                    bones = struct.unpack_from('<I', raw, 8)[0]
                    rigs = [p.rig(pack.read(m), bones) for m in model_names]
                    if not all(r == rigs[0] for r in rigs):
                        raise ValueError('Shared movement has incompatible skeletons')
                    solver = object.__new__(hold.AimedMotion)
                    solver.bones = bones
                    solver.target, solver.parents = rigs[0]
                    fixed = solver.masculine_free_arm(raw)
                    destination = 'characters/player_two/darker_male_stride/' + hashlib.sha256(fixed).hexdigest()[:24]
                    changes[destination + '.sanm'] = fixed
                    cache[key] = destination
                node['attributes']['Name'] = cache[key]
                changed = True
        if changed:
            changes[table] = art.encode(tree)
    return changes


class Overlay:
    def __init__(self, read, cancel):
        self.original_read = read
        self.cancel = cancel
        self.changes = {}
        self.animation_key = None

    def read(self, path):
        self.cancel()
        return self.changes[path] if path in self.changes else self.original_read(path)


def animations(read, angles, cancel=lambda: None, progress=lambda message: None):
    pack = Overlay(read, cancel)
    progress('Preparing corrected crossbow reloads...')
    crossbow = {}
    for alias in sorted(p.GRIP_ACTORS):
        for stance in ('STAND', 'CROUCH'):
            actor = pose.Actor(pack, 'Crossbow', stance, alias)
            path = art.norm(actor.actions['RELOAD']['attributes']['Name']) + '.sanm'
            raw = pose.crossbow_reload(actor)
            if path in crossbow and crossbow[path] != raw:
                raise ValueError('Conflicting crossbow reload')
            crossbow[path] = raw
    pack.changes.update(crossbow)
    progress('Preparing corrected weapon poses...')
    initial = sniper_stage(pack, 'initial', angles)
    for path in list(initial):
        if path.endswith('.bxml'):
            initial[path] = merge_table(pack.read(path), initial[path], 'SNIPERRIFLE', SNIPER_GROUPS)
    pack.changes.update(initial)
    pack.changes.update(head_stage(pack))
    for key in (None, 'NotMulti'):
        pack.changes.update(sniper_stage(pack, 'frame', angles, animation_key=key))
        pack.changes.update(neck_stage(pack, animation_key=key))
    aim = sniper_stage(pack, 'aim', angles, animation_key='NotMulti')
    neck = neck_stage(pack, animation_key='NotMulti', back=True)
    # These independently authored changes share tables but touch disjoint groups.
    for path in aim.keys() & neck.keys():
        if not path.endswith('.bxml'):
            if aim[path] != neck[path]:
                raise ValueError('Conflicting campaign clips')
            continue
        baseline = art.decode(pack.read(path))
        first, second = art.decode(aim[path]), art.decode(neck[path])
        if not len(baseline['children']) == len(first['children']) == len(second['children']):
            raise ValueError('Campaign table shape changed')
        for i, (old, a, b) in enumerate(zip(baseline['children'], first['children'], second['children'])):
            if b != old:
                if a != old:
                    raise ValueError('Overlapping campaign group changes')
                first['children'][i] = b
        neck[path] = art.encode(first)
    pack.changes.update(aim)
    pack.changes.update(neck)
    pack.changes.update(sniper_stage(pack, 'crossbow', angles, animation_key='NotMulti'))
    progress('Preparing male walking animations...')
    pack.changes.update(gait_stage(pack))
    return pack.changes


def build(staged, originals, payload, cancel=lambda: None, progress=lambda message: None):
    """Write uncommitted campaign archives; the caller verifies final archive pins."""
    staged, originals, payload = Path(staged), Path(originals), Path(payload)
    with ExitStack() as stack:
        def reader(path):
            cancel()
            stream = stack.enter_context(path.open('rb'))
            raw = stack.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ))
            entries = {row['name']: row for row in archive.read(raw)['entries']}
            def read(name):
                cancel()
                entry = entries[archive.canonical(name)]
                return raw[entry['offset']:entry['offset'] + entry['size']]
            return entries, read
        _, base = reader(staged / 'packfile.pck')
        _, original = reader(originals / 'packfile.pck')
        angle_path = payload / 'character-campaign-angles.json'
        if angle_path.stat().st_size > 256 * 1024:
            raise ValueError('Campaign angle recipe is too large')
        raw_angles = angle_path.read_bytes()
        if hashlib.sha256(raw_angles).hexdigest() != '3da0058a84d3b04883e9f1a664740f10f44a245f41a6dafc5cac18b4a9e5b304':
            raise ValueError('Campaign angle recipe changed')
        angles = json.loads(raw_angles)
        generated = animations(base, angles, cancel, progress)
        tables = {path: raw for path, raw in generated.items() if path.endswith('.bxml')}
        references = {path[:-5]: [(clip, kind) for clip in third_person_animation.clips(raw) for kind in art.KINDS]
                      for path, raw in sorted(tables.items())}
        wanted = {clip + '.sanm' for values in references.values() for clip, _ in values}
        changes = {path: raw for path, raw in generated.items() if path in tables or path in wanted}
        dropped, actors = character_dropped_clips.resources(original)
        changes.update(dropped)
        props = art.decode(base('xml/actortemplates_props.bxml'))
        names = {node['attributes']['name'] for node in props['children']}
        if any(node['attributes']['name'] in names for node in actors):
            raise ValueError('Dropped-clip actor already exists in base content')
        props['children'].extend(actors)
        changes['xml/actortemplates_props.bxml'] = art.encode(props)
        progress('Writing corrected campaign characters...')
        archive.compose_file(staged / 'packfile.pck', changes, staged / 'packfile.pck.campaign', cancel)
        models = sorted(path[:-4] for path in dropped if path.endswith('.rx1'))
        level_entries, level_read = reader(staged / 'LvlSingl.pck')
        old_entries, old_read = reader(originals / 'LvlSingl.pck')
        level_changes = {}
        def select(present):
            result = [(model, kind) for model in models for kind in ('ModelResource', 'HavokObjectResource')]
            for table, dependencies in references.items():
                if (table, 'AnimatedCharacterResource') in present:
                    result.extend(dependencies)
            return result
        progress('Preparing campaign animation and clip references...')
        for path in sorted(level_entries):
            raw = level_read(path)
            if path.startswith('levels/singleplayer/') and '/streaming/' in path and '_resources' in path and path.endswith('.bxml'):
                raw, _ = art.append_resource_bytes(raw, select=select)
            if path not in old_entries or raw != old_read(path):
                level_changes[path] = raw
        # Rebase on the disc to stay within the native archive's 32-bit offsets.
        archive.compose_file(originals / 'LvlSingl.pck', level_changes, staged / 'LvlSingl.pck.campaign', cancel)
    return {name: staged / (name + '.campaign') for name in ('packfile.pck', 'LvlSingl.pck')}


def group_signature(tree, weapon):
    result = []
    for group in tree['children']:
        for node in group['children']:
            if node['name'] != 'KeyframeAnimation':
                continue
            flags = pose.flags(node)
            if weapon not in flags:
                continue
            item = copy.deepcopy(node)
            item['children'] = [x for x in item['children'] if not (x['name'] == 'Modifier' and x['attributes'].get('Flag') in p.WEAPONS)]
            result.append((group['attributes'].get('ToolName'), item))
    return result

def merge_table(current, source, weapon, groups):
    tree = art.decode(current)
    incoming = art.decode(source)
    by_group = {g['attributes'].get('ToolName'): g for g in incoming['children']}
    for group in tree['children']:
        if group['attributes'].get('ToolName') not in groups:
            continue
        other = by_group.get(group['attributes'].get('ToolName'))
        if other is None:
            continue
        inserts = [n for n in other['children'] if n['name'] == 'KeyframeAnimation' and weapon in pose.flags(n)]
        if not inserts:
            continue
        output = []
        inserted = False
        for node in group['children']:
            if node['name'] == 'KeyframeAnimation' and weapon in pose.flags(node):
                if not inserted:
                    output.extend(copy.deepcopy(inserts))
                    inserted = True
                if pose.flags(node) & p.WEAPONS - {weapon}:
                    node = copy.deepcopy(node)
                    node['children'] = [x for x in node['children'] if not (x['name'] == 'Modifier' and x['attributes'].get('Flag') == weapon)]
                    output.append(node)
            else:
                output.append(node)
        assert inserted
        group['children'] = output
        group['attributes']['KeyedAnimationCount'] = str(sum((n['name'] == 'KeyframeAnimation' for n in output)))
    for flag in p.WEAPONS - {weapon}:
        assert group_signature(art.decode(current), flag) == group_signature(tree, flag), (weapon, flag)
    assert group_signature(tree, weapon) == group_signature(incoming, weapon), weapon
    return art.encode(tree)
