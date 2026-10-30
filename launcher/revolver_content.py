"""Retain the starting revolver and preload carryable guns from the verified disc."""
import copy

import bonus_content
import character_assets as art
import revolver_scripts

WEAPONS = 'xml/actortemplates_weapons.bxml'
PROJECTILES = 'xml/projectiletemplates.bxml'
PRELOAD = 'levels/singleplayer/wrongtrain/streaming/wrongtrain_a_resources.bxml'
DISARM = 'levels/singleplayer/m12_citadelunderattack/resources/cinematics/m12_aa_introactiveview.bxml'
ROUND = 'RetainedBasicPistolRound'
WEAPON_DIRECTORIES = dict(dwpistol=27, dwrevolver=35, doublepistol=17,
                          dwrifle=29, dwshotgun=34, dwsniperrifle=25,
                          dwcrossbow=22, dwrailrocket=23)
EFFECTS = ('arrow_swoosh', 'Rail_Rocket_Exhaust', 'explosionRocket',
           'ExplosionBolt', 'fuse01', 'dustcloud')
# These authored on-foot starts deliberately replace the previous inventory.
# Keep their story reset, then return the retained gun alongside the authored kit.
RESTORE_LOADOUTS = {
    'levels/singleplayer/citadel_launch/citadel_launch_aa/citadel_launch_aa_actors.bxml': {
        'Spawnpoint_1': ('Revolver', 'Dynamite'),
        'Spawnpoint_CoOpOnly': ('Revolver', 'Dynamite'),
    },
    'levels/singleplayer/fallofcitadel/fallofcitadel_a/fallofcitadel_a_actors.bxml': {
        'Spawnpoint_1': ('Dynamite', 'Revolver'),
        'Spawnpoint_2': ('Dynamite', 'Revolver'),
    },
    'levels/singleplayer/groundzero/groundzero_a/groundzero_a_actors.bxml': {
        'Spawnpoint_2': ('Dynamite', 'Revolver'),
        'Spawnpoint_CoOPOnly': ('Dynamite', 'Revolver'),
    },
    'levels/singleplayer/m03_cemetery/m03_c/m03_c_actors.bxml': {
        'Spawnpoint_1': ('Revolver',),
        'Spawnpoint_Coop': ('Revolver',),
    },
    'levels/singleplayer/m10_tradingpost/m10_a/m10_a_actors.bxml': {
        'Spawnpoint_3': ('Dynamite', 'Revolver', 'Rifle'),
        'Spawnpoint_4': ('Dynamite', 'Revolver', 'Rifle'),
    },
    'levels/singleplayer/m20_penetratingdeadfall/hub_a/hub_a_actors.bxml': {
        'Spawnpoint_1': ('Dynamite', 'Revolver', 'Rifle'),
        'Spawnpoint_2': ('Dynamite', 'Revolver', 'Rifle'),
    },
}
SCRIPT_RESTORE_LAYOUTS = {
    'levels/singleplayer/m11_hangtown/m11_f/m11_f_actors.bxml': (
        ('CitadelLaunch_DWShotgun_1', 'ShotgunPickup'),
        ('CitadelLaunch_DWShotgun_2', 'ShotgunPickup')),
    'levels/singleplayer/m12_citadelunderattack/m12_aa/m12_aa_actors.bxml': (
        ('IntroDoorRevolver_Player1', 'RevolverPickup'),
        ('IntroDoorRevolver_Player2', 'RevolverPickup')),
    'levels/singleplayer/m15_splittingpaths/m15_d/m15_d_actors.bxml': (
        ('CitadelLaunch_DWShotgun_1', 'ShotgunPickup'),
        ('CitadelLaunch_DWShotgun_2', 'ShotgunPickup')),
    'levels/singleplayer/m17_invasion/m17_b/m17_b_actors.bxml': (
        ('CitadelLaunch_DWShotgun_1', 'ShotgunPickup'),
        ('CitadelLaunch_DWShotgun_2', 'ShotgunPickup')),
}


def tune_weapons(raw, archive_offset):
    # This table also contains the existing Splitter platform edits. Preserve them
    # when its original in-place version is replaced by an appended resource.
    candidate = bytearray(raw)
    patches = [(offset - archive_offset, before, after)
               for offset, before, after in bonus_content.PATCHES
               if archive_offset <= offset < archive_offset + len(raw)]
    if len(patches) != 2:
        raise ValueError('Unexpected revolver/bonus resource boundary')
    for offset, before, after in patches:
        if len(before) != len(after) or candidate[offset:offset + len(before)] != before:
            raise ValueError('Revolver bonus selector differs')
        candidate[offset:offset + len(before)] = after
    tree = art.decode(candidate)
    weapon = art.child(art.child(tree, 'BasicPistol'), 'WeaponComponent')
    projectile = art.child(weapon, 'm_projectileTemplate')['attributes']
    reserve = art.child(weapon, 'm_reserveAmmoMax')['attributes']
    if projectile['value'] != 'PistolRound' or reserve['value'] != '36':
        raise ValueError('Unsupported starting revolver tuning')
    projectile['value'] = ROUND
    redeemer = art.child(art.child(tree, 'Revolver'), 'WeaponComponent')
    for name, before, after in (('m_reticleRange', '20.000000', '40.000000'),
                                ('m_cutoffRange', '30.000000', '50.000000')):
        field = art.child(weapon, name)['attributes']
        if field['value'] != before or art.child(redeemer, name)['attributes']['value'] != after:
            raise ValueError('Unsupported starting revolver range')
        field['value'] = after
    return art.encode(tree)


def tune_projectiles(raw):
    tree = art.decode(raw)
    rows = art.named(tree, 'projectileTypes')['children']
    original = [row for row in rows if art.fields(row).get('name') == 'PistolRound']
    if len(original) != 1 or any(art.fields(row).get('name') == ROUND for row in rows):
        raise ValueError('Unsupported starting revolver projectile table')
    clone = copy.deepcopy(original[0])
    if float(art.named(clone, 'damage')['value']) != 20.0:
        raise ValueError('Unsupported starting revolver damage')
    if art.named(clone, 'coneAperture')['value'] != '3':
        raise ValueError('Unsupported starting revolver spread')
    art.named(clone, 'name')['value'] = ROUND
    art.named(clone, 'damage')['value'] = '65.000000'
    art.named(clone, 'coneAperture')['value'] = '0.000000'
    rows.append(clone)
    return art.encode(tree)


def campaign_dependencies(preloads, effects_raw):
    """Union the authored carryable-gun sets, including launched projectiles."""
    rows = {}
    counts = {name: set() for name in WEAPON_DIRECTORIES}
    for raw in preloads:
        for row in art.named(art.decode(raw), 'data')['children']:
            values = art.fields(row)
            name, kind = values['name'], values['type']
            key = (art.norm(name), kind)
            for directory in counts:
                if key[0].startswith('accessories/weapons/' + directory + '/'):
                    counts[directory].add(key)
                    rows.setdefault(key, (name, kind))
            # FlameBolt's arrow is outside the Crossbow's own directory.
            if key == ('accessories/weapons/bow/base_arrow', 'ModelResource'):
                rows.setdefault(key, (name, kind))
    if {name: len(keys) for name, keys in counts.items()} != WEAPON_DIRECTORIES or len(rows) != 213:
        raise ValueError('Incomplete original carryable weapon resource sets')
    prototypes = art.named(art.decode(effects_raw), 'ParticlePrototypes')['children']
    for effect in EFFECTS:
        matches = [row['attributes'] for row in prototypes if row['attributes'].get('name') == effect]
        if len(matches) != 1 or matches[0] != {'name': effect, 'pathname': 'FX/' + effect}:
            raise ValueError('Unexpected carryable projectile effect registration')
        rows[(art.norm(matches[0]['pathname']), 'ParticleEffectResource')] = (matches[0]['pathname'], 'ParticleEffectResource')
    rows[('fx/textures/effects/particles', 'TexDictionaryResource')] = ('FX/Textures/Effects/Particles', 'TexDictionaryResource')
    return [rows[key] for key in sorted(rows)]


def complete_audio(raw, original_arrow):
    tree = art.decode(raw)
    if tree['name'] != 'BankLayoutConfig':
        raise ValueError('Unsupported carryable weapon sound layout')
    rows = art.named(tree, 'banks')['children']
    if any(art.fields(row).get('name') == 'NPC_ARROW' for row in rows):
        return raw
    rows.append(copy.deepcopy(original_arrow))
    return art.encode(tree)


def preserve_disarm(raw):
    """The unarmed Citadel introduction must remove the retained gun as well."""
    tree = art.decode(raw)
    matches = [row for row in tree['children']
               if row['name'] == 'sequence_entry' and row['attributes'].get('id') == '22']
    if tree['name'] != 'event_sequence' or len(matches) != 1:
        raise ValueError('Unsupported Citadel disarm sequence')
    original = matches[0]
    event = art.child(original, 'event')['children'][0]
    params = art.child(event, 'm_luaEventParams')['children']
    if (event['attributes'].get('name') != 'Lua'
            or art.norm(art.child(event, 'm_luaEventFile')['attributes']['value']) != 'scripts/removeinventory'
            or [row['attributes']['value'] for row in params] != ['Player0', 'Revolver']):
        raise ValueError('Unsupported Citadel disarm event')
    clone = copy.deepcopy(original)
    ids = [int(row['attributes']['id']) for row in tree['children'] if row['name'] == 'sequence_entry']
    clone['attributes']['id'] = str(max(ids) + 1)
    clone['attributes']['name'] = 'Remove Starting Revolver'
    event = art.child(clone, 'event')['children'][0]
    art.child(event, 'm_luaEventParams')['children'][1]['attributes']['value'] = 'BasicPistol'
    tree['children'].insert(tree['children'].index(original) + 1, clone)
    return art.encode(tree)


def restore_starting_revolver(path, raw):
    """Extend only verified player spawn kits, using the native overflow slot."""
    expected = RESTORE_LOADOUTS.get(path)
    if expected is None:
        raise ValueError('Unsupported revolver restoration layout')
    tree = art.decode(raw)
    if tree['name'] != 'layout':
        raise ValueError('Unsupported revolver restoration table')
    actors = art.named(tree, 'actor_list')['children']
    for layout_name, weapons in expected.items():
        matches = [row for row in actors
                   if row['attributes'].get('layout_name') == layout_name]
        if len(matches) != 1 or matches[0]['attributes'].get('name') != 'SpawnPoint':
            raise ValueError('Unsupported revolver restoration spawn')
        component = art.child(matches[0], 'DefaultInventoryComponent')
        items = art.child(component, 'm_defaultItems')
        groups = items['children']
        # Each original group deterministically grants one item. Do not turn a
        # randomized kit, an NPC or an intentional empty/disarmed spawn into one.
        if (items['attributes'].get('type') != 'inventoryItemArray'
                or len(groups) != len(weapons)
                or any(group['name'] != 'inventoryGroup'
                       or len(group['children']) != 1
                       or group['children'][0]['name'] != 'inventoryItem'
                       or group['children'][0]['attributes'] != {
                           'actor': weapon, 'probability': '1.000000'}
                       for group, weapon in zip(groups, weapons))):
            raise ValueError('Unsupported revolver restoration items')
        clone = copy.deepcopy(groups[weapons.index('Revolver')])
        clone['children'][0]['attributes'].update(actor='BasicPistol', locator='bag')
        # Preserve the order and identity of all authored grants. The explicit
        # bag locator avoids replacing either original gun in a two-gun kit,
        # including when Carry All is disabled.
        groups.append(clone)
    return art.encode(tree)


def add_script_restore_pickups(path, raw):
    """Add dormant, owner-specific grants for the verified re-arming scripts."""
    expected = SCRIPT_RESTORE_LAYOUTS.get(path)
    if expected is None:
        raise ValueError('Unsupported scripted revolver restoration layout')
    tree = art.decode(raw)
    if tree['name'] != 'layout':
        raise ValueError('Unsupported scripted revolver restoration table')
    actors = art.named(tree, 'actor_list')['children']
    names = [f'CampaignBasicPistol_Player{owner}' for owner in range(2)]
    if any(row['attributes'].get('layout_name') in names for row in actors):
        raise ValueError('Scripted revolver restoration already exists')
    for name, (source_name, template) in zip(names, expected):
        matches = [row for row in actors
                   if row['attributes'].get('layout_name') == source_name]
        if len(matches) != 1 or matches[0]['attributes'].get('name') != template:
            raise ValueError('Unsupported scripted revolver source actor')
        fields = matches[0]['attributes']
        if (not {'location', 'direction', 'up'} <= fields.keys()
                or fields.keys() - {'name', 'layout_name', 'spawn_at_load', 'location', 'direction', 'up'}):
            raise ValueError('Unsupported scripted revolver placement')
        attributes = dict(fields, name='BasicPistol', layout_name=name, spawn_at_load='false')
        # Use the actual weapon's existing PickupComponent, not a pickup wrapper.
        # Only this dormant actor prefers the bag; normal world pickups and the
        # global BasicPistol template retain their original slot rules.
        actors.append(dict(name='actor', attributes=attributes, value=None, children=[
            dict(name='component', attributes={'name': 'WeaponComponent'}, value=None, children=[
                dict(name='param', attributes={'name': 'm_locatorNames', 'type': 'filteredStringArray'},
                     value=None, children=[dict(name='string', attributes={'value': slot},
                                                value=None, children=[])
                                           for slot in ('bag', 'loc_RightHand', 'pocket')])])]))
    return art.encode(tree)


def prepare(source, groups, extension, spectral, roster):
    """Append one final stage, leaving the established character stages pinned."""
    source.report('Preparing starting revolver...')
    read = source.read
    result = {name: {} for name in ('packfile.pck', 'LvlSingl.pck', 'audio.pck')}
    result['packfile.pck'][WEAPONS] = tune_weapons(read(WEAPONS), source.metadata['sources'][WEAPONS]['offset'])
    result['packfile.pck'][PROJECTILES] = tune_projectiles(read(PROJECTILES))
    result[source.metadata['sources'][DISARM]['archive']][DISARM] = preserve_disarm(read(DISARM))
    for path, raw in revolver_scripts.patch_scripts(read).items():
        result[source.metadata['sources'][path]['archive']][path] = raw
    for path in RESTORE_LOADOUTS:
        result[source.metadata['sources'][path]['archive']][path] = restore_starting_revolver(path, read(path))
    for path in SCRIPT_RESTORE_LAYOUTS:
        result[source.metadata['sources'][path]['archive']][path] = add_script_restore_pickups(path, read(path))

    originals = sorted(path for path in source.metadata['sources']
                       if path.startswith('levels/singleplayer/')
                       and path.endswith(('_resources.bxml', '_resources_coop.bxml')))
    if len(originals) != 102:
        raise ValueError('Incomplete starting revolver campaign coverage')
    merged = {path: read(path) for path in originals}
    deps = campaign_dependencies(merged.values(), read('fx/effects.bxml'))
    for stage in (groups, extension, spectral, roster):
        for path, raw in stage.get('LvlSingl.pck', {}).items():
            if path.startswith('levels/singleplayer/') and '/streaming/' in path and '_resources' in path and path.endswith('.bxml'):
                merged[path] = raw
    for completed, (path, raw) in enumerate(sorted(merged.items()), 1):
        source.cancel()
        adapted, added = art.append_resource_bytes(raw, deps)
        if added:
            result['LvlSingl.pck'][path] = adapted
        if completed % 100 == 0 or completed == len(merged):
            source.report(f'Preparing revolver campaign areas: {completed}/{len(merged)}')
    # FlameBolt also requests the original NPC arrow flight cue. Keep existing
    # per-chapter bank choices; add only this missing alias, including variants.
    audio = {path: read(path) for path in source.metadata['sources']
             if path.startswith('levels/singleplayer/') and path.endswith('.bblf')}
    arrow = None
    for raw in audio.values():
        for row in art.named(art.decode(raw), 'banks')['children']:
            if art.fields(row).get('name') == 'NPC_ARROW':
                if art.fields(row) != {'name': 'NPC_ARROW', 'file': 'NPC_ARROW'}:
                    raise ValueError('Unexpected original arrow sound alias')
                arrow = row
    if len(audio) != 102 or arrow is None:
        raise ValueError('Incomplete carryable weapon sound layouts')
    for stage in (groups, extension, spectral, roster):
        audio.update({path: raw for path, raw in stage.get('audio.pck', {}).items()
                      if path.startswith('levels/singleplayer/') and path.endswith('.bblf')})
    for path, raw in sorted(audio.items()):
        source.cancel()
        adapted = complete_audio(raw, arrow)
        if adapted != raw:
            result['audio.pck'][path] = adapted
    return result
