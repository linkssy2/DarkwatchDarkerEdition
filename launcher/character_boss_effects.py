"""Attach original boss presentation to the existing player actor families.

The boss AI, attacks, collision, inventory and damage rules are never copied.
Only converted player bodies receive the aura; the original NPC stays intact.
"""
import copy
import hashlib
import struct

import character_assets as art
import character_boss as boss
import character_repaint as repaint
import character_spectral_hands as spectral_hands
import character_hand_seams as hand_seams


PLAYER = 'CassidySpectralPlayerTwo'
HANDS = 'CassidySpectralHands'
SOLO = 'CassidySpectralSolo'
SOLO_HANDS = 'CassidySpectralSoloHands'
HANDS_MODEL = 'characters/player_first/base_pov_cassidyspectral'
AURA = 'CassidySpectralAura'
AURA_SOURCE = 'FX/CassidyAura'
AURA_PLAYER = 'FX/CassidySpectralAura'
ARRAYS = ('m_name', 'm_particleEffectsName', 'm_locatorsName',
          'm_skeletonSpawned', 'm_spawnAtLoad', 'm_removeOnDeath')


def _param(component, name, value):
    art.child(component, name)['attributes']['value'] = value


def _aura(player, original_boss):
    source = art.child(original_boss, 'ParticleEmitterComponent')
    target = art.child(player, 'ParticleEmitterComponent')
    old = [art.child(source, name)['children'] for name in ARRAYS]
    rows = [art.child(target, name)['children'] for name in ARRAYS]
    visibility = art.child(target, 'm_viewVisibility')['children']
    if ({len(row) for row in old} != {7} or len({len(row) for row in rows}) != 1
            or len(visibility) != len(rows[0])):
        raise ValueError('Unexpected spectral particle array layout')
    values = [row[5]['attributes'].get('value') for row in old]
    if values != ['CassidyAura', 'CassidyAura', 'loc_bossQuaternary', '0', '1', '1']:
        raise ValueError('Original Cassidy aura differs')
    if any(row['attributes'].get('value') == AURA for row in rows[0]):
        raise ValueError('Spectral aura is already attached')
    for name, source_row, target_rows in zip(ARRAYS, old, rows):
        row = copy.deepcopy(source_row[5])
        if name in ('m_name', 'm_particleEffectsName'):
            row['attributes']['value'] = AURA
        target_rows.append(row)
    # Keep an actor's aura out of its own first-person camera while the other
    # split-screen player still sees it, like the original player power auras.
    visibility.append(dict(name='string', attributes={'value': 'ThirdPersonOnly'},
                           children=[], value=None))


def augment(prepared, original, references):
    """Return independent spectral copies of the accepted solo/co-op actors."""
    result = copy.deepcopy(prepared)
    original_boss = art.child(original, 'BossCassidy')
    paths = {ref['alias']: ref['output'][:-5] for ref in references}
    if not {'Multi', 'NotMulti', 'Horse', 'Vehicle', 'SoloMulti'} <= paths.keys():
        raise ValueError('Incomplete spectral animation maps')
    if any(row['attributes'].get('name') in (PLAYER, HANDS, SOLO, SOLO_HANDS)
           for row in result['children']):
        raise ValueError('Spectral actors already exist')
    for source_name, source_hands, name, hands_name, locator in (
            (art.PLAYER, art.HANDS, PLAYER, HANDS, boss.LOCATOR),
            (art.SOLO, art.SOLO_HANDS, SOLO, SOLO_HANDS, boss.SOLO_LOCATOR)):
        player = copy.deepcopy(art.child(prepared, source_name))
        hands = copy.deepcopy(art.child(prepared, source_hands))
        player['attributes']['name'] = name
        hands['attributes']['name'] = hands_name
        render = art.child(player, 'AlternativeModelsRenderComponent')
        _param(render, 'm_modelResourcePath', boss.MODEL)
        for row in art.child(render, 'm_alternativeModelPaths')['children']:
            row['attributes']['value'] = boss.MODEL
        # Wingless body proportions match the player: retain its bounds/culling.
        _param(art.child(player, 'InventoryComponent'), 'm_handActorName', hands_name)
        _param(art.child(player, 'LocatorAttachmentComponent'), 'm_locatorFileName', locator)
        animation = art.child(player, 'AnimationComponent')
        maps = art.child(animation, 'm_AnimationFiles')['children']
        if len(maps) != 4 or {row['attributes']['key'] for row in maps} != {
                'Multi', 'NotMulti', 'Horse', 'Vehicle'}:
            raise ValueError('Unexpected player animation map family')
        for row in maps:
            alias = row['attributes']['key']
            target = 'SoloMulti' if name == SOLO and alias == 'Multi' else alias
            if target not in paths:
                raise ValueError('Missing spectral solo map')
            row['attributes']['value'] = paths[target]
        glow = art.child(player, 'GlowComponent')
        # Both original actors already use special glow. Retain the player's
        # power behavior and exact defaults instead of forcing permanent glow.
        for field in ('m_alwaysGlow', 'm_specialGlow'):
            _param(glow, field, art.child(art.child(original_boss, 'GlowComponent'), field)['attributes']['value'])
        _aura(player, original_boss)
        hand_component = art.child(hands, 'PlayerHandsComponent')
        _param(hand_component, 'm_HandsModel', HANDS_MODEL)
        for row in art.child(hand_component, 'm_AlternativeHandsModels')['children']:
            row['attributes']['value'] = HANDS_MODEL
        _param(art.child(hands, 'LocatorAttachmentComponent'), 'm_locatorFileName', HANDS_MODEL)
        result['children'].extend((player, hands))
    return result


def register_aura(original):
    """Register the subdued player effect without changing the boss prototype."""
    result = copy.deepcopy(original)
    prototypes = art.named(result, 'ParticlePrototypes')
    matches = [row for row in prototypes['children']
               if row['attributes'].get('name') == 'CassidyAura']
    if (len(matches) != 1 or matches[0]['attributes'] != {
            'name': 'CassidyAura', 'pathname': AURA_SOURCE, 'hubs': 'GroundZero/GroundZero_A'}
            or any(row['attributes'].get('name') == AURA for row in prototypes['children'])):
        raise ValueError('Unexpected original Cassidy effect registration')
    alias = copy.deepcopy(matches[0])
    alias['attributes'] = {'name': AURA, 'pathname': AURA_PLAYER}
    prototypes['children'].append(alias)
    return result


def dependencies():
    return [(AURA_PLAYER, 'ParticleEffectResource'),
            ('FX/Textures/Effects/Particles', 'TexDictionaryResource'),
            (HANDS_MODEL, 'ModelResource'), (HANDS_MODEL, 'SkeletonLayoutResource'),
            (HANDS_MODEL, 'LocatorResource')]


def subtle_aura(original):
    """Reduce only the original aura's sprite dimensions and opacity."""
    if hashlib.sha256(original).hexdigest() != 'c851429cba9b4bed3d1a1358585b1a7817c2ed9ed16be7092a4734418fc895f6':
        raise ValueError('Unexpected original Cassidy aura')
    result = bytearray(original)
    count, = struct.unpack_from('<I', original, 0x20)
    table, = struct.unpack_from('<I', original, 0x38)
    for emitter in struct.unpack_from('<'+'I'*count, original, table):
        alpha, width, height = struct.unpack_from('<3I', original, emitter+0x94)
        dimensions = [struct.unpack_from('<f', original, curve+16)[0] for curve in (width, height)]
        # Native SEP curves feed billboard size and RGBA; cap the boss's huge flash at player scale.
        scale = min(0.4, 2.4/max(dimensions))
        for curve, factor in ((alpha, 0.25), (width, scale), (height, scale)):
            if struct.unpack_from('<I', original, curve)[0] & 7 != 1:
                raise ValueError('Unexpected Cassidy aura curve')
            for offset in (4, 16):  # Native evaluator: random range and constant value.
                value, = struct.unpack_from('<f', original, curve+offset)
                struct.pack_into('<f', result, curve+offset, value*factor)
    return bytes(result)


def prepare(read):
    """Derive private hands and the smaller player-only aura from the disc."""
    hands, _ = spectral_hands.bake(read(repaint.SOURCE), read(boss.BOSS+'.rx1'))
    hands, recipe = hand_seams.bake(hands)
    outputs = {HANDS_MODEL+'.rx1': hands, hand_seams.RECIPE: recipe}
    for extension in ('jlist', 'llist', 'bllist'):
        outputs[HANDS_MODEL+'.'+extension] = read(
            'characters/player_first/base_pov_chaz.'+extension)
    outputs['fx/effects.bxml'] = art.encode(register_aura(art.decode(read('fx/effects.bxml'))))
    outputs[AURA_PLAYER.lower()+'.sep'] = subtle_aura(read('fx/cassidyaura.sep'))
    read('fx/textures/effects/particles.rx1')
    return outputs
