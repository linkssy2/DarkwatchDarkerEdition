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
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "launcher"))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


intake = sys.modules.get("intake") or load("intake", ROOT / "tools/intake.py")
bonus = sys.modules.get("bonus_content") or load("bonus_content", ROOT / "launcher/bonus_content.py")
gameplay_hd = sys.modules.get("gameplay_hd") or load("gameplay_hd", ROOT / "launcher/gameplay_hd.py")
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
        shutil.copyfile(ROOT / "launcher/bonus_content.py", self.payload / "bonus_content.py")
        shutil.copyfile(ROOT / "launcher/gameplay_hd.py", self.payload / "gameplay_hd.py")
        for name in ('character_animation.py', 'character_archive.py', 'character_assets.py',
                     'character_repaint.py', 'character_content.py', 'character_boss.py',
                     'character_boss_effects.py', 'character_spectral_hands.py', 'character_hand_seams.py',
                     'character_secondary.py',
                     'character-catalog.json'):
            shutil.copyfile(ROOT / 'launcher' / name, self.payload / name)
        (self.payload / 'character-art').mkdir()
        for size in (1024, 256):
            name = f'cassidy-hands-{size}.dds'
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

    def test_disk_budget_includes_all_character_copies(self):
        original_bytes = sum(len(data) for data in self.data.values())
        spare = original_bytes + 512 * 1024 * 1024
        usage = shutil._ntuple_diskusage(total=spare, used=0, free=spare)
        with patch.object(shutil, 'disk_usage', return_value=usage):
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


if __name__ == "__main__":
    unittest.main()
