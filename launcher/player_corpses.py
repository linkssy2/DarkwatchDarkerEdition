"""Derive inert player-body props from the user's existing character resources."""
import copy
import math
import struct

import character_assets as art

PREFIX = 'Corpse_'


def append(actors, read):
    """Return appended templates and per-player preload dependencies.

    ``read`` resolves the composed character output before the original disc.
    The runtime must place/copy the dead pose before explicitly activating the
    body. These props have no player, inventory, health, script or network state.
    """
    result = copy.deepcopy(actors)
    prototype = art.child(art.decode(read('xml/actortemplates_props.bxml')), 'CassidyHeadless_Ragdoll')
    existing = {row['attributes']['name'] for row in actors['children']}
    dependencies = {}
    tables = {}
    for player in actors['children']:
        components = {row['attributes'].get('name'): row for row in player['children']}
        if 'PlayerComponent' not in components:
            continue
        name = player['attributes']['name']
        if PREFIX + name in existing:
            raise ValueError('Player corpse template already exists: ' + name)
        body = art.child(components['AlternativeModelsRenderComponent'], 'm_modelResourcePath')['attributes']['value']
        animation = components['AnimationComponent']
        ragdoll = art.child(animation, 'm_ragdollFileName')['attributes']['value']
        mode = 'NotMulti' if name == 'Chaz' or name.endswith('Solo') else 'Multi'
        table = next(row['attributes']['value'] for row in art.child(animation, 'm_AnimationFiles')['children']
                     if row['attributes']['key'] == mode)
        key = art.norm(table)
        if key not in tables:
            tables[key] = art.decode(read(key + '.bxml'))
        clips = {art.norm(row['attributes']['Name']) for row in art.walk(tables[key])
                 if row['name'] == 'KeyframeAnimation'}
        # Full-body authored deaths; lower/upper-body idle clips are unsuitable
        # as an initial physical pose. Both 22- and 51-bone variants are retained.
        matches = [clip for clip in clips if clip.rsplit('/', 1)[-1] in ('dwagentmale_death', 'chaz_deathfalltoknees')]
        if len(matches) != 1:
            raise ValueError('Expected one matching full-body death animation: ' + name)
        start = matches[0]
        raw = read(start + '.sanm')
        if len(raw) < 24:
            raise ValueError('Truncated player corpse start animation')
        version, magic, bones, duration, _, _ = struct.unpack_from('<IIIfII', raw)
        joints = read(art.norm(body) + '.jlist').decode('ascii').split()
        if not (16 <= version <= 40 and magic == 0xf11e0006 and bones in (22, 51) and
                bones == len(joints) and len(set(joints)) == len(joints) and math.isfinite(duration) and duration > 0):
            raise ValueError('Player corpse animation does not match its model: ' + name)
        corpse = copy.deepcopy(prototype)
        corpse['attributes'] = dict(name=PREFIX + name, category='Mechanics - Props')
        corpse['children'] = [copy.deepcopy(art.child(prototype, kind)) for kind in
                              ('RagdollPropSimpleAnimationComponent', 'RenderComponent', 'MaterialComponent')]
        component = art.child(corpse, 'RagdollPropSimpleAnimationComponent')
        mapping = art.child(component, 'm_AnimationMap')
        entry = copy.deepcopy(mapping['children'][0])
        entry['attributes'] = dict(key='Start', value=start)
        mapping['children'] = [entry]
        art.child(component, 'm_ragdollFileName')['attributes']['value'] = ragdoll
        art.child(component, 'm_lifeTimeLimit')['attributes']['value'] = '-1.000000'
        art.child(component, 'm_activateRagdollOnSpawn')['attributes']['value'] = 'false'
        art.child(art.child(corpse, 'RenderComponent'), 'm_modelResourcePath')['attributes']['value'] = body
        result['children'].append(corpse)
        dependencies[name] = [(body, 'ModelResource'), (body, 'SkeletonLayoutResource'),
                              (ragdoll, 'HavokObjectResource'),
                              *((start, kind) for kind in art.KINDS)]
    if not dependencies:
        raise ValueError('No playable characters for corpse templates')
    return result, dependencies


def prepare(source, *stages):
    """Append inert templates and only the already-selected bodies' resources."""
    source.report('Preparing cooperative player bodies...')
    composed = {}
    for stage in stages:
        for changes in stage.values():
            composed.update(changes)
    def read(path):
        path = art.norm(path)
        return composed[path] if path in composed else source.read(path)
    characters = 'xml/actortemplates_characters.bxml'
    actors, dependencies = append(art.decode(read(characters)), read)
    result = {'packfile.pck': {characters: art.encode(actors)}, 'LvlSingl.pck': {}}
    paths = {path for path in source.metadata['sources']
             if path.startswith('levels/singleplayer/') and
             path.endswith(('_resources.bxml', '_resources_coop.bxml'))}
    paths.update(path for path in composed if path.startswith('levels/singleplayer/') and
                 '/streaming/' in path and '_resources' in path and path.endswith('.bxml'))
    def selected(present):
        deps = []
        for player_deps in dependencies.values():
            # The existing selection tables already choose which body models
            # reside in this area. Do not load the entire character roster.
            if (art.norm(player_deps[0][0]), 'ModelResource') in present:
                deps.extend(player_deps)
        return deps
    for completed, path in enumerate(sorted(paths), 1):
        source.cancel()
        adapted, added = art.append_resource_bytes(read(path), select=selected)
        if added:
            result['LvlSingl.pck'][path] = adapted
        if completed % 100 == 0 or completed == len(paths):
            source.report(f'Preparing cooperative player bodies: {completed}/{len(paths)} areas')
    return result
