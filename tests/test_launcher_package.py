"""Package boundary checks use synthetic disc bytes and never launch the game."""
from pathlib import Path
import ast
import importlib.util
import json
import re
import shutil
import subprocess
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
    def test_release_checker_and_verified_https_runtime_are_packaged(self):
        with patch.object(package, 'hd_sources', return_value={}):
            plan = package.sources()
        self.assertIn('payload/release_check.py', plan)
        self.assertIn('payload/release_download.py', plan)
        self.assertIn('payload/release_update.py', plan)
        for name in ('_ssl.pyd', 'libssl-3.dll', 'libcrypto-3.dll', '_socket.pyd', 'select.pyd', 'unicodedata.pyd'):
            self.assertIn('payload/python/' + name, plan)

    @unittest.skipUnless(sys.platform == 'win32' and (package.PYTHON / 'python.exe').is_file(),
                         'Windows embedded Python is required')
    def test_shipped_python_can_import_https_checker_with_verified_tls(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = Path(folder)
            runtime = payload / 'python'
            runtime.mkdir()
            for name in package.PYTHON_FILES:
                shutil.copyfile(package.PYTHON / name, runtime / name)
            (runtime / 'python312._pth').write_text(package.GENERATED['payload/python/python312._pth'])
            shutil.copyfile(ROOT / 'launcher/release_check.py', payload / 'release_check.py')
            smoke = subprocess.run([str(runtime / 'python.exe'), '-B', '-c',
                "import release_check,ssl; context=ssl.create_default_context(); "
                "assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED; "
                "assert 'api.github.com'.encode('idna')==b'api.github.com'"],
                capture_output=True, text=True, timeout=15)
            self.assertEqual(smoke.returncode, 0, smoke.stderr)

    def test_release_version_agrees_across_both_exes_backend_and_platform_labels(self):
        version = package.VERSION
        assembly_version = '.'.join((version.split('.') + ['0'] * 4)[:4])
        backend = ast.parse((ROOT / 'launcher/setup_backend.py').read_text(encoding='utf-8'))
        value = next(ast.literal_eval(node.value) for node in backend.body
                     if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and
                     target.id == 'PACKAGE_VERSION' for target in node.targets))
        self.assertEqual(value, version)
        for name in ('Launcher.cs', 'DirectPlay.cs'):
            source = (ROOT / 'launcher' / name).read_text(encoding='utf-8')
            for attribute in ('AssemblyVersion', 'AssemblyFileVersion', 'AssemblyInformationalVersion'):
                found = re.findall(attribute + r'\("([^"]+)"\)', source)
                self.assertEqual(found, [version if attribute == 'AssemblyInformationalVersion' else assembly_version])
        self.assertIn('assemblyIdentity version="' + assembly_version + '"',
                      (ROOT / 'launcher/app.manifest').read_text(encoding='utf-8'))
        self.assertIn('DARKER EDITION   /   ' + version + '"',
                      (ROOT / 'launcher/MainWindow.xaml').read_text(encoding='utf-8'))
        self.assertIn('Darkwatch: Darker Edition - ' + version + '\n', package.GENERATED['README.txt'])
        self.assertTrue((ROOT / 'launcher/linux/README-LINUX.md').read_text(encoding='utf-8').startswith(
            '# Darkwatch: Darker Edition ' + version + ' —'))

    def test_spanish_is_generated_from_own_disc_without_bundled_game_text(self):
        with patch.object(package, 'hd_sources', return_value={}):
            plan = package.sources()
        for name in ('payload/language/es/language_text.bin', 'payload/spanish-text-catalog.json', 'payload/spanish-catalog.json'):
            self.assertNotIn(name, plan)
        for module in ('ps2_spanish.py', 'ps2_disc.py', 'ps2_text.py', 'ps2_dialogue.py', 'ps2_movies.py'):
            self.assertIn('payload/' + module, plan)
        self.assertIn('payload/ps2-spanish-catalog.json', plan)
        self.assertIn('payload/ps2-spanish-corrections.json', plan)
        self.assertFalse(any(Path(name).suffix.lower() in ('.pck', '.xmv', '.wav', '.bin') for name in plan))
        with tempfile.TemporaryDirectory() as folder, patch.object(package, 'REPO', Path(folder)):
            root = Path(folder)
            source_name = 'xbexbe/src/common/language.cpp'
            source = root / source_name
            source.parent.mkdir(parents=True)
            source.write_bytes(b'fixture v3 reader')
            build = {'host_sources': {'files': [{'path': source_name, 'sha256': package.sha(source)}]}}
            catalog = root / 'catalog.json'
            row = dict(size=32, sha256='a' * 64)
            data = dict(schema_version=1, language='es', files={name: row for name in
                ('language_text.bin', 'assets/audioDlg.pck', 'assets/Movies2.pck', 'assets/Movies3.pck', 'assets/Movies4.pck')})
            catalog.write_text(json.dumps(data))
            plan = {'payload/ps2-spanish-catalog.json': catalog}
            package.check_spanish_text(plan, build)
            for name in ('payload/spanish-catalog.json', 'payload/spanish-text-catalog.json', 'payload/language/es/language_text.bin'):
                with self.assertRaisesRegex(ValueError, 'Bundled game translations'):
                    package.check_spanish_text(dict(plan, **{name: root / 'old.bin'}), build)
            catalog.write_text(json.dumps(dict(data, files={'language_text.bin': row})))
            with self.assertRaisesRegex(ValueError, 'complete PS2 Spanish'):
                package.check_spanish_text(plan, build)
            catalog.write_text(json.dumps(data))
            source.write_bytes(b'different reader')
            with self.assertRaisesRegex(ValueError, 'reader differs'):
                package.check_spanish_text(plan, build)

    def test_only_recorded_release_runtime_can_be_packaged(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(package, 'REPO', Path(folder)):
            root = Path(folder) / 'build/xbexbe-release'
            root.mkdir(parents=True)
            exe = root / 'darkwatch_xbe.exe'
            exe.write_bytes(b'release runtime fixture')
            manifest = root / 'build-manifest.json'
            sdk_patch = package.REPO / 'patches/xbexbe.patch'
            sdk_patch.parent.mkdir()
            sdk_patch.write_bytes(b'fixture SDK patch')
            info = {'executable': {'sha256': package.sha(exe)}, 'release_profile': package.RELEASE_PROFILE,
                    'toolchain': {'build_patch': {'sha256': package.sha(sdk_patch)}}}
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

    def test_current_sdk_patch_must_match_recorded_runtime_build(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(package, 'REPO', Path(folder)):
            root = package.REPO / 'build/xbexbe-release'
            root.mkdir(parents=True)
            exe = root / 'darkwatch_xbe.exe'
            exe.write_bytes(b'fixture runtime')
            sdk_patch = package.REPO / 'patches/xbexbe.patch'
            sdk_patch.parent.mkdir()
            sdk_patch.write_bytes(b'compiled SDK fixes')
            manifest = root / 'build-manifest.json'
            info = {'executable': {'sha256': package.sha(exe)}, 'release_profile': package.RELEASE_PROFILE,
                    'toolchain': {'build_patch': {'sha256': package.sha(sdk_patch)}}}
            plan = {'payload/runtime/darkwatch_xbe.exe': exe}
            manifest.write_text(json.dumps(info))
            self.assertEqual(package.check_sources(plan), package.sha(exe))
            sdk_patch.write_bytes(b'new shader fix not compiled yet')
            with self.assertRaisesRegex(ValueError, 'SDK patch differs'):
                package.check_sources(plan)
            sdk_patch.write_bytes(b'compiled SDK fixes')
            manifest.write_text(json.dumps(dict(info, toolchain={})))
            with self.assertRaisesRegex(ValueError, 'SDK patch differs'):
                package.check_sources(plan)
            manifest.write_text(json.dumps(info))
            sdk_patch.unlink()
            with self.assertRaisesRegex(ValueError, 'SDK patch differs'):
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
        plan = package.sources()
        for name in ('revolver_content.py', 'revolver_scripts.py'):
            self.assertEqual(plan['payload/' + name], ROOT / 'launcher' / name)
        with tempfile.TemporaryDirectory() as folder, patch.object(package,'REPO',Path(folder)):
            root = Path(folder)
            source_name = 'xbexbe/src/common/character_content.cpp'
            source = root/source_name
            source.parent.mkdir(parents=True)
            source.write_text('\n'.join(f'{name} {size} {digest}' for name,(size,digest) in character_content.INSTALLED.items()))
            build = {'host_sources': {'files': [{'path':source_name,'sha256':package.sha(source)}]}}
            shutil.copyfile(ROOT/'launcher/character-catalog.json',root/'character-catalog.json')
            plan = {'payload/character-catalog.json':root/'character-catalog.json'}
            for character in ('cassidy', 'tala'):
                for size in (1024,256):
                    name = f'{character}-hands-{size}.dds'
                    shutil.copyfile(ROOT/'launcher/assets'/name,root/name)
                    plan['payload/character-art/'+name] = root/name
            package.check_character_catalog(plan,build)
            old = source.read_bytes()
            source.write_bytes(old+b'changed')
            with self.assertRaisesRegex(ValueError,'differs from the runtime'):
                package.check_character_catalog(plan,build)
            source.write_bytes(old)
            for character in ('cassidy', 'tala'):
                art = root/f'{character}-hands-256.dds'
                original = art.read_bytes()
                art.write_bytes(b'wrong authored art')
                with self.assertRaisesRegex(ValueError,'approved conversion'):
                    package.check_character_catalog(plan,build)
                art.write_bytes(original)

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
            with patch.object(package, 'sources', return_value=plan), patch.object(package, 'check_build', return_value={'executable': {'sha256': package.sha(exe)}}) as check_build:
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
                # Linux packaging uses this same verifier for an existing Windows payload.
                check_build.side_effect = ValueError('SDK patch differs from the runtime build; rebuild it first.')
                with self.assertRaisesRegex(ValueError, 'SDK patch differs'):
                    package.verify(out)
                check_build.side_effect = None
                check_build.return_value = {'executable': {'sha256': '1' * 64}}
                with self.assertRaisesRegex(ValueError, 'Packaged runtime differs'):
                    package.verify(out)
                check_build.return_value = {'executable': {'sha256': package.sha(exe)}}
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
