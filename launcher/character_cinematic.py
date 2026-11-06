"""Retarget authored cinematic protagonists while preserving the original scenes."""
import copy

import character_animation as animation
import character_assets as art
import character_boss as boss

CHARACTERS = 'xml/actortemplates_characters.bxml'
PROPS = 'xml/actortemplates_props.bxml'
CIVILIAN_CLOAK = 'Accessories/Flair/Cloak/BASE_cloakCiv'
JERICHO_CLOAK = 'Accessories/Flair/Cloak/BASE_cloak'
LAYOUTS = (
    'levels/singleplayer/citadel_launch/citadel_launch_aa/citadel_launch_aa_actors.bxml',
    'levels/singleplayer/fallofcitadel/fallofcitadel_b/fallofcitadel_b_actors.bxml',
    'levels/singleplayer/m02_canyonshoot/hub_a/hub_a_actors.bxml',
    'levels/singleplayer/m03_cemetery/m03_a/m03_a_actors.bxml',
    'levels/singleplayer/m05_devilsbelly/hub_a/hub_a_actors.bxml',
    'levels/singleplayer/m07_dwoutpost/m07_b/m07_b_actors.bxml',
    'levels/singleplayer/m08_regulator/hub_b/hub_b_actors.bxml',
    'levels/singleplayer/m10_tradingpost/m10_a/m10_a_actors.bxml',
    'levels/singleplayer/m10_tradingpost/m10_c/m10_c_actors.bxml',
    'levels/singleplayer/m11_hangtown/m11_g/m11_g_actors.bxml',
    'levels/singleplayer/m15_splittingpaths/m15_a/m15_a_actors.bxml',
    'levels/singleplayer/m15_splittingpaths/m15_d/m15_d_actors.bxml',
    'levels/singleplayer/m17_invasion/m17_c/m17_c_actors.bxml',
    'levels/singleplayer/m17_invasion/m17_d/m17_d_actors.bxml',
    'levels/singleplayer/m19_ridetodeadfall/m19_a/m19_a_actors.bxml',
)
CLOAKS = {
    'levels/singleplayer/fallofcitadel/fallofcitadel_b/fallofcitadel_b_actors.bxml': (('Cloak', 'CloakDemo'),),
    'levels/singleplayer/m03_cemetery/m03_a/m03_a_actors.bxml': (('Cloak', 'Civ_cloak'),),
    'levels/singleplayer/m05_devilsbelly/hub_a/hub_a_actors.bxml': (('cloak', 'Civ_cloak'),),
    'levels/singleplayer/m07_dwoutpost/m07_b/m07_b_actors.bxml': (('Cloak', 'Civ_cloak'),),
    'levels/singleplayer/m08_regulator/hub_b/hub_b_actors.bxml': (('Cloak', 'CloakDemo'),),
    'levels/singleplayer/m10_tradingpost/m10_a/m10_a_actors.bxml': (('Cloak', 'CloakDemo'),),
    'levels/singleplayer/m10_tradingpost/m10_c/m10_c_actors.bxml': (('cloak', 'CloakDemo'),),
    'levels/singleplayer/m11_hangtown/m11_g/m11_g_actors.bxml': (('Cloak', 'CloakDemo'),),
    'levels/singleplayer/m15_splittingpaths/m15_a/m15_a_actors.bxml': (('Cloak', 'CloakDemo'),),
    'levels/singleplayer/m17_invasion/m17_c/m17_c_actors.bxml': (('cloak', 'CloakDemo'),),
    'levels/singleplayer/m19_ridetodeadfall/m19_a/m19_a_actors.bxml': (('Cloak', 'CloakDemo'),),
}
TABLE = 'characters/player_third/chazminematic.bxml'
DIRECT = (
    'characters/player_third/sanm/lo/feedevent_01_jericho',
    'characters/player_third/sanm/lo/feedevent_devilsb_jericho_evil',
    'characters/player_third/sanm/lo/feedevent_devilsb_jericho_good',
    'characters/player_third/sanm/lo/feedevent_devilsb_jericho_idle',
    'characters/player_third/sanm/lo/feedevent_givearm_jericho',
    'characters/player_third/sanm/lo/feedevent_idle_jericho',
    'characters/player_third/sanm/lo/feedevent_outpost_jericho_evil',
    'characters/player_third/sanm/lo/feedevent_outpost_jericho_good',
    'characters/player_third/sanm/lo/feedevent_outpost_jericho_idle',
    'characters/player_third/sanm/lo/feedevent_splitpath_jericho_evil',
    'characters/player_third/sanm/lo/feedevent_splitpath_jericho_good',
    'characters/player_third/sanm/lo/feedevent_splitpath_jericho_idle',
    'characters/player_third/sanm/lo/feedevent_tradingpost_jericho_evil',
    'characters/player_third/sanm/lo/feedevent_tradingpost_jericho_good',
    'characters/player_third/sanm/lo/feedevent_tradingpost_jericho_idle',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/ec_c01_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/ec_c02_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/ec_c03_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/ec_c04_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/gc_c01_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/gc_c02_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/gc_c03_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/gc_c04_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/gc_c06_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/gc_c07_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/sd_c01_jericho',
    'levels/singleplayer/fallofcitadel/resources/cinematics/sanm/sd_c02_jericho',
)
EVENTS = {
    'levels/singleplayer/m08_regulator/resources/cinematics/m08_alamo_intro.bxml': 'CinematicJericho_1',
    'levels/singleplayer/m10_tradingpost/resources/cinematics/talaintro.bxml': 'CinematicJericho_2',
    'levels/singleplayer/m19_ridetodeadfall/resources/cinematics/m19_a_oozerintro.bxml': 'CinematicJericho_1',
}
TEMPLATES = ('CinematicJericho', 'CinematicCivJericho')
BASIC = (
    'characters/gunslinger/sanm/lo/gnslingr_crouch',
    'characters/player_third/sanm/lo/jericho_idle',
    'characters/player_third/sanm/lo/jericho_run',
    'characters/player_third/sanm/lo/jericho_trainjumpdown',
    'characters/player_third/sanm/lo/jericho_walk',
)
COMPANIONS = (BASIC[2] + '.bxml', BASIC[3] + '.banim')
SOURCES = (*LAYOUTS, *EVENTS, TABLE, PROPS, *(path + '.sanm' for path in (*BASIC, *DIRECT)), *COMPANIONS)
PLAYERS = ('CassidySolo', 'CassidySpectralSolo', 'CivilianJerichoSolo',
           'TrooperSolo', 'BlueTrooperSolo', 'RedTrooperSolo', 'TalaSolo',
           'VampireTalaSolo', 'BossTalaSolo')
JERICHO_MODEL = 'Characters/Player_Third/base_chaz'


def layout_variant(raw, identity, path):
    if type(identity) is not int or not 0 <= identity <= len(PLAYERS):
        raise ValueError('Invalid cinematic character')
    if path not in LAYOUTS:
        raise ValueError('Unsupported cinematic layout')
    tree = art.decode(raw)
    actors = art.named(tree, 'actor_list')['children']
    replacements = 0
    for row in actors:
        name = row['attributes'].get('name')
        if name not in TEMPLATES:
            continue
        # Keep layout names, empty-inventory overrides and script targets intact.
        row['attributes']['name'] = f'Selected{name}{identity}'
        replacements += 1
        if identity == 0:
            continue  # Jericho retains the authored coat, animation and story inventory.
        for component in row['children']:
            if component['attributes'].get('name') != 'InventoryComponent':
                continue
            for items in component['children']:
                if items['attributes'].get('name') == 'm_defaultItems':
                    # Remove only Jericho's wearable coat, retaining weapons.
                    for group in art.walk(items):
                        group['children'] = [item for item in group['children']
                            if not (item['name'] == 'inventoryItem' and
                                    item['attributes'].get('actor') in ('cloak', 'Civ_cloak'))]
    if not replacements:
        raise ValueError('Missing cinematic protagonist')
    # The original co-op placeholder retains the cape's named script lifecycle.
    for name, template in CLOAKS.get(path, ()) if identity else ():
        matches = [row for row in actors if row['attributes'].get('layout_name') == name]
        if len(matches) != 1 or matches[0]['attributes'].get('name') != template:
            raise ValueError('Unexpected cinematic cloak: ' + path)
        matches[0]['attributes']['name'] = 'CoOpCloakDemo'
    return art.encode(tree)


def event_variant(raw, identity, path):
    if type(identity) is not int or not 1 <= identity <= len(PLAYERS) or path not in EVENTS:
        raise ValueError('Unsupported cinematic event route')
    tree = art.decode(raw)
    changed = 0
    for event in art.walk(tree):
        if event['name'] != 'score_event' or event['attributes'].get('name') != 'PlayAnimation':
            continue
        if art.child(event, 'm_actorName')['attributes']['value'] != EVENTS[path]:
            continue
        clip = art.child(event, 'm_animationFile')
        if art.norm(clip['attributes']['value']) != BASIC[3]:
            continue
        clip['attributes']['value'] = f'characters/player_cinematic/{identity}/jericho_trainjumpdown'
        changed += 1
    if changed != 1:
        raise ValueError('Unexpected cinematic jump event')
    return art.encode(tree)


def prepare(source, *stages):
    source.report('Preparing selected characters for in-game cinematics...')
    composed = {}
    for stage in stages:
        for changes in stage.values():
            composed.update(changes)

    def read(path):
        path = art.norm(path)
        return composed[path] if path in composed else source.read(path)

    actors = art.decode(read(CHARACTERS))
    originals = [copy.deepcopy(art.child(actors, name)) for name in TEMPLATES]
    table = art.decode(read(TABLE))
    clips = {art.norm(row['attributes']['Name']) for row in art.walk(table)
             if row['name'] == 'KeyframeAnimation'}
    if clips != set(BASIC):
        raise ValueError('Unexpected cinematic animation table')
    source_model = read(animation.CHAZ)
    source_frames = animation.frames(source_model)
    if len({path.rsplit('/', 1)[-1] for path in (*BASIC, *DIRECT)}) != len(BASIC) + len(DIRECT):
        raise ValueError('Cinematic clip destination collision')
    output = {'packfile.pck': {}, 'LvlSingl.pck': {}}
    props = art.decode(read(PROPS))
    coat = art.child(art.child(art.child(props, 'Civ_cloak'), 'RenderComponent'), 'm_modelResourcePath')
    if art.norm(coat['attributes']['value']) != art.norm(CIVILIAN_CLOAK):
        raise ValueError('Unexpected civilian cloak model')
    # Keep Civ_cloak's removal name and animation; selected non-Jericho bodies already omit it.
    coat['attributes']['value'] = JERICHO_CLOAK
    output['packfile.pck'][PROPS] = art.encode(props)
    # The regular choice uses the original skeleton, timing, eye glow and story behavior.
    # Only the body differs from a chapter's CinematicCivJericho presentation.
    for original in originals:
        clone = copy.deepcopy(original)
        clone['attributes']['name'] = f'Selected{original["attributes"]["name"]}0'
        art.child(art.child(clone, 'RenderComponent'), 'm_modelResourcePath')['attributes']['value'] = JERICHO_MODEL
        actors['children'].append(clone)
    dependencies = []
    for identity, name in enumerate(PLAYERS, 1):
        source.cancel()
        player = art.child(actors, name)
        body = art.child(art.child(player, 'AlternativeModelsRenderComponent'),
                         'm_modelResourcePath')['attributes']['value']
        locator = art.child(art.child(player, 'LocatorAttachmentComponent'),
                            'm_locatorFileName')['attributes']['value']
        prefix = f'characters/player_cinematic/{identity}/'
        target_model = read(body + '.rx1')
        extended = identity in (2, 9)
        params = (boss.body_parameters(source_model, target_model) if extended else
                  animation.parameters(source_frames, animation.frames(target_model)))
        mapped = {}
        for path in (*BASIC, *DIRECT):
            source.cancel()
            raw = read(path + '.sanm')
            adapted, _ = animation.retarget(animation.expand(raw), params)
            animation.verify_preserved(raw, adapted)
            target = prefix + path.rsplit('/', 1)[-1]
            output['packfile.pck'][target + '.sanm'] = boss.expand_player(adapted) if extended else adapted
            mapped[path] = target
        # Direct cinematic events retain their original resource names and companions;
        # only their pose-file read is routed by the runtime. Basic table clips
        # have new names, so retain their authored events/path companions too.
        for path in COMPANIONS:
            stem, extension = path.rsplit('.', 1)
            output['packfile.pck'][mapped[stem] + '.' + extension] = read(path)
        adapted_table = copy.deepcopy(table)
        for row in art.walk(adapted_table):
            if row['name'] == 'KeyframeAnimation':
                row['attributes']['Name'] = mapped[art.norm(row['attributes']['Name'])]
        output['packfile.pck'][prefix + 'animation.bxml'] = art.encode(adapted_table)
        for original in originals:
            clone = copy.deepcopy(original)
            clone['attributes']['name'] = f'Selected{original["attributes"]["name"]}{identity}'
            art.child(art.child(clone, 'RenderComponent'), 'm_modelResourcePath')['attributes']['value'] = body
            art.child(art.child(clone, 'LocatorAttachmentComponent'), 'm_locatorFileName')['attributes']['value'] = locator
            maps = art.child(art.child(clone, 'AnimationComponent'), 'm_AnimationFiles')['children']
            if len(maps) != 1 or maps[0]['attributes'] != dict(key='Always', value='Characters/Player_Third/chazMinematic'):
                raise ValueError('Unexpected cinematic actor animation map')
            maps[0]['attributes']['value'] = prefix + 'animation'
            # Use the selected presentation's emitter, not Jericho's single-eye glow.
            for index, component in enumerate(clone['children']):
                if component['attributes']['name'] == 'ParticleEmitterComponent':
                    clone['children'][index] = copy.deepcopy(art.child(player, 'ParticleEmitterComponent'))
            actors['children'].append(clone)
        deps = [(body, kind) for kind in ('ModelResource', 'SkeletonLayoutResource')]
        deps += [(locator, 'LocatorResource'), (prefix + 'animation', 'AnimatedCharacterResource')]
        deps += [(mapped[path], kind) for path in BASIC for kind in animation.KINDS]
        dependencies.append((art.norm(body), deps))
    output['packfile.pck'][CHARACTERS] = art.encode(actors)
    chapters = {path.split('/')[2] for path in LAYOUTS}
    for path in LAYOUTS:
        for identity in range(len(PLAYERS) + 1):
            output['LvlSingl.pck'][path[:-5] + f'_selectedcharacter{identity}.bxml'] = layout_variant(read(path), identity, path)
    for path in EVENTS:
        for identity in range(1, len(PLAYERS) + 1):
            output['LvlSingl.pck'][path[:-5] + f'_selectedcharacter{identity}.bxml'] = event_variant(read(path), identity, path)
    paths = {path for path in (*source.metadata['sources'], *composed)
             if path.startswith('levels/singleplayer/') and '/streaming/' in path
             and '_resources' in path and path.endswith('.bxml')}
    if not paths:
        raise ValueError('Missing cinematic character preload tables')

    regular = [(JERICHO_MODEL, kind) for kind in ('ModelResource', 'SkeletonLayoutResource', 'LocatorResource')]

    def selected(present, cinematic):
        result = regular + [(JERICHO_CLOAK, kind) for kind in ('ModelResource', 'SkeletonLayoutResource')
                            if (art.norm(CIVILIAN_CLOAK), 'ModelResource') in present]
        if cinematic:
            result += [dep for body, deps in dependencies if (body, 'ModelResource') in present for dep in deps]
        return result

    for path in sorted(paths):
        source.cancel()
        adapted, added = art.append_resource_bytes(read(path), regular,
            select=lambda present: selected(present, path.split('/')[2] in chapters))
        if added:
            output['LvlSingl.pck'][path] = adapted
    return output
