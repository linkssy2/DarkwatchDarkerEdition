"""Synthetic coverage and untrusted-file checks; no copyrighted text fixtures."""
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import ps2_text as spanish
import character_archive as archive
import character_assets as bxml


def table(rows):
    tree = dict(name='root', attributes={}, value=None, children=[])
    for key, value in rows:
        tree['children'].append(dict(name='element', attributes={}, value=None,
            children=[dict(name='textID', attributes={}, value=key, children=[]),
                      dict(name='localizedText', attributes={}, value=value, children=[])]))
    return bxml.encode(tree)


def pack(rows=128, compact=False):
    data = bytearray(2048)
    entry = dict(name='fixture/resource.bin', offset=0, size=16, pointer=0)
    entries, names = archive.build_rows([entry], rows)
    used = rows // 2 if compact else rows
    data.extend(struct.pack('<4I', used, 1, rows - 1, 0))
    for row in entries[:used]:
        data.extend(struct.pack('<QII', *row))
    for name in names:
        if name:
            raw = name.encode('ascii')
            data.extend(struct.pack('<II', 0, len(raw)) + raw)
    footer = bytearray(40)
    struct.pack_into('<II', footer, 32, 2048, 0xFFFFFFFB)
    return bytes(data + footer)


class SpanishTextTests(unittest.TestCase):
    def test_latin1_is_preserved_and_only_supported_accents_are_normalized(self):
        raw = table([('EXAMPLE', 'placeholder')]).replace(b'placeholder', b'\xed' + b' ' * 10)
        self.assertEqual(spanish.read_table(raw), {'example': '\xed' + ' ' * 10})
        self.assertEqual(spanish.normalized('áéíóúüñ\xa0¡¿'), 'ÁÉÍÓÚÜÑ ¡¿')
        self.assertEqual(spanish.normalized('Pulsa ^PrimaryStart^.'), 'Pulsa ^PrimaryStart^.')
        for invalid in ('\0', 'bad\x1f', 'a\x80', 'a\u2014', ''):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                spanish.normalized(invalid)

    def test_bxml_rejects_truncation_version_indices_and_duplicate_ids(self):
        raw = table([('sample', 'sample text')])
        for size in range(len(raw)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                spanish.read_table(raw[:size])
        for invalid in (raw + b'x', b'\2' + raw[1:], raw[:4] + b'\xff\xff' + raw[6:],
                        raw[:-2] + b'\xfe\xff', table([('same', 'one'), ('SAME', 'two')])):
            with self.subTest(invalid=invalid[:12]), self.assertRaises(ValueError):
                spanish.read_table(invalid)

    def test_pck_compact_rows_do_not_change_original_payload(self):
        original = pack(compact=True)
        parsed = spanish.read_pack(original)
        self.assertEqual(len(parsed['rows']), 128)
        self.assertEqual(parsed['raw'][:2048], original[:2048])
        self.assertEqual(parsed['entries'][0]['name'], 'fixture/resource.bin')
        self.assertEqual(struct.unpack_from('<I', original, 2048)[0], 64)
        self.assertEqual(spanish.read_pack(pack())['entries'], parsed['entries'])

    def test_pck_rejects_corrupt_counts_extents_and_names(self):
        original = pack(compact=True)
        bad_headers = ((63, 1, 127, 0), (64, 65, 127, 0), (64, 1, 126, 0),
                       (64, 1, 127, 1), (1048577, 1, 2097151, 0))
        for header in bad_headers:
            bad = bytearray(original)
            struct.pack_into('<4I', bad, 2048, *header)
            with self.subTest(header=header), self.assertRaises(ValueError):
                spanish.read_pack(bad)
        for bad in (b'', original[:-1], original.replace(b'fixture/resource.bin', b'fixture/../evil___bin')):
            with self.assertRaises(ValueError):
                spanish.read_pack(bad)

    def test_context_key_preserves_distinct_bank_meanings_in_binary(self):
        original = {'one_e.bxml': {'same': 'Open the item'}, 'two_e.bxml': {'same': 'Open'}}
        community = {'one_s.bxml': {'same': 'Abre el objeto'}, 'two_s.bxml': {'same': 'Abrir'}}
        data, report = spanish.catalogue(original, community, {})
        self.assertEqual(data[:8], b'DWES0003')
        count, = struct.unpack_from('<I', data, 8)
        self.assertEqual(count, 2)
        pos, found = 12, {}
        for _ in range(count):
            identity, length = struct.unpack_from('<QI', data, pos)
            pos += 12
            found[identity] = data[pos:pos + length].decode('latin1')
            pos += length
        self.assertEqual(pos, len(data))
        self.assertEqual(found[spanish.context_id('same', 'Open')], 'Abrir')
        self.assertEqual(found[spanish.context_id('same', 'Open the item')], 'Abre el objeto')
        self.assertNotIn(b'Open', data)
        self.assertNotIn(b'same', data)
        self.assertEqual(report['english_nonempty_rows'], 2)
        self.assertFalse(report['original_contexts_embedded'])
        with patch.object(spanish, 'context_id', return_value=42):
            with self.assertRaisesRegex(ValueError, 'identity collision'):
                spanish.catalogue(original, community, {})

    def test_context_identity_has_stable_encoding_and_a_separator(self):
        self.assertEqual(spanish.context_id('GEN_Test', 'Back'), 0x7dd34ffb1b12a266)
        self.assertNotEqual(spanish.context_id('ab', 'c'), spanish.context_id('a', 'bc'))
        self.assertEqual(spanish.context_id('gen_test', 'Back'), spanish.context_id('GEN_TEST', 'Back'))

    def test_missing_translation_conflicts_and_control_token_changes_fail_closed(self):
        original = {'one_e.bxml': {'example': 'Use ^Jump^ or ^0^.'}}
        for community in ({}, {'one_s.bxml': {'example': 'Usa un botón.'}},
                          {'one_s.bxml': {'example': 'Usa ^Jump^ y ^0^ ^0^.'}}):
            with self.assertRaises(ValueError):
                spanish.catalogue(original, community, {})
        original['two_e.bxml'] = original['one_e.bxml']
        community = {'one_s.bxml': {'example': 'Usa ^Jump^ o ^0^.'},
                     'two_s.bxml': {'example': 'Pulsa ^Jump^ o ^0^.'}}
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            spanish.catalogue(original, community, {})
        edits = {spanish.context_id('example', 'Use ^Jump^ or ^0^.'): 'Usa ^Jump^ o ^0^.'}
        data, report = spanish.catalogue(original, community, edits)
        self.assertEqual(report['unique_contexts'], 1)
        self.assertEqual(report['english_nonempty_rows'], 2)
        self.assertIn(b'^Jump^', data)

    def test_corrections_require_exact_unique_contexts_and_all_must_be_used(self):
        identity = spanish.context_id('example', 'Fixture')
        document = dict(schema=1, contexts={f'{identity:016x}': 'Ejemplo'})
        self.assertEqual(spanish.corrections(json.dumps(document)), {identity: 'Ejemplo'})
        for invalid in ({}, [], dict(document, schema=2), dict(document, extra='x'),
                        dict(schema=1, contexts={'not-a-hash': 'Ejemplo'}),
                        dict(schema=1, contexts={f'{identity:016x}': 2})):
            with self.assertRaises(ValueError):
                spanish.corrections(json.dumps(invalid))
        with self.assertRaisesRegex(ValueError, 'Unused'):
            spanish.catalogue({'one_e.bxml': {'example': 'Other text'}},
                              {'one_s.bxml': {'example': 'Otro texto'}},
                              spanish.corrections(json.dumps(document)))


if __name__ == '__main__':
    unittest.main()
