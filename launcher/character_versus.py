"""Prepare full-roster versus presentations from the verified local game data."""
import copy
from contextlib import ExitStack
import mmap
from pathlib import Path

import character_archive as archive
import character_assets as art
import character_boss_effects
import character_roster

ACTORS = ('JerichoVersus', 'CassidySolo', 'CassidySpectralSolo',
          'CivilianJerichoSolo', 'TrooperSolo', 'BlueTrooperSolo',
          'RedTrooperSolo', 'TalaSolo', 'VampireTalaSolo', 'BossTalaSolo')


def character_dependencies(read, cancel=lambda: None):
    actors = art.decode(read(character_roster.CHARACTERS))
    if any(row['attributes'].get('name') == ACTORS[0] for row in actors['children']):
        raise ValueError('Versus character already prepared')
    jericho = copy.deepcopy(art.child(actors, 'JerichoCoop'))
    jericho['attributes']['name'] = ACTORS[0]
    render = art.child(jericho, 'AlternativeModelsRenderComponent')
    model = art.child(render, 'm_modelResourcePath')['attributes']['value']
    for row in art.child(render, 'm_alternativeModelPaths')['children']:
        row['attributes']['value'] = model
    actors['children'].append(jericho)
    families = {}
    for name in ACTORS:
        cancel()
        actor = art.child(actors, name)
        hands = art.child(art.child(actor, 'InventoryComponent'), 'm_handActorName')['attributes']['value']
        dependencies = character_roster._dependencies(actor, art.child(actors, hands), read)
        if name == 'CassidySpectralSolo':
            dependencies.extend(character_boss_effects.dependencies())
        families[name] = character_roster._unique(dependencies)
    return actors, families


def resources(read, multiplayer_paths, read_multiplayer, read_audio, cancel=lambda: None):
    actors, families = character_dependencies(read, cancel)
    dependencies = character_roster._unique(dep for family in families.values() for dep in family)
    paths = sorted(path for path in multiplayer_paths if path.startswith('levels/multiplayer/')
                   and path.endswith('_resources.bxml') and '/streaming/' in path)
    if len(paths) != 26:
        raise ValueError('Incomplete original versus map coverage')
    pack = {character_roster.CHARACTERS: art.encode(actors)}
    audio = {}
    for path in paths:
        cancel()
        # One shared roster per map avoids hundreds of four-player combination copies.
        pack[path[:-5] + '_versus.bxml'], _ = art.append_resource_bytes(read_multiplayer(path), dependencies)
        bank = path.replace('/streaming/', '/resources/audio/').replace('_resources.bxml', '.bblf')
        audio[bank[:-5] + '_versus.bblf'] = art.encode(
            character_roster._voice_banks(art.decode(read_audio(bank)), (1, 7)))
    return pack, audio


def build(pack_path, audio_path, original_multiplayer, cancel=lambda: None):
    """Write separate outputs; the caller must verify pins before committing them."""
    with ExitStack() as stack:
        def reader(path):
            stream = stack.enter_context(Path(path).open('rb'))
            raw = stack.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ))
            entries = {row['name']: row for row in archive.read(raw)['entries']}
            def read(name):
                cancel()
                row = entries[archive.canonical(name)]
                return raw[row['offset']:row['offset'] + row['size']]
            return entries, read
        _, read = reader(pack_path)
        paths, multiplayer = reader(original_multiplayer)
        _, audio = reader(audio_path)
        pack_changes, audio_changes = resources(read, paths, multiplayer, audio, cancel)
        outputs = {'packfile.pck': Path(str(pack_path) + '.versus'),
                   'audio.pck': Path(str(audio_path) + '.versus')}
        archive.compose_file(pack_path, pack_changes, outputs['packfile.pck'], cancel)
        archive.compose_file(audio_path, audio_changes, outputs['audio.pck'], cancel)
    return outputs
