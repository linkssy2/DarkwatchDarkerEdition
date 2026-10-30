"""Prepare additional player presentations from the user's verified disc.

Templates retain the original player mechanics. Only selected bodies, animation
families and voice banks are appended to a chapter's original preload lists.
"""
import copy
import itertools
import math

import character_animation as animation
import character_assets as art
import character_boss_effects
import character_repaint as rw
import character_spectral_hands as skin
import character_tala

CHARACTERS = 'xml/actortemplates_characters.bxml'
TALA = 'characters/talaagent/base_agenttala'
TALA_HANDS = 'characters/player_first/base_pov_tala'
ROSTER = {
    3: ('CivilianJericho', 'characters/player_third/base_jerichociv',
        'characters/player_first/base_pov_civchaz'),
    4: ('Trooper', 'characters/multiplayer/base_dwstormtrooper',
        'characters/player_first/base_pov_chaz'),
    5: ('BlueTrooper', 'characters/multiplayer/base_dwstormtrooper_blue',
        'characters/player_first/base_pov_blue'),
    6: ('RedTrooper', 'characters/multiplayer/base_dwstormtrooper_red',
        'characters/player_first/base_pov_red'),
    7: ('Tala', TALA, TALA_HANDS),
    8: ('VampireTala', character_tala.VAMPIRE, 'characters/player_first/base_pov_vampiretala'),
    9: ('BossTala', character_tala.MODEL, 'characters/player_first/base_pov_bosstala'),
}


def _unique(dependencies):
    rows = {(art.norm(name), kind): (name, kind) for name, kind in dependencies}
    return [rows[key] for key in sorted(rows)]


def _trooper_locators(player, multiplayer, coop):
    """Keep the grip authored for the Trooper body used by our player clips."""
    result = copy.deepcopy(player)
    lookup = {row['attributes']['name']: row for row in multiplayer['children']}
    # The generic multiplayer grip is turned sideways relative to this rig's
    # co-op animations. Solo animations are also retargeted to this same rig.
    lookup['loc_RightHand'] = art.child(coop, 'loc_RightHand')
    for index, row in enumerate(result['children']):
        replacement = lookup.get(row['attributes']['name'])
        if replacement is not None:
            result['children'][index] = copy.deepcopy(replacement)
    return result


def _hands(original, tala, identity=7):
    """Transfer Tala's original arms/UVs onto the existing articulated POV rig."""
    source, target = skin._geometry(tala, 0), skin._geometry(original, 0)
    old_binds = list(map(skin._inverse, source['inverse']))
    binds = list(map(skin._inverse, target['inverse']))
    model = {key: [] for key in ('positions', 'uv', 'uv1', 'colors', 'bones', 'weights', 'triangles')}
    # Source shoulder/elbow/wrist bones map to the original POV articulation.
    arms = (
        ('left', (18, 19, 20), (1, 2, 4), 21, range(5, 11)),
        ('right', (13, 14, 15), (11, 12, 14), 16, range(15, 22)),
    )
    for side, old, new, child, fingers in arms:
        allowed = [sum((row.get(b, 0.0) for b in (*old, child))) >= 0.98 for row in source['weights']]
        triangles = [tri for tri in source['triangles'] if all((allowed[i] for i in tri))]
        used = sorted({i for tri in triangles for i in tri})
        welded, boundary = skin._boundary(triangles, source['positions'])
        expected = {7: (224, 317, 9), 8: (220 if side == 'left' else 219, 228, 6),
                    9: (455, 598, 6)}[identity]
        if (len(used), len(triangles), len(boundary)) != expected:
            raise ValueError('Original Tala arm topology differs')
        scales = []
        for j, (a, b) in enumerate(zip(old, new)):
            if j < 2:
                length = math.dist(old_binds[a][12:15], old_binds[old[j + 1]][12:15])
                wanted = math.dist(binds[b][12:15], binds[new[j + 1]][12:15])
            else:
                length = max(
                    skin._point(source['positions'][i], source['inverse'][a])[0]
                    for i in used
                    if source['weights'][i].get(a, 0.0) + source['weights'][i].get(child, 0.0) > 0.5)
                wanted = max(
                    skin._point(position, target['inverse'][b])[2]
                    for position, weights in zip(target['positions'], target['weights'])
                    if sum(weights.get(k, 0.0) for k in (b, *fingers)) > 0.5)
            if not 0.01 < length < 1 or not 0.01 < wanted < 1:
                raise ValueError('Unexpected Tala arm proportions')
            scales.append(wanted / length)
        mapping = {vertex: len(model['positions']) + i for i, vertex in enumerate(used)}
        for i in used:
            weights = [source['weights'][i].get(b, 0.0) for b in old]
            weights[2] += source['weights'][i].get(child, 0.0)
            total = sum(weights)
            point = [0.0, 0.0, 0.0]
            for a, b, scale, weight in zip(old, new, scales, weights):
                x, y, z = skin._point(source['positions'][i], source['inverse'][a])
                mapped = skin._point((-z, y, x * scale), binds[b])
                for axis in range(3):
                    point[axis] += mapped[axis] * weight / total
            model['positions'].append(point)
            for key in ('uv', 'colors'):
                model[key].append(source[key][i])
        for ids, weights in skin._finger_weights(
                source, used, triangles, source['inverse'], old, new, child,
                side, scales[2], target, binds, tala=identity == 7,
                tala_variant={7: None, 8: 'vampire', 9: 'boss'}[identity]):
            model['bones'].append(ids)
            model['weights'].append(weights)
        ring = {i for edge in boundary for i in edge}
        # Close and extend the shoulder cut beyond the first-person camera.
        end = min(skin._point(position, target['inverse'][new[0]])[2]
                  for position, weights in zip(target['positions'], target['weights'])
                  if weights.get(new[0], 0.0) > 0.98)
        for i in used:
            if welded[i] in ring:
                index = mapping[i]
                local = list(skin._point(model['positions'][index], target['inverse'][new[0]]))
                local[2] = end
                model['positions'][index] = skin._point(local, binds[new[0]])
                model['bones'][index], model['weights'][index] = ([new[0], 0, 0, 0], [255, 0, 0, 0])
        model['triangles'].extend(tuple(mapping[i] for i in tri) for tri in triangles)
        model['triangles'].extend(skin._cap(boundary, mapping, model['positions'], target['inverse'][new[0]]))
    material = {7: b'TalaAgent_body_clr\x00', 8: b'Tala_Body_A_Clr\x00',
                9: b'Tala_Body_A_Clr_X\x00'}[identity]
    return skin._emit(model, original, tala, source, target, material)


def _hand_actor(original, name, model):
    result = copy.deepcopy(art.child(original, 'ChazHands'))
    result['attributes']['name'] = name
    hands = art.child(result, 'PlayerHandsComponent')
    art.child(hands, 'm_HandsModel')['attributes']['value'] = model
    for row in art.child(hands, 'm_AlternativeHandsModels')['children']:
        row['attributes']['value'] = model
    # All POV meshes share Chaz's rig; variant locator lists omit dual pistols.
    return result


def _actor(original, identity, solo):
    prefix, model, _ = ROSTER[identity]
    player = copy.deepcopy(art.child(original, 'Chaz' if solo else 'CoOpChaz'))
    if not solo:
        art.remove_coop_eye_billboards(player)
    name = prefix + ('Solo' if solo else 'Coop')
    player['attributes']['name'] = name
    render = art.child(player, 'AlternativeModelsRenderComponent')
    art.child(render, 'm_modelResourcePath')['attributes']['value'] = model
    for row in art.child(render, 'm_alternativeModelPaths')['children']:
        row['attributes']['value'] = model
    locator = 'characters/player_roster/' + name.lower()
    art.child(art.child(player, 'LocatorAttachmentComponent'), 'm_locatorFileName')['attributes']['value'] = locator
    hand_name = name + 'Hands' if identity >= 7 else prefix + 'Hands'
    if identity == 4:
        hand_name = 'ChazHands'
    art.child(art.child(player, 'InventoryComponent'), 'm_handActorName')['attributes']['value'] = hand_name
    component = art.child(player, 'AnimationComponent')
    character = {3: 'civilianjericho', 4: 'trooper', 5: 'colortrooper', 6: 'colortrooper',
                 7: 'tala', 8: 'vampiretala', 9: 'bosstala'}[identity]
    source = {alias: destination.replace('cassidy', character)[:-5] for alias, _, destination, _, _, _ in animation.TABLES}
    if solo:
        source['Multi'] = 'characters/player_two/' + character + 'solomultiplayeranimation'
    for row in art.child(component, 'm_AnimationFiles')['children']:
        row['attributes']['value'] = source[row['attributes']['key']]
    ragdoll_actor = 'AgentTala' if identity >= 7 else 'Chaz' if identity == 3 else 'CoOpChaz'
    original_animation = art.child(art.child(original, ragdoll_actor), 'AnimationComponent')
    art.child(component, 'm_ragdollFileName')['attributes']['value'] = (
        art.child(original_animation, 'm_ragdollFileName')['attributes']['value'])
    if identity >= 7:
        npc = art.child(original, 'AgentTala')
        voice = art.child(art.child(npc, 'SpeakerComponent'), 'm_speakerMap')['children']
        own = {row['attributes']['key']: row for row in voice if row['attributes'].get('sound', '').startswith('TALA_')}
        for row in art.child(art.child(player, 'SpeakerComponent'), 'm_speakerMap')['children']:
            if row['attributes']['key'] in own:
                attrs = own[row['attributes']['key']]['attributes']
                # VOICE is a chapter alias; the player uses Tala's explicit bank.
                row['attributes'].update(bank='TALA', sound=attrs['sound'])
    return player, hand_name, locator


def _dependencies(actor, hand, read):
    body = art.child(art.child(actor, 'AlternativeModelsRenderComponent'), 'm_modelResourcePath')['attributes']['value']
    hand_model = art.child(art.child(hand, 'PlayerHandsComponent'), 'm_HandsModel')['attributes']['value']
    deps = [(m, t) for m in (body, hand_model) for t in ('ModelResource', 'SkeletonLayoutResource')]
    for obj in (actor, hand):
        deps.append((art.child(art.child(obj, 'LocatorAttachmentComponent'), 'm_locatorFileName')['attributes']['value'], 'LocatorResource'))
    component = art.child(actor, 'AnimationComponent')
    deps.append((art.child(component, 'm_ragdollFileName')['attributes']['value'], 'HavokObjectResource'))
    tables = [row['attributes']['value'] for row in art.child(component, 'm_AnimationFiles')['children']]
    tables.append('characters/player_first/chazhands')
    for table in tables:
        deps.append((table, 'AnimatedCharacterResource'))
        for node in art.walk(art.decode(read(table + '.bxml'))):
            if node['name'] == 'KeyframeAnimation':
                deps.extend(((node['attributes']['Name'], kind) for kind in animation.KINDS))
    return _unique(deps)


def suffix(choices):
    if (len(choices) not in (1, 2)
            or any(type(n) is not int or not 0 <= n < 10 for n in choices)
            or max(choices) < 3):
        raise ValueError('Invalid roster route')
    return 'roster_' + '_'.join(str(n) for n in sorted(choices))



def _voice_banks(audio, choices):
    """Admit only selected player voices, preserving chapter-specific aliases."""
    layout = copy.deepcopy(audio)
    banks = art.named(layout, 'banks')['children']
    selected = []
    if any(identity in (1, 2) for identity in choices):
        selected.append('CASSIDY')
    if any(identity in (7, 8, 9) for identity in choices):
        selected.append('TALA')
    for bank_name in selected:
        rows = [row for row in banks if art.fields(row)['name'].upper() == bank_name]
        if not rows:
            banks.append(art.element(dict(name=bank_name, file=bank_name)))
            continue
        fields = art.fields(rows[0])
        if (len(rows) != 1 or fields.get('name') != bank_name or fields.get('file') != bank_name
                or set(fields) - {'name', 'file', 'preload'}):
            raise ValueError('Unexpected player voice bank alias')
        if 'preload' in fields:
            if fields['preload'] not in ('true', 'false'):
                raise ValueError('Invalid voice preload flag')
            # Fall of Citadel B deliberately leaves the NPC bank nonresident.
            art.named(rows[0], 'preload')['value'] = 'true'
    return layout


def prepare(source, groups, extension, spectral, tala_variants=False, *, tala_pixels=None):
    read = source.read
    original = art.decode(read(CHARACTERS))
    merged = {**groups['packfile.pck'], **extension['packfile.pck'], **spectral['packfile.pck']}
    actors = art.decode(merged[CHARACTERS])
    outputs = {}
    families = {}
    roster = {identity: row for identity, row in ROSTER.items() if tala_variants or identity < 8}

    def resource(name):
        key = art.norm(name)
        return outputs[key] if key in outputs else merged[key] if key in merged else read(key)

    targets = (
        ('civilianjericho', ROSTER[3][1] + '.rx1'),
        ('trooper', animation.STORM),
        ('colortrooper', ROSTER[5][1] + '.rx1'),
        ('tala', TALA + '.rx1'),
    )
    for character, model in targets:
        label = {'civilianjericho': 'Civilian Jericho', 'trooper': 'Trooper',
                 'colortrooper': 'Blue and Red Troopers', 'tala': 'Tala'}[character]
        added, _, _ = animation.prepare(
            read, art.decode, art.encode, model, character, cancel=source.cancel,
            progress=lambda message, label=label: source.report(f'Preparing {label} {message}'))
        outputs.update(added)
    source.report('Preparing Tala first-person hands...')
    outputs[TALA_HANDS + '.rx1'] = (
        rw.repaint_tala(read(rw.SOURCE), tala_pixels) if tala_pixels is not None
        else _hands(read(rw.SOURCE), read(TALA + '.rx1')))
    source.cancel()
    for ext in ('jlist', 'llist', 'bllist'):
        outputs[TALA_HANDS + '.' + ext] = read('characters/player_first/base_pov_chaz.' + ext)
    if tala_variants:
        source.report('Preparing wingless Boss Tala model...')
        outputs[character_tala.MODEL + '.rx1'] = character_tala.model(read)
        outputs[character_tala.MODEL + '.jlist'] = character_tala.secondary.joint_names(
            read(character_tala.ORIGINAL_BOSS + '.jlist'))
        source.report('Preparing Vampire Tala animations...')
        added, _, _ = animation.prepare(read, art.decode, art.encode,
            character_tala.VAMPIRE + '.rx1', 'vampiretala', cancel=source.cancel,
            progress=lambda message: source.report('Preparing Vampire Tala ' + message))
        outputs.update(added)
        outputs.update(character_tala.animations(read, outputs[character_tala.MODEL + '.rx1'],
            cancel=source.cancel, progress=lambda message: source.report('Preparing Boss Tala ' + message)))
        for identity in (8, 9):
            source.report(f'Preparing {roster[identity][0]} first-person hands...')
            _, model, hands = roster[identity]
            outputs[hands + '.rx1'] = _hands(read(rw.SOURCE), resource(model + '.rx1'), identity)
            for ext in ('jlist', 'llist', 'bllist'):
                outputs[hands + '.' + ext] = read('characters/player_first/base_pov_chaz.' + ext)
    # Blue/red share their own bind basis; the standard trooper differs.
    blue = animation.frames(read(ROSTER[5][1] + '.rx1'))
    red = animation.frames(read(ROSTER[6][1] + '.rx1'))
    if blue.keys() != red.keys():
        raise ValueError('Trooper variant joints differ')
    for joint in blue:
        first = blue[joint]['rotation'] + blue[joint]['translation']
        second = red[joint]['rotation'] + red[joint]['translation']
        if max(abs(a - b) for a, b in zip(first, second)) > 1e-5:
            raise ValueError('Trooper variant rig differs')
    for identity in (5, 6):
        outputs[ROSTER[identity][1] + '.jlist'] = read('characters/multiplayer/base_dwstormtrooper.jlist')
    for identity, (prefix, model, hand_model) in roster.items():
        source.report(f'Preparing player equipment: {identity - 2}/{len(roster)}')
        joints = set(resource(model + '.jlist').decode('ascii').split())
        chaz = art.decode(read('characters/player_third/base_chaz.bllist'))
        coop = art.decode(read('characters/multiplayer/base_dwstormtrooper_coop.bllist'))
        if identity >= 7:
            npc = art.decode(read((TALA if identity == 7 else character_tala.VAMPIRE) + '.bllist'))
        elif identity in (4, 5, 6):
            npc = art.decode(read('characters/multiplayer/base_dwstormtrooper.bllist'))
        for solo in (True, False):
            source.cancel()
            player, hand_name, locator = _actor(original, identity, solo)
            if identity >= 7:
                loc = art.solo_locators(chaz, npc) if solo else art.adapt_locators(coop, npc)
            elif identity == 3:
                loc = chaz if solo else art.jericho_locators(chaz, coop, joints)
            else:
                loc = _trooper_locators(chaz if solo else coop, npc, coop)
            if any((row['attributes']['parent'] not in joints | {'ORIGIN'} for row in loc['children'])):
                raise ValueError('Missing character attachment bone')
            outputs[locator + '.bllist'] = art.encode(loc)
            actors['children'].append(player)
            existing = [a for a in actors['children'] if a['attributes'].get('name') == hand_name]
            hand = existing[0] if existing else _hand_actor(original, hand_name, hand_model)
            if not existing:
                actors['children'].append(hand)
            families[identity, solo] = _dependencies(player, hand, resource)
    outputs[CHARACTERS] = art.encode(actors)
    existing_characters = (
        (0, ('Chaz', 'JerichoCoop')),
        (1, ('CassidySolo', 'CassidyPlayerTwo')),
        (2, ('CassidySpectralSolo', 'CassidySpectralPlayerTwo')),
    )
    for identity, names in existing_characters:
        for solo, name in zip((True, False), names):
            player = art.child(actors, name)
            hand = art.child(actors, art.child(art.child(player, 'InventoryComponent'), 'm_handActorName')['attributes']['value'])
            deps = _dependencies(player, hand, resource)
            if identity == 2:
                deps += character_boss_effects.dependencies()
            families[identity, solo] = _unique(deps)
    bank = art.decode(read('audio/tala/tala.babf'))
    cues = {art.named(row, 'id')['value'] for row in art.named(bank, 'prototypes')['children']}
    if not {'TALA_ATTACK', 'TALA_DMG_LO', 'TALA_DMG_M', 'TALA_DMG_HI', 'TALA_DEATH'} <= cues:
        raise ValueError('Tala voice cues missing')
    resources = sorted(name for name in source.metadata['sources']
                       if name.startswith('levels/singleplayer/')
                       and name.endswith(('_resources.bxml', '_resources_coop.bxml')))
    if len(resources) != 102:
        raise ValueError('Incomplete roster chapter coverage')
    result = {'packfile.pck': outputs, 'LvlSingl.pck': {}, 'audio.pck': {}}
    choices = [(identity,) for identity in roster]
    choices += [pair for pair in itertools.combinations_with_replacement(range(10 if tala_variants else 8), 2)
                if max(pair) >= 3]
    # Character dependencies do not change between campaign areas.
    choice_dependencies = {}
    for pair in choices:
        modes = (True,) if len(pair) == 1 else (True, False)
        choice_dependencies[pair] = _unique(dep for identity in pair for mode in modes
                                            for dep in families[identity, mode])
    source.report(f'Preparing campaign character combinations: 0/{len(resources)} areas')
    for completed, path in enumerate(resources, 1):
        source.cancel()
        original_resources = read(path)
        audio_path = path.replace('/streaming/', '/resources/audio/').replace('_resources', '')[:-5] + '.bblf'
        audio = art.decode(read(audio_path))
        for pair in choices:
            source.cancel()
            tag = suffix(pair)
            adapted, _ = art.append_resource_bytes(original_resources, choice_dependencies[pair])
            target = path[:-5] + '_' + tag + '.bxml'
            result['LvlSingl.pck'][target] = adapted
            owner = source.metadata['sources'][audio_path]['archive']
            result.setdefault(owner, {})[audio_path[:-5] + '_' + tag + '.bblf'] = (
                art.encode(_voice_banks(audio, pair)))
        source.report(f'Preparing campaign character combinations: {completed}/{len(resources)} areas')
    return result, families
