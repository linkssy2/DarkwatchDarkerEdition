"""Private preview generation: affine skinning, wrapping, pins and migration."""
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'launcher'))
sys.path.insert(0, str(ROOT/'tools'))
import character_preview as preview
import setup_backend as setup


class CharacterPreviewTests(unittest.TestCase):
    def test_tala_variants_keep_old_ids_and_use_only_wingless_playable_boss(self):
        self.assertEqual(len(preview.MODELS), 10)
        self.assertEqual(preview.MODELS[7:], (
            'characters/talaagent/base_agenttala.rx1',
            'characters/tala/base_cine_tala.rx1',
            'characters/player_roster/base_tala_boss.rx1'))
        self.assertNotIn('characters/tala_cine/base_cine_tala.rx1', preview.MODELS)
        self.assertNotIn('characters/tala_boss/base_tala_boss.rx1', preview.MODELS)
        self.assertEqual((preview.VERSION, preview.MAGIC), (3, b'DWCP0003'))

    def test_import_uses_only_standard_library(self):
        check = subprocess.run([sys.executable, '-S', '-c',
            'import sys;sys.path.insert(0,sys.argv[1]);import character_preview', str(ROOT/'launcher')],
            capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_fnv_matches_runtime_reference(self):
        self.assertEqual(preview.fnv(b''), 0xcbf29ce484222325)
        self.assertEqual(preview.fnv(b'hello'), 0xa430d84680aabd0b)
        self.assertEqual(preview._rgba(0xff9cceff), 0xffffce9c)

    def test_affine_padding_does_not_drop_animated_translation(self):
        # Native inverse binds end in padding zero, not a homogeneous one.
        inverse = (*preview.IDENTITY[:-1], 0.)
        mesh = dict(parts=[(0, 1, [inverse])],
                    vertices=[((0., 0., 0.), (0., 1., 0.), (0., 0.), 0xffffffff, {0: 1.})])
        local = (1., 0., 0., 0., 1., 0., 0., 0., 1., 0., 0., 0.)
        rig = {0: dict(frame=1)}
        frames = [(*local, -1, 0), (*local, 0, 0)]
        clip = (struct.pack('<IIIfII', 40, 0xf11e0006, 1, 1.5, 0, 8)+struct.pack('<II', 2, 0)+
                struct.pack('<8f', 0., 0., 0., 0., 1.5, 0., 1., 0.))
        with patch.object(preview.boss, 'rig', return_value=(rig, frames, 0)):
            duration, poses = preview._poses(b'', clip, mesh, lambda: None)
        self.assertEqual(duration, 1.5)
        self.assertAlmostEqual(poses[15][0][1], .5)
        self.assertEqual(poses[15][0][3:], (0., 1., 0.))

    def mesh(self, uvs):
        return dict(vertices=[((0., 0., 0.), (0., 1., 0.), uv, 0xffffffff, {0: 1.}) for uv in uvs],
                    triangles=[(0, 1, 2, 0, 0xffffffff)])

    def test_wrapping_preserves_barycentric_surface_and_animation(self):
        vertices, triangles = preview._wrap(self.mesh(((-.2, .2), (1.6, .2), (.2, 1.3))))
        self.assertGreater(len(triangles), 1)
        area = 0.
        for a, b, c, _, _ in triangles:
            weights = []
            for i in (a, b, c):
                u, v, _, refs = vertices[i]
                self.assertTrue(0 <= u <= 1 and 0 <= v <= 1)
                self.assertAlmostEqual(sum(w for _, w in refs), 1.)
                row = dict(refs); weights.append((row.get(1, 0.), row.get(2, 0.)))
            p, q, r = weights
            area += abs((q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]))/2
        self.assertAlmostEqual(area, .5)

    def test_constant_uv_keeps_visible_geometry(self):
        vertices, triangles = preview._wrap(self.mesh(((1., 0.), (1., 0.), (1., 0.))))
        self.assertEqual(len(triangles), 1)
        self.assertEqual(len(vertices), 3)

    def test_bad_sources_and_uvs_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'idle'):
            preview.build(lambda _: b'not the original idle')
        with self.assertRaisesRegex(ValueError, 'UV'):
            preview._wrap(self.mesh(((float('nan'), 0.), (1., 0.), (0., 1.))))
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory); (assets/'packfile.pck').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'size differs'):
                preview.prepare(assets, assets/preview.NAME)
            self.assertFalse((assets/preview.NAME).exists())

    def test_existing_installation_migration_is_atomic_and_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory); (current/'assets').mkdir()
            original = dict(schema_version=1, language='es', saved='preserved')
            setup.write_json(current/'install.json', original)
            target = current/preview.NAME
            payload = b'generated private preview'
            record = dict(version=preview.VERSION, size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            backend = object.__new__(setup.Setup)
            backend.check_cancel = lambda: None; backend.notify = lambda *a, **kw: None
            backend.digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            def prepare(assets, destination, cancel):
                self.assertEqual(assets, current/'assets'); cancel(); destination.write_bytes(payload); return record
            with patch.object(setup, 'require_closed'), patch.object(preview, 'prepare', side_effect=prepare) as converter:
                backend.prepare_previews(current)
                backend.prepare_previews(current)
                self.assertEqual(converter.call_count, 1)
                target.write_bytes(b'broken')
                backend.prepare_previews(current)
                self.assertEqual(converter.call_count, 2)
            self.assertEqual(setup.read_json(current/'install.json'), dict(original, character_preview=record))
            target.unlink()
            before = (current/'install.json').read_bytes()
            with patch.object(setup, 'require_closed'), patch.object(preview, 'prepare', side_effect=ValueError('bad source')):
                with self.assertRaisesRegex(ValueError, 'bad source'):
                    backend.prepare_previews(current)
            self.assertEqual((current/'install.json').read_bytes(), before)

    def test_cancel_before_cache_commit_keeps_previous_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = b'verified synthetic archive'
            (folder/'packfile.pck').write_bytes(source)
            output = folder/preview.NAME; output.write_bytes(b'previous')
            calls = 0
            def cancel():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise setup.Cancelled('cancel at commit')
            with patch.dict(preview.character_content.INSTALLED,
                            {'packfile.pck': (len(source), hashlib.sha256(source).hexdigest())}), \
                 patch.object(preview.archive, 'read', return_value={'entries': []}), \
                 patch.object(preview, 'build', return_value=b'new local preview'):
                with self.assertRaises(setup.Cancelled):
                    preview.prepare(folder, output, cancel)
            self.assertEqual(output.read_bytes(), b'previous')
            self.assertFalse(list(folder.glob('.character-preview-*')))


if __name__ == '__main__':
    unittest.main()
