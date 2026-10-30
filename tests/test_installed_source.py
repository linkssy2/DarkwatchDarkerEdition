"""Source recovery uses only private tails and verifies full original archive pins."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'launcher'), str(ROOT / 'tools')]
import character_archive as archive
import installed_source as recovery
from test_launcher_characters import tiny_archive, pin


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = self.root / 'original'
        self.installed = self.root / 'installed'
        self.saved = self.root / 'recovery'
        self.output = self.root / 'restored'
        self.original.mkdir()
        self.installed.mkdir()
        self.raw = tiny_archive()
        self.pins = {name: pin(self.raw) for name in ('packfile.pck', 'LvlSingl.pck', 'audio.pck')}
        self.patches = ((16, self.raw[16:18], b'ZZ'),)
        mocked = patch.object(recovery.bonus_content, 'PATCHES', self.patches)
        mocked.start()
        self.addCleanup(mocked.stop)
        for name in self.pins:
            (self.original / name).write_bytes(self.raw)
            raw = bytearray(self.raw)
            if name == 'packfile.pck':
                raw[16:18] = b'ZZ'
            (self.installed / name).write_bytes(archive.compose(raw, {'fixture/replaced.bin': b'new resource'}))

    def capture(self):
        recovery.capture(self.original, self.saved, self.pins)

    def test_recovers_exact_originals_from_appended_payload_and_split_patch(self):
        self.assertFalse(recovery.has_recovery(self.saved, self.pins))
        self.capture()
        self.assertTrue(recovery.has_recovery(self.saved, self.pins))
        before = {p.name: p.read_bytes() for p in self.installed.iterdir()}
        with patch.object(recovery, 'CHUNK', 17):
            recovery.restore(self.installed, self.saved, self.output, self.pins)
        for name in self.pins:
            self.assertEqual((self.output / name).read_bytes(), self.raw)
            self.assertEqual((self.installed / name).read_bytes(), before[name])
        self.assertLess(sum(p.stat().st_size for p in self.saved.iterdir()), sum(p['size'] for p in self.pins.values()))

    def test_capture_rejects_altered_source_and_does_not_overwrite(self):
        (self.original / 'packfile.pck').write_bytes(b'X' + self.raw[1:])
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.capture()
        self.assertFalse(self.saved.exists())
        (self.original / 'packfile.pck').write_bytes(self.raw)
        self.capture()
        with self.assertRaises(FileExistsError):
            self.capture()
        self.assertTrue(recovery.has_recovery(self.saved, self.pins))

    def test_bad_tail_or_prefix_fails_full_hash_and_removes_partial_output(self):
        self.capture()
        tail_path = self.saved / 'packfile.pck.tail'
        tail = tail_path.read_bytes()
        original = (self.installed / 'packfile.pck').read_bytes()
        for target, data in ((tail_path, b'X' + tail[1:]),
                             (self.installed / 'packfile.pck', b'X' + original[1:])):
            target.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'checksum'):
                recovery.restore(self.installed, self.saved, self.output, self.pins)
            self.assertFalse((self.output / 'packfile.pck').exists())
            tail_path.write_bytes(tail)
            (self.installed / 'packfile.pck').write_bytes(original)

    def test_truncated_bad_footer_and_oversized_tails_are_rejected(self):
        self.capture()
        path = self.saved / 'packfile.pck.tail'
        tail = path.read_bytes()
        for data in (tail[:-1], tail[:-4] + bytes(4), bytes(16), tail + bytes(8)):
            path.write_bytes(data)
            self.assertFalse(recovery.has_recovery(self.saved, self.pins))
            with self.assertRaises(ValueError):
                recovery.restore(self.installed, self.saved, self.output, self.pins)
            self.assertFalse(self.output.exists())
        path.write_bytes(tail)
        with patch.object(recovery, 'MAX_TAIL', 64):
            self.assertFalse(recovery.has_recovery(self.saved, self.pins))

    def test_cancellation_keeps_input_and_existing_destination(self):
        self.capture()
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise InterruptedError('cancel')
        with patch.object(recovery, 'CHUNK', 17), self.assertRaises(InterruptedError):
            recovery.restore(self.installed, self.saved, self.output, self.pins, cancel)
        self.assertFalse((self.output / 'packfile.pck').exists())
        (self.output / 'packfile.pck').write_bytes(b'keep existing')
        with self.assertRaises(FileExistsError):
            recovery.restore(self.installed, self.saved, self.output, self.pins)
        self.assertEqual((self.output / 'packfile.pck').read_bytes(), b'keep existing')

    def test_capture_cancel_and_invalid_bonus_source_are_rejected(self):
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise InterruptedError('cancel')
        with patch.object(recovery, 'CHUNK', 17), self.assertRaises(InterruptedError):
            recovery.capture(self.original, self.saved, self.pins, cancel)
        self.assertFalse(self.saved.exists())
        self.capture()
        path = self.installed / 'packfile.pck'
        data = path.read_bytes()
        path.write_bytes(data[:16] + b'??' + data[18:])
        with self.assertRaisesRegex(ValueError, 'bonus selector'):
            recovery.restore(self.installed, self.saved, self.output, self.pins)
        self.assertFalse(self.output.exists())
        path.write_bytes(data[:30])
        with self.assertRaisesRegex(ValueError, 'truncated'):
            recovery.restore(self.installed, self.saved, self.output, self.pins)
        self.assertFalse(self.output.exists())

    def test_unsafe_paths_and_hardlinks_are_rejected(self):
        self.capture()
        for name in ('../outside', '/absolute', 'CON', 'folder/name'):
            with self.assertRaises(ValueError):
                recovery.restore(self.installed, self.saved, self.output, {name: pin(self.raw)})
        path = self.saved / 'packfile.pck.tail'
        os.link(path, self.root / 'hardlink')
        self.assertFalse(recovery.has_recovery(self.saved, self.pins))
        with self.assertRaisesRegex(ValueError, 'unlinked'):
            recovery.restore(self.installed, self.saved, self.output, self.pins)

    def test_linked_recovery_root_is_rejected(self):
        self.capture()
        link = self.root / 'link'
        try:
            link.symlink_to(self.saved, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks is unavailable')
        self.assertFalse(recovery.has_recovery(link, self.pins))
        with self.assertRaises(ValueError):
            recovery.restore(self.installed, link, self.output, self.pins)


if __name__ == '__main__':
    unittest.main()
