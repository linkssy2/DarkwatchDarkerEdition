"""Complete solo player body animation using that player's native co-op poses.

Keep the original solo story lifecycle while adding the already retargeted
on-foot groups. Private body reload clones follow native hands timing; gameplay
templates, first-person clips, scripts and rigs remain unchanged.
"""
import copy

import character_assets as art
import character_animation
import character_reload
import character_starter_reload
import character_weapon_pose
import character_weapon_hold

CHARACTERS = 'xml/actortemplates_characters.bxml'
PLAYERS = ('Chaz', 'CassidySolo', 'CassidySpectralSolo', 'CivilianJerichoSolo',
           'TrooperSolo', 'BlueTrooperSolo', 'RedTrooperSolo', 'TalaSolo',
           'VampireTalaSolo', 'BossTalaSolo')
COOP_PLAYERS = ('JerichoCoop', 'CassidyPlayerTwo', 'CassidySpectralPlayerTwo',
                'CivilianJerichoCoop', 'TrooperCoop', 'BlueTrooperCoop',
                'RedTrooperCoop', 'TalaCoop', 'VampireTalaCoop', 'BossTalaCoop')
PRESERVED_GROUPS = ('Death Group', 'Spawn', 'Reference')
EXCLUDED_GROUPS = ('Death', 'Turret Actions')
NATIVE_FULL = 'characters/multiplayer/multiplayeranimation.bxml'
JERICHO_FULL = 'characters/player_two/reload/jerichomultiplayer.bxml'


def groups(tree):
    if tree['name'] != 'AnimationSystem' or tree['value'] is not None:
        raise ValueError('Unsupported player animation table')
    result = [row for row in tree['children'] if row['name'] == 'AnimationGroup']
    names = [row['attributes'].get('ToolName') for row in result]
    if (len(result) != int(tree['attributes']['GroupCount']) or
            None in names or len(names) != len(set(names)) or
            any(row['name'] not in ('AnimationGroup', 'SystemModifierDefault')
                for row in tree['children'])):
        raise ValueError('Unexpected player animation groups')
    return {row['attributes']['ToolName']: row for row in result}


def complete(basic_raw, full_raw):
    basic, full = art.decode(basic_raw), art.decode(full_raw)
    old, current = groups(basic), groups(full)
    if set(old) != {'Lower Body', *PRESERVED_GROUPS} or not set(EXCLUDED_GROUPS) <= current.keys():
        raise ValueError('Unsupported solo/co-op animation pair')
    # Full defaults use STOPPED instead of the sparse table's MOVING. Do not
    # combine these mutually exclusive states; the original locomotion updates
    # select MOVING as soon as the player actually walks.
    result = copy.deepcopy(full)
    result['children'] = [row for row in result['children'] if
                          row['attributes'].get('ToolName') not in EXCLUDED_GROUPS]
    result['children'].extend(copy.deepcopy(old[name]) for name in PRESERVED_GROUPS)
    result['attributes']['GroupCount'] = str(len(current) - len(EXCLUDED_GROUPS) + len(PRESERVED_GROUPS))
    groups(result)
    return art.encode(result)


def clips(raw):
    return sorted({art.norm(row['attributes']['Name']) for row in art.walk(art.decode(raw))
                   if row['name'] == 'KeyframeAnimation'})


def gate_redeemer_aim(raw):
    """Give both pistols exclusive normal/fanning aim overlays."""
    tree = art.decode(raw)
    aim = groups(tree).get('Pistol Aim')
    if aim is None:
        raise ValueError('Missing player pistol aim group')
    base = {'REVOLVER', 'AIMING', 'OUT_OF_VEHICLE'}
    actions = {'AIM_POSE_UP', 'AIM_POSE_DOWN', 'AIM_POSE_LEFT', 'AIM_POSE_RIGHT'}
    stances = ({'STAND'}, {'CROUCH', 'STOPPED'}, {'CROUCH', 'MOVING'})
    expected = {(action, frozenset(stance)) for action in actions for stance in stances}
    found = {'pistol': set(), 'normal': set(), 'fan': set(), 'pistol_fan': set()}
    result, changed = [], False
    for node in aim['children']:
        if node['name'] != 'KeyframeAnimation':
            raise ValueError('Unexpected Redeemer aim node')
        flags = {child['attributes']['Flag'] for child in node['children']
                 if child['name'] == 'Modifier'}
        action = node['attributes'].get('AnimationID')
        if action not in actions:
            raise ValueError('Unexpected Redeemer aim action')
        if flags in (base, base | {'ALT_WEAPON_OPERATE'},
                     (base - {'REVOLVER'}) | {'PISTOL', 'ALT_WEAPON_OPERATE'}):
            kind, key = ('pistol_fan' if 'PISTOL' in flags else 'fan'), action
            if 'ALT_WEAPON_OPERATE' not in flags:
                node['children'].append(dict(name='Modifier', attributes={'Flag': 'ALT_WEAPON_OPERATE'},
                                             children=[], value=None))
                changed = True
            result.append(node)
        else:
            stance = flags & {'STAND', 'CROUCH', 'STOPPED', 'MOVING'}
            key = (action, frozenset(stance))
            if key not in expected:
                raise ValueError('Unexpected Redeemer aim stance')
            shared = base | {'PISTOL'} | stance
            if flags == shared:
                pistol, normal = copy.deepcopy(node), copy.deepcopy(node)
                pistol['children'] = [c for c in pistol['children'] if c.get('attributes', {}).get('Flag') != 'REVOLVER']
                pistol['children'].append(dict(name='Modifier', attributes={'Flag': 'NORMAL_WEAPON_OPERATE'},
                                               children=[], value=None))
                normal['children'] = [c for c in normal['children'] if c.get('attributes', {}).get('Flag') != 'PISTOL']
                normal['children'].append(dict(name='Modifier', attributes={'Flag': 'NORMAL_WEAPON_OPERATE'},
                                               children=[], value=None))
                if key in found['pistol']:
                    raise ValueError('Unexpected duplicate pistol aim selector')
                found['pistol'].add(key)
                result.extend((pistol, normal))
                kind, changed = 'normal', True
            elif flags in (shared - {'REVOLVER'}, (shared - {'REVOLVER'}) | {'NORMAL_WEAPON_OPERATE'}):
                kind = 'pistol'
                if 'NORMAL_WEAPON_OPERATE' not in flags:
                    node['children'].append(dict(name='Modifier', attributes={'Flag': 'NORMAL_WEAPON_OPERATE'},
                                                 children=[], value=None))
                    changed = True
                result.append(node)
            elif flags == (shared - {'PISTOL'}) | {'NORMAL_WEAPON_OPERATE'}:
                kind = 'normal'
                result.append(node)
            else:
                raise ValueError('Unexpected Redeemer aim selector')
        if key in found[kind]:
            raise ValueError('Unexpected duplicate Redeemer aim selector')
        found[kind].add(key)
    if not found['pistol_fan']:
        for node in result[:]:
            flags = {c['attributes']['Flag'] for c in node['children'] if c['name'] == 'Modifier'}
            if flags != base | {'ALT_WEAPON_OPERATE'}:
                continue
            clone = copy.deepcopy(node)
            next(c for c in clone['children'] if c.get('attributes', {}).get('Flag') == 'REVOLVER')['attributes']['Flag'] = 'PISTOL'
            result.append(clone)
            found['pistol_fan'].add(node['attributes']['AnimationID'])
            changed = True
    if found != {'pistol': expected, 'normal': expected, 'fan': actions, 'pistol_fan': actions}:
        raise ValueError('Incomplete Redeemer aim coverage')
    # Native operation changes retire ineligible held poses; gating both families
    # prevents the previous one remaining layered over the newly selected aim.
    aim['children'] = result
    aim['attributes']['KeyedAnimationCount'] = str(len(result))
    return art.encode(tree) if changed else raw


def prepare(source, *stages):
    source.report('Preparing third-person character animations...')
    composed, archives = {}, {}
    for stage in stages:
        for archive, changes in stage.items():
            composed.update(changes)
            archives.update((path, archive) for path in changes)

    output = {'packfile.pck': {}, 'LvlSingl.pck': {}}

    def read(path):
        path = art.norm(path)
        return (output['packfile.pck'][path] if path in output['packfile.pck'] else
                composed[path] if path in composed else source.read(path))

    actors = art.decode(read(CHARACTERS))
    aliases = {}
    for name in (*PLAYERS, *COOP_PLAYERS):
        rows = art.child(art.child(art.child(actors, name), 'AnimationComponent'),
                         'm_AnimationFiles')['children']
        mapping = {row['attributes']['key']: art.norm(row['attributes']['value']) + '.bxml'
                   for row in rows}
        if len(mapping) != len(rows) or set(mapping) != {'NotMulti', 'Multi', 'Horse', 'Vehicle'}:
            raise ValueError('Unsupported player animation aliases: ' + name)
        aliases[name] = mapping

    dependencies = {}
    grip_offsets = character_weapon_pose.read_grip_offsets()
    originals = {mapping['Multi']: read(mapping['Multi']) for mapping in aliases.values()}
    processed = set()
    for character_index, (name, mapping) in enumerate(aliases.items(), 1):
        source.cancel()
        def report_clips(label, prepared):
            processed.update(prepared)
            source.report(f'Preparing animations: character {character_index}/{len(aliases)}, '
                          f'{len(processed):,} files processed - {label}')
        report_clips('aiming', ())
        actor = art.child(actors, name)
        model = art.norm(art.child(art.child(actor, 'AlternativeModelsRenderComponent'),
                                   'm_modelResourcePath')['attributes']['value']) + '.rx1'
        locator = art.norm(art.child(art.child(actor, 'LocatorAttachmentComponent'),
                                     'm_locatorFileName')['attributes']['value']) + '.bllist'
        basis = (character_animation.STORM if name in COOP_PLAYERS and name != 'JerichoCoop'
                 else character_animation.CHAZ)
        path = mapping['Multi']
        table, pose_clips = character_weapon_pose.prepare_table(
            gate_redeemer_aim(originals[path]), read, source.read, read(model), read(locator), basis)
        output['packfile.pck'].update(pose_clips)
        report_clips('weapon holds', pose_clips)
        table, hold_clips = character_weapon_hold.prepare_table(
            table, read, source.read, read(model), read(locator), basis, name, grip_offsets)
        output['packfile.pck'].update(hold_clips)
        report_clips('revolver reloads', hold_clips)
        starter_offset = grip_offsets.get((name, 'BasicPistol'), (0., 0.))[0]
        table, starter_clips = character_starter_reload.prepare_table(
            table, read, source.read, read(model), read(locator), basis, starter_offset, actor=name)
        output['packfile.pck'].update(starter_clips)
        report_clips('weapon grips', starter_clips)
        table, grip_clips = character_weapon_pose.prepare_grip_table(
            table, read, source.read, read(model), read(locator), basis, name, grip_offsets)
        output['packfile.pck'].update(grip_clips)
        report_clips('reload timing', grip_clips)
        # Retiming expects the original unsplit selectors; completed updates
        # already contain these durations before the shared fitting stage.
        table, added_clips = character_reload.prepare_table(table, read)
        output['packfile.pck'].update(added_clips)
        report_clips('movement and jump animations', added_clips)
        table, motion_clips = character_weapon_hold.prepare_aimed_motion_table(
            table, read, source.read, read(model), read(locator), basis, name, grip_offsets)
        output['packfile.pck'].update(motion_clips)
        report_clips('Redeemer reloads', motion_clips)
        table, redeemer_clips = character_reload.prepare_redeemer_table(
            table, read, source.read, read(model), read(locator), basis, name,
            grip_offsets.get((name, 'Revolver'), (0., 0.))[0])
        report_clips('magazine reloads', redeemer_clips)
        table, mechanical_clips = character_reload.prepare_mechanical_table(
            table, read, source.read, read(model), read(locator), basis, name, grip_offsets)
        report_clips('character complete', mechanical_clips)
        added_clips.update(redeemer_clips)
        added_clips.update(mechanical_clips)
        added_clips.update(pose_clips)
        added_clips.update(hold_clips)
        added_clips.update(grip_clips)
        added_clips.update(motion_clips)
        added_clips.update(starter_clips)
        referenced = {clip + '.sanm' for clip in clips(table)}
        added_clips = {clip: data for clip, data in added_clips.items() if clip in referenced}
        destination = JERICHO_FULL if path == NATIVE_FULL else path
        if destination in output['packfile.pck'] and output['packfile.pck'][destination] != table:
            raise ValueError('Conflicting shared character body poses: ' + name)
        output['packfile.pck'][destination] = table
        output['packfile.pck'].update(added_clips)
        dependencies[destination[:-5]] = [(clip[:-5], kind)
            for clip in sorted(added_clips) for kind in art.KINDS]
    # Temporary pose clones used only as inputs to a retimed clone need not be
    # installed or streamed. Shared tables can still reference the same output.
    referenced = {clip + '.sanm' for path, data in output['packfile.pck'].items()
                  if path.endswith('.bxml') for clip in clips(data)}
    output['packfile.pck'] = {path: data for path, data in output['packfile.pck'].items()
                            if not path.endswith('.sanm') or path in referenced}
    # Native competitive multiplayer shares Chaz's Multi table. Preserve that
    # route; solo uses the completed NotMulti table and co-op uses JerichoCoop.
    if aliases['Chaz']['Multi'] != NATIVE_FULL or aliases['JerichoCoop']['Multi'] != NATIVE_FULL:
        raise ValueError('Unexpected native Jericho animation routes')
    aliases['Chaz']['Multi'] = JERICHO_FULL
    aliases['JerichoCoop']['Multi'] = JERICHO_FULL
    maps = art.child(art.child(art.child(actors, 'JerichoCoop'), 'AnimationComponent'), 'm_AnimationFiles')
    next(row for row in maps['children'] if row['attributes']['key'] == 'Multi')['attributes']['value'] = JERICHO_FULL[:-5]
    output['packfile.pck'][CHARACTERS] = art.encode(actors)
    dependencies[NATIVE_FULL[:-5]] = [(JERICHO_FULL[:-5], 'AnimatedCharacterResource'),
                                     *dependencies[JERICHO_FULL[:-5]]]

    jericho_clips = []
    for name in PLAYERS:
        source.cancel()
        mapping = aliases[name]
        path = mapping['NotMulti']
        # Shared original solo tables are completed once, then reused by the
        # matching character (the blue/red trooper pair shares a body rig).
        original = composed[path] if path in composed else source.read(path)
        completed = complete(original, read(mapping['Multi']))
        if path in output['packfile.pck'] and output['packfile.pck'][path] != completed:
            raise ValueError('Conflicting shared solo animation table')
        output['packfile.pck'][path] = completed
        dependencies[path[:-5]] = dependencies[mapping['Multi'][:-5]]
        if name == 'Chaz':
            jericho_clips = clips(output['packfile.pck'][path])

    # Selected-character preloads already include their matching full Multi
    # clips. The native Jericho solo manifests only preload his sparse table.
    deps = [(clip, kind) for clip in jericho_clips for kind in art.KINDS]
    native_solo = {path for path in source.metadata['sources']
                   if path.startswith('levels/singleplayer/') and '/streaming/' in path
                   and path.endswith('_resources.bxml')}
    if len(native_solo) != 51:
        raise ValueError('Incomplete native solo campaign preload coverage')
    paths = {path for path in (*source.metadata['sources'], *composed)
             if path.startswith('levels/singleplayer/') and '/streaming/' in path
             and '_resources' in path and path.endswith('.bxml')}
    source.report(f'Linking animations to levels: 0/{len(paths):,} files')
    for completed, path in enumerate(sorted(paths), 1):
        source.cancel()
        def selected(present):
            requested = list(deps) if path in native_solo else []
            for table, resources in dependencies.items():
                if (table, 'AnimatedCharacterResource') in present:
                    requested.extend(resources)
            return requested
        raw, added = art.append_resource_bytes(read(path), select=selected)
        if added:
            archive = archives.get(path) or source.metadata['sources'][path]['archive']
            output.setdefault(archive, {})[path] = raw
        if completed % 25 == 0 or completed == len(paths):
            source.report(f'Linking animations to levels: {completed:,}/{len(paths):,} files')
    return output
