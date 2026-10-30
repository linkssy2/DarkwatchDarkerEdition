"""Roster routes, voice residency and original first-person attachment contracts."""
import copy
import itertools
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import character_assets as art
import character_roster as roster
import character_archive as archive


def layout(*banks):
    return dict(name='root', attributes={}, value=None, children=[
        dict(name='banks', attributes={}, value=None,
             children=[art.element(bank) for bank in banks])])


def locators(**transforms):
    return dict(name='locator_list', attributes={}, value=None, children=[
        dict(name='locator', attributes=dict(name=name, parent='test_bone',
             pos='0, 0, 0', rot=rotation, scale='1, 1, 1'), children=[], value=None)
        for name, rotation in transforms.items()])


class RosterTests(unittest.TestCase):
    def test_trooper_uses_body_grip_in_both_player_locator_schemas(self):
        solo = locators(loc_RightHand='solo grip', loc_Head='solo head',
                        loc_Private='solo attachment')
        coop = locators(loc_RightHand='co-op grip', loc_Head='co-op head',
                        loc_RightWeapon='co-op holster')
        multiplayer = locators(loc_RightHand='sideways grip', loc_Head='trooper head',
                               loc_Unused='not part of player schema')
        before = copy.deepcopy((solo, coop, multiplayer))
        for player in (solo, coop):
            with self.subTest(player=player):
                result = roster._trooper_locators(player, multiplayer, coop)
                self.assertEqual([row['attributes']['name'] for row in result['children']],
                                 [row['attributes']['name'] for row in player['children']])
                self.assertEqual(art.child(result, 'loc_RightHand'), art.child(coop, 'loc_RightHand'))
                self.assertEqual(art.child(result, 'loc_Head'), art.child(multiplayer, 'loc_Head'))
                for row in player['children']:
                    if row['attributes']['name'] not in ('loc_RightHand', 'loc_Head'):
                        self.assertEqual(art.child(result, row['attributes']['name']), row)
                art.child(result, 'loc_RightHand')['attributes']['rot'] = 'changed result'
        self.assertEqual((solo, coop, multiplayer), before)

    def test_trooper_rejects_missing_authored_grip(self):
        with self.assertRaises(ValueError):
            roster._trooper_locators(locators(loc_RightHand='solo'),
                                     locators(loc_RightHand='multiplayer'), locators(loc_Head='head'))

    def test_routes_are_bounded_and_pair_order_independent(self):
        pairs = [pair for pair in itertools.combinations_with_replacement(range(10), 2)
                 if max(pair) >= 3]
        self.assertEqual(len({roster.suffix(pair) for pair in pairs}), 49)
        for pair in pairs:
            self.assertEqual(roster.suffix(pair), roster.suffix(pair[::-1]))
        self.assertEqual(roster.suffix((7,)), 'roster_7')
        for invalid in ((), (0,), (1, 2), (10,), (-1, 7), (True, 7), (3.0,), (3, 4, 5)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                roster.suffix(invalid)

    def test_voice_residency_preserves_npc_alias_and_input(self):
        original = layout(dict(name='VOICE', file='CHAPTER_VOICE'),
                          dict(name='TALA', file='TALA', preload='false'))
        snapshot = copy.deepcopy(original)
        converted = roster._voice_banks(original, (1, 7))
        banks = [art.fields(row) for row in art.named(converted, 'banks')['children']]
        self.assertEqual(banks, [dict(name='VOICE', file='CHAPTER_VOICE'),
                                dict(name='TALA', file='TALA', preload='true'),
                                dict(name='CASSIDY', file='CASSIDY')])
        self.assertEqual(original, snapshot)
        self.assertEqual(roster._voice_banks(converted, (1, 7)), converted)

    def test_unselected_voice_banks_stay_untouched(self):
        original = layout(dict(name='TALA', file='TALA', preload='false'))
        self.assertEqual(roster._voice_banks(original, (3, 4)), original)
        spectral = roster._voice_banks(layout(), (2, 6))
        self.assertEqual([art.fields(row) for row in art.named(spectral, 'banks')['children']],
                         [dict(name='CASSIDY', file='CASSIDY')])

    def test_selected_alias_rejects_ambiguity_or_wrong_bank(self):
        for original in (
            layout(dict(name='TALA', file='OTHER')),
            layout(dict(name='TALA', file='TALA', preload='maybe')),
            layout(dict(name='TALA', file='TALA', unexpected='true')),
            layout(dict(name='TALA', file='TALA'), dict(name='TALA', file='TALA')),
        ):
            with self.subTest(original=original), self.assertRaises(ValueError):
                roster._voice_banks(original, (7,))




if __name__ == '__main__':
    unittest.main()
