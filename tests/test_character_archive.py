"""Exact archive compatibility and transactional, bounded file composition."""
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import character_archive as archive
from test_launcher_characters import tiny_archive


class CharacterArchiveTests(unittest.TestCase):
    def test_coalesced_rows_match_previous_writer(self):
        # Frozen outputs of the former scan-based writer, including near-full tables.
        for capacity, count, seed, expected in (
            (64, 62, 7, '825ee5691d0f086ca3b86ceb3531da381bc2e26643256695c1b2af6413f6b7c9'),
            (256, 245, 8, 'f9cc2208fc152d115d9c642b3620cb60820eb87b60ce359ea5058bc4744d71e5'),
            (4096, 3900, 9, 'c3d7bdaf90105dd674716224bc31ade1411952f5fced08deef0a7e1722a90c5f'),
        ):
            with self.subTest(capacity=capacity):
                entries = [dict(name=f'fixture/resource-{i:06d}.bxml', offset=i * 73,
                                size=i % 101 + 1) for i in range(count)]
                random.Random(seed).shuffle(entries)
                result = archive.build_rows(entries, capacity)
                self.assertEqual(hashlib.sha256(json.dumps(result, separators=(',', ':')).encode()).hexdigest(), expected)
        duplicate = dict(name='fixture/duplicate', offset=0, size=1)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            archive.build_rows([duplicate, duplicate], 64)

    def test_compose_matches_frozen_previous_bytes(self):
        raw = archive.compose(tiny_archive(), {'fixture/replaced.bin': b'replacement', 'fixture/added.bin': b'new'})
        self.assertEqual(len(raw), 7306)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), 'b6985535986c51d135218c030fdde21132c8899b7fe86f1dd8194c12ca645591')
        self.assertIsInstance(raw, bytes)

    def test_file_composition_matches_every_in_memory_stage(self):
        original = tiny_archive()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'original.pck'
            source.write_bytes(original)
            expected = original
            current = source
            for i, replacements in enumerate((
                {'fixture/added.bin': b'new', 'fixture/replaced.bin': b'replacement'},
                {'fixture/big.bin': bytes(range(256)) * (36 * 1024)},
                {'fixture/added.bin': b'changed again'},
            )):
                target = Path(folder) / f'stage-{i}.pck'
                expected = archive.compose(expected, replacements)
                self.assertIsNone(archive.compose_file(current, replacements, target))
                self.assertEqual(target.read_bytes(), expected)
                current = target
            self.assertEqual(source.read_bytes(), original)

    def test_cancel_during_write_and_verification_removes_only_own_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.pck', Path(folder) / 'target.pck'
            original = tiny_archive()
            source.write_bytes(original)
            replacements = {'fixture/big.bin': b'a' * (9 * 1024 * 1024)}
            total = 0
            def count():
                nonlocal total
                total += 1
            archive.compose_file(source, replacements, target, count)
            target.unlink()
            for stop in (1, 3, 7, total - 1, total):
                calls = 0
                def cancel():
                    nonlocal calls
                    calls += 1
                    if calls == stop:
                        raise InterruptedError('cancelled')
                with self.subTest(stop=stop), self.assertRaisesRegex(InterruptedError, 'cancelled'):
                    archive.compose_file(source, replacements, target, cancel)
                self.assertFalse(target.exists())
                self.assertEqual(source.read_bytes(), original)

    def test_existing_destinations_and_invalid_inputs_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.pck', Path(folder) / 'target.pck'
            original = tiny_archive()
            source.write_bytes(original)
            target.write_bytes(b'existing destination')
            with self.assertRaises(FileExistsError):
                archive.compose_file(source, {'fixture/new': b'new'}, target)
            self.assertEqual(target.read_bytes(), b'existing destination')
            with self.assertRaisesRegex(ValueError, 'differ'):
                archive.compose_file(source, {'fixture/new': b'new'}, source)
            target.unlink()
            for replacements in ({}, {'fixture/new': b''}, {'../escape': b'x'}, {'fixture/a': b'a', 'Fixture/A': b'b'}):
                with self.subTest(replacements=replacements), self.assertRaises(ValueError):
                    archive.compose_file(source, replacements, target)
                self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), original)

    def test_payload_verification_failure_cleans_output_without_masking_error(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.pck', Path(folder) / 'target.pck'
            original = tiny_archive()
            source.write_bytes(original)
            verify = archive._verify_composition
            def corrupt(original, replacements, output, cancel):
                damaged = bytearray(output)
                damaged[0] ^= 1
                verify(original, replacements, damaged, cancel)
            with patch.object(archive, '_verify_composition', side_effect=corrupt), \
                    self.assertRaisesRegex(AssertionError, 'Payload preservation'):
                archive.compose_file(source, {'fixture/new': b'new'}, target)
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
