"""Exact-output and admission checks for the encoded resource-list fast path."""
import copy
import hashlib
import json
import mmap
import os
from pathlib import Path
import random
import struct
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import character_assets as art
import character_archive as archive
import revolver_content


def node(name, children=(), value=None, attributes=None):
    return dict(name=name, attributes=attributes or {}, children=list(children), value=value)


def resource_tree(rows=()):
    return node('ResourceSetCInfo', [node('data', [art.element(dict(name=n, type=t)) for n, t in rows])])


def reference(raw, dependencies):
    tree, added = art.append_resources(art.decode(raw), dependencies)
    return art.encode(tree), added


def table_encoded(tree, strings):
    """Construct valid alternate string ordering without the canonical encoder."""
    def text(value):
        return strings.index(value)
    def emit(row):
        result = struct.pack('<HH', text(row['name']), len(row['attributes']))
        result += b''.join(struct.pack('<HH', text(k), text(v)) for k, v in row['attributes'].items())
        result += struct.pack('<H', len(row['children'])) + b''.join(emit(c) for c in row['children'])
        return result + struct.pack('<H', 65535 if row['value'] is None else text(row['value']))
    return b'\1\0\0\0' + struct.pack('<H', len(strings)) + b''.join(
        struct.pack('<H', len(s.encode('ascii'))) + s.encode('ascii') for s in strings) + emit(tree)


class EncodedResourceTests(unittest.TestCase):
    def test_repeated_area_layout_is_reused_without_cross_variant_state(self):
        raw = bytearray(art.encode(resource_tree([('body/a', 'ModelResource')])))
        art._resource_layout.cache_clear()
        for path in ('first', 'second', 'first'):
            deps = [(path, 'ModelResource')]
            self.assertEqual(art.append_resource_bytes(raw, deps), reference(raw, deps))
        self.assertEqual(art._resource_layout.cache_info().misses, 1)
        self.assertEqual(art._resource_layout.cache_info().hits, 2)
        raw[raw.index(b'body/a') + 5] = ord('b')
        self.assertEqual(art.append_resource_bytes(raw, []), reference(raw, []))
        self.assertEqual(art._resource_layout.cache_info().misses, 2)
        self.assertEqual(art._resource_layout.cache_info().currsize, 1)

    def test_resident_resource_selector_matches_decoded_list_and_fallback(self):
        original = resource_tree([('Body\\A', 'ModelResource'), ('body/b', 'OtherResource')])
        canonical = art.encode(original)
        strings = ['type', 'ModelResource', 'OtherResource', 'name', 'Body\\A', 'body/b',
                   'element', 'data', 'ResourceSetCInfo']
        alternate = table_encoded(original, strings)
        for raw in (canonical, alternate):
            calls = []
            def selected(present):
                self.assertIsInstance(present, frozenset)
                self.assertEqual(present, {('body/a', 'ModelResource'), ('body/b', 'OtherResource')})
                calls.append(present)
                return [('body/a/death', 'AnimationResource')]
            if raw == canonical:
                with patch.object(art, 'decode', side_effect=AssertionError('Selector decoded canonical data')):
                    actual = art.append_resource_bytes(raw, select=selected)
            else:
                actual = art.append_resource_bytes(raw, select=selected)
            self.assertEqual(actual, reference(raw, [('body/a/death', 'AnimationResource')]))
            self.assertEqual(len(calls), 1)
            self.assertEqual(art.append_resource_bytes(raw, select=lambda _: []), reference(raw, []))

    def test_canonical_rows_exact_order_deduplication_and_purity(self):
        for rows in ([], [('a/b', 'ModelResource')], [('a/b', 'ModelResource'), ('a/b', 'SkeletonResource')]):
            raw = bytearray(art.encode(resource_tree(rows)))
            deps = [('A\\B', 'ModelResource'), ('a/b', 'SkeletonResource'), ('new', 'ModelResource'),
                    ('NEW', 'ModelResource'), ('element', 'type'), ('', '')]
            before = copy.deepcopy((raw, deps))
            expected = reference(raw, deps)
            with patch.object(art, 'decode', side_effect=AssertionError('Canonical list fell back')):
                actual = art.append_resource_bytes(raw, iter(deps))
            self.assertEqual(actual, expected)
            self.assertIsInstance(actual[0], bytes)
            self.assertEqual((raw, deps), before)
            self.assertEqual(art.append_resource_bytes(actual[0], deps), (actual[0], []))
            self.assertEqual(art.append_resource_bytes(raw, []), (bytes(raw), []))

    def test_noncanonical_valid_layouts_keep_old_serialization(self):
        original = resource_tree([('path', 'ModelResource')])
        cases = []
        strings = ['type', 'ModelResource', 'name', 'path', 'element', 'data', 'ResourceSetCInfo']
        cases.append(table_encoded(original, strings))
        cases.append(table_encoded(original, strings + ['unused', 'path']))
        original['attributes']['note'] = 'root attribute'
        original['value'] = 'root value'
        original['children'].insert(0, node('other', value='before'))
        original['children'].append(node('later', value='after'))
        data = art.named(original, 'data')
        data['attributes']['note'] = 'list attribute'
        data['value'] = 'list value'
        data['children'][0]['children'].reverse()
        cases.append(art.encode(original))
        for raw in cases:
            with self.subTest(raw=raw[:20]):
                deps = [('added', 'ModelResource')]
                self.assertEqual(art.append_resource_bytes(raw, deps), reference(raw, deps))
                self.assertEqual(art.append_resource_bytes(raw, []), reference(raw, []))

    def test_malformed_and_duplicate_resources_rejected(self):
        valid = art.encode(resource_tree([('path', 'ModelResource')]))
        malformed = [valid[:cut] for cut in range(len(valid))]
        malformed += [valid + b'x', b'\2' + valid[1:], b'\1\0\0\0' + struct.pack('<H', 20000),
                      b'\1\0\0\0\1\0' + struct.pack('<H', 4096),
                      b'\1\0\0\0\1\0\1\0\xff',
                      art.encode(resource_tree([('a/b', 'T'), ('A\\B', 'T')])),
                      art.encode(node('WrongRoot')), art.encode(node('ResourceSetCInfo')),
                      art.encode(node('ResourceSetCInfo', [node('data'), node('data')]))]
        for field in ('extra', 'name'):
            tree = resource_tree([('path', 'ModelResource')])
            tree['children'][0]['children'][0]['children'].append(node(field, value='bad'))
            malformed.append(art.encode(tree))
        for bad in malformed:
            with self.subTest(raw=bad[:12]), self.assertRaises((ValueError, KeyError, AttributeError)):
                art.append_resource_bytes(bad, [])

    def test_mutated_binary_matches_reference_admission(self):
        raw = art.encode(resource_tree([('path', 'ModelResource'), ('second', 'OtherResource')]))
        rng = random.Random(1707)
        for _ in range(400):
            bad = bytearray(raw)
            bad[rng.randrange(len(bad))] = rng.randrange(256)
            deps = [('new', 'Resource')]
            try:
                expected = reference(bad, deps)
            except (ValueError, KeyError, AttributeError, TypeError):
                with self.assertRaises((ValueError, KeyError, AttributeError, TypeError)):
                    art.append_resource_bytes(bad, deps)
            else:
                self.assertEqual(art.append_resource_bytes(bad, deps), expected)

    def test_fallback_keeps_generic_parser_bounds(self):
        strings = ['ResourceSetCInfo', 'data', 'key', 'value']
        header = b'\1\0\0\0' + struct.pack('<H', len(strings)) + b''.join(
            struct.pack('<H', len(s)) + s.encode('ascii') for s in strings)
        bodies = [
            [0, 64],  # Attribute bound is checked before reading attribute pairs.
            [0, 2, 2, 3, 2, 3, 0, 65535],  # Duplicate attribute name.
            [0, 0, 20000],  # Child count boundary.
            [0, 0, 1, 9, 0, 0, 65535, 65535],  # Invalid child-name index.
            [0, 0, 1] + [1, 0, 1] * 64 + [1, 0, 0] + [65535] * 66,
        ]
        for body in bodies:
            raw = header + struct.pack('<' + 'H' * len(body), *body)
            with self.subTest(body=body[:10]):
                with self.assertRaises(ValueError):
                    reference(raw, [])
                with self.assertRaises(ValueError):
                    art.append_resource_bytes(raw, [])

    def test_dependency_ascii_string_and_structure_limits(self):
        empty = art.encode(resource_tree())
        for deps in ([('bad\N{LATIN SMALL LETTER E WITH ACUTE}', 'T')], [('a' * 4096, 'T')],
                     [('a', '\N{LATIN SMALL LETTER E WITH ACUTE}')], [('a', 'T' * 4096)]):
            with self.assertRaises(ValueError):
                art.append_resource_bytes(empty, deps)
        good = [('a' * 4095, 'T')]
        self.assertEqual(art.append_resource_bytes(empty, good), reference(empty, good))
        raw = art.encode(resource_tree([(str(i), str(i) + 'T') for i in range(9997)]))
        self.assertEqual(struct.unpack_from('<H', raw, 4)[0], 19999)
        with self.assertRaisesRegex(ValueError, 'strings'):
            art.append_resource_bytes(raw, [('new', 'T')])
        raw = art.encode(resource_tree([(str(i // 2), str(i % 2)) for i in range(19999)]))
        with self.assertRaisesRegex(ValueError, 'bounds'):
            art.append_resource_bytes(raw, [('new', 'T')])




if __name__ == '__main__':
    unittest.main()
