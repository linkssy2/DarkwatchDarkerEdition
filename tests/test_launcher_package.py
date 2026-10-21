"""Package boundary checks use synthetic disc bytes and never launch the game."""
from pathlib import Path
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
SPEC = importlib.util.spec_from_file_location('launcher_package', ROOT / 'launcher/package.py')
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class LauncherPackageTests(unittest.TestCase):
    def test_only_recorded_release_runtime_can_be_packaged(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(package, 'REPO', Path(folder)):
            root = Path(folder) / 'build/xbexbe-release'
            root.mkdir(parents=True)
            exe = root / 'darkwatch_xbe.exe'
            exe.write_bytes(b'release runtime fixture')
            manifest = root / 'build-manifest.json'
            info = {'executable': {'sha256': package.sha(exe)}, 'release_profile': package.RELEASE_PROFILE}
            plan = {'payload/runtime/darkwatch_xbe.exe': exe}
            manifest.write_text(json.dumps(info))
            self.assertEqual(package.check_sources(plan), package.sha(exe))
            for invalid in (None, {'name': 'diagnostic'}, dict(package.RELEASE_PROFILE, diagnostics=True),
                            dict(package.RELEASE_PROFILE, strict_assets=False)):
                manifest.write_text(json.dumps(dict(info, release_profile=invalid)))
                with self.assertRaisesRegex(ValueError, 'quiet release-candidate'):
                    package.check_sources(plan)
            manifest.write_text(json.dumps(info))
            exe.write_bytes(b'different runtime')
            with self.assertRaisesRegex(ValueError, 'Runtime differs'):
                package.check_sources(plan)

    def test_exact_allowlist_and_original_payload_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'payload').mkdir()
            good = root / 'payload/runtime.exe'
            good.write_bytes(b'host runtime fixture')
            expected = {'payload/runtime.exe': package.sha(good)}
            self.assertEqual(package.audit(root, expected, set()), expected)
            for name in ('default.xbe', 'disc.iso', 'disc.xiso', 'packfile.pck', 'hd-ui.pack', 'settings.toml',
                         'gameplay-hd/texture.dwt', 'optional-textures.zip', 'hdd/save.bin'):
                extra = root / name
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_bytes(b'not allowed')
                with self.assertRaises(ValueError):
                    package.audit(root, expected, set())
                extra.unlink()
            with self.assertRaises(ValueError):
                package.audit(root, expected, {package.sha(good)})
            good.write_bytes(b'changed runtime')
            with self.assertRaises(ValueError):
                package.audit(root, expected, set())

    def test_optional_texture_download_stays_out_of_base_package(self):
        with patch.object(package, 'hd_sources', return_value={}):
            plan = package.sources()
        self.assertIn('payload/gameplay_hd.py', plan)
        self.assertIn('payload/gameplay-hd-catalog.json', plan)
        self.assertTrue(all(Path(name).suffix.lower() not in ('.dwt', '.pack') for name in plan))
        self.assertEqual([name for name in plan if name.endswith('.zip')], ['payload/python/python312.zip'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / 'replacement.dwt'
            file.write_bytes(b'DWGAME02fixture')
            with self.assertRaisesRegex(ValueError, 'Forbidden'):
                package.audit(root, {'replacement.dwt': package.sha(file)}, set())

    def test_optional_texture_catalog_matches_runtime_build(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(package, 'REPO', Path(folder)):
            root = Path(folder)
            metadata_name = 'xbexbe/config/gameplay_hd_assets.json'
            header_name = 'xbexbe/src/common/gameplay_texture_assets.h'
            metadata, header = root / metadata_name, root / header_name
            metadata.parent.mkdir(parents=True)
            header.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({'textures': [{'name': 'fixture', 'width': 2, 'height': 2, 'dds_mips': 2}]}))
            header.write_text('compiled metadata fixture')
            build = {'host_sources': {'files': [{'path': name, 'sha256': package.sha(root / name)}
                                               for name in (metadata_name, header_name)]}}
            catalog = root / 'catalog.json'
            good = {'schema_version': 1, 'kind': 'darkwatch-gameplay-hd', 'version': '1',
                    'texture_catalog_sha256': package.sha(metadata),
                    'files': [{'path': 'gameplay-hd/fixture.dwt', 'size': 60, 'sha256': 'a' * 64}]}
            catalog.write_text(json.dumps(good))
            package.check_texture_catalog(catalog, build)
            for changed in (dict(good, texture_catalog_sha256='0' * 64), dict(good, files=[]),
                            dict(good, files=good['files'] * 2),
                            dict(good, files=[dict(good['files'][0], size=61)])):
                catalog.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'catalog is stale'):
                    package.check_texture_catalog(catalog, build)
            catalog.write_text(json.dumps(good))
            for file in (metadata, header):
                original = file.read_bytes()
                file.write_bytes(original + b' ')
                with self.assertRaisesRegex(ValueError, 'differs from the runtime build'):
                    package.check_texture_catalog(catalog, build)
                file.write_bytes(original)

    def test_character_archive_pins_and_authored_art_match_runtime(self):
        import character_content
        with tempfile.TemporaryDirectory() as folder, patch.object(package,'REPO',Path(folder)):
            root = Path(folder)
            source_name = 'xbexbe/src/common/character_content.cpp'
            source = root/source_name
            source.parent.mkdir(parents=True)
            source.write_text('\n'.join(f'{name} {size} {digest}' for name,(size,digest) in character_content.INSTALLED.items()))
            build = {'host_sources': {'files': [{'path':source_name,'sha256':package.sha(source)}]}}
            shutil.copyfile(ROOT/'launcher/character-catalog.json',root/'character-catalog.json')
            plan = {'payload/character-catalog.json':root/'character-catalog.json'}
            for size in (1024,256):
                name = f'cassidy-hands-{size}.dds'
                shutil.copyfile(ROOT/'launcher/assets'/name,root/name)
                plan['payload/character-art/'+name] = root/name
            package.check_character_catalog(plan,build)
            old = source.read_bytes()
            source.write_bytes(old+b'changed')
            with self.assertRaisesRegex(ValueError,'differs from the runtime'):
                package.check_character_catalog(plan,build)
            source.write_bytes(old)
            (root/'cassidy-hands-256.dds').write_bytes(b'wrong authored art')
            with self.assertRaisesRegex(ValueError,'approved conversion'):
                package.check_character_catalog(plan,build)

    def test_hd_artwork_only_referenced_and_no_traversal(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(package, 'REPO', Path(folder)):
            art = Path(folder) / 'xbexbe/hd_ui'
            art.mkdir(parents=True)
            overrides = art / 'overrides.toml'
            overrides.write_text('[[texture]]\nfile="approved.png"\n[[texture.region]]\nfile="cell.png"\n')
            (art / 'approved.png').write_bytes(b'art')
            (art / 'old-unused.png').write_bytes(b'old art')
            names = set(package.hd_sources())
            self.assertEqual(names, {'payload/hd_ui/overrides.toml', 'payload/hd_ui/approved.png', 'payload/hd_ui/cell.png'})
            for invalid in ('../original.png', 'C:/original.png', 'sub\\\\original.png', 'movie.xmv'):
                overrides.write_text('[[texture]]\nfile=' + json.dumps(invalid) + '\n')
                with self.assertRaises(ValueError):
                    package.hd_sources()

    def test_fresh_assembly_finalization_and_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            disc = source / 'supported-disc.json'
            disc.write_text(json.dumps({'files': {'default.xbe': {'sha256': '0' * 64}}}))
            exe = source / 'runtime.exe'
            exe.write_bytes(b'fixture host program')
            plan = {'payload/supported-disc.json': disc, 'payload/runtime/darkwatch_xbe.exe': exe}
            out = root / 'package'
            with patch.object(package, 'sources', return_value=plan), patch.object(package, 'check_sources', return_value=package.sha(exe)):
                info = package.assemble(out)
                self.assertFalse(info['complete'])
                self.assertEqual((out / 'payload/python/python312._pth').read_text(), 'python312.zip\n.\n..\n')
                with self.assertRaises(ValueError):
                    package.assemble(out)
                with self.assertRaises(ValueError):
                    package.finalize(out)
                (out / package.LAUNCHER).write_bytes(b'fixture compiled launcher')
                with self.assertRaisesRegex(ValueError, 'both launch executables'):
                    package.finalize(out)
                (out / package.DIRECT_PLAY).write_bytes(b'fixture compiled direct play')
                complete = package.finalize(out)
                self.assertTrue(complete['complete'])
                self.assertEqual(complete['release_profile'], package.RELEASE_PROFILE)
                self.assertEqual(package.verify(out), complete['files'])
                with self.assertRaises(ValueError):
                    package.finalize(out)
                for name in (package.LAUNCHER, package.DIRECT_PLAY):
                    original = (out / name).read_bytes()
                    (out / name).write_bytes(b'tampered')
                    with self.assertRaises(ValueError):
                        package.verify(out)
                    (out / name).write_bytes(original)


if __name__ == '__main__':
    unittest.main()
