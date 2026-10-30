"""Exercise setup transactions with tiny synthetic XDVDFS discs and a harmless EXE."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(ROOT / 'launcher'))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


intake = sys.modules.get("intake") or load("intake", ROOT / "tools/intake.py")
bonus = sys.modules.get("bonus_content") or load("bonus_content", ROOT / "launcher/bonus_content.py")
gameplay_hd = sys.modules.get("gameplay_hd") or load("gameplay_hd", ROOT / "launcher/gameplay_hd.py")
language_pack = sys.modules.get("language_pack") or load("language_pack", ROOT / "launcher/language_pack.py")
for name in ('character_animation', 'character_archive', 'character_assets', 'character_repaint', 'character_content'):
    if name not in sys.modules:
        load(name, ROOT / 'launcher' / (name + '.py'))
characters = sys.modules['character_content']
setup = load("darkwatch_setup_backend", ROOT / "launcher/setup_backend.py")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_iso(path, data, offset=0, bad_name=None, cycle=False):
    table = bytearray(2048)
    cursor, sectors = 0, []
    for index, (name, blob) in enumerate(data.items()):
        encoded = (bad_name if index == 0 and bad_name else name).encode("ascii")
        next_cursor = (cursor + 14 + len(encoded) + 3) & ~3
        right = next_cursor // 4 if index < len(data) - 1 else 0
        if cycle and index == 1:
            right = cursor // 4
        sector = 41 + index
        struct.pack_into("<HHIIBB", table, cursor, 0, right, sector, len(blob), 32, len(encoded))
        table[cursor + 14:cursor + 14 + len(encoded)] = encoded
        sectors.append((sector, blob))
        cursor = next_cursor
    descriptor = bytearray(2048)
    descriptor[:20] = descriptor[-20:] = intake.MAGIC
    struct.pack_into("<II", descriptor, 20, 40, cursor)
    with path.open("wb") as target:
        target.seek(offset + 0x10000)
        target.write(descriptor)
        target.seek(offset + 40 * 2048)
        target.write(table)
        for sector, blob in sectors:
            target.seek(offset + sector * 2048)
            target.write(blob)


class LauncherSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix="darkwatch-launcher-worker-")
        cls.worker_dir = Path(cls.fixture.name)
        compiler = shutil.which("clang++") or shutil.which("g++")
        if not compiler:
            known = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/Llvm/x64/bin/clang++.exe")
            compiler = str(known) if known.is_file() else None
        if not compiler:
            raise unittest.SkipTest("A C++ compiler is required for the harmless native setup worker")
        source = cls.worker_dir / "worker.cpp"
        source.write_text(r'''#include <fstream>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <thread>
#include <chrono>
#include <iostream>
int main(int n,char**a){if(n==4){if(std::getenv("DARKWATCH_TEST_BUILDER_FAIL")){std::cerr<<"fixture preparation failed";return 7;}
if(std::getenv("DARKWATCH_TEST_BUILDER_WAIT"))std::this_thread::sleep_for(std::chrono::seconds(10));
std::ofstream f(a[2],std::ios::binary);f<<"synthetic HD pack";return f?0:3;}
if(n==2&&!std::strcmp(a[1],"--prepare-shaders")){
 std::string mode=std::getenv("WORKER_SHADER_MODE")?std::getenv("WORKER_SHADER_MODE"):"warm";
 if(mode=="silent")return 0;
 if(mode=="fail"){std::cerr<<"fixture shader failure";return 7;}
 if(mode=="error"){std::cout<<R"({"state":"error","message":"fixture native shader error"})"<<std::endl;return 7;}
 if(mode=="oversize"){std::cout<<std::string(20000,'x')<<std::endl;return 0;}
 if(mode!="warm"){
  std::filesystem::create_directory("cache");std::ofstream("cache/prepared.fixture")<<"one completed job";
  std::cout<<R"({"state":"shader_prepare","completed":1,"total":2,"progress":50})"<<std::endl;
  if(mode=="repeat")std::cout<<R"({"state":"shader_prepare","completed":1,"total":2,"progress":50})"<<std::endl;
  if(mode=="wait")std::this_thread::sleep_for(std::chrono::seconds(20));
  if(mode!="incomplete")std::cout<<R"({"state":"shader_prepare","completed":2,"total":2,"progress":100})"<<std::endl;
 }
 std::cout<<R"({"state":"shader_ready"})"<<std::endl;
 return mode=="ready-fail"?8:0;
}
if(std::getenv("WORKER_TEST_EXIT"))return 22;
std::ofstream f("worker-ran.txt"); f<<"harmless launcher fixture"; return f?0:4;}
''')
        cls.worker = cls.worker_dir / "worker.exe"
        built = subprocess.run([compiler, "-std=c++17", str(source), "-o", str(cls.worker)], capture_output=True, text=True)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="darkwatch-launcher-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Never inspect or migrate the developer's real launcher installation.
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "LocalAppData")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.package = self.root / "package"
        self.payload = self.package / "payload"
        (self.payload / "runtime").mkdir(parents=True)
        (self.payload / "hd_ui").mkdir()
        (self.payload / "hd_ui/overrides.toml").write_text("# test fixture\n")
        shutil.copyfile(ROOT / "tools/intake.py", self.payload / "intake.py")
        shutil.copyfile(ROOT / "launcher/setup_backend.py", self.payload / "setup_backend.py")
        shutil.copyfile(ROOT / "launcher/release_check.py", self.payload / "release_check.py")
        shutil.copyfile(ROOT / "launcher/release_update.py", self.payload / "release_update.py")
        shutil.copyfile(ROOT / "launcher/release_download.py", self.payload / "release_download.py")
        shutil.copyfile(ROOT / "launcher/installed_source.py", self.payload / "installed_source.py")
        shutil.copyfile(ROOT / "launcher/bonus_content.py", self.payload / "bonus_content.py")
        shutil.copyfile(ROOT / "launcher/gameplay_hd.py", self.payload / "gameplay_hd.py")
        shutil.copyfile(ROOT / "launcher/language_pack.py", self.payload / "language_pack.py")
        for name in ('character_animation.py', 'character_archive.py', 'character_assets.py',
                     'character_repaint.py', 'character_content.py', 'character_boss.py',
                     'character_boss_effects.py', 'character_spectral_hands.py', 'character_hand_seams.py',
                     'character_secondary.py', 'character_preview.py', 'character_roster.py', 'character_tala.py',
                     'revolver_content.py', 'revolver_scripts.py',
                     'character-catalog.json'):
            shutil.copyfile(ROOT / 'launcher' / name, self.payload / name)
        (self.payload / 'character-art').mkdir()
        for character in ('cassidy', 'tala'):
            for size in (1024, 256):
                name = f'{character}-hands-{size}.dds'
                shutil.copyfile(ROOT / 'launcher/assets' / name, self.payload / 'character-art' / name)
        self.texture = b"DWGAME02" + struct.pack("<4IQ", 1, 1, 1, 4, 1) + b"RGBA" + b"12345678"
        self.catalog = dict(schema_version=1, kind="darkwatch-gameplay-hd", version="1", texture_catalog_sha256="1" * 64,
                            files=[dict(path="gameplay-hd/example.dwt", size=len(self.texture), sha256=sha(self.texture))])
        (self.payload / "gameplay-hd-catalog.json").write_text(json.dumps(self.catalog))
        for name in (setup.EXE, "darkwatch_hd_ui_builder.exe"):
            shutil.copyfile(self.worker, self.payload / "runtime" / name)
        self.data = {"default.xbe": b"XBEH supported fixture", "packfile.pck": b"original texture fixture", "audio.pck": b"sound fixture"}
        self.installed_data = dict(self.data, **{"packfile.pck": b"ORiginal TExture FIxture"})
        selectors = patch.multiple(bonus, ORIGINAL_SHA256=sha(self.data["packfile.pck"]),
                                   INSTALLED_SHA256=sha(self.installed_data["packfile.pck"]),
                                   PATCHES=((0, b"or", b"OR"), (9, b"te", b"TE"), (17, b"fi", b"FI")))
        selectors.start()
        self.addCleanup(selectors.stop)
        def fixture_characters(assets, payload, cancel, progress):
            # Archive/character conversion has its own tests. Here the tiny
            # synthetic disc exercises the real outer installation transaction.
            cancel()
            target = assets / 'packfile.pck'
            target.write_bytes(bonus.patch_pack(target.read_bytes()))
        fixture = patch.multiple(characters, prepare=fixture_characters,
                                 INSTALLED={'packfile.pck': (len(self.installed_data['packfile.pck']),
                                                            sha(self.installed_data['packfile.pck']))})
        fixture.start()
        self.addCleanup(fixture.stop)
        # Tiny setup fixtures are not PCK archives; the real recovery codec has
        # its own synthetic and original-disc reconstruction tests.
        def capture_source(assets, recovery, originals, cancel):
            recovery.mkdir()
            for name in originals:
                cancel()
                (recovery / (name + '.tail')).write_bytes((assets / name).read_bytes())
        def restore_source(assets, recovery, target, originals, cancel):
            target.mkdir()
            for name, pin in originals.items():
                cancel()
                raw = (recovery / (name + '.tail')).read_bytes()
                if len(raw) != pin['size'] or sha(raw) != pin['sha256']:
                    raise ValueError('Source recovery is damaged')
                (target / name).write_bytes(raw)
        recovery = patch.multiple(setup.installed_source, capture=capture_source, restore=restore_source,
                                  has_recovery=lambda folder, originals: all((folder / (name + '.tail')).is_file() for name in originals))
        recovery.start()
        self.addCleanup(recovery.stop)
        def fixture_preview(assets, output, cancel):
            # Preview codec has focused tests; exercise its real transaction here.
            cancel()
            data = b'synthetic private preview cache'
            output.write_bytes(data)
            return dict(version=setup.character_preview.VERSION, size=len(data), sha256=sha(data))
        preview = patch.object(setup.character_preview, 'prepare', side_effect=fixture_preview)
        preview.start()
        self.addCleanup(preview.stop)
        self.disc = dict(schema_version=1, xbe_sha256=sha(self.data["default.xbe"]),
                         files=[dict(path=name, size=len(blob), sha256=sha(blob)) for name, blob in self.data.items()])
        (self.payload / "supported-disc.json").write_text(json.dumps(self.disc))
        self.repin()
        self.iso = self.root / "my disc.iso"
        make_iso(self.iso, self.data)
        self.install = self.package / "GameData"
        self.events = []
        self.backend = setup.Setup(self.package, self.install, notify=lambda event, message, **kw: self.events.append(dict(event=event, message=message, **kw)))
        self.running = patch.object(setup, "game_running", return_value=False)
        self.running.start()
        self.addCleanup(self.running.stop)

    def repin(self):
        pins = {p.relative_to(self.package).as_posix(): sha(p.read_bytes()) for p in self.payload.rglob("*") if p.is_file()}
        (self.package / "package-manifest.json").write_text(json.dumps(dict(version=setup.PACKAGE_VERSION, complete=True,
                release_profile=setup.RELEASE_PROFILE, runtime_sha256=pins["payload/runtime/" + setup.EXE], files=pins)))

    def install_disc(self):
        with setup.exclusive(self.install):
            return Path(self.backend.import_iso(self.iso)["install_dir"])

    def install_direct(self):
        with setup.exclusive(self.install):
            return Path(self.backend.use_iso(self.iso)["install_dir"])

    def test_direct_iso_keeps_source_and_only_prepared_host_assets(self):
        before = self.iso.read_bytes()
        current = self.install_direct()
        self.assertEqual(self.iso.read_bytes(), before)
        self.assertEqual(set(self.snapshot(current / 'assets')), {'default.xbe', 'packfile.pck'})
        self.assertFalse((current / 'source-recovery').exists())
        marker = setup.tomllib.loads((current / setup.DISC_SOURCE).read_text(encoding='utf-8'))
        self.assertEqual(marker, dict(schema_version=1, path=str(self.iso), overrides=['packfile.pck']))
        state = self.backend.status()
        self.assertTrue(state['ready'])
        self.assertTrue(state['iso_available'])
        self.assertEqual(state['source_mode'], 'iso')
        self.assertEqual(state['iso_path'], str(self.iso))
        self.assertEqual(self.backend.verify(), current)

    def test_drop_in_iso_prepares_direct_source_and_existing_install_wins(self):
        folder = self.package / 'assets'
        folder.mkdir()
        iso = folder / 'My Xbox Disc.XISO'
        shutil.copyfile(self.iso, iso)
        before = iso.read_bytes()
        with setup.exclusive(self.install):
            self.assertTrue(self.backend.use_drop_in_iso(folder))
        current = self.backend.active()
        self.assertEqual(self.backend.status()['iso_path'], str(iso))
        self.assertEqual(set(self.snapshot(current / 'assets')), {'default.xbe', 'packfile.pck'})
        self.assertEqual(iso.read_bytes(), before)
        self.assertTrue(any(event.get('automatic_setup') for event in self.events))
        (folder / 'other.iso').write_bytes(b'unsupported extra disc')
        snapshot = self.snapshot(current)
        with patch.object(self.backend, 'use_iso', side_effect=AssertionError('Existing install must win')):
            self.assertFalse(self.backend.use_drop_in_iso(folder))
            iso.unlink()
            self.assertFalse(self.backend.use_drop_in_iso(folder))
        self.assertEqual(self.snapshot(current), snapshot)

    def test_drop_in_iso_empty_multiple_and_unsupported_never_install(self):
        folder = self.package / 'assets'
        self.assertFalse(self.backend.use_drop_in_iso(folder))
        folder.mkdir()
        (folder / 'README.txt').write_text('instructions')
        self.assertFalse(self.backend.use_drop_in_iso(folder))
        (folder / 'one.iso').write_bytes(b'not an Xbox image')
        (folder / 'two.XISO').write_bytes(b'not another Xbox image')
        with self.assertRaisesRegex(setup.SetupError, 'Several disc images'):
            self.backend.use_drop_in_iso(folder)
        (folder / 'two.XISO').unlink()
        before = self.snapshot(folder)
        with setup.exclusive(self.install), self.assertRaises((setup.SetupError, intake.IntakeError)):
            self.backend.use_drop_in_iso(folder)
        self.assertIsNone(self.backend.active())
        self.assertEqual(self.snapshot(folder), before)

    def test_drop_in_play_dispatch_prepares_before_launch_and_stops_on_error(self):
        folder = self.package / 'assets'
        folder.mkdir()
        iso = folder / 'game.iso'
        iso.write_bytes(b'unsupported disc')
        arguments = ['--package', str(self.package), '--install-root', str(self.install),
                     '--auto-iso-folder', str(folder), '--play']
        with patch.object(setup, 'Setup', return_value=self.backend), patch.object(setup, 'emit'), \
             patch.object(self.backend, 'play', return_value=dict(installed=True, ready=True, message='Prepared then launched')) as play:
            self.assertEqual(setup.main(arguments), 1)
            play.assert_not_called()
            shutil.copyfile(self.iso, iso)
            self.assertEqual(setup.main(arguments), 0)
            play.assert_called_once()
        self.assertEqual(self.backend.status()['iso_path'], str(iso))
        self.assertEqual(self.backend.verify(), self.backend.active())

    def test_direct_iso_rejects_unextracted_corrupt_data_without_replacing_install(self):
        current = self.install_disc()
        before = self.snapshot(current)
        make_iso(self.iso, dict(self.data, **{'audio.pck': b'wrong fixture'}))
        with self.assertRaisesRegex(setup.SetupError, 'damaged or unsupported audio.pck'):
            self.install_direct()
        self.assertEqual(self.backend.active(), current)
        self.assertEqual(self.snapshot(current), before)
        self.assertEqual(list((self.install / 'versions').iterdir()), [current])

    def test_direct_iso_missing_source_is_recoverable_without_mutation(self):
        current = self.install_direct()
        before = self.snapshot(current)
        self.iso.unlink()
        state = self.backend.status()
        self.assertFalse(state['ready'])
        self.assertFalse(state['iso_available'])
        self.assertEqual(state['source_mode'], 'iso')
        with patch.object(setup.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(setup.SetupError, 'ISO is unavailable'):
                self.backend.play()
            launch.assert_not_called()
        self.assertEqual(self.snapshot(current), before)

    def test_direct_iso_relocation_reuses_preparation_and_user_data(self):
        current = self.install_direct()
        (current / 'hdd').mkdir()
        (current / 'hdd/save').write_bytes(b'progress')
        before = self.snapshot(current)
        self.iso = self.iso.rename(self.root / 'Moved Español 🦇.iso')
        with patch.object(characters, 'prepare', side_effect=AssertionError('unnecessary content rebuild')):
            result = self.backend.use_iso(self.iso)
        self.assertTrue(result['ready'])
        self.assertEqual(result['iso_path'], str(self.iso))
        self.assertEqual(self.backend.active(), current)
        after = self.snapshot(current)
        for name in before.keys() - {'install.json', setup.DISC_SOURCE}:
            self.assertEqual(before[name], after[name], name)
        self.assertEqual(list((self.install / 'versions').iterdir()), [current])

    def test_direct_iso_runtime_and_content_updates_reuse_same_install(self):
        current = self.install_direct()
        preserved = {setup.SETTINGS: b'bindings', 'hdd/save': b'solo', 'hdd2/save': b'coop',
                     'cache/shader': b'cache', 'gameplay-hd/custom': b'HD', 'language/es/private': b'Spanish'}
        for name, data in preserved.items():
            path = current / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        assets = self.snapshot(current / 'assets')
        marker = (current / setup.DISC_SOURCE).read_bytes()
        (self.payload / 'runtime/new-runtime.dll').write_bytes(b'new runtime')
        self.repin()
        self.backend = setup.Setup(self.package, self.install, notify=lambda *a, **k: None)
        with patch.object(self.backend, 'read_iso_files', side_effect=AssertionError('unneeded ISO asset read')), \
                patch.object(characters, 'prepare', side_effect=AssertionError('unneeded conversion')):
            self.assertTrue(self.backend.update()['ready'])
        record = setup.read_json(current / 'install.json')
        record['content_revision'] = 'older-direct-content'
        setup.write_json(current / 'install.json', record)
        self.assertTrue(self.backend.status()['update_available'])
        self.assertTrue(self.backend.update()['ready'])
        self.assertEqual(self.backend.active(), current)
        self.assertEqual(list((self.install / 'versions').iterdir()), [current])
        self.assertEqual(self.snapshot(current / 'assets'), assets)
        self.assertEqual((current / setup.DISC_SOURCE).read_bytes(), marker)
        for name, data in preserved.items():
            self.assertEqual((current / name).read_bytes(), data, name)
        self.assertFalse(list(current.glob('.update-*')))

    def test_direct_iso_relocated_old_revision_updates_without_second_install(self):
        current = self.install_direct()
        record = setup.read_json(current / 'install.json')
        record['content_revision'] = 'older-direct-content'
        setup.write_json(current / 'install.json', record)
        self.iso = self.iso.rename(self.root / 'relocated.iso')
        self.assertTrue(self.backend.use_iso(self.iso)['ready'])
        self.assertEqual(list((self.install / 'versions').iterdir()), [current])
        self.assertEqual(self.backend.verify(), current)

    def test_direct_iso_interrupted_location_repair_is_retryable(self):
        current = self.install_direct()
        original_receipt = (current / 'install.json').read_bytes()
        assets = self.snapshot(current / 'assets')
        self.iso = self.iso.rename(self.root / 'relocated.iso')
        writer = setup.write_json
        def interrupt(path, value):
            if path == current / 'install.json':
                raise OSError('interrupted source receipt')
            return writer(path, value)
        with patch.object(setup, 'write_json', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted source receipt'):
                self.backend.use_iso(self.iso)
        self.assertEqual((current / 'install.json').read_bytes(), original_receipt)
        self.assertFalse(self.backend.status()['ready'])
        with patch.object(characters, 'prepare', side_effect=AssertionError('unnecessary rebuild')):
            self.assertTrue(self.backend.use_iso(self.iso)['ready'])
        self.assertEqual(self.snapshot(current / 'assets'), assets)
        self.assertEqual(self.backend.active(), current)

    def test_direct_iso_supports_full_original_disc_partition(self):
        make_iso(self.iso, self.data, offset=0x18300000)
        current = self.install_direct()
        record = setup.read_json(current / 'install.json')
        self.assertEqual(record['partition_offset'], 0x18300000)
        self.assertEqual(self.backend.verify(), current)

    def test_direct_iso_source_changed_during_preparation_cannot_commit(self):
        previous = self.install_disc()
        prepare = characters.prepare
        def change_source(*args, **kwargs):
            prepare(*args, **kwargs)
            stamp = self.iso.stat().st_mtime_ns + 1_000_000_000
            os.utime(self.iso, ns=(stamp, stamp))
        before = self.snapshot(self.install)
        with patch.object(characters, 'prepare', side_effect=change_source):
            with self.assertRaisesRegex(setup.SetupError, 'ISO changed'):
                self.install_direct()
        self.assertEqual(self.backend.active(), previous)
        self.assertEqual(self.snapshot(self.install), before)

    def test_direct_iso_changed_source_and_marker_cannot_launch(self):
        current = self.install_direct()
        record = setup.read_json(current / 'install.json')
        marker = (current / setup.DISC_SOURCE).read_bytes()
        (current / setup.DISC_SOURCE).write_text('schema_version=1\npath="other.iso"\n')
        self.assertFalse(self.backend.status()['ready'])
        with self.assertRaisesRegex(setup.SetupError, 'record differs'):
            self.backend.verify()
        (current / setup.DISC_SOURCE).write_bytes(marker)
        with self.iso.open('r+b') as source:
            source.seek(43 * 2048)
            source.write(b'wrong fixture')
        self.assertFalse(self.backend.status()['ready'])
        # A preserved timestamp still cannot bypass explicit byte verification.
        os.utime(self.iso, ns=(record['iso_mtime_ns'], record['iso_mtime_ns']))
        with self.assertRaisesRegex(setup.SetupError, 'damaged or unsupported audio.pck'):
            self.backend.verify()

    def test_direct_iso_cancelled_preparation_and_update_preserve_current(self):
        previous = self.install_disc()
        before = self.snapshot(self.install)
        with patch.object(characters, 'prepare', side_effect=setup.Cancelled('cancelled')):
            with self.assertRaises(setup.Cancelled):
                self.install_direct()
        self.assertEqual(self.snapshot(self.install), before)
        self.assertEqual(self.backend.active(), previous)
        current = self.install_direct()
        record = setup.read_json(current / 'install.json')
        record['content_revision'] = 'older-direct-content'
        setup.write_json(current / 'install.json', record)
        before = self.snapshot(current)
        with patch.object(characters, 'prepare', side_effect=setup.Cancelled('cancelled')):
            with self.assertRaises(setup.Cancelled):
                self.backend.update()
        self.assertEqual(self.snapshot(current), before)

    def test_direct_iso_spanish_reads_only_required_source_into_temporary_stage(self):
        _, _, ps2, iso = self.spanish_variants()
        current = self.install_direct()
        before = self.snapshot(current / 'assets')
        def prepare(source, assets, output, cancel, notify):
            self.assertEqual(source, iso)
            self.assertEqual(set(self.snapshot(assets)), {'audio.pck', 'packfile.pck'})
            self.assertEqual((assets / 'audio.pck').read_bytes(), self.data['audio.pck'])
            self.assertEqual((assets / 'packfile.pck').read_bytes(), self.installed_data['packfile.pck'])
            self.voice_bundle(output, ps2)
        fixture = SimpleNamespace(prepare=prepare, XBOX={'audio.pck': None})
        with patch.dict(sys.modules, {'ps2_spanish': fixture}):
            result = self.backend.install_spanish(iso)
        self.assertTrue(result['spanish_audio_installed'])
        self.assertEqual(self.snapshot(current / 'assets'), before)
        self.assertFalse(list(self.install.glob('.spanish-ps2-*')))
        self.assertTrue(self.backend.spanish_valid(current))

    def make_legacy_install(self):
        legacy = Path(os.environ["LOCALAPPDATA"]) / "DarkwatchDarkerEdition"
        current = legacy / "versions" / ("a" * 32)
        current.mkdir(parents=True)
        (legacy / ".launcher.lock").write_bytes(b"\0")
        (legacy / "active.json").write_text(json.dumps(dict(version=current.name)))
        (current / "install.json").write_text(json.dumps(dict(disc_sha256=self.backend.files["payload/supported-disc.json"])))
        for relative, content in {setup.SETTINGS: b"prior controls", "hdd/E/save.dat": b"prior progress",
                                  "hdd2/E/save.dat": b"second player", "cache/shader.bin": b"prior cache",
                                  "logs/old.log": b"prior diagnostics"}.items():
            path = current / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return legacy, current

    def snapshot(self, directory):
        return {path.relative_to(directory).as_posix(): path.read_bytes()
                for path in directory.rglob("*") if path.is_file()}

    def test_real_builder_transaction_and_harmless_launch(self):
        before = self.iso.read_bytes()
        self.assertFalse(self.backend.status()["ready"])
        with patch.object(tempfile, "TemporaryFile", wraps=tempfile.TemporaryFile) as temporary:
            current = self.install_disc()
        self.assertEqual(temporary.call_args.kwargs["dir"], current)
        self.assertEqual(self.iso.read_bytes(), before)
        self.assertEqual((current / "assets/audio.pck").read_bytes(), self.data["audio.pck"])
        self.assertEqual((current / "hd-ui.pack").read_bytes(), b"synthetic HD pack")
        self.assertFalse(list(current.rglob('*.log')))
        self.assertTrue(self.backend.status()["ready"])
        self.assertEqual(self.backend.verify(), current)
        # This executable writes one marker and exits. It is never Darkwatch.
        children = []
        real_popen = subprocess.Popen
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(subprocess, "Popen", side_effect=spawn) as launched, patch.dict(os.environ, {"XBE_PERF": "1", "XBE_CAPTURE_DIR": "bad-path", "XBE_OTHER_DIAG": "1", "DARKWATCH_TEST_FLAG": "1"}):
            result = self.backend.play()
        self.assertNotIn("XBE_PERF", launched.call_args.kwargs["env"])
        self.assertNotIn("XBE_CAPTURE_DIR", launched.call_args.kwargs["env"])
        self.assertNotIn("XBE_OTHER_DIAG", launched.call_args.kwargs["env"])
        self.assertNotIn("DARKWATCH_TEST_FLAG", launched.call_args.kwargs["env"])
        self.assertEqual(children[0].wait(timeout=5), 0)
        self.assertGreater(result["pid"], 0)
        import time
        for _ in range(100):
            if (current / "worker-ran.txt").exists():
                break
            time.sleep(.02)
        self.assertEqual((current / "worker-ran.txt").read_text(), "harmless launcher fixture")

    def test_old_spanish_is_preserved_but_requires_ps2_import(self):
        current, legacy, ps2, iso = self.spanish_variants()
        self.install_old_spanish(current, legacy)
        language_pack.select(current, "es")
        before = self.snapshot(current)
        self.assertFalse(self.backend.status()["spanish_installed"])
        with self.assertRaisesRegex(setup.SetupError, "PS2 ISO import"):
            self.backend.play()
        self.assertEqual(self.snapshot(current), before)
        with patch.object(setup, "game_running", return_value=True), self.assertRaises(setup.SetupError):
            self.backend.set_language("en")
        self.assertEqual(self.snapshot(current), before)
        self.backend.verify()
        self.assertIn("PS2 ISO", self.backend.hd_warning)
        archive = self.root / "old Spanish.zip"
        self.voice_bundle(archive, legacy)
        with self.assertRaisesRegex(setup.SetupError, "Older language ZIPs"):
            self.backend.install_spanish(archive)
        self.assertEqual(self.snapshot(current), before)
        # An Xbox repair keeps the original version untouched and never activates
        # unrecognized old Spanish content in the new version.
        repaired = self.install_disc()
        self.assertEqual(self.snapshot(current), before)
        self.assertFalse((repaired / "language/es").exists())
        self.assertEqual(language_pack.selected(repaired), "es")
        with self.assertRaisesRegex(setup.SetupError, "PS2 ISO import"):
            self.backend.play()
        self.backend.set_language("en")
        with patch.object(self.backend, "prepare_shaders"), patch.object(setup.subprocess, "Popen") as launch:
            launch.return_value.wait.return_value = 0
            self.backend.play()
            launch.assert_called_once()

    def update_fixture(self, current, content=False):
        (self.payload / 'runtime/new-runtime.dll').write_bytes(b'updated runtime dependency')
        self.repin()
        self.backend = setup.Setup(self.package, self.install, notify=lambda *a, **k: None)
        if content:
            record = setup.read_json(current / 'install.json')
            record['content_revision'] = 'previous-content-revision'
            setup.write_json(current / 'install.json', record)
        self.iso.unlink(missing_ok=True)

    def test_update_reuses_assets_and_preserves_user_data_without_iso(self):
        current = self.install_disc()
        preserved = {setup.SETTINGS: b'custom settings', 'hdd/save.bin': b'solo',
                     'hdd2/save.bin': b'coop', 'cache/shader.bin': b'cache',
                     'gameplay-hd/custom.dwt': b'optional HD', 'language/es/private.bin': b'Spanish'}
        for name, data in preserved.items():
            target = current / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        assets = self.snapshot(current / 'assets')
        self.update_fixture(current)
        self.assertTrue(self.backend.status()['update_available'])
        with patch.object(characters, 'prepare', side_effect=AssertionError('unnecessary content rebuild')), \
                patch.object(self.backend, 'copy_user_data', side_effect=AssertionError('unnecessary save copy')):
            result = self.backend.update()
        self.assertTrue(result['ready'])
        self.assertFalse(result['update_available'])
        self.assertEqual(self.backend.active(), current)
        self.assertEqual(list((self.install / 'versions').iterdir()), [current])
        self.assertEqual(self.snapshot(current / 'assets'), assets)
        for name, data in preserved.items():
            self.assertEqual((current / name).read_bytes(), data)
        self.assertEqual((current / 'new-runtime.dll').read_bytes(), b'updated runtime dependency')
        self.assertFalse(list(current.glob('.update-*')))

    def test_legacy_runtime_update_needs_no_recovery_or_iso(self):
        current = self.install_disc()
        shutil.rmtree(current / 'source-recovery')
        record = setup.read_json(current / 'install.json')
        record.pop('package_sha256')
        record.pop('artwork_sha256')
        setup.write_json(current / 'install.json', record)
        self.update_fixture(current)
        self.assertTrue(self.backend.update()['ready'])
        self.assertFalse((current / 'source-recovery').exists())

    def test_content_update_restores_originals_and_keeps_same_install(self):
        current = self.install_disc()
        original_assets = self.snapshot(current / 'assets')
        (current / 'hdd').mkdir()
        (current / 'hdd/progress').write_bytes(b'progress')
        self.update_fixture(current, content=True)
        self.assertTrue(self.backend.update()['ready'])
        self.assertEqual(self.snapshot(current / 'assets'), original_assets)
        self.assertEqual((current / 'hdd/progress').read_bytes(), b'progress')
        self.assertEqual(self.backend.active(), current)

    def test_content_update_stages_only_converter_inputs(self):
        self.data.update({'LvlMulti.pck': b'multiplayer animation donor',
                          'Movies1.pck': b'unmodified movie payload'})
        self.disc['files'] = [dict(path=name, size=len(blob), sha256=sha(blob)) for name, blob in self.data.items()]
        (self.payload / 'supported-disc.json').write_text(json.dumps(self.disc))
        self.repin()
        make_iso(self.iso, self.data)
        self.backend = setup.Setup(self.package, self.install, notify=lambda *a, **k: None)
        current = self.install_disc()
        before = self.snapshot(current / 'assets')
        (current / 'hdd').mkdir()
        (current / 'hdd/progress').write_bytes(b'preserved save')
        self.update_fixture(current, content=True)
        needed = (512 * 1024 * 1024 + sum((self.package / name).stat().st_size for name in self.backend.files
                                         if name.startswith('payload/runtime/')) +
                  sum(item['size'] for item in self.backend.assets if item['path'] in self.backend.iso_preparation_names()) +
                  sum(size for size, _ in characters.INSTALLED.values()) +
                  max(size for size, _ in characters.INSTALLED.values()))
        convert = characters.prepare
        def checked_conversion(assets, payload, cancel, progress):
            self.assertEqual({path.name for path in assets.iterdir()},
                             {'default.xbe', 'LvlMulti.pck', 'packfile.pck'})
            self.assertEqual((assets / 'LvlMulti.pck').read_bytes(), self.data['LvlMulti.pck'])
            return convert(assets, payload, cancel, progress)
        with patch.object(characters, 'prepare', side_effect=checked_conversion), \
                patch.object(self.backend, 'copy_file', wraps=self.backend.copy_file) as copied, \
                patch.object(setup.shutil, 'disk_usage', return_value=SimpleNamespace(free=needed)):
            self.assertTrue(self.backend.update()['ready'])
        copied_assets = {Path(call.args[0]).name for call in copied.call_args_list
                         if Path(call.args[0]).parent == current / 'assets'}
        self.assertEqual(copied_assets, {'default.xbe', 'LvlMulti.pck'})
        self.assertEqual(self.snapshot(current / 'assets'), before)
        self.assertEqual((current / 'hdd/progress').read_bytes(), b'preserved save')
        self.assertEqual(self.backend.active(), current)
        self.assertFalse(list(current.glob('.update-*')))

    def test_content_update_still_authenticates_unstaged_files(self):
        current = self.install_disc()
        self.update_fixture(current, content=True)
        # This file is no longer copied into the converter stage, but corruption
        # must still stop the update before preparation or any installed changes.
        (current / 'assets/audio.pck').write_bytes(b'damaged audio')
        before = self.snapshot(current)
        with patch.object(characters, 'prepare', side_effect=AssertionError('must validate first')):
            with self.assertRaisesRegex(setup.SetupError, 'data is damaged: audio.pck'):
                self.backend.update()
        self.assertEqual(self.snapshot(current), before)

    def test_legacy_content_update_explains_final_import_without_changes(self):
        current = self.install_disc()
        shutil.rmtree(current / 'source-recovery')
        self.update_fixture(current, content=True)
        before = self.snapshot(current)
        self.assertFalse(self.backend.status()['update_available'])
        with self.assertRaisesRegex(setup.SetupError, 'one final ISO import'):
            self.backend.update()
        self.assertEqual(self.snapshot(current), before)

    def test_failed_or_cancelled_update_keeps_installed_files(self):
        current = self.install_disc()
        self.update_fixture(current, content=True)
        recovery = current / 'source-recovery/packfile.pck.tail'
        valid = recovery.read_bytes()
        recovery.write_bytes(b'damaged')
        before = self.snapshot(current)
        with self.assertRaisesRegex(ValueError, 'recovery'):
            self.backend.update()
        self.assertEqual(self.snapshot(current), before)
        recovery.write_bytes(valid)
        before = self.snapshot(current)
        with patch.object(characters, 'prepare', side_effect=setup.Cancelled('cancelled')):
            with self.assertRaises(setup.Cancelled):
                self.backend.update()
        self.assertEqual(self.snapshot(current), before)
        with patch.object(setup, 'game_running', return_value=True):
            with self.assertRaisesRegex(setup.SetupError, 'Close Darkwatch'):
                self.backend.update()
        self.assertEqual(self.snapshot(current), before)

    def test_interrupted_commit_is_retryable_before_play(self):
        current = self.install_disc()
        self.update_fixture(current, content=True)
        original_receipt = (current / 'install.json').read_bytes()
        replace = os.replace
        def interrupt(source, target):
            if Path(target) == current / 'new-runtime.dll':
                raise OSError('interrupted update commit')
            return replace(source, target)
        with patch.object(os, 'replace', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted update commit'):
                self.backend.update()
        self.assertEqual((current / 'install.json').read_bytes(), original_receipt)
        self.assertTrue(self.backend.needs_update(current))
        self.assertTrue(self.backend.update()['ready'])
        self.assertEqual(self.backend.verify(), current)

    def test_attach_reuses_previous_folder_and_persists_for_direct_launch(self):
        current = self.install_disc()
        self.iso.unlink()
        local = self.root / 'new release/GameData'
        attached = setup.Setup(self.package, local, notify=lambda *a, **k: None)
        before = self.snapshot(current)
        result = attached.use_installation(current)
        self.assertTrue(result['ready'])
        self.assertEqual(attached.active(), current)
        self.assertEqual(self.snapshot(current), before)
        self.assertEqual(setup.read_json(local / 'installation-location.json')['root'], str(self.install))
        self.assertFalse((local / 'versions').exists())
        reopened = setup.Setup(self.package, local, notify=lambda *a, **k: None)
        self.assertEqual(reopened.verify(), current)
        with patch.object(reopened, 'prepare_shaders'), patch.object(setup.subprocess, 'Popen') as launch:
            launch.return_value.wait.return_value = 0
            reopened.play()
        self.assertEqual(launch.call_args.args[0], [str(current / setup.EXE)])

    def test_reattach_ignores_broken_reference_but_rejects_chains_and_wrong_disc(self):
        current = self.install_disc()
        local = self.root / 'new release/GameData'
        local.mkdir(parents=True)
        (local / 'installation-location.json').write_text('broken json')
        attached = setup.Setup(self.package, local, notify=lambda *a, **k: None, ignore_location=True)
        self.assertTrue(attached.use_installation(self.package)['ready'])
        another = setup.Setup(self.package, self.root / 'third/GameData', notify=lambda *a, **k: None)
        with self.assertRaisesRegex(setup.SetupError, 'previous Darkwatch folder|linked launcher'):
            another.use_installation(local)
        record = setup.read_json(current / 'install.json')
        record['disc_sha256'] = '0' * 64
        setup.write_json(current / 'install.json', record)
        with self.assertRaisesRegex(setup.SetupError, 'different disc revision'):
            another.use_installation(self.install)
        self.assertFalse((another.local_root / 'installation-location.json').exists())

    def test_no_bundled_spanish_and_old_text_only_is_not_admitted(self):
        current, legacy, ps2, iso = self.spanish_variants()
        # Stale files accidentally left beside a newer launcher cannot restore
        # the discontinued built-in or ZIP-import paths.
        folder = self.payload / "language/es"
        folder.mkdir(parents=True)
        (folder / "language_text.bin").write_bytes(legacy["language_text.bin"])
        for name in ("spanish-catalog.json", "spanish-text-catalog.json"):
            (self.payload / name).write_text(json.dumps(dict(schema_version=1, language="es", files={
                "language_text.bin": dict(size=len(legacy["language_text.bin"]), sha256=sha(legacy["language_text.bin"]))})))
        self.repin()
        self.backend = setup.Setup(self.package, self.install, notify=lambda *a, **k: None)
        fresh = self.install_disc()
        self.assertFalse((fresh / "language/es").exists())
        self.assertFalse(self.backend.status()["spanish_installed"])
        self.install_old_spanish(fresh, {"language_text.bin": legacy["language_text.bin"]})
        before = self.snapshot(fresh)
        with self.assertRaisesRegex(setup.SetupError, "PS2 ISO import"):
            self.backend.set_language("es")
        self.assertEqual(self.snapshot(fresh), before)
        self.assertEqual(self.backend.set_language("en")["language"], "en")

    def test_ps2_spanish_reimport_copy_failure_preserves_previous_version(self):
        current, legacy, ps2, iso = self.spanish_variants()
        self.install_old_spanish(current, ps2)
        language_pack.select(current, "es")
        before = self.snapshot(current)
        real_copy = self.backend.copy_file
        def fail_media(source, destination):
            if str(destination).replace("\\", "/").endswith("language/es/assets/audioDlg.pck"):
                Path(destination).write_bytes(b"partial")
                raise OSError("synthetic media copy failure")
            return real_copy(source, destination)
        with patch.object(self.backend, "copy_file", side_effect=fail_media):
            repaired = self.install_disc()
        self.assertEqual(self.snapshot(current), before)
        self.assertFalse((repaired / "language/es").exists())
        self.assertTrue(self.backend.status()["ready"])
        self.assertFalse(self.backend.status()["spanish_installed"])
        self.backend.set_language("en")

    @staticmethod
    def install_old_spanish(current, files):
        for name, data in files.items():
            target = current / "language/es" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def spanish_variants(self):
        current = self.install_disc()
        text = b"DWES0003 generated PS2 fixture"
        legacy = {"language_text.bin": b"older text", "assets/audioDlg.pck": b"older compatible voices"}
        ps2 = {"language_text.bin": text, "assets/audioDlg.pck": b"verified PS2 converted voice fixture",
               "assets/Movies1.pck": b"verified compatible movie fixture"}
        (self.payload / "ps2-spanish-catalog.json").write_text(json.dumps(dict(schema_version=1, language="es", files={
            key: dict(size=len(data), sha256=sha(data)) for key, data in ps2.items()})))
        (self.payload / "ps2_spanish.py").write_text("# Converter boundary is controlled in these transaction tests.\n")
        self.repin()
        self.backend = setup.Setup(self.package, self.install, notify=lambda *a, **k: None)
        iso = self.root / "PS2 Español 🦇.ISO"
        iso.write_bytes(b"synthetic PS2 source; converter tested separately")
        self.backend.update()
        return current, legacy, ps2, iso

    @staticmethod
    def voice_bundle(path, files):
        with zipfile.ZipFile(path, "w") as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)

    def test_ps2_spanish_atomic_replacement_preserves_text_settings_and_saves(self):
        current, legacy, ps2, iso = self.spanish_variants()
        old_zip = self.root / "legacy voices.zip"
        self.voice_bundle(old_zip, legacy)
        self.install_old_spanish(current, legacy)
        settings = current / setup.SETTINGS
        settings.write_text('[controls]\nsensitivity=1.7\n[language]\ntext="en"\n')
        (current / "hdd").mkdir()
        (current / "hdd/save.bin").write_bytes(b"solo progress")
        (current / "hdd2").mkdir()
        (current / "hdd2/save.bin").write_bytes(b"coop progress")
        original_assets, original_settings = self.snapshot(current / "assets"), settings.read_bytes()
        calls = []
        def prepare(source, assets, output, cancel, notify):
            calls.append((source, assets, output))
            cancel()
            self.assertEqual(source, iso)
            self.assertEqual(assets, current / "assets")
            self.assertEqual(output.parent.parent, self.install)
            self.voice_bundle(output, ps2)
        with patch.dict(sys.modules, {"ps2_spanish": SimpleNamespace(prepare=prepare)}):
            result = self.backend.install_spanish(iso)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][2].parent.exists())
        self.assertTrue(result["spanish_audio_installed"])
        self.assertEqual(result["language"], "en")
        self.assertTrue(self.backend.spanish_valid(current))
        self.assertEqual(settings.read_bytes(), original_settings)
        self.assertEqual(self.snapshot(current / "assets"), original_assets)
        self.assertEqual(iso.read_bytes(), b"synthetic PS2 source; converter tested separately")
        self.backend.set_language("es")
        self.assertEqual(self.backend.verify(), current)
        repaired = self.install_disc()
        self.assertTrue(self.backend.spanish_valid(repaired))
        self.assertEqual(self.backend.status()["language"], "es")
        self.assertEqual((repaired / "language/es/assets/audioDlg.pck").read_bytes(), ps2["assets/audioDlg.pck"])
        self.assertEqual((repaired / "language/es/assets/Movies1.pck").read_bytes(), ps2["assets/Movies1.pck"])
        self.assertEqual((repaired / "hdd/save.bin").read_bytes(), b"solo progress")
        self.assertEqual((repaired / "hdd2/save.bin").read_bytes(), b"coop progress")
        self.assertEqual(self.snapshot(repaired / "assets"), original_assets)
        self.backend.set_language("en")
        movie = repaired / "language/es/assets/Movies1.pck"
        movie.write_bytes(b"x" * len(ps2["assets/Movies1.pck"]))
        self.assertFalse(self.backend.spanish_valid(repaired))
        with self.assertRaisesRegex(setup.SetupError, "PS2 ISO import"):
            self.backend.set_language("es")
        self.assertEqual(language_pack.selected(repaired), "en")
        # The replaced community files remain in an inactive backup.
        backups = list((current / "language").glob(".spanish-stage-*-previous"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.snapshot(backups[0]), legacy)
        with self.assertRaisesRegex(setup.SetupError, "Older language ZIPs"):
            self.backend.install_spanish(old_zip)

    def test_ps2_spanish_failures_do_not_replace_previous_media(self):
        current, legacy, ps2, iso = self.spanish_variants()
        archive = self.root / "legacy.zip"
        self.voice_bundle(archive, legacy)
        self.install_old_spanish(current, legacy)
        language_pack.select(current, "es")
        before = self.snapshot(current)
        def malformed(source, assets, output, cancel, notify):
            self.voice_bundle(output, dict(ps2, **{"assets/audioDlg.pck": b"x" * len(ps2["assets/audioDlg.pck"])}))
        def unlisted(source, assets, output, cancel, notify):
            self.voice_bundle(output, dict(ps2, **{"assets/Movies4.pck": b"unverified extra movie"}))
        def old_text(source, assets, output, cancel, notify):
            self.voice_bundle(output, dict(ps2, **{"language_text.bin": b"x" * len(ps2["language_text.bin"])}))
        def unsupported(*args):
            raise ValueError("Unsupported PS2 disc revision")
        def cancelled(source, assets, output, cancel, notify):
            self.voice_bundle(output, ps2)
            raise setup.Cancelled("Cancelled")
        for prepare in (malformed, unlisted, old_text, unsupported, cancelled):
            with self.subTest(prepare=prepare.__name__), patch.dict(sys.modules, {"ps2_spanish": SimpleNamespace(prepare=prepare)}):
                with self.assertRaises(ValueError):
                    self.backend.install_spanish(iso)
            self.assertEqual(self.snapshot(current), before)
            self.assertFalse(list(self.install.glob(".spanish-ps2-*")))
        def valid(source, assets, output, cancel, notify):
            self.voice_bundle(output, ps2)
        with patch.dict(sys.modules, {"ps2_spanish": SimpleNamespace(prepare=valid)}), \
             patch.object(setup, "require_closed", side_effect=(None, setup.SetupError("Close Darkwatch"))):
            with self.assertRaisesRegex(setup.SetupError, "Close Darkwatch"):
                self.backend.install_spanish(iso)
        self.assertEqual(self.snapshot(current), before)
        self.assertFalse(list(self.install.glob(".spanish-ps2-*")))
        with patch.object(self.backend, "ps2_language_catalog", None), self.assertRaisesRegex(setup.SetupError, "does not support"):
            self.backend.install_spanish(iso)
        self.assertEqual(self.snapshot(current), before)

    def test_ps2_spanish_pins_and_space_gate_conversion_and_reimport(self):
        current, legacy, ps2, iso = self.spanish_variants()
        before = self.snapshot(current)
        usage = shutil._ntuple_diskusage(total=128 * 1024 ** 2, used=0, free=128 * 1024 ** 2)
        with patch.object(shutil, "disk_usage", return_value=usage), self.assertRaisesRegex(setup.SetupError, "free space"):
            self.backend.install_spanish(iso)
        self.assertEqual(self.snapshot(current), before)
        base = sum(f["size"] for f in self.backend.assets) + sum(size for size, _ in characters.INSTALLED.values()) + 512 * 1024 ** 2
        self.install_old_spanish(current, legacy)
        before = self.snapshot(current)
        ps2_size = sum(row["size"] for row in self.backend.ps2_language_catalog.files.values())
        usage = shutil._ntuple_diskusage(total=base + ps2_size - 1, used=0, free=base + ps2_size - 1)
        with patch.object(shutil, "disk_usage", return_value=usage), self.assertRaisesRegex(setup.SetupError, "free space"):
            self.install_disc()
        self.assertEqual(self.backend.active(), current)
        catalog = self.payload / "ps2-spanish-catalog.json"
        catalog.write_bytes(catalog.read_bytes() + b" ")
        with self.assertRaisesRegex(setup.SetupError, "PS2 Spanish catalog is damaged"):
            setup.Setup(self.package, self.install)
        with self.assertRaisesRegex(setup.SetupError, "Launcher file is damaged"):
            self.backend.install_spanish(iso)
        self.assertEqual(self.snapshot(current), before)

    def test_portable_package_moves_with_saves_and_launches_only_from_new_folder(self):
        current = self.install_disc()
        settings = current / setup.SETTINGS
        settings.write_bytes(b"portable settings")
        (current / "hdd/E").mkdir(parents=True)
        (current / "hdd/E/save.dat").write_bytes(b"portable progress")
        (current / "cache").mkdir()
        (current / "cache/shader.bin").write_bytes(b"portable cache")
        original = self.snapshot(self.package)
        moved = self.root / "moved portable package"
        self.assertTrue(self.package.resolve().is_relative_to(self.root.resolve()))
        self.assertTrue(moved.resolve().is_relative_to(self.root.resolve()))
        shutil.move(str(self.package), moved)
        backend = setup.Setup(moved, moved / "GameData", notify=lambda *args, **kw: None)
        relocated = backend.verify()
        self.assertEqual(self.snapshot(moved), original)
        self.assertFalse(self.package.exists())
        self.assertFalse(Path(os.environ["LOCALAPPDATA"]).exists())
        children = []
        real_popen = subprocess.Popen
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(subprocess, "Popen", side_effect=spawn) as launched:
            backend.play()
        self.assertEqual(launched.call_args.kwargs["cwd"], relocated)
        self.assertEqual(children[0].wait(timeout=5), 0)
        self.assertEqual((relocated / "worker-ran.txt").read_text(), "harmless launcher fixture")
        self.assertEqual((relocated / setup.SETTINGS).read_bytes(), b"portable settings")
        self.assertEqual((relocated / "hdd/E/save.dat").read_bytes(), b"portable progress")
        self.assertEqual((relocated / "cache/shader.bin").read_bytes(), b"portable cache")

    def test_same_folder_status_verify_play_preserve_all_save_bytes(self):
        current = self.install_disc()
        files = {"hdd/E/UDATA/43430016/profile/Profile 1": b"existing signed profile fixture",
                 "hdd/E/UDATA/43430016/damaged/Profile 2": b"interrupted profile",
                 "hdd/E/UDATA/43430016/empty/Profile 3": b"",
                 "hdd2/E/UDATA/43430016/other/Profile 1": b"second instance progress"}
        for relative, data in files.items():
            path = current / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        original = {name: self.snapshot(current / name) for name in ("hdd", "hdd2")}
        pointer = (self.install / "active.json").read_bytes()
        children = []
        real_popen = subprocess.Popen
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child
        self.assertTrue(self.backend.status()["ready"])
        self.assertEqual(self.backend.verify(), current)
        with patch.object(subprocess, "Popen", side_effect=spawn):
            self.backend.play()
        for child in children:
            self.assertEqual(child.wait(timeout=5), 0)
        self.assertEqual(self.backend.active(), current)
        self.assertEqual((self.install / "active.json").read_bytes(), pointer)
        for name, contents in original.items():
            self.assertEqual(self.snapshot(current / name), contents)

    @unittest.skipUnless(os.name == "nt", "Previous Windows launcher migration")
    def test_first_import_adopts_prior_saves_without_using_legacy_for_play(self):
        legacy, previous = self.make_legacy_install()
        original = self.snapshot(legacy)
        self.assertFalse(self.backend.status()["installed"])
        with patch.object(subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(setup.SetupError, "Import your own"):
                self.backend.play()
            spawn.assert_not_called()
        current = self.install_disc()
        for relative in (setup.SETTINGS, "hdd/E/save.dat", "hdd2/E/save.dat", "cache/shader.bin"):
            self.assertEqual((current / relative).read_bytes(), (previous / relative).read_bytes())
        self.assertFalse((current / "logs").exists())
        self.assertEqual(self.snapshot(legacy), original)

    @unittest.skipUnless(os.name == "nt", "Previous Windows launcher migration")
    def test_portable_repair_prefers_newer_data_over_legacy_install(self):
        legacy, previous = self.make_legacy_install()
        first = self.install_disc()
        (first / setup.SETTINGS).write_bytes(b"new portable controls")
        (first / "hdd/E/save.dat").write_bytes(b"new portable progress")
        (legacy / "active.json").write_text('{"version":"../damaged"}')
        before = self.snapshot(legacy)
        repaired = self.install_disc()
        self.assertEqual((repaired / setup.SETTINGS).read_bytes(), b"new portable controls")
        self.assertEqual((repaired / "hdd/E/save.dat").read_bytes(), b"new portable progress")
        self.assertEqual(self.snapshot(legacy), before)

    @unittest.skipUnless(os.name == "nt", "Previous Windows launcher migration")
    def test_failed_first_import_keeps_legacy_and_portable_pointer_unpublished(self):
        legacy, _ = self.make_legacy_install()
        before = self.snapshot(legacy)
        real_replace = os.replace
        def fail_commit(source, target):
            if Path(target) == self.install / "active.json":
                raise OSError("portable commit blocked")
            return real_replace(source, target)
        with patch.object(os, "replace", side_effect=fail_commit):
            with self.assertRaisesRegex(OSError, "portable commit blocked"):
                self.install_disc()
        self.assertEqual(self.snapshot(legacy), before)
        self.assertIsNone(self.backend.active())
        self.assertFalse(list((self.install / "versions").iterdir()))

    @unittest.skipUnless(os.name == "nt", "Previous Windows launcher migration")
    def test_damaged_or_different_legacy_identity_blocks_migration(self):
        legacy, previous = self.make_legacy_install()
        for pointer, metadata in (({"version": "../escape"}, {}),
                                  ({"version": previous.name}, {"disc_sha256": "0" * 64})):
            with self.subTest(pointer=pointer, metadata=metadata):
                (legacy / "active.json").write_text(json.dumps(pointer))
                (previous / "install.json").write_text(json.dumps(metadata))
                before = self.snapshot(legacy)
                with self.assertRaisesRegex(setup.SetupError, "Could not preserve saves"):
                    self.install_disc()
                self.assertEqual(self.snapshot(legacy), before)
                self.assertIsNone(self.backend.active())
                self.assertFalse(list((self.install / "versions").iterdir()))

    @unittest.skipUnless(os.name == "nt", "Previous Windows launcher migration")
    def test_migration_respects_previous_launcher_lock(self):
        legacy, _ = self.make_legacy_install()
        before = self.snapshot(legacy)
        with setup.exclusive(legacy):
            with self.assertRaisesRegex(setup.SetupError, "already in progress"):
                self.install_disc()
        self.assertEqual(self.snapshot(legacy), before)
        self.assertIsNone(self.backend.active())

    @unittest.skipUnless(os.name == "nt", "Previous Windows launcher migration")
    def test_relative_appdata_does_not_select_an_unrelated_install(self):
        legacy, _ = self.make_legacy_install()
        before = self.snapshot(legacy)
        working = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, {"LOCALAPPDATA": "LocalAppData"}):
                current = self.install_disc()
        finally:
            os.chdir(working)
        self.assertFalse((current / setup.SETTINGS).exists())
        self.assertFalse((current / "hdd").exists())
        self.assertEqual(self.snapshot(legacy), before)

    def test_repair_keeps_saves_bindings_cache_and_prior_version(self):
        first = self.install_disc()
        user = {setup.SETTINGS: b"latest wheel binding", "hdd/E/save.dat": b"progress", "hdd2/E/save.dat": b"player2", "cache/shader.bin": b"cache"}
        for name, data in user.items():
            path = first / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (first / "logs").mkdir()
        (first / "logs/old.log").write_text("old diagnostics")
        (first / "CrashDumps").mkdir()
        (first / "CrashDumps/old.dmp").write_bytes(b"old dump")
        receipt = json.loads((first / 'install.json').read_text())
        receipt['content_revision'] = bonus.CONTENT_REVISION
        (first / 'install.json').write_text(json.dumps(receipt))
        self.assertFalse(self.backend.status()['ready'])
        second = self.install_disc()
        self.assertNotEqual(first, second)
        for name, data in user.items():
            self.assertEqual((second / name).read_bytes(), data)
            self.assertEqual((first / name).read_bytes(), data)
        for relative in ('logs/old.log', 'CrashDumps/old.dmp'):
            self.assertTrue((first / relative).is_file())
            self.assertFalse((second / relative).exists())

    def test_character_conversion_failure_and_cancel_preserve_old_install(self):
        current = self.install_disc()
        before = self.snapshot(self.install)
        for error in (ValueError('unsupported character resource'), setup.Cancelled('cancelled conversion')):
            with self.subTest(error=str(error)), patch.object(characters, 'prepare', side_effect=error):
                with self.assertRaises(type(error)):
                    self.backend.import_iso(self.iso)
                self.assertEqual(self.snapshot(self.install), before)
                self.assertEqual(self.backend.active(), current)

    def test_v4_character_update_rebuilds_assets_and_preserves_both_saves(self):
        first = self.install_disc()
        user = {
            "hdd/E/UDATA/43430016/17AA1AB206DC/Profile 1": b"single-player checkpoint",
            "hdd/E/UDATA/43430016/006F004F0FE1/CoOp": b"co-op checkpoint",
            setup.SETTINGS: b"retained player controls and graphics",
            "cache/shader.bin": b"retained shader cache",
        }
        for name, data in user.items():
            target = first / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        receipt = json.loads((first / 'install.json').read_text())
        receipt['content_revision'] = 'wartrain-splitter-characters-v4'
        (first / 'install.json').write_text(json.dumps(receipt))
        (first / 'assets/packfile.pck').write_bytes(b'old character assets must not be reused')
        before = self.snapshot(first)
        self.assertFalse(self.backend.status()['ready'])
        with self.assertRaisesRegex(setup.SetupError, 'character content update'):
            self.backend.verify()
        with patch.object(characters, 'prepare', wraps=characters.prepare) as conversion:
            second = self.install_disc()
            conversion.assert_called_once()
        self.assertNotEqual(first, second)
        self.assertEqual((second / 'assets/packfile.pck').read_bytes(), self.installed_data['packfile.pck'])
        self.assertEqual(json.loads((second / 'install.json').read_text())['content_revision'],
                         characters.CONTENT_REVISION)
        for name, data in user.items():
            self.assertEqual((second / name).read_bytes(), data)
        self.assertEqual(self.snapshot(first), before)

    def test_disk_budget_includes_all_character_copies(self):
        original_bytes = sum(len(data) for data in self.data.values())
        base = original_bytes + 512 * 1024 * 1024
        converted = [size for size, _ in characters.INSTALLED.values()]
        # Both the final files and the next streamed archive need disk space.
        for spare in (base, base + sum(converted) + max(converted) - 1):
            usage = shutil._ntuple_diskusage(total=spare, used=0, free=spare)
            with self.subTest(free=spare), patch.object(shutil, 'disk_usage', return_value=usage):
                with patch.object(self.backend, 'read_iso_files', side_effect=AssertionError('must fail before copying')):
                    with self.assertRaisesRegex(setup.SetupError, 'Not enough free space'):
                        self.install_disc()
        self.assertIsNone(self.backend.active())

    def test_immediate_startup_failure_is_visible_without_touching_install(self):
        current = self.install_disc()
        with patch.dict(os.environ, {"WORKER_TEST_EXIT": "1"}):
            with self.assertRaisesRegex(setup.SetupError, 'could not start.*00000016'):
                self.backend.play()
        self.assertEqual(self.backend.verify(), current)

    def test_shader_preparation_is_shared_by_import_play_and_warm_launch(self):
        current = self.install_disc()
        (current / "cache").mkdir()
        (current / "cache/prior.fixture").write_bytes(b"compatible previous shader")
        pointer = (self.install / "active.json").read_bytes()
        observed = []
        notify = self.backend.notify
        def inspect(event, message, **fields):
            notify(event, message, **fields)
            if event == "shader_prepare":
                stages = set((self.install / "versions").iterdir()) - {current}
                self.assertEqual(len(stages), 1)
                stage = stages.pop()
                self.assertEqual((stage / "cache/prior.fixture").read_bytes(), b"compatible previous shader")
                self.assertEqual((self.install / "active.json").read_bytes(), pointer)
                observed.append(fields["percent"])
        self.backend.notify = inspect
        with patch.dict(os.environ, {"WORKER_SHADER_MODE": "cold"}):
            prepared = self.install_disc()
        self.assertEqual(observed, [50, 100])
        self.assertEqual((prepared / "cache/prepared.fixture").read_bytes(), b"one completed job")
        self.backend.notify = notify
        self.events.clear()
        with patch.dict(os.environ, {"WORKER_SHADER_MODE": "warm"}):
            self.backend.play()
        self.assertFalse(any(event["event"] == "shader_prepare" for event in self.events))
        self.assertTrue(any(event["event"] == "shader_ready" for event in self.events))
        self.assertTrue((prepared / "worker-ran.txt").is_file())

    def test_failed_or_incomplete_shaders_never_start_the_game_or_publish_import(self):
        current = self.install_disc()
        pointer = (self.install / "active.json").read_bytes()
        for mode in ("silent", "fail", "error", "incomplete", "oversize", "ready-fail"):
            with self.subTest(mode=mode), patch.dict(os.environ, {"WORKER_SHADER_MODE": mode}):
                with self.assertRaisesRegex(setup.SetupError, "Shader preparation"):
                    self.backend.play()
                self.assertFalse((current / "worker-ran.txt").exists())
                with self.assertRaisesRegex(setup.SetupError, "Shader preparation"):
                    self.backend.import_iso(self.iso)
                self.assertEqual((self.install / "active.json").read_bytes(), pointer)
                self.assertEqual(set((self.install / "versions").iterdir()), {current})

    def test_shader_progress_can_exceed_total_timeout(self):
        current = self.install_disc()
        clock = [0.0]
        notify = self.backend.notify
        def advance(event, message, **fields):
            notify(event, message, **fields)
            if event == "shader_prepare":
                clock[0] += 800
        self.backend.notify = advance
        with patch.dict(os.environ, {"WORKER_SHADER_MODE": "cold"}), patch.object(setup.time, "monotonic", side_effect=lambda: clock[0]):
            self.backend.prepare_shaders(current)
        self.assertEqual(clock[0], 1600)
        self.assertTrue(any(event["event"] == "shader_ready" for event in self.events))
        clock[0] = 0
        with patch.dict(os.environ, {"WORKER_SHADER_MODE": "repeat"}), patch.object(setup.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(setup.SetupError, "no progress"):
                self.backend.prepare_shaders(current)

    def test_shader_cancel_and_deadline_reap_worker_and_keep_completed_cache(self):
        current = self.install_disc()
        original = (self.install / "active.json").read_bytes()
        real_popen = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child
        cancel = self.root / "cancel-shaders"
        self.backend.cancel_file = cancel
        notify = self.backend.notify
        def cancel_on_progress(event, message, **fields):
            notify(event, message, **fields)
            if event == "shader_prepare":
                cancel.touch()
        self.backend.notify = cancel_on_progress
        with patch.dict(os.environ, {"WORKER_SHADER_MODE": "wait"}), patch.object(subprocess, "Popen", side_effect=spawn):
            with self.assertRaises(setup.Cancelled):
                self.backend.play()
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertFalse((current / "worker-ran.txt").exists())
        self.assertEqual((current / "cache/prepared.fixture").read_bytes(), b"one completed job")
        self.assertEqual((self.install / "active.json").read_bytes(), original)
        cancel.unlink()
        self.backend.notify = notify
        with patch.dict(os.environ, {"WORKER_SHADER_MODE": "wait"}), patch.object(setup, "SHADER_PREPARE_TIMEOUT", 0.15), patch.object(subprocess, "Popen", side_effect=spawn):
            with self.assertRaisesRegex(setup.SetupError, "too long"):
                self.backend.play()
        self.assertEqual(len(children), 2)
        self.assertIsNotNone(children[-1].returncode)
        self.assertFalse((current / "worker-ran.txt").exists())

    def test_real_builder_failure_has_useful_error_without_install_logs(self):
        current = self.install_disc()
        with patch.dict(os.environ, {"DARKWATCH_TEST_BUILDER_FAIL": "1"}):
            with self.assertRaisesRegex(setup.SetupError, 'fixture preparation failed'):
                self.backend.import_iso(self.iso)
        self.assertEqual(self.backend.active(), current)
        self.assertFalse(list(self.install.rglob('*.log')))

    def test_failure_and_cancel_keep_previous_install(self):
        current = self.install_disc()
        pointer = (self.install / "active.json").read_bytes()
        before_versions = set((self.install / "versions").iterdir())
        bad = dict(self.data, **{"audio.pck": b"wrong fixture"})
        make_iso(self.iso, bad)
        with self.assertRaisesRegex(setup.SetupError, "damaged or unsupported"):
            self.backend.import_iso(self.iso)
        self.assertEqual((self.install / "active.json").read_bytes(), pointer)
        self.assertEqual(set((self.install / "versions").iterdir()), before_versions)
        make_iso(self.iso, self.data)
        with patch.object(self.backend, "build_hd", side_effect=setup.Cancelled("cancelled")):
            with self.assertRaises(setup.Cancelled):
                self.backend.import_iso(self.iso)
        self.assertEqual(self.backend.active(), current)
        self.assertEqual(set((self.install / "versions").iterdir()), before_versions)
        cancel = self.root / "cancel"
        cancel.touch()
        self.backend.cancel_file = cancel
        with self.assertRaises(setup.Cancelled):
            self.backend.import_iso(self.iso)
        self.assertEqual(self.backend.active(), current)

    def test_builder_failure_and_commit_failure_are_transactional(self):
        current = self.install_disc()
        with patch.object(self.backend, "build_hd", side_effect=setup.SetupError("builder failed")):
            with self.assertRaisesRegex(setup.SetupError, "builder failed"):
                self.backend.import_iso(self.iso)
        real_replace = os.replace
        def fail_commit(source, target):
            if Path(target) == self.install / "active.json":
                raise OSError("commit blocked")
            return real_replace(source, target)
        with patch.object(os, "replace", side_effect=fail_commit):
            with self.assertRaisesRegex(OSError, "commit blocked"):
                self.backend.import_iso(self.iso)
        self.assertEqual(self.backend.verify(), current)

    def test_cancel_stops_only_running_builder_and_keeps_install(self):
        current = self.install_disc()
        cancel = self.root / "cancel-builder"
        self.backend.cancel_file = cancel
        children = []
        real_popen = subprocess.Popen
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            cancel.touch()
            return child
        with patch.dict(os.environ, {"DARKWATCH_TEST_BUILDER_WAIT": "1"}), patch.object(subprocess, "Popen", side_effect=spawn):
            with self.assertRaises(setup.Cancelled):
                self.backend.import_iso(self.iso)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertNotEqual(children[0].returncode, 0)
        self.assertTrue(cancel.exists())
        self.assertEqual(self.backend.active(), current)
        self.assertEqual(set((self.install / "versions").iterdir()), {current})

    def test_damaged_assets_runtime_hd_or_missing_files_block_play(self):
        current = self.install_disc()
        for relative in ("assets/default.xbe", "assets/audio.pck", setup.EXE, "hd-ui.pack"):
            path = current / relative
            original = path.read_bytes()
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with patch.object(subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(setup.SetupError, "Missing or damaged"):
                    self.backend.play()
                spawn.assert_not_called()
            path.write_bytes(original)
        (current / "assets/audio.pck").unlink()
        self.assertFalse(self.backend.status()["ready"])
        with self.assertRaises(setup.SetupError):
            self.backend.verify()

    def test_running_game_blocks_import_and_duplicate_play(self):
        with patch.object(setup, "game_running", return_value=True):
            with self.assertRaisesRegex(setup.SetupError, "Close Darkwatch"):
                self.backend.import_iso(self.iso)
            with self.assertRaisesRegex(setup.SetupError, "Close Darkwatch"):
                self.backend.play()

    def test_partition_detection_xbe_identity_and_unsafe_disc_tree(self):
        for offset in setup.PARTITIONS:
            make_iso(self.iso, self.data, offset=offset)
            with self.iso.open("rb") as source:
                found, _ = self.backend.find_volume(source, self.iso.stat().st_size)
            self.assertEqual(found, offset)
        wrong = dict(self.data, **{"default.xbe": b"XBEH unsupported test!"})
        for options in (dict(data=wrong), dict(data=self.data, bad_name="../default"), dict(data=self.data, cycle=True)):
            make_iso(self.iso, **options)
            with self.iso.open("rb") as source:
                with self.assertRaises(setup.SetupError):
                    self.backend.find_volume(source, self.iso.stat().st_size)

    def test_iso_and_xiso_extensions_import_both_supported_disc_layouts(self):
        for extension in ('.iso', '.xiso'):
            for offset in setup.PARTITIONS:
                with self.subTest(extension=extension, offset=offset):
                    image = self.root / ('my disc' + extension)
                    make_iso(image, self.data, offset=offset)
                    with setup.exclusive(self.install):
                        current = Path(self.backend.import_iso(image)['install_dir'])
                    self.assertEqual(self.backend.verify(), current)
                    for name, data in self.installed_data.items():
                        self.assertEqual((current / 'assets' / name).read_bytes(), data)
                    self.assertEqual(json.loads((current / 'install.json').read_text())['partition_offset'], offset)

    def test_package_damage_and_escaped_active_pointer_rejected(self):
        (self.payload / "runtime" / setup.EXE).write_bytes(b"corrupt")
        with self.assertRaisesRegex(setup.SetupError, "Launcher file is damaged"):
            self.backend.import_iso(self.iso)
        self.install.mkdir(exist_ok=True)
        (self.install / "active.json").write_text('{"version":"../escape"}')
        with self.assertRaisesRegex(setup.SetupError, "Installation record"):
            self.backend.active()

    def test_incomplete_package_and_missing_artwork_rejected(self):
        metadata = self.package / "package-manifest.json"
        value = json.loads(metadata.read_text())
        value["complete"] = False
        metadata.write_text(json.dumps(value))
        with self.assertRaisesRegex(setup.SetupError, "incomplete"):
            setup.Setup(self.package, self.install)
        value["complete"] = True
        value["release_profile"]["diagnostics"] = True
        metadata.write_text(json.dumps(value))
        with self.assertRaisesRegex(setup.SetupError, "required release runtime"):
            setup.Setup(self.package, self.install)
        (self.payload / "hd_ui/overrides.toml").write_text('[[texture]]\nfile="missing.png"\n')
        self.repin()
        backend = setup.Setup(self.package, self.install, notify=lambda *args, **kw: None)
        with self.assertRaisesRegex(setup.SetupError, "artwork package is incomplete"):
            backend.import_iso(self.iso)

    def test_cli_json_contract_and_public_metadata(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = setup.main(["--package", str(self.package), "--install-root", str(self.install), "--status"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["event"], "status")
        self.assertFalse(result["installed"])
        shipped = json.loads((ROOT / "launcher/supported-disc.json").read_text())
        self.assertEqual(len(shipped["files"]), 23)
        pin = json.loads((ROOT / "config/xbexbe-toolchain.json").read_text())
        self.assertEqual(shipped["xbe_sha256"], pin["xbe_sha256"])
        self.assertEqual(next(row["sha256"] for row in shipped["files"] if row["path"] == "default.xbe"), pin["xbe_sha256"])

    def test_release_check_is_separate_from_installation_and_offline_failure(self):
        import release_check
        for status in ('available', 'current', 'unavailable'):
            checked = dict(status=status, current_version=setup.PACKAGE_VERSION, platform='linux', message='release check')
            output = io.StringIO()
            before = self.snapshot(self.package)
            with patch.object(release_check, 'check', return_value=checked) as check, \
                    patch.object(setup, 'Setup', side_effect=AssertionError('must not open installation')), \
                    patch('sys.stdout', output):
                code = setup.main(['--package', str(self.package), '--install-root', str(self.install),
                                   '--check-updates', '--platform', 'linux'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue()), dict(event='release_check', **checked))
            check.assert_called_once_with(setup.PACKAGE_VERSION, 'linux')
            self.assertEqual(self.snapshot(self.package), before)


if __name__ == "__main__":
    unittest.main()
