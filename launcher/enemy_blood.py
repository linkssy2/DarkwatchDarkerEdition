"""Reuse the native player blood-stain component for ordinary enemy templates."""
import copy

import character_assets as art


TARGETS = (
    'Kegger', 'Reaper', 'CoffinReaper', 'SuperReaper', 'TomahawkBrave',
    'BowBrave', 'Gunslinger', 'Turretslinger', 'Rifleman', 'Banshee',
    'SuperBanshee', 'UndeadRyder', 'DarkRyder',
)


def append(actors):
    """Keep native projection, the shared ten-stain pool and original damage rules.

    Solo and cooperative missions use these same enemy templates. Oozer-family
    materials, bosses, friendlies and player/corpse variants remain unchanged.
    """
    result = copy.deepcopy(actors)
    prototype = art.child(art.child(result, 'Chaz'), 'GoreComponent')
    if prototype != art.child(art.child(result, 'CoOpChaz'), 'GoreComponent') or prototype['children']:
        raise ValueError('Expected the native default player blood-stain component')
    for name in TARGETS:
        actor = art.child(result, name)
        for kind in ('HealthComponent', 'DismemberDamageableComponent'):
            art.child(actor, kind)
        material = art.child(art.child(actor, 'MaterialComponent'), 'm_materialName')
        if material['attributes']['value'] != 'bd_enemy_default':
            raise ValueError('Unexpected blood-stain enemy material: ' + name)
        existing = [c for c in actor['children'] if c['attributes'].get('name') == 'GoreComponent']
        if existing and existing != [prototype]:
            raise ValueError('Conflicting blood-stain component: ' + name)
        if not existing:
            actor['children'].append(copy.deepcopy(prototype))
    return result
