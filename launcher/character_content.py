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
import character_cinematic
import character_repaint
import character_roster
import character_tala
import revolver_content
import player_corpses
import third_person_animation
import enemy_blood

BASE_REVISION = 'character-reload-right-wrist-v36'
CONTENT_REVISION = 'character-campaign-feedback-v37'
CATALOG_SHA256 = 'dbb39545b03e60c701f8f9464764e2f216572f7f7b2800c7b76ab0646c321c87'
CHARACTERS = 'xml/actortemplates_characters.bxml'
BASE_INSTALLED = {
    'packfile.pck': (180615493, 'b65720e8b43c3d938d296f0a2a617c747e233b9670096d65a0b88ef5b84dc50a'),
    'LvlSingl.pck': (2399384131, '097bade9fad236a7e5e7f5cab83985368df3aba1246e1dd1ca0592bcfcc9d860'),
    'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285'),
}
INSTALLED = {
    'packfile.pck': (199441106, 'e19c6eeb1494bb7ede1f9976f0d402c970be44ae7da1a2754fd063a2b2e48257'),
    'LvlSingl.pck': (3018752579, '55e931aa28853a38ad8c8072140b4cfcb4c30e6c9e4c27eb851d4d142b727180'),
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
    if result['content_revision'] != BASE_REVISION or result['schema_version'] != 1:
        raise ValueError('Unsupported character conversion revision')
    if {name: (pin['size'], pin['sha256']) for name, pin in result['installed'].items()} != BASE_INSTALLED:
        raise ValueError('Character conversion output pins differ')
    result['campaign_base'] = dict(content_revision=result['content_revision'], installed=result['installed'])
    result['content_revision'] = CONTENT_REVISION
    result['installed'] = {name: dict(size=size, sha256=digest) for name, (size, digest) in INSTALLED.items()}
    return result


def base_catalog(metadata):
    result = dict(metadata)
    result['content_revision'] = metadata['campaign_base']['content_revision']
    result['installed'] = metadata['campaign_base']['installed']
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
        progress=lambda message: source.report('Preparing Cassidy ' + message),
        arm_maps=character_animation.player_arm_parameters(read, art.decode,
            character_animation.frames(read(character_animation.CASSIDY)),
            'characters/cassidy/base_cassidy.bllist'),
        dual_arm_maps=character_animation.player_arm_parameters(read, art.decode,
            character_animation.frames(read(character_animation.CASSIDY)),
            'characters/cassidy/base_cassidy.bllist', dual=True,
            dual_locators={basis: art.encode(adapt(art.decode(read(path)), art.decode(read('characters/cassidy/base_cassidy.bllist'))))
                for basis, path, adapt in (
                    (character_animation.CHAZ, 'characters/player_third/base_chaz.bllist', art.solo_locators),
                    (character_animation.STORM, 'characters/multiplayer/base_dwstormtrooper_coop.bllist', art.adapt_locators))}))
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


def _discard_replaced_chapters(latest, *previous):
    # Later chapter stages read the latest resource for each path. The final
    # archive uses that same merge, so release superseded multi-GB tables now.
    for stage in previous:
        chapters = stage.get('LvlSingl.pck', {})
        for path in latest.get('LvlSingl.pck', {}):
            chapters.pop(path, None)


def prepare(assets, payload, cancel=lambda: None, progress=lambda message: None, *, previous_assets=None):
    """Create verified copies inside a caller-owned, uncommitted install stage."""
    assets, payload = Path(assets), Path(payload)
    final_metadata = catalog(payload)
    metadata = base_catalog(final_metadata)
    def finalize(staged):
        import character_campaign
        outputs = character_campaign.build(staged, assets, payload, cancel, progress)
        for name, path in outputs.items():
            checked_file(path, final_metadata['installed'][name], cancel)
        for name, path in outputs.items():
            os.replace(path, staged / name)
    if previous_assets is not None:
        import character_update
        if character_update.try_reuse_base(assets, previous_assets, metadata, cancel, progress, finalize):
            return
        if character_update.try_prepare(assets, payload, previous_assets, metadata, cancel, progress, finalize=finalize):
            return
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
        _discard_replaced_chapters(revolver, groups, extension, spectral, roster)
        corpses = player_corpses.prepare(source, groups, extension, spectral, roster, revolver)
        _discard_replaced_chapters(corpses, groups, extension, spectral, roster, revolver)
        fanning = {'packfile.pck': revolver_content.prepare_fanning(
            source, groups, extension, spectral, roster, revolver, corpses)}
        cinematic = character_cinematic.prepare(
            source, groups, extension, spectral, roster, revolver, corpses, fanning)
        _discard_replaced_chapters(cinematic, groups, extension, spectral, roster, revolver, corpses, fanning)
        third_person = third_person_animation.prepare(
            source, groups, extension, spectral, roster, revolver, corpses, fanning, cinematic)
        _discard_replaced_chapters(third_person, groups, extension, spectral, roster, revolver, corpses, fanning, cinematic)
        third_person['packfile.pck'][CHARACTERS] = art.encode(enemy_blood.append(
            art.decode(third_person['packfile.pck'][CHARACTERS])))
        source.report('Finishing Boss Tala presentation...')
        presentation = {'packfile.pck': {character_tala.MODEL + '.rx1': character_tala.presentation(
            roster['packfile.pck'][character_tala.MODEL + '.rx1'],
            spectral['packfile.pck'][character_boss.MODEL + '.rx1'])}}
        source.cancel()
    with tempfile.TemporaryDirectory(prefix='.characters-', dir=assets) as temporary:
        staged = Path(temporary)
        for archive_index, name in enumerate(INSTALLED, 1):
            cancel()
            progress(f'Preparing character archive {archive_index}/{len(INSTALLED)}: {name}')
            current = assets / name
            checked_file(current, metadata['originals'][name], cancel)
            if name == 'LvlSingl.pck':
                # The final chapter archive is composed from the original, not
                # from superseded intermediate tables. Its exact installed pin
                # verifies every final resource without writing those copies.
                changes = {}
                for stage in (groups, extension, spectral, roster, revolver, corpses, fanning, cinematic, third_person, presentation):
                    changes.update(stage.get(name, {}))
                target = staged / (name + '.final')
                progress(f'Writing updated animations: {len(changes):,} resources in {name}')
                pck.compose_file(current, changes, target, cancel)
                current = target
            if name == 'packfile.pck':
                current = staged / (name + '.base')
                current.write_bytes(bonus_content.patch_pack((assets / name).read_bytes()))
            # Keep every intermediate proof on disk instead of retaining several
            # multi-gigabyte archive copies in memory.
            stages = () if name == 'LvlSingl.pck' else ((groups[name], 'v7_archives'),
                      (extension.get(name), 'base_archives'),
                      (spectral.get(name), 'spectral_archives'),
                      (roster.get(name) or None, 'roster_archives'))
            for index, (changes, proof) in enumerate(stages):
                cancel()
                if changes is not None:
                    progress(f'Writing {name}: preparation step {index + 1}/{len(stages) + 1}')
                    target = staged / f'{name}.{index}'
                    pck.compose_file(current, changes, target, cancel)
                    previous, current = current, target
                    if previous.parent == staged:
                        previous.unlink()
                checked_file(current, metadata[proof][name], cancel)
            if name != 'LvlSingl.pck' and (revolver.get(name) or corpses.get(name) or fanning.get(name) or cinematic.get(name) or third_person.get(name) or presentation.get(name)):
                changes = dict(revolver.get(name, {}))
                changes.update(corpses.get(name, {}))
                changes.update(fanning.get(name, {}))
                changes.update(cinematic.get(name, {}))
                changes.update(third_person.get(name, {}))
                changes.update(presentation.get(name, {}))
                source = current
                target = staged / (name + '.final')
                progress(f'Writing updated animations: {len(changes):,} resources in {name}')
                pck.compose_file(source, changes, target, cancel)
                if current.parent == staged:
                    current.unlink()
                current = target
            progress(f'Verifying completed character archive {archive_index}/{len(INSTALLED)}: {name}')
            checked_file(current, metadata['installed'][name], cancel)
            os.replace(current, staged / name)
        # No original in this stage is replaced until all copies pass their pins.
        finalize(staged)
        cancel()
        for name in INSTALLED:
            os.replace(staged / name, assets / name)
