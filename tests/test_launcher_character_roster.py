"""Small synthetic contracts for selected-character routes and voice residency."""
import copy
import itertools
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import character_assets as art
import character_roster as roster


def layout(*banks):
    return dict(name='root', attributes={}, value=None, children=[
        dict(name='banks', attributes={}, value=None,
             children=[art.element(bank) for bank in banks])])


class RosterTests(unittest.TestCase):
    def test_routes_are_bounded_and_pair_order_independent(self):
        pairs = [pair for pair in itertools.combinations_with_replacement(range(8), 2)
                 if max(pair) >= 3]
        self.assertEqual(len({roster.suffix(pair) for pair in pairs}), 30)
        for pair in pairs:
            self.assertEqual(roster.suffix(pair), roster.suffix(pair[::-1]))
        self.assertEqual(roster.suffix((7,)), 'roster_7')
        for invalid in ((), (0,), (1, 2), (8,), (-1, 7), (True, 7), (3.0,), (3, 4, 5)):
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
