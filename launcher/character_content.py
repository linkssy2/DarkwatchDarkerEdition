"""Build selectable-character resources from a verified, user-supplied disc.

The package contains conversion code, hashes and authored hand repaints only.
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
import character_roster
import revolver_content

CONTENT_REVISION = 'revolver-headshot-characters-v13'
CATALOG_SHA256 = '9b260c514454b533279be79dd5a29a47a659c05b72a7c9f687f3c4a53ea1d483'
CHARACTERS = 'xml/actortemplates_characters.bxml'
INSTALLED = {
    'packfile.pck': (143099169, 'ceacf60e64cafc0d676fa5b03a0a11289811ba29a1bd7adcfbcea6582827466f'),
    'LvlSingl.pck': (1792512951, '4897d56557d87584ed6804d9b4eab172ae959460e89f13715088bc0391d672b3'),
    'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285'),
}
REPAINT = {
    1024: '73ca5d8c1ab1451c8863ee91139678f28af63b992934090acf233433ebabb3a3',
    256: 'fee9d7abf2f7b0100937f576c0bd1564c71f06b0d07b9ece14300d51c8f5113f',
}
TALA_REPAINT = {
    1024: '0a129bc58ffe9639b0b9ff62c670380c36951d203f697aa7505a383fcb9b02b2',
    256: '2036c65069474ce6cab9bcba9db9396e59a3146416f90b1df5d629c0e75d479d',
}


def checked(raw, pin, label):
    if len(raw) != pin['size'] or pck.sha(raw) != pin['sha256']:
        raise ValueError(f'Character conversion verification failed: {label}')
    return raw


def checked_file(path, pin, cancel):
    if path.stat().st_size != pin['size']:
        raise ValueError(f'Character conversion verification failed: {path.name}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            cancel()
            digest.update(block)
    if digest.hexdigest() != pin['sha256']:
        raise ValueError(f'Character conversion verification failed: {path.name}')


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
    def __init__(self, streams, metadata, cancel, progress=lambda message: None):
        self.streams, self.metadata, self.cancel = streams, metadata, cancel
        self.progress = progress

    def report(self, message):
        self.cancel()
        self.progress(message)
        self.cancel()

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
    outputs, tables, solo_clips = character_animation.prepare(
        read, art.decode, art.encode, cancel=source.cancel,
        progress=lambda message: source.report('Preparing Cassidy ' + message))
    source.report('Preparing Cassidy character and hands...')
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
    for completed, path in enumerate(resources, 1):
        solo = not path.endswith('_coop.bxml')
        outputs[path], _ = art.append_resource_bytes(read(path), dependencies[solo])
        bank_path = path.replace('/streaming/', '/resources/audio/').replace('_resources', '')[:-5]+'.bblf'
        old = read(bank_path)
        tree, changed = (art.solo_bank if solo else art.append_voice_bank)(art.decode(old))
        outputs[bank_path] = art.encode(tree) if changed else old
        if completed % 10 == 0 or completed == len(resources):
            source.report(f'Preparing Cassidy campaign areas: {completed}/{len(resources)}')
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
    source.report('Preparing Jericho co-op character...')
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
        extension['LvlSingl.pck'][variant(path, 'jericho')], _ = art.append_resource_bytes(read(path), deps)
        extension['LvlSingl.pck'][variant(path)], _ = art.append_resource_bytes(outputs[path], deps)
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
    read_count = 0
    def spectral_read(path):
        nonlocal read_count
        data = read(path)
        read_count += 1
        if read_count % 25 == 0:
            source.report(f'Preparing Spectral Cassidy: {read_count} resources processed')
        return data
    source.report('Preparing Spectral Cassidy model and animations...')
    outputs, references = character_boss.prepare(spectral_read)
    prepared = art.decode(extension['packfile.pck'][CHARACTERS])
    outputs[CHARACTERS] = art.encode(character_boss_effects.augment(prepared, art.decode(read(CHARACTERS)), references))
    source.report('Preparing Spectral Cassidy hands and effects...')
    effects = character_boss_effects.prepare(read)
    source.cancel()
    if outputs.keys() & effects.keys():
        raise ValueError('Duplicate spectral presentation resource')
    outputs.update(effects)
    result = {'packfile.pck': outputs, 'LvlSingl.pck': {}}
    dependencies = {solo: spectral_dependencies(read, references, solo) for solo in (False, True)}
    resources = sorted(path for path in source.metadata['sources'] if path.startswith('levels/singleplayer/')
                       and path.endswith(('_resources.bxml', '_resources_coop.bxml')))
    if len(resources) != 102:
        raise ValueError('Incomplete spectral hub coverage')
    for completed, path in enumerate(resources, 1):
        source.cancel()
        target = variant(path)
        raw = extension['LvlSingl.pck'].get(target, groups['LvlSingl.pck'][target])
        result['LvlSingl.pck'][variant(path, 'cassidy_spectral')], _ = art.append_resource_bytes(
            raw, dependencies[not path.endswith('_coop.bxml')])
        if completed % 10 == 0 or completed == len(resources):
            source.report(f'Preparing Spectral Cassidy campaign areas: {completed}/{len(resources)}')
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
        source = Source(streams, metadata, cancel, progress)
        groups, extension, spectral = build_resources(source, payload)
        def tala_pixels(size):
            data = (payload / 'character-art' / f'tala-hands-{size}.dds').read_bytes()
            if pck.sha(data) != TALA_REPAINT[size]:
                raise ValueError('Tala hand repaint changed')
            return data
        roster, _ = character_roster.prepare(source, groups, extension, spectral,
                                             tala_variants=True, tala_pixels=tala_pixels)
        revolver = revolver_content.prepare(source, groups, extension, spectral, roster)
    with tempfile.TemporaryDirectory(prefix='.characters-', dir=assets) as temporary:
        staged = Path(temporary)
        for name in INSTALLED:
            cancel()
            progress('Preparing character resources...')
            current = assets / name
            checked_file(current, metadata['originals'][name], cancel)
            if name == 'packfile.pck':
                current = staged / (name + '.base')
                current.write_bytes(bonus_content.patch_pack((assets / name).read_bytes()))
            # Keep every intermediate proof on disk instead of retaining several
            # multi-gigabyte archive copies in memory.
            stages = ((groups[name], 'v7_archives'),
                      (extension.get(name), 'base_archives'),
                      (spectral.get(name), 'spectral_archives'),
                      (roster.get(name) or None, 'roster_archives'))
            for index, (changes, proof) in enumerate(stages):
                cancel()
                if changes is not None:
                    target = staged / f'{name}.{index}'
                    pck.compose_file(current, changes, target, cancel)
                    previous, current = current, target
                    if previous.parent == staged:
                        previous.unlink()
                checked_file(current, metadata[proof][name], cancel)
            if revolver.get(name):
                if name == 'LvlSingl.pck':
                    # Keep every intermediate proof, but write each final chapter
                    # table once. Appending its superseded copies crosses 2 GiB.
                    final = {}
                    for stage in (groups, extension, spectral, roster, revolver):
                        final.update(stage.get(name, {}))
                    source, changes = assets / name, final
                    checked_file(source, metadata['originals'][name], cancel)
                else:
                    source, changes = current, revolver[name]
                target = staged / (name + '.final')
                pck.compose_file(source, changes, target, cancel)
                if current.parent == staged:
                    current.unlink()
                current = target
            checked_file(current, metadata['installed'][name], cancel)
            os.replace(current, staged / name)
        # No original in this stage is replaced until all copies pass their pins.
        cancel()
        for name in INSTALLED:
            os.replace(staged / name, assets / name)
