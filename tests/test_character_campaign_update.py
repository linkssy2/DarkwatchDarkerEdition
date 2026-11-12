"""Campaign updates must fail before replacing any caller-owned source archive."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import character_update


def pin(raw):
    return {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


class CampaignUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.assets, self.previous = root / 'assets', root / 'previous'
        self.assets.mkdir()
        self.previous.mkdir()
        self.originals = {name: ('original ' + name).encode() for name in ('packfile.pck', 'LvlSingl.pck', 'audio.pck')}
        self.prepared = {name: ('prepared ' + name).encode() for name in self.originals}
        for name in self.originals:
            (self.assets / name).write_bytes(self.originals[name])
            (self.previous / name).write_bytes(self.prepared[name])
        self.metadata = {'originals': {n: pin(r) for n, r in self.originals.items()},
                         'installed': {n: pin(r) for n, r in self.prepared.items()}}

    def run_update(self, finalize, cancel=lambda: None):
        return character_update.try_reuse_base(self.assets, self.previous, self.metadata,
                                               cancel, lambda message: None, finalize)

    def assert_originals(self):
        self.assertEqual({n: (self.assets / n).read_bytes() for n in self.originals}, self.originals)
        self.assertEqual({n: (self.previous / n).read_bytes() for n in self.prepared}, self.prepared)
        self.assertEqual(sorted(p.name for p in self.assets.iterdir()), sorted(self.originals))

    def test_failed_final_conversion_preserves_all_sources(self):
        def fail(staged):
            (staged / 'packfile.pck').write_bytes(b'partial conversion')
            raise ValueError('final archive identity differs')
        with self.assertRaisesRegex(ValueError, 'final archive identity'):
            self.run_update(fail)
        self.assert_originals()

    def test_changed_prior_release_falls_back_without_finalizing(self):
        (self.previous / 'packfile.pck').write_bytes(b'x' * len(self.prepared['packfile.pck']))
        called = []
        self.assertFalse(self.run_update(lambda staged: called.append(staged)))
        self.assertEqual(called, [])
        self.assertEqual({n: (self.assets / n).read_bytes() for n in self.originals}, self.originals)

    def test_changed_disc_fails_before_finalizing(self):
        (self.assets / 'LvlSingl.pck').write_bytes(b'wrong disc')
        called = []
        with self.assertRaises(ValueError):
            self.run_update(lambda staged: called.append(staged))
        self.assertEqual(called, [])

    def test_success_installs_only_completed_outputs(self):
        def finish(staged):
            for name, raw in self.prepared.items():
                self.assertEqual((staged / name).read_bytes(), raw)
                (staged / name).write_bytes(raw + b' finished')
            self.assertEqual({n: (self.assets / n).read_bytes() for n in self.originals}, self.originals)
        self.assertTrue(self.run_update(finish))
        self.assertEqual({n: (self.assets / n).read_bytes() for n in self.originals},
                         {n: r + b' finished' for n, r in self.prepared.items()})
        self.assertEqual({n: (self.previous / n).read_bytes() for n in self.prepared}, self.prepared)


if __name__ == '__main__':
    unittest.main()
