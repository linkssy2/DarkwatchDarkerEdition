"""Own-disc conversion contracts using synthetic resources, never a game launch."""
from contextlib import ExitStack
import copy
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
import character_campaign


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

    def test_discard_only_superseded_chapter_resources(self):
        first = {'LvlSingl.pck': {'replaced': b'old', 'kept': b'untouched'},
                 'packfile.pck': {'replaced': b'old model'}, 'audio.pck': {'replaced': b'old audio'}}
        second = {'LvlSingl.pck': {'replaced': b'intermediate', 'other': b'second'}}
        latest = {'LvlSingl.pck': {'replaced': b'new', 'added': b'new path'}}
        expected = copy.deepcopy((first, second, latest))
        def merged(stages):
            result = {}
            for stage in stages:
                result.update(stage['LvlSingl.pck'])
            return result
        content._discard_replaced_chapters(latest, first, second)
        self.assertEqual(merged((first, second, latest)), merged(expected))
        self.assertEqual(first['LvlSingl.pck'], {'kept': b'untouched'})
        self.assertEqual(second['LvlSingl.pck'], {'other': b'second'})
        self.assertEqual(first['packfile.pck'], expected[0]['packfile.pck'])
        self.assertEqual(first['audio.pck'], expected[0]['audio.pck'])
        self.assertEqual(latest, expected[2])

    def test_install_all_verified_copies_or_leave_originals(self):
        originals = {name: tiny_archive() for name in ('packfile.pck', 'LvlSingl.pck', 'audio.pck')}
        groups = {name: {'fixture/replaced.bin': b'first conversion'} for name in originals}
        extension = {name: {'fixture/added.bin': b'second conversion'} for name in ('packfile.pck', 'LvlSingl.pck')}
        first = {name: archive.compose(data, groups[name]) for name, data in originals.items()}
        base = {name: archive.compose(data, extension[name]) if name in extension else data for name, data in first.items()}
        reference_model = content.character_boss.MODEL + '.rx1'
        tala_model = content.character_tala.MODEL + '.rx1'
        spectral = {'packfile.pck': {reference_model: b'third conversion'}}
        third = {name: archive.compose(data, spectral[name]) if name in spectral else data for name, data in base.items()}
        roster = {name: {'fixture/roster.bin': b'fourth conversion'} for name in originals}
        roster['packfile.pck'][tala_model] = b'native model for derivation'
        fourth = {name: archive.compose(data, roster[name]) for name, data in third.items()}
        revolver = {name: {'fixture/revolver.bin': b'fifth conversion'} for name in originals}
        revolver['LvlSingl.pck']['fixture/replaced.bin'] = b'final chapter table'
        corpses = {name: {'fixture/corpse.bin': b'sixth conversion'} for name in ('packfile.pck', 'LvlSingl.pck')}
        corpses['LvlSingl.pck']['fixture/replaced.bin'] = b'final chapter corpse table'
        final = {name: archive.compose(data, dict(revolver[name], **corpses.get(name, {}))) for name, data in fourth.items()}
        fanning = {'fixture/fanning.bin': b'seventh conversion', 'fixture/revolver.bin': b'fanning weapon'}
        cinematic = {'packfile.pck': {'fixture/cinematic.bin': b'eighth conversion'},
                     'LvlSingl.pck': {'fixture/replaced.bin': b'final cinematic chapter table'}}
        third_person = {'packfile.pck': {'fixture/onfoot.bin': b'full body animation'},
                        'LvlSingl.pck': {'fixture/replaced.bin': b'full body preload'}}
        third_person['packfile.pck'][content.CHARACTERS] = art.encode(
            dict(name='root', attributes={}, children=[], value=None))
        presentation = b'final presentation model'
        final['packfile.pck'] = archive.compose(fourth['packfile.pck'],
            {**revolver['packfile.pck'], **corpses['packfile.pck'], **fanning, **cinematic['packfile.pck'], **third_person['packfile.pck'], tala_model: presentation})
        combined = {}
        for stage in (groups, extension, spectral, roster, revolver, corpses, cinematic, third_person):
            combined.update(stage.get('LvlSingl.pck', {}))
        final['LvlSingl.pck'] = archive.compose(originals['LvlSingl.pck'], combined)
        # Compaction changes offsets, never the resource contents or original payload.
        appended = archive.compose(fourth['LvlSingl.pck'],
            {**revolver['LvlSingl.pck'], **corpses['LvlSingl.pck'], **cinematic['LvlSingl.pck'], **third_person['LvlSingl.pck']})
        def resources(raw):
            return {row['name']: raw[row['offset']:row['offset'] + row['size']]
                    for row in archive.read(raw)['entries']}
        self.assertEqual(resources(final['LvlSingl.pck']), resources(appended))
        self.assertLess(len(final['LvlSingl.pck']), len(appended))
        metadata = dict(schema_version=1, content_revision=content.BASE_REVISION,
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
            with patch.object(content, 'INSTALLED', installed), patch.object(content, 'BASE_INSTALLED', installed), \
                    patch.object(character_campaign, 'build', return_value={}), \
                    patch.object(content, 'build_resources', side_effect=lambda *args: copy.deepcopy((groups,extension,spectral))), \
                    patch.object(content.character_roster, 'prepare', side_effect=lambda *args, **kwargs: (copy.deepcopy(roster), {})), \
                    patch.object(content.revolver_content, 'prepare', side_effect=lambda *args: copy.deepcopy(revolver)), \
                    patch.object(content.revolver_content, 'prepare_fanning', return_value=fanning), \
                    patch.object(content.player_corpses, 'prepare', side_effect=lambda *args: copy.deepcopy(corpses)), \
                    patch.object(content.character_cinematic, 'prepare', side_effect=lambda *args: copy.deepcopy(cinematic)), \
                    patch.object(content.third_person_animation, 'prepare', side_effect=lambda *args: copy.deepcopy(third_person)), \
                    patch.object(content.enemy_blood, 'append', side_effect=lambda data: data), \
                    patch.object(content.character_tala, 'presentation', return_value=presentation) as finish, \
                    patch.object(content.bonus_content, 'patch_pack', side_effect=lambda data:data):
                with patch.object(content, 'CATALOG_SHA256', reset()), \
                        patch.object(archive, 'compose_file', wraps=archive.compose_file) as compose_file:
                    messages = []
                    content.prepare(assets,payload,progress=messages.append)
                chapter_writes = [call for call in compose_file.call_args_list
                                  if call.args[2].name.startswith('LvlSingl.pck')]
                self.assertEqual(len(chapter_writes), 1)
                self.assertEqual(chapter_writes[0].args[0], assets/'LvlSingl.pck')
                self.assertEqual(chapter_writes[0].args[1], combined)
                for index, name in enumerate(installed, 1):
                    self.assertIn(f'Preparing character archive {index}/{len(installed)}: {name}', messages)
                    self.assertIn(f'Verifying completed character archive {index}/{len(installed)}: {name}', messages)
                    self.assertTrue(any(message.startswith('Writing updated animations: ') and
                                        message.endswith(' in ' + name) for message in messages))
                self.assertEqual({name:(assets/name).read_bytes() for name in final},final)
                finish.assert_called_once_with(b'native model for derivation', b'third conversion')
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
                corpses['LvlSingl.pck']['fixture/corpse.bin'] = b'wrong corpse output'
                with patch.object(content, 'CATALOG_SHA256', reset()), self.assertRaisesRegex(ValueError, 'verification failed'):
                    content.prepare(assets, payload)
                self.assertEqual({name: (assets/name).read_bytes() for name in originals}, originals)
                corpses['LvlSingl.pck']['fixture/corpse.bin'] = b'sixth conversion'
                third_person['LvlSingl.pck']['fixture/replaced.bin'] = b'wrong animation output'
                with patch.object(content, 'CATALOG_SHA256', reset()), self.assertRaisesRegex(ValueError, 'verification failed'):
                    content.prepare(assets, payload)
                self.assertEqual({name: (assets/name).read_bytes() for name in originals}, originals)
                third_person['LvlSingl.pck']['fixture/replaced.bin'] = b'full body preload'
                finish.return_value = b'wrong presentation output'
                with patch.object(content, 'CATALOG_SHA256', reset()), self.assertRaisesRegex(ValueError, 'verification failed'):
                    content.prepare(assets, payload)
                self.assertEqual({name: (assets/name).read_bytes() for name in originals}, originals)
                finish.return_value = presentation
                cancel_now = [False]
                def cancel():
                    if cancel_now[0]: raise InterruptedError('cancelled')
                def progress(message):
                    if message.startswith('Preparing character archive '): cancel_now[0] = True
                with patch.object(content,'CATALOG_SHA256',reset()), self.assertRaises(InterruptedError):
                    content.prepare(assets,payload,cancel,progress)
                self.assertEqual({name:(assets/name).read_bytes() for name in originals},originals)
                self.assertEqual(set(p.name for p in assets.iterdir()),set(originals))

    def test_catalog_and_authored_pixels_match_shipped_pins(self):
        metadata = content.catalog(ROOT/'launcher')
        self.assertEqual(len(metadata['v7_outputs']),820)
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
