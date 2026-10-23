"""Build selectable-character resources from a verified, user-supplied disc.

The package contains conversion code, hashes and an authored hand repaint only.
Original archives stay intact until all three converted copies pass their pins.
The caller supplies an isolated installation stage and commits it afterwards.
"""
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

import bonus_content
import character_animation
import character_archive as pck
import character_assets as art
import character_boss
import character_boss_effects
import character_repaint

CONTENT_REVISION = 'wartrain-splitter-characters-v2'
CATALOG_SHA256 = 'fc0d0ee90f780cd61d7caa15b4605bcfa46b3dd27dbc82be077d3a97412c6946'
CHARACTERS = 'xml/actortemplates_characters.bxml'
INSTALLED = {
    'packfile.pck': (120732531, '6a17c34ba180c839350297725248887c17b3b7540870978ee2b3ebb8b7cd778d'),
    'LvlSingl.pck': (258077411, 'ebf982c749184e05f7ed3342ce108d063e2e1c92611b19245d3c1871fb24c216'),
    'audio.pck': (137958865, 'f148f43fbaeedbaa3ba6465fd009a802681900dafb24de671dea1c2ffaa67c01'),
}
REPAINT = {
    1024: '73ca5d8c1ab1451c8863ee91139678f28af63b992934090acf233433ebabb3a3',
    256: 'fee9d7abf2f7b0100937f576c0bd1564c71f06b0d07b9ece14300d51c8f5113f',
}


def checked(raw, pin, label):
    if len(raw) != pin['size'] or pck.sha(raw) != pin['sha256']:
        raise ValueError(f'Character conversion verification failed: {label}')
    return raw


def catalog(payload):
    path = payload / 'character-catalog.json'
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Character conversion catalog is too large')
    raw = path.read_bytes()
    if pck.sha(raw) != CATALOG_SHA256:
        raise ValueError('Unsupported character conversion catalog')
    result = json.loads(raw)
    if result['content_revision'] != CONTENT_REVISION or result['schema_version'] != 1:
        raise ValueError('Unsupported character conversion revision')
    if {name: (pin['size'], pin['sha256']) for name, pin in result['installed'].items()} != INSTALLED:
        raise ValueError('Character conversion output pins differ')
    return result


class Source:
    """Bounded seeks; every resource read must match its original-disc identity."""
    def __init__(self, streams, metadata, cancel):
        self.streams, self.metadata, self.cancel = streams, metadata, cancel

    def read(self, path):
        self.cancel()
        path = pck.canonical(path)
        pin = self.metadata['sources'].get(path)
        if pin is None:
            raise ValueError(f'Unlisted character resource: {path}')
        stream = self.streams[pin['archive']]
        size = self.metadata['originals'][pin['archive']]['size']
        if pin['offset'] < 0 or pin['size'] < 0 or pin['offset'] + pin['size'] > size:
            raise ValueError('Character resource lies outside its archive')
        stream.seek(pin['offset'])
        return checked(stream.read(pin['size']), pin, path)


def variant(path, suffix='cassidy'):
    stem, extension = pck.canonical(path).rsplit('.', 1)
    if not stem.startswith('levels/singleplayer/') or extension not in ('bxml', 'bblf'):
        raise ValueError('Unsupported character preload path')
    return f'{stem}_{suffix}.{extension}'


def build_resources(source, payload):
    """Produce the accepted presentation-only resources, checking every output."""
    read, metadata = source.read, source.metadata
    outputs, tables, solo_clips = character_animation.prepare(read, art.decode, art.encode)
    original = art.decode(read(CHARACTERS))
    bank = art.decode(read('audio/cassidy/cassidy.babf'))
    cues = {art.named(row, 'id')['value'] for row in art.named(bank, 'prototypes')['children']}
    actors = art.candidate(original, cues, True)
    hands = copy.deepcopy(art.child(actors, art.HANDS))
    hands['attributes']['name'] = art.SOLO_HANDS
    actors['children'].extend([art.solo_actor(original), hands])
    outputs[CHARACTERS] = art.encode(actors)
    npc = art.decode(read('characters/cassidy/base_cassidy.bllist'))
    coop = art.decode(read('characters/multiplayer/base_dwstormtrooper_coop.bllist'))
    chaz = art.decode(read('characters/player_third/base_chaz.bllist'))
    outputs[art.norm(art.LOCATOR)+'.bllist'] = art.encode(art.adapt_locators(coop, npc))
    outputs[art.norm(art.SOLO_LOCATOR)+'.bllist'] = art.encode(art.solo_locators(chaz, npc))
    def pixels(size):
        data = (payload / 'character-art' / f'cassidy-hands-{size}.dds').read_bytes()
        if pck.sha(data) != REPAINT[size]:
            raise ValueError('Character hand repaint changed')
        return data
    outputs[art.norm(art.HANDS_MODEL)+'.rx1'] = character_repaint.repaint(read(character_repaint.SOURCE), pixels)
    for extension in ('jlist', 'llist', 'bllist'):
        outputs[art.norm(art.HANDS_MODEL)+'.'+extension] = read('characters/player_first/base_pov_chaz.'+extension)
    resources = sorted(path for path in metadata['sources'] if path.startswith('levels/singleplayer/')
                       and path.endswith(('_resources.bxml', '_resources_coop.bxml')))
    if len(resources) != 102:
        raise ValueError('Incomplete character hub coverage')
    dependencies = {solo: art.mode_dependencies(tables, solo, solo_clips) for solo in (False, True)}
    for path in resources:
        solo = not path.endswith('_coop.bxml')
        tree, _ = art.append_resources(art.decode(read(path)), dependencies[solo])
        outputs[path] = art.encode(tree)
        bank_path = path.replace('/streaming/', '/resources/audio/').replace('_resources', '')[:-5]+'.bblf'
        old = read(bank_path)
        tree, changed = (art.solo_bank if solo else art.append_voice_bank)(art.decode(old))
        outputs[bank_path] = art.encode(tree) if changed else old
    if set(outputs) != set(metadata['v7_outputs']):
        raise ValueError('Character conversion resource set differs')
    for name, data in outputs.items():
        checked(data, metadata['v7_outputs'][name], name)
    groups = {name: {} for name in INSTALLED}
    for name, data in outputs.items():
        owner = metadata['sources'].get(name, {}).get('archive', 'packfile.pck')
        target = variant(name) if name.startswith('levels/singleplayer/') else name
        groups[owner][target] = data

    # Preserve the original CoOpChaz mechanics while offering original Jericho art.
    clone = art.jericho_actor(original)
    actors['children'].append(clone)
    joints = set(read('characters/player_third/base_chaz.jlist').decode('ascii').split())
    extension = {'packfile.pck': {
        CHARACTERS: art.encode(actors),
        art.norm(art.JERICHO_LOCATOR)+'.bllist': art.encode(art.jericho_locators(chaz, coop, joints)),
    }, 'LvlSingl.pck': {}}
    deps = [('Characters/Player_Third/base_chaz', kind) for kind in ('ModelResource', 'SkeletonLayoutResource')]
    deps.append((art.JERICHO_LOCATOR, 'LocatorResource'))
    animation = art.child(clone, 'AnimationComponent')
    deps.append((art.child(animation, 'm_ragdollFileName')['attributes']['value'], 'HavokObjectResource'))
    for row in art.child(animation, 'm_AnimationFiles')['children']:
        name = row['attributes']['value']
        deps.append((name, 'AnimatedCharacterResource'))
        for node in art.walk(art.decode(read(name+'.bxml'))):
            if node['name'] == 'KeyframeAnimation':
                clip = art.norm(node['attributes']['Name'])
                deps.extend((clip, kind) for kind in art.KINDS)
    hands = art.child(art.child(original, 'ChazHands'), 'PlayerHandsComponent')
    hand_model = art.child(hands, 'm_HandsModel')['attributes']['value']
    deps.extend((hand_model, kind) for kind in ('ModelResource', 'SkeletonLayoutResource'))
    deps.extend([('Characters/Player_First/ChazHands', 'AnimatedCharacterResource'),
                 ('Characters/Player_First/BASE_POV_Chaz', 'LocatorResource')])
    unique = {(art.norm(name), kind): (name, kind) for name, kind in deps}
    deps = [unique[key] for key in sorted(unique)]
    for path in resources:
        if not path.endswith('_coop.bxml'):
            continue
        tree, _ = art.append_resources(art.decode(read(path)), deps)
        extension['LvlSingl.pck'][variant(path, 'jericho')] = art.encode(tree)
        tree, _ = art.append_resources(art.decode(outputs[path]), deps)
        extension['LvlSingl.pck'][variant(path)] = art.encode(tree)
    spectral = build_spectral(source, groups, extension)
    return groups, extension, spectral


def spectral_dependencies(read, references, solo):
    """Keep the new body's residency separate from living Cassidy and Jericho."""
    deps = [(character_boss.MODEL, kind) for kind in ('ModelResource', 'SkeletonLayoutResource')]
    deps.extend([(character_boss.SOLO_LOCATOR if solo else character_boss.LOCATOR, 'LocatorResource'),
                 (art.RAGDOLL, 'HavokObjectResource'),
                 ('Characters/Player_First/ChazHands', 'AnimatedCharacterResource')])
    deps.extend(character_boss_effects.dependencies())
    for table in references:
        if table['alias'] == ('Multi' if solo else 'SoloMulti'):
            continue
        deps.append((table['output'][:-5], 'AnimatedCharacterResource'))
        deps.extend((clip['output'][:-5], kind) for clip in table['clips'] for kind in art.KINDS)
    for node in art.walk(art.decode(read('characters/player_first/chazhands.bxml'))):
        if node['name'] == 'KeyframeAnimation':
            deps.extend((node['attributes']['Name'], kind) for kind in art.KINDS)
    unique = {(art.norm(name), kind): (name, kind) for name, kind in deps}
    return [unique[key] for key in sorted(unique)]


def build_spectral(source, groups, extension):
    """Add boss presentation without changing the verified living-player resources."""
    read = source.read
    outputs, references = character_boss.prepare(read)
    prepared = art.decode(extension['packfile.pck'][CHARACTERS])
    outputs[CHARACTERS] = art.encode(character_boss_effects.augment(prepared, art.decode(read(CHARACTERS)), references))
    effects = character_boss_effects.prepare(read)
    if outputs.keys() & effects.keys():
        raise ValueError('Duplicate spectral presentation resource')
    outputs.update(effects)
    result = {'packfile.pck': outputs, 'LvlSingl.pck': {}}
    dependencies = {solo: spectral_dependencies(read, references, solo) for solo in (False, True)}
    resources = sorted(path for path in source.metadata['sources'] if path.startswith('levels/singleplayer/')
                       and path.endswith(('_resources.bxml', '_resources_coop.bxml')))
    if len(resources) != 102:
        raise ValueError('Incomplete spectral hub coverage')
    for path in resources:
        target = variant(path)
        raw = extension['LvlSingl.pck'].get(target, groups['LvlSingl.pck'][target])
        tree, _ = art.append_resources(art.decode(raw), dependencies[not path.endswith('_coop.bxml')])
        result['LvlSingl.pck'][variant(path, 'cassidy_spectral')] = art.encode(tree)
    # The complete composed archives are checked before the installation is committed.
    return result


def prepare(assets, payload, cancel=lambda: None, progress=lambda message: None):
    """Create verified copies inside a caller-owned, uncommitted install stage."""
    assets, payload = Path(assets), Path(payload)
    metadata = catalog(payload)
    with ExitStack() as stack:
        streams = {}
        for name, pin in metadata['originals'].items():
            cancel()
            stream = stack.enter_context((assets / name).open('rb'))
            if os.fstat(stream.fileno()).st_size != pin['size'] or hashlib.file_digest(stream, 'sha256').hexdigest() != pin['sha256']:
                raise ValueError(f'Unsupported original character archive: {name}')
            streams[name] = stream
        progress('Preparing selectable characters...')
        groups, extension, spectral = build_resources(Source(streams, metadata, cancel), payload)
    with tempfile.TemporaryDirectory(prefix='.characters-', dir=assets) as temporary:
        staged = Path(temporary)
        for name in INSTALLED:
            cancel()
            progress('Preparing character resources...')
            raw = checked((assets / name).read_bytes(), metadata['originals'][name], name)
            if name == 'packfile.pck':
                raw = bonus_content.patch_pack(raw)
            raw = pck.compose(raw, groups[name])
            checked(raw, metadata['v7_archives'][name], name)
            cancel()
            if name in extension:
                raw = pck.compose(raw, extension[name])
            checked(raw, metadata['base_archives'][name], name)
            cancel()
            if name in spectral:
                raw = pck.compose(raw, spectral[name])
            checked(raw, metadata['installed'][name], name)
            (staged / name).write_bytes(raw)
            del raw
        # No original in this stage is replaced until all copies pass their pins.
        cancel()
        for name in INSTALLED:
            os.replace(staged / name, assets / name)
