"""Own-disc conversion contracts using synthetic resources, never a game launch."""
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import character_archive as archive
import character_assets as art
import character_content as content


def pin(data):
    return dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())


def tiny_archive():
    payload = bytearray(b'synthetic original bytes' + bytes(2048-24))
    entries = [dict(name='fixture/unchanged.bin', offset=0, size=9, pointer=0),
               dict(name='fixture/replaced.bin', offset=10, size=8, pointer=0)]
    rows, names = archive.build_rows(entries, 64)
    start = len(payload)
    payload.extend(struct.pack('<4I', 64, 2, 63, 0))
    for row in rows:
        payload.extend(struct.pack('<QII', *row))
    for name in names:
        if name is not None:
            raw = name.encode('ascii')
            payload.extend(struct.pack('<II', 0, len(raw))+raw)
    footer = bytearray(40)
    struct.pack_into('<II', footer, 32, start, 0xfffffffb)
    return bytes(payload+footer)


class CharacterConversionTests(unittest.TestCase):
    def test_stdlib_only_import(self):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c',
            'import sys;sys.path.insert(0,sys.argv[1]);import character_content', str(ROOT/'launcher')],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_bxml_roundtrip_and_malformed_data(self):
        tree = dict(name='root', attributes={'name': 'example'}, value=None,
                    children=[art.element(dict(name='fixture/a', type='FixtureResource'))])
        raw = art.encode(tree)
        self.assertEqual(art.decode(raw), tree)
        for bad in (raw[:-1], raw+b'x', b'\2\0\0\0'+raw[4:], b'\1\0\0\0\xff\xff'):
            with self.subTest(bad=bad[:8]), self.assertRaises(ValueError):
                art.decode(bad)

    def test_archive_append_retains_originals_and_rejects_aliases(self):
        original = tiny_archive()
        result = archive.compose(original, {'fixture/replaced.bin': b'replacement', 'fixture/added.bin': b'new'})
        parsed = archive.read(result)
        rows = {row['name']: row for row in parsed['entries']}
        old = archive.read(original)
        self.assertEqual(result[:old['start']], original[:old['start']])
        for name, data in (('fixture/replaced.bin', b'replacement'), ('fixture/added.bin', b'new')):
            row = rows[name]
            self.assertEqual(result[row['offset']:row['offset']+row['size']], data)
            self.assertEqual(row['offset'] % 2048, 0)
        self.assertEqual(rows['fixture/unchanged.bin']['offset'], 0)
        for invalid in ({'../escape': b'x'}, {'fixture/a': b'a', 'Fixture/A': b'b'}, {'fixture/a': b''}):
            with self.assertRaises(ValueError):
                archive.compose(original, invalid)
        for bad in (original[:-1], original[:-4]+bytes(4)):
            with self.assertRaises(ValueError):
                archive.read(bad)

    def test_source_checks_bounds_identity_and_cancellation(self):
        raw = b'0123456789'
        metadata = dict(originals={'fixture.pck': pin(raw)}, sources={
            'fixture/a': dict(archive='fixture.pck', offset=2, **pin(b'234'))})
        source = content.Source({'fixture.pck': io.BytesIO(raw)}, metadata, lambda: None)
        self.assertEqual(source.read('Fixture/A'), b'234')
        for name in ('../escape', 'fixture/missing'):
            with self.assertRaises(ValueError):
                source.read(name)
        metadata['sources']['fixture/a']['size'] = 99
        with self.assertRaisesRegex(ValueError, 'outside'):
            source.read('fixture/a')
        metadata['sources']['fixture/a']['size'] = 3
        metadata['sources']['fixture/a']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            source.read('fixture/a')
        def cancel():
            raise InterruptedError('cancelled')
        source.cancel = cancel
        with self.assertRaises(InterruptedError):
            source.read('fixture/a')

    def test_install_all_verified_copies_or_leave_originals(self):
        originals = {name: tiny_archive() for name in ('packfile.pck', 'LvlSingl.pck', 'audio.pck')}
        groups = {name: {'fixture/replaced.bin': b'first conversion'} for name in originals}
        extension = {name: {'fixture/added.bin': b'second conversion'} for name in ('packfile.pck', 'LvlSingl.pck')}
        first = {name: archive.compose(data, groups[name]) for name, data in originals.items()}
        base = {name: archive.compose(data, extension[name]) if name in extension else data for name, data in first.items()}
        spectral = {'packfile.pck': {'fixture/spectral.bin': b'third conversion'}}
        third = {name: archive.compose(data, spectral[name]) if name in spectral else data for name, data in base.items()}
        roster = {name: {'fixture/roster.bin': b'fourth conversion'} for name in originals}
        fourth = {name: archive.compose(data, roster[name]) for name, data in third.items()}
        revolver = {name: {'fixture/revolver.bin': b'fifth conversion'} for name in originals}
        revolver['LvlSingl.pck']['fixture/replaced.bin'] = b'final chapter table'
        final = {name: archive.compose(data, revolver[name]) for name, data in fourth.items()}
        combined = {}
        for stage in (groups, extension, spectral, roster, revolver):
            combined.update(stage.get('LvlSingl.pck', {}))
        final['LvlSingl.pck'] = archive.compose(originals['LvlSingl.pck'], combined)
        # Compaction changes offsets, never the resource contents or original payload.
        appended = archive.compose(fourth['LvlSingl.pck'], revolver['LvlSingl.pck'])
        def resources(raw):
            return {row['name']: raw[row['offset']:row['offset'] + row['size']]
                    for row in archive.read(raw)['entries']}
        self.assertEqual(resources(final['LvlSingl.pck']), resources(appended))
        self.assertLess(len(final['LvlSingl.pck']), len(appended))
        metadata = dict(schema_version=1, content_revision=content.CONTENT_REVISION,
                        originals={name: pin(data) for name,data in originals.items()},
                        v7_archives={name: pin(data) for name,data in first.items()},
                        base_archives={name: pin(data) for name,data in base.items()},
                        spectral_archives={name: pin(data) for name,data in third.items()},
                        roster_archives={name: pin(data) for name,data in fourth.items()},
                        installed={name: pin(data) for name,data in final.items()})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            assets, payload = root/'assets', root/'payload'
            assets.mkdir(); payload.mkdir()
            def reset():
                for name, data in originals.items():
                    (assets/name).write_bytes(data)
                raw = json.dumps(metadata).encode()
                (payload/'character-catalog.json').write_bytes(raw)
                return pin(raw)['sha256']
            installed = {name:(len(data),pin(data)['sha256']) for name,data in final.items()}
            with patch.object(content, 'INSTALLED', installed), patch.object(content, 'build_resources', return_value=(groups,extension,spectral)), \
                    patch.object(content.character_roster, 'prepare', return_value=(roster, {})), \
                    patch.object(content.revolver_content, 'prepare', return_value=revolver), \
                    patch.object(content.bonus_content, 'patch_pack', side_effect=lambda data:data):
                with patch.object(content, 'CATALOG_SHA256', reset()):
                    content.prepare(assets,payload)
                self.assertEqual({name:(assets/name).read_bytes() for name in final},final)
                self.assertEqual(set(p.name for p in assets.iterdir()),set(final))
                # A later bad output cannot leave an earlier archive installed.
                metadata['v7_archives']['audio.pck']['sha256'] = '0'*64
                with patch.object(content, 'CATALOG_SHA256', reset()), self.assertRaisesRegex(ValueError,'verification failed'):
                    content.prepare(assets,payload)
                self.assertEqual({name:(assets/name).read_bytes() for name in originals},originals)
                metadata['v7_archives']['audio.pck'] = pin(first['audio.pck'])
                # Fourth-stage failure also leaves every original intact.
                roster['audio.pck']['fixture/roster.bin'] = b'wrong roster output'
                with patch.object(content, 'CATALOG_SHA256', reset()), self.assertRaisesRegex(ValueError, 'verification failed'):
                    content.prepare(assets, payload)
                self.assertEqual({name: (assets/name).read_bytes() for name in originals}, originals)
                roster['audio.pck']['fixture/roster.bin'] = b'fourth conversion'
                # The last-stage failure must also leave every original intact.
                revolver['audio.pck']['fixture/revolver.bin'] = b'wrong revolver output'
                with patch.object(content, 'CATALOG_SHA256', reset()), self.assertRaisesRegex(ValueError, 'verification failed'):
                    content.prepare(assets, payload)
                self.assertEqual({name: (assets/name).read_bytes() for name in originals}, originals)
                revolver['audio.pck']['fixture/revolver.bin'] = b'fifth conversion'
                cancel_now = [False]
                def cancel():
                    if cancel_now[0]: raise InterruptedError('cancelled')
                def progress(message):
                    if message == 'Preparing character resources...': cancel_now[0] = True
                with patch.object(content,'CATALOG_SHA256',reset()), self.assertRaises(InterruptedError):
                    content.prepare(assets,payload,cancel,progress)
                self.assertEqual({name:(assets/name).read_bytes() for name in originals},originals)
                self.assertEqual(set(p.name for p in assets.iterdir()),set(originals))

    def test_catalog_and_authored_pixels_match_shipped_pins(self):
        metadata = content.catalog(ROOT/'launcher')
        self.assertEqual(len(metadata['v7_outputs']),835)
        for character, pins in (('cassidy', content.REPAINT), ('tala', content.TALA_REPAINT)):
            for size,digest in pins.items():
                self.assertEqual(pin((ROOT/'launcher/assets'/f'{character}-hands-{size}.dds').read_bytes())['sha256'],digest)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'character-catalog.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Unsupported'):
                content.catalog(path.parent)


if __name__ == '__main__':
    unittest.main()
