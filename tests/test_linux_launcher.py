"""Synthetic Proton orchestration only: no Wine, installation or game is launched."""

from contextlib import ExitStack, contextmanager, nullcontext
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import queue
import signal
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("linux_launcher", ROOT / "launcher/linux/launcher.py")
linux = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(linux)
ADAPTER_SPEC = importlib.util.spec_from_file_location("linux_backend_adapter", ROOT / "launcher/linux/run_backend.py")
adapter = importlib.util.module_from_spec(ADAPTER_SPEC)
ADAPTER_SPEC.loader.exec_module(adapter)
WINE_PATH = linux.wine_path
MOUNT_PATHS = linux.mount_paths


def linux_spelling(path):
    # Fixture files may be hosted on Windows; production paths remain Linux paths.
    value = path.as_posix() if isinstance(path, Path) else str(path)
    if len(value) > 2 and value[1] == ":":
        value = "/fixture/" + value[3:]
    return value


class Process:
    def __init__(self, events=(), code=0):
        self.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in events))
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def wait(self):
        return self.code


class LinuxLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / "Darker Edition café").resolve()
        self.root.mkdir()
        self.steam = self.root / "Native Steam"
        self.library = self.root / "Other Library"
        self.proton = self.library / "steamapps/common/Proton - Experimental/proton"
        self.runtime = self.library / "steamapps/common/SteamLinuxRuntime_steamrt4/_v2-entry-point"
        self.write(self.steam / "steamapps/libraryfolders.vdf", '"libraryfolders" { "1" { "path" ' +
                   json.dumps(str(self.library), ensure_ascii=False) + ' } }')
        self.write(self.proton, "installed executable")
        self.write(self.proton.parent / "toolmanifest.vdf", '"manifest" { "require_tool_appid" "4183110" }')
        self.write(self.library / "steamapps/appmanifest_4183110.acf", '"AppState" { "installdir" "SteamLinuxRuntime_steamrt4" }')
        self.write(self.runtime, "installed executable")
        self.proton.chmod(0o755)
        self.runtime.chmod(0o755)
        for file in ("payload/python/python.exe", "payload/setup_backend.py", "package-manifest.json"):
            self.write(self.root / "windows" / file, "payload fixture")
        self.write(self.root / "linux/run_backend.py", "adapter fixture")
        self.tools = (self.steam, self.proton, self.runtime)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def action_patches(self, process):
        stack = ExitStack()
        self.addCleanup(stack.close)
        popen = stack.enter_context(mock.patch.object(linux.subprocess, "Popen", return_value=process))
        stack.enter_context(mock.patch.object(linux.signal, "getsignal", return_value=None))
        signals = stack.enter_context(mock.patch.object(linux.signal, "signal"))
        stack.enter_context(mock.patch.object(linux, "action_lock", return_value=nullcontext()))
        stack.enter_context(mock.patch.object(linux, "mount_paths", side_effect=lambda paths: MOUNT_PATHS([linux_spelling(p) for p in paths])))
        stack.enter_context(mock.patch.object(linux, "wine_path", side_effect=lambda path: WINE_PATH(linux_spelling(path))))
        return popen, signals

    def test_runtime_follows_proton_manifest_in_second_library(self):
        self.assertEqual(linux.steam_tools(self.steam), tuple(p.resolve() for p in self.tools))

    def test_drop_in_iso_uses_normal_direct_action_only_for_fresh_install(self):
        iso = self.root / 'assets/Darkwatch Espa\u00f1ol.XISO'
        self.write(iso, 'unchanged ISO fixture')
        self.write(iso.parent / 'README.txt', 'instructions')
        for installed in (False, True, None):
            with self.subTest(installed=installed):
                calls = []
                def run(root, tools, action, path=None, output=print, status=None):
                    calls.append((action, path))
                    if status is not None:
                        status.update(event='status', installed=installed)
                    return 0
                with mock.patch.object(linux, 'run_action', side_effect=run):
                    self.assertFalse(linux.detect_assets_iso(self.root, self.tools, output=lambda _: None))
                self.assertEqual(calls, [('--status', None)] + ([('--use-iso', iso)] if installed is False else []))
                self.assertEqual(iso.read_text(), 'unchanged ISO fixture')

    def test_drop_in_ambiguous_unsupported_or_bad_status_keeps_selection(self):
        iso = self.root / 'assets/one.iso'
        self.write(iso, 'unsupported fixture')
        for mode in ('multiple', 'unsupported', 'bad-status'):
            with self.subTest(mode=mode):
                second = self.root / 'assets/two.xiso'
                if mode == 'multiple':
                    self.write(second, 'second fixture')
                else:
                    second.unlink(missing_ok=True)
                calls, messages = [], []
                def run(root, tools, action, path=None, output=print, status=None):
                    calls.append(action)
                    if status is not None:
                        status.update(installed=False)
                        return 1 if mode == 'bad-status' else 0
                    output('Unsupported Xbox image')
                    return 1
                with mock.patch.object(linux, 'run_action', side_effect=run):
                    self.assertEqual(linux.detect_assets_iso(self.root, self.tools, output=messages.append), mode != 'bad-status')
                self.assertEqual(calls, ['--status'] + (['--use-iso'] if mode == 'unsupported' else []))
                self.assertEqual(iso.read_text(), 'unsupported fixture')
                if mode != 'bad-status':
                    self.assertTrue(messages)

    def test_empty_assets_does_not_start_proton_for_detection(self):
        self.write(self.root / 'assets/README.txt', 'instructions')
        self.write(self.root / 'assets/nested/disc.iso', 'nested files are not auto-selected')
        with mock.patch.object(linux, 'run_action') as run:
            self.assertFalse(linux.detect_assets_iso(self.root, self.tools))
        run.assert_not_called()

    def test_drop_in_startup_runs_before_interactive_menu(self):
        with mock.patch.object(linux.sys, 'platform', 'linux'), \
             mock.patch.object(linux.sys.stdin, 'isatty', return_value=True), \
             mock.patch.object(linux, 'steam_tools', return_value=self.tools), \
             mock.patch.object(linux, 'start_release_check', return_value=None), \
             mock.patch.object(linux, 'detect_assets_iso', return_value=True) as detect, \
             mock.patch('builtins.input', side_effect=['0', '0', '0']), mock.patch('builtins.print') as output:
            self.assertEqual(linux.main([]), 0)
        detect.assert_called_once()
        self.assertTrue(output.call_args_list[0].args[0].startswith('\nSelect Game'))

    def test_release_check_reads_package_version_and_uses_linux_without_game_data(self):
        self.write(self.root / "windows/package-manifest.json", '{"version":"0.6.1"}')
        self.write(self.root / "windows/payload/release_check.py", '''
def check(version, platform):
    assert platform == "linux"
    return dict(status="available", current_version=version, latest_version="0.7",
                message="Linux release 0.7 is available.",
                release_url="https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7")
''')
        with mock.patch.object(linux.subprocess, "Popen") as process:
            result = linux.check_releases(self.root)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["current_version"], "0.6.1")
        self.assertIn(result["release_url"], linux.release_text(result))
        process.assert_not_called()
        self.assertFalse((self.root / "GameData").exists())
        self.assertFalse((self.root / ".proton").exists())

    def test_release_check_failure_is_advisory_and_preserves_installation_files(self):
        self.write(self.root / "windows/package-manifest.json", '{"version":"0.6.1"}')
        self.write(self.root / "windows/payload/release_check.py", 'def check(*args):\n    raise OSError("offline")\n')
        self.write(self.root / "GameData/installation-location.json", "existing reference")
        self.write(self.root / "GameData/active.json", "existing receipt")
        self.write(self.root / "GameData/save/profile", "existing save")
        before = {p: p.read_bytes() for p in (self.root / "GameData").rglob("*") if p.is_file()}
        self.assertEqual(linux.check_releases(self.root)["status"], "unavailable")
        self.write(self.root / "windows/package-manifest.json", "invalid")
        self.assertEqual(linux.check_releases(self.root)["status"], "unavailable")
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertFalse((self.root / "last-setup-error.txt").exists())

    def test_cli_release_check_does_not_require_steam_or_start_proton(self):
        for status in ("available", "current", "unavailable"):
            with self.subTest(status=status), mock.patch.object(linux.sys, "platform", "linux"), \
                 mock.patch.object(linux, "steam_tools") as steam, \
                 mock.patch.object(linux, "run_action") as action, \
                 mock.patch.object(linux, "check_releases", return_value=dict(status=status, message="Release check " + status)), \
                 mock.patch("builtins.print") as output:
                self.assertEqual(linux.main(["--check-updates"]), 0)
                output.assert_called_once_with("Release check " + status)
                steam.assert_not_called()
                action.assert_not_called()

    def test_background_release_check_does_not_delay_play_or_quit(self):
        entered, finish = threading.Event(), threading.Event()
        def slow_check(root):
            entered.set()
            finish.wait(3)
            return dict(status="unavailable", message="Offline")
        pending = None
        try:
            with mock.patch.object(linux, "check_releases", side_effect=slow_check):
                pending = linux.start_release_check(self.root)
                self.assertTrue(entered.wait(1))
                self.assertTrue(pending.empty())
                with mock.patch.object(linux.sys, "platform", "linux"), \
                     mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
                     mock.patch.object(linux, "steam_tools", return_value=self.tools), \
                     mock.patch.object(linux, "start_release_check", return_value=pending) as start, \
                     mock.patch.object(linux, "run_action", return_value=0) as run, \
                     mock.patch("builtins.input", side_effect=["1", "0"]), mock.patch("builtins.print"):
                    self.assertEqual(linux.main([]), 0)
                    self.assertFalse(finish.is_set())
                    start.assert_called_once()
                    self.assertEqual(run.call_args.args[2:], ("--play", None))
        finally:
            finish.set()
            if pending is not None:
                self.assertEqual(pending.get(timeout=2)["status"], "unavailable")

    def test_menu_release_notice_and_manual_check_only_show_results(self):
        available = dict(status="available", message="New Linux release", release_url="https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7")
        pending = queue.Queue()
        pending.put(available)
        with mock.patch.object(linux.sys, "platform", "linux"), \
             mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(linux, "steam_tools", return_value=self.tools), \
             mock.patch.object(linux, "start_release_check", return_value=pending) as start, \
             mock.patch.object(linux, "check_releases", return_value=dict(status="current", message="Already current")) as check, \
             mock.patch.object(linux, "run_action") as run, \
             mock.patch("builtins.input", side_effect=["3", "1", "0", "0"]), mock.patch("builtins.print") as output:
            self.assertEqual(linux.main([]), 0)
            start.assert_called_once()
            check.assert_called_once()
            run.assert_not_called()
            self.assertIn(mock.call("New Linux release\n" + available["release_url"]), output.call_args_list)
            self.assertIn(mock.call("Already current"), output.call_args_list)

    def test_download_update_locks_existing_data_and_preserves_user_files(self):
        self.write(self.root / "windows/package-manifest.json", '{"version":"0.6.1"}')
        self.write(self.root / "GameData/active.json", '{"version":"installed"}')
        self.write(self.root / "GameData/save/profile", 'save')
        self.write(self.root / ".proton/cache/keep", 'cache')
        held, acquired = [], []
        @contextmanager
        def lock(path):
            held.append(path)
            acquired.append(path)
            try:
                yield
            finally:
                held.remove(path)
        updater = SimpleNamespace(prepare=mock.Mock(), apply=mock.Mock(return_value="0.7"),
                                  pending=mock.Mock(return_value=False), recover=mock.Mock())
        def prepare(root, version, platform, notify, cancel):
            self.assertEqual((root, version, platform), (self.root, "0.6.1", "linux"))
            self.assertEqual(len(held), 2)
            self.assertIn(str(self.root / "windows/payload"), sys.path)
            cancel()
            notify("progress", "Downloading", percent=10)
        updater.prepare.side_effect = prepare
        messages = []
        original_path = sys.path[:]
        with mock.patch.object(linux, "load_updater", return_value=updater), \
             mock.patch.object(linux, "require_game_closed") as closed, \
             mock.patch.object(linux, "action_lock", side_effect=lock):
            self.assertTrue(linux.download_update(self.root, messages.append))
        self.assertEqual(acquired, [self.root / ".proton/launcher.lock", self.root / "GameData/.launcher.lock"])
        self.assertFalse(held)
        self.assertEqual(closed.call_count, 2)
        updater.apply.assert_called_once_with(self.root)
        self.assertEqual(sys.path, original_path)
        self.assertIn("10%  Downloading", messages)
        self.assertEqual((self.root / "GameData/save/profile").read_text(), 'save')
        self.assertEqual((self.root / ".proton/cache/keep").read_text(), 'cache')

    def test_update_locks_the_external_installation_without_creating_another_one(self):
        data = self.root.parent / "Existing GameData"
        self.write(data / "active.json", '{}')
        self.write(self.root / "GameData/installation-location.json", '{"root":"Z:\\\\existing"}')
        with mock.patch.object(linux, "native_wine_path", return_value=data), \
             mock.patch.object(linux, "require_game_closed"), \
             mock.patch.object(linux, "action_lock", return_value=nullcontext()) as lock:
            with linux.update_locks(self.root):
                pass
        self.assertEqual(lock.call_args_list, [mock.call(self.root / ".proton/launcher.lock"), mock.call(data / ".launcher.lock")])
        self.assertFalse((self.root / "GameData/active.json").exists())

    def test_cancelled_or_failed_download_recovers_pending_files_and_restores_handlers(self):
        self.write(self.root / "windows/package-manifest.json", '{"version":"0.6.1"}')
        for cancelled in (True, False):
            updater = SimpleNamespace(prepare=mock.Mock(), apply=mock.Mock(side_effect=ValueError("commit failed")),
                                      pending=mock.Mock(return_value=True), recover=mock.Mock(return_value=True))
            with self.subTest(cancelled=cancelled), mock.patch.object(linux, "load_updater", return_value=updater), \
                 mock.patch.object(linux, "update_locks", return_value=nullcontext()), \
                 mock.patch.object(linux, "require_game_closed"), \
                 mock.patch.object(linux.signal, "getsignal", return_value=None), \
                 mock.patch.object(linux.signal, "signal") as signals:
                if cancelled:
                    def prepare(root, version, platform, notify, check_cancel):
                        signals.call_args_list[0].args[1](signal.SIGINT, None)
                        check_cancel()
                    updater.prepare.side_effect = prepare
                with self.assertRaises(linux.UpdateCancelled if cancelled else ValueError):
                    linux.download_update(self.root, lambda _: None)
                updater.recover.assert_called_once_with(self.root)
                self.assertEqual(signals.call_count, 4)
                if cancelled:
                    updater.apply.assert_not_called()

    def test_recovery_prefers_preserved_runner_and_happens_before_steam_discovery(self):
        runner = self.root / ".launcher-update/runner/release_update.py"
        self.write(runner, 'identity = "preserved"\n')
        self.write(self.root / "windows/payload/release_update.py", 'raise RuntimeError("mixed package")\n')
        self.assertEqual(linux.load_updater(self.root, recovery=True).identity, "preserved")
        self.write(self.root / ".launcher-update/transaction.json", '{"phase":"applying"}')
        updater = SimpleNamespace(pending=mock.Mock(return_value=True), recover=mock.Mock(return_value=True))
        with mock.patch.object(linux.sys, "platform", "linux"), \
             mock.patch.object(linux, "__file__", str(self.root / "linux/launcher.py")), \
             mock.patch.object(linux, "load_updater", return_value=updater), \
             mock.patch.object(linux, "update_locks", return_value=nullcontext()), \
             mock.patch.object(linux, "restart_launcher") as restart, \
             mock.patch.object(linux, "steam_tools") as steam, mock.patch("builtins.print"):
            self.assertEqual(linux.main(["--play"]), 0)
        updater.recover.assert_called_once_with(self.root)
        restart.assert_called_once_with(self.root, ["--play"])
        steam.assert_not_called()

    def test_proc_guard_rejects_game_and_same_installation_steam_setup(self):
        proc = self.root / "fake-proc"
        for arguments in (["Z:\\game\\darkwatch_xbe.exe"],
                          ["python.exe", str(self.root / "linux/run_backend.py"), "--play"],
                          ["python.exe", str(self.root / "windows/payload/setup_backend.py"), "--import-iso"]):
            self.write(proc / "123/cmdline", "\0".join(arguments))
            with self.subTest(arguments=arguments), self.assertRaises(linux.LauncherError):
                linux.require_game_closed(self.root, proc)
        self.write(proc / "123/cmdline", "python3\0unrelated.py")
        linux.require_game_closed(self.root, proc)
        with self.assertRaises(linux.LauncherError):
            linux.require_game_closed(self.root, self.root / "absent-proc")

    def test_real_recovery_restores_managed_file_and_next_start_discards_backup(self):
        scratch = self.root / ".launcher-update"
        runner = scratch / "runner/release_update.py"
        self.write(runner, (ROOT / "launcher/release_update.py").read_text(encoding="utf-8"))
        name = "windows/payload/example.py"
        self.write(self.root / name, "new package")
        self.write(scratch / "backup" / name, "old package")
        self.write(self.root / "GameData/kept-save", "saved progress")
        state = dict(phase="applying", platform="linux", version="0.6.2", files={name: dict(
            old=hashlib.sha256(b"old package").hexdigest(), new=hashlib.sha256(b"new package").hexdigest())})
        self.write(scratch / "transaction.json", json.dumps(state))
        with mock.patch.object(linux, "update_locks", return_value=nullcontext()):
            self.assertTrue(linux.recover_update(self.root, lambda _: None))
            self.assertEqual((self.root / name).read_text(), "old package")
            self.assertEqual(json.loads((scratch / "transaction.json").read_text())["phase"], "rolled_back")
            self.assertFalse(adapter.update_interrupted(self.root))
            self.assertTrue(scratch.is_dir())
            self.assertFalse(linux.recover_update(self.root, lambda _: None))
        self.assertFalse(scratch.exists())
        self.assertEqual((self.root / "GameData/kept-save").read_text(), "saved progress")

    def test_cli_download_restarts_new_code_and_preserves_runtime_options(self):
        for installed in (True, False):
            with self.subTest(installed=installed), mock.patch.object(linux.sys, "platform", "linux"), \
                 mock.patch.object(linux, "__file__", str(self.root / "linux/launcher.py")), \
                 mock.patch.object(linux, "recover_update", return_value=False), \
                 mock.patch.object(linux, "download_update", return_value=installed) as download, \
                 mock.patch.object(linux, "restart_launcher") as restart, \
                 mock.patch.object(linux, "steam_tools") as steam:
                self.assertEqual(linux.main(["--steam-root", "/my steam", "--proton", "/my proton", "--download-update"]), 0)
                download.assert_called_once_with(self.root)
                restart.assert_called_once_with(self.root, ["--steam-root", str(Path("/my steam")), "--proton", str(Path("/my proton"))] + (["--update"] if installed else []))
                steam.assert_not_called()
        with mock.patch.object(linux.os, "execv") as execute:
            linux.restart_launcher(self.root, ["--update"])
        execute.assert_called_once_with(sys.executable, [sys.executable, "-B", str(self.root / "linux/launcher.py"), "--update"])

    def test_menu_download_and_update_uses_explicit_choice_only(self):
        with mock.patch.object(linux.sys, "platform", "linux"), \
             mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(linux, "recover_update", return_value=False), \
             mock.patch.object(linux, "steam_tools", return_value=self.tools), \
             mock.patch.object(linux, "start_release_check", return_value=queue.Queue()), \
             mock.patch.object(linux, "download_update", return_value=True) as download, \
             mock.patch.object(linux, "restart_launcher") as restart, \
             mock.patch("builtins.input", side_effect=["3", "2"]), mock.patch("builtins.print"):
            self.assertEqual(linux.main([]), 0)
        download.assert_called_once()
        self.assertEqual(restart.call_args.args[1], ["--update"])

    def test_spanish_install_and_language_value_are_forwarded(self):
        popen, _ = self.action_patches(Process([dict(event="result", ready=True, language="es")]))
        disc = self.root / "PS2 Español's disc.iso"
        disc.write_bytes(b"fixture")
        popen.return_value = Process([dict(event="result", ready=True, language="es")])
        self.assertEqual(linux.run_action(self.root, self.tools, "--install-spanish", disc, lambda _: None), 0)
        self.assertEqual(popen.call_args.args[0][-2:], ["--install-spanish", WINE_PATH(linux_spelling(disc))])
        popen.return_value = Process([dict(event="result", ready=True, language="es")])
        self.assertEqual(linux.run_action(self.root, self.tools, "--set-language", "es", lambda _: None), 0)
        self.assertEqual(popen.call_args.args[0][-2:], ["--set-language", "es"])
        with self.assertRaises(linux.LauncherError):
            linux.run_action(self.root, self.tools, "--set-language", "../evil")

    def test_explicit_proton_folder_and_runtime3_dependency(self):
        selected = self.steam / "compatibilitytools.d/Chosen Proton/proton"
        self.write(selected, "chosen installed executable")
        selected.chmod(0o755)
        self.write(selected.parent / "toolmanifest.vdf", '"require_tool_appid" "1628350"')
        self.write(self.library / "steamapps/appmanifest_1628350.acf", '"installdir" "SteamLinuxRuntime_sniper"')
        sniper = self.library / "steamapps/common/SteamLinuxRuntime_sniper/_v2-entry-point"
        self.write(sniper, "installed")
        sniper.chmod(0o755)
        for option in (selected, selected.parent):
            self.assertEqual(linux.steam_tools(self.steam, option),
                             (self.steam.resolve(), selected.resolve(), sniper.resolve()))

    def test_missing_matching_runtime_does_not_substitute_another(self):
        (self.library / "steamapps/appmanifest_4183110.acf").unlink()
        with self.assertRaisesRegex(linux.LauncherError, "4183110"):
            linux.steam_tools(self.steam)

    def test_manifest_requires_unambiguous_numeric_dependency(self):
        for content in ('"require_tool_appid" "../../escape"',
                        '"require_tool_appid" "1" "require_tool_appid" "2"', ""):
            self.write(self.proton.parent / "toolmanifest.vdf", content)
            with self.assertRaisesRegex(linux.LauncherError, "dependency"):
                linux.steam_tools(self.steam)

    def test_runtime_install_directory_cannot_escape_library(self):
        self.write(self.library / "steamapps/appmanifest_4183110.acf", '"installdir" "../escape"')
        with self.assertRaises(linux.LauncherError):
            linux.steam_tools(self.steam)

    def test_absolute_unicode_paths_are_single_windows_arguments(self):
        self.assertEqual(WINE_PATH(PurePosixPath("/home/me/My Games/café's $disc.iso")),
                         "Z:\\home\\me\\My Games\\café's $disc.iso")
        for path in ("relative/file.iso", "/a:b/disc.iso", "/a\\b/disc.iso", "/a\nb.iso"):
            with self.assertRaises(linux.LauncherError):
                WINE_PATH(path)

    def test_import_preserves_backend_contract_and_does_not_play(self):
        disc = self.root.parent / "External ISO" / "café's $disc.xiso"
        self.write(disc, "disc fixture")
        process = Process([{"event": "progress", "message": "Preparing", "percent": 20},
                           {"event": "result", "message": "Installed", "ready": True}])
        popen, _ = self.action_patches(process)
        messages = []
        with mock.patch.dict(os.environ, {"PROTON_LOG": "1", "WINEDEBUG": "+all", "SteamGameId": "123", "SteamAppId": "123"}):
            result = linux.run_action(self.root, self.tools, "--import-iso", disc, messages.append)
        self.assertEqual(result, 0)
        popen.assert_called_once()
        args, kwargs = popen.call_args
        command = args[0]
        self.assertEqual(command[:7], [str(self.runtime), "--verb=run", "--", str(self.proton), "run",
                                      WINE_PATH(linux_spelling(self.root / "windows/payload/python/python.exe")), "-B"])
        self.assertEqual(command[7], WINE_PATH(linux_spelling(self.root / "linux/run_backend.py")))
        self.assertEqual(command[-2:], ["--import-iso", WINE_PATH(linux_spelling(disc))])
        self.assertNotIn("--play", command)
        self.assertNotIn("waitforexitandrun", command)
        self.assertNotIn("shell", kwargs)
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["env"]["PROTON_LOG"], "1")
        self.assertEqual(kwargs["env"]["WINEDEBUG"], "+all")
        self.assertEqual(kwargs["env"]["STEAM_COMPAT_DATA_PATH"], str(self.root / ".proton"))
        self.assertEqual(kwargs["env"]["STEAM_COMPAT_INSTALL_PATH"], str(self.root / "windows"))
        self.assertEqual(kwargs["env"]["XDG_CACHE_HOME"], str(self.root / ".proton/cache"))
        self.assertEqual(kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RW"], linux_spelling(self.root) + ":" + linux_spelling(self.proton.parent))
        self.assertIn(linux_spelling(disc.parent), kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RO"])
        self.assertNotIn("SteamGameId", kwargs["env"])
        self.assertNotIn("SteamAppId", kwargs["env"])
        self.assertIn("20%  Preparing", messages)
        self.assertFalse(list((self.root / "GameData").glob(".cancel-*")))

    def test_proton_options_are_preserved_with_owned_portable_paths(self):
        selected = {"PROTON_LOG": "1", "WINEDEBUG": "+timestamp,+seh",
                    "VKD3D_DEBUG": "info", "DXVK_LOG_LEVEL": "debug",
                    "PROTON_NO_ESYNC": "1", "DXVK_HUD": "fps",
                    "STEAM_COMPAT_DATA_PATH": "/unrelated-prefix",
                    "PRESSURE_VESSEL_FILESYSTEMS_RW": "/unrelated-mount"}
        with mock.patch.dict(os.environ, selected, clear=True), \
             mock.patch.object(linux, "mount_paths", side_effect=lambda paths: MOUNT_PATHS([linux_spelling(p) for p in paths])):
            env = linux.launch_environment(self.root, *self.tools)
        for name in ("PROTON_LOG", "WINEDEBUG", "VKD3D_DEBUG", "DXVK_LOG_LEVEL", "PROTON_NO_ESYNC", "DXVK_HUD"):
            self.assertEqual(env[name], selected[name])
        self.assertEqual(env["STEAM_COMPAT_DATA_PATH"], str(self.root / ".proton"))
        self.assertNotIn("/unrelated-mount", env["PRESSURE_VESSEL_FILESYSTEMS_RW"])
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(linux, "mount_paths", side_effect=lambda paths: MOUNT_PATHS([linux_spelling(p) for p in paths])):
            defaults = linux.launch_environment(self.root, *self.tools)
        self.assertEqual({name: defaults[name] for name in ("PROTON_LOG", "WINEDEBUG", "VKD3D_DEBUG", "DXVK_LOG_LEVEL")},
                         dict(PROTON_LOG="0", WINEDEBUG="-all", VKD3D_DEBUG="none", DXVK_LOG_LEVEL="none"))

    def test_iso_inside_portable_folder_is_not_remounted_readonly(self):
        disc = self.root / "My disc.iso"
        self.write(disc, "disc fixture")
        popen, _ = self.action_patches(Process([{"event": "result", "message": "OK"}]))
        self.assertEqual(linux.run_action(self.root, self.tools, "--import-iso", disc, lambda _: None), 0)
        self.assertEqual(popen.call_args.kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RO"], "")
        self.assertIn(linux_spelling(self.root), popen.call_args.kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RW"])

    def test_direct_iso_action_and_retained_disc_are_mounted_readonly(self):
        disc = self.root.parent / "External ISO" / "Español's $disc.xiso"
        self.write(disc, "disc fixture")
        popen, _ = self.action_patches(Process([dict(event="result", ready=True)]))
        self.assertEqual(linux.run_action(self.root, self.tools, "--use-iso", disc, lambda _: None), 0)
        self.assertEqual(popen.call_args.args[0][-2:], ["--use-iso", WINE_PATH(linux_spelling(disc))])
        self.assertIn(linux_spelling(disc.parent), popen.call_args.kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RO"])
        self.assertNotIn("--import-iso", popen.call_args.args[0])
        version = "1" * 32
        self.write(self.root / "GameData/active.json", json.dumps(dict(version=version)))
        self.write(self.root / "GameData/versions" / version / "install.json",
                   json.dumps(dict(source_mode="iso", iso_path=WINE_PATH(linux_spelling(disc)))))
        spanish = self.root.parent / "Spanish.iso"
        self.write(spanish, "PS2 fixture")
        for action, argument in (("--play", None), ("--status", None), ("--verify", None),
                                 ("--update", None), ("--install-spanish", spanish)):
            with self.subTest(action=action), mock.patch.object(linux, "native_wine_path", return_value=disc) as native:
                popen.return_value = Process([dict(event="result", ready=True)])
                self.assertEqual(linux.run_action(self.root, self.tools, action, argument, lambda _: None), 0)
                native.assert_called_once_with(WINE_PATH(linux_spelling(disc)))
                env = popen.call_args.kwargs["env"]
                self.assertIn(linux_spelling(disc.parent), env["PRESSURE_VESSEL_FILESYSTEMS_RO"])
                self.assertNotIn(linux_spelling(disc.parent), env["PRESSURE_VESSEL_FILESYSTEMS_RW"])

    def test_missing_or_invalid_saved_iso_cannot_block_reselection(self):
        data = self.root / "GameData"
        version = "a" * 32
        self.write(data / "active.json", json.dumps(dict(version=version)))
        metadata = data / "versions" / version / "install.json"
        for content in ('{broken', '{}', json.dumps(dict(source_mode="iso", iso_path="C:\\disc.iso"))):
            self.write(metadata, content)
            self.assertIsNone(linux.saved_iso_path(data))
        missing = self.root.parent / "Removed drive/disc.iso"
        self.write(metadata, json.dumps(dict(source_mode="iso", iso_path="Z:\\Removed drive\\disc.iso")))
        with mock.patch.object(linux, "native_wine_path", return_value=missing):
            self.assertIsNone(linux.saved_iso_path(data))
        disc = self.root.parent / "Relocated.iso"
        self.write(disc, "disc fixture")
        popen, _ = self.action_patches(Process([dict(event="result", ready=True)]))
        with mock.patch.object(linux, "saved_iso_path", side_effect=AssertionError("Old ISO must not be mounted during repair")):
            self.assertEqual(linux.run_action(self.root, self.tools, "--use-iso", disc, lambda _: None), 0)
        self.assertIn(linux_spelling(disc.parent), popen.call_args.kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RO"])

    def test_optional_hd_error_is_failure_even_if_base_game_is_ready(self):
        pack = self.root / "pack.zip.001"
        self.write(pack, "pack")
        popen, _ = self.action_patches(Process([{"event": "error", "message": "Part missing", "ready": True}]))
        self.assertEqual(linux.run_action(self.root, self.tools, "--install-hd-textures", pack, lambda _: None), 1)
        self.assertEqual(popen.call_args.args[0][-2], "--install-hd-textures")
        popen.assert_called_once()

    def test_status_and_verify_do_not_launch_an_extra_process(self):
        for action, event in (("--status", "status"), ("--verify", "result"), ("--play", "result")):
            with self.subTest(action=action):
                result = {"event": event, "message": "OK", "installed": False, "ready": False}
                popen, _ = self.action_patches(Process([result]))
                status = {}
                self.assertEqual(linux.run_action(self.root, self.tools, action, output=lambda _: None, status=status), 0)
                self.assertEqual(status, result if event == "status" else {})
                popen.assert_called_once()
                self.assertEqual(popen.call_args.args[0][-1], action)

    def test_status_reports_installed_spanish_resources(self):
        self.action_patches(Process([dict(event="status", message="Ready", ready=True,
                                         language="es", spanish_installed=True, spanish_audio_installed=True)]))
        messages = []
        self.assertEqual(linux.run_action(self.root, self.tools, "--status", output=messages.append), 0)
        self.assertIn("Language: es. Spanish text: available. Spanish voices: installed.", messages[-1])

    def test_use_existing_installation_accepts_package_data_and_active_version(self):
        old = self.root.parent / "Previous café installation"
        data = old / "GameData"
        active = data / "versions/installed"
        self.write(data / "active.json", '{"version":"installed"}')
        self.write(active / "install.json", '{}')
        self.write(active / "save/profile", 'keep this save')
        # Attaching a replacement must remain possible if the old reference broke.
        self.write(self.root / "GameData/installation-location.json", '{broken')
        for folder in (old, data, active):
            with self.subTest(folder=folder):
                popen, _ = self.action_patches(Process([dict(event="status", update_available=True, ready=False)]))
                messages = []
                self.assertEqual(linux.run_action(self.root, self.tools, "--use-installation", folder, messages.append), 0)
                command = popen.call_args.args[0]
                self.assertEqual(command[-2:], ["--use-installation", WINE_PATH(linux_spelling(data))])
                self.assertEqual(command[command.index("--install-root") + 1], WINE_PATH(linux_spelling(self.root / "GameData")))
                env = popen.call_args.kwargs["env"]
                self.assertIn(linux_spelling(data), env["PRESSURE_VESSEL_FILESYSTEMS_RW"].split(":"))
                self.assertNotIn(linux_spelling(old), env["PRESSURE_VESSEL_FILESYSTEMS_RO"].split(":"))
                self.assertIn("Ready to play: no. Update available: yes.", messages[-1])
                self.assertNotIn("--update", command)
                self.assertEqual((active / "save/profile").read_text(), 'keep this save')
                self.assertEqual((self.root / "GameData/installation-location.json").read_text(), '{broken')

    def test_persistent_external_installation_is_writable_for_update_and_optional_actions(self):
        data = self.root.parent / "Old installation/GameData"
        self.write(data / "active.json", '{"version":"installed"}')
        reference = WINE_PATH(linux_spelling(data))
        self.write(self.root / "GameData/installation-location.json", json.dumps(dict(root=reference)))
        disc = self.root.parent / "PS2.iso"
        self.write(disc, "fixture")
        for action, argument in (("--status", None), ("--update", None), ("--play", None),
                                 ("--set-language", "es"), ("--install-spanish", disc)):
            with self.subTest(action=action), mock.patch.object(linux, "native_wine_path", return_value=data) as convert:
                popen, _ = self.action_patches(Process([dict(event="result", ready=True)]))
                self.assertEqual(linux.run_action(self.root, self.tools, action, argument, lambda _: None), 0)
                convert.assert_called_once_with(reference)
                command = popen.call_args.args[0]
                self.assertIn(action, command)
                self.assertEqual(command[command.index("--install-root") + 1], WINE_PATH(linux_spelling(self.root / "GameData")))
                self.assertIn(linux_spelling(data), popen.call_args.kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RW"].split(":"))
                self.assertEqual(json.loads((self.root / "GameData/installation-location.json").read_text()), dict(root=reference))
                self.assertFalse(list((self.root / "GameData").glob(".cancel-*")))

    def test_wine_installation_location_only_accepts_absolute_z_drive(self):
        self.assertEqual(linux.native_wine_path("Z:\\home\\me\\Games café\\GameData"), Path("/home/me/Games café/GameData"))
        self.assertEqual(linux.native_wine_path("z:/home/me/GameData"), Path("/home/me/GameData"))
        for value in (None, 7, "", "C:\\GameData", "Z:GameData", "/home/me/GameData", "\\\\host\\share", "Z:\\bad:folder", "Z:\\bad\nfolder"):
            with self.subTest(value=value), self.assertRaises(linux.LauncherError):
                linux.native_wine_path(value)

    def test_invalid_persistent_location_is_not_ignored_or_overwritten(self):
        location = self.root / "GameData/installation-location.json"
        popen, _ = self.action_patches(Process())
        for text in ('{bad', '[]', '{}', '{"root":7}', '{"root":"C:\\\\Games"}', ' ' * 65537):
            self.write(location, text)
            with self.subTest(text=text[:40]), self.assertRaises(linux.LauncherError):
                linux.run_action(self.root, self.tools, "--status")
            self.assertEqual(location.read_text(), text)
        popen.assert_not_called()

    def test_use_installation_refuses_missing_file_noninstall_and_reference_chain(self):
        data = self.root.parent / "External GameData"
        self.write(data / "active.json", '{}')
        self.write(data / "installation-location.json", '{}')
        plain = self.root.parent / "Plain folder"
        plain.mkdir()
        file = self.root.parent / "not-a-folder"
        self.write(file, 'keep')
        popen, _ = self.action_patches(Process())
        for folder in (None, self.root.parent / "missing", file, plain, data):
            with self.subTest(folder=folder), self.assertRaises(linux.LauncherError):
                linux.run_action(self.root, self.tools, "--use-installation", folder)
        popen.assert_not_called()
        self.assertEqual(file.read_text(), 'keep')

    def test_external_update_cancel_keeps_reference_and_uses_local_cancel_channel(self):
        data = self.root.parent / "External GameData"
        self.write(data / "active.json", '{}')
        self.write(data / "save/profile", 'keep')
        location = self.root / "GameData/installation-location.json"
        reference = json.dumps(dict(root=WINE_PATH(linux_spelling(data))))
        self.write(location, reference)
        process = Process()
        _, signals = self.action_patches(process)

        def events():
            handler = next(call.args[1] for call in signals.call_args_list if call.args[0] == signal.SIGINT)
            handler(signal.SIGINT, None)
            self.assertEqual(len(list((self.root / "GameData").glob(".cancel-*"))), 1)
            self.assertFalse(list(data.glob(".cancel-*")))
            yield '{"event":"error","message":"Cancelled","cancelled":true}\n'

        process.stdout = events()
        with mock.patch.object(linux, "native_wine_path", return_value=data):
            self.assertEqual(linux.run_action(self.root, self.tools, "--update", output=lambda _: None), 130)
        self.assertEqual(location.read_text(), reference)
        self.assertEqual((data / "save/profile").read_text(), 'keep')
        self.assertFalse(list((self.root / "GameData").glob(".cancel-*")))

    @unittest.skipUnless(os.name == "posix", "Native Linux symlink behavior")
    def test_external_installation_rejects_native_links_before_mounting(self):
        data = self.root.parent / "External GameData"
        self.write(data / "active.json", '{}')
        other = self.root.parent / "other.txt"
        self.write(other, "keep")
        link = data / "linked-file"
        link.symlink_to(other)
        popen, _ = self.action_patches(Process())
        for action in ("--use-installation", "--update"):
            self.write(self.root / "GameData/installation-location.json", json.dumps(dict(root=WINE_PATH(data))))
            with self.subTest(action=action), self.assertRaisesRegex(linux.LauncherError, "linked file or folder"):
                linux.run_action(self.root, self.tools, action, data if action == "--use-installation" else None)
        link.unlink()
        alias = self.root.parent / "GameData alias"
        alias.symlink_to(data, target_is_directory=True)
        with self.assertRaisesRegex(linux.LauncherError, "linked file or folder"):
            linux.run_action(self.root, self.tools, "--use-installation", alias)
        popen.assert_not_called()
        self.assertEqual(other.read_text(), "keep")

    def test_process_failure_and_missing_terminal_event_fail(self):
        for process in (Process([], 0), Process([{"event": "progress", "message": "Wait"}], 0),
                        Process([{"event": "result", "message": "OK"}], 7)):
            popen, _ = self.action_patches(process)
            self.assertEqual(linux.run_action(self.root, self.tools, "--verify", output=lambda _: None), 1)
            popen.assert_called_once()

    def test_backend_error_shows_bounded_proton_tail_but_success_stays_quiet(self):
        lines = [f"Proton line {index}: " + "x" * 1100 for index in range(11)]
        for event, code in (("error", 1), ("result", 0)):
            with self.subTest(event=event):
                process = Process()
                process.stdout = io.StringIO("\n".join(lines) + "\n" +
                                             json.dumps(dict(event=event, message="Finished")) + "\n")
                self.action_patches(process)
                messages = []
                self.assertEqual(linux.run_action(self.root, self.tools, "--verify", output=messages.append), code)
                expected = ["Finished"] + ([line[:1000] for line in lines[-8:]] if code else [])
                self.assertEqual(messages, expected)

    def test_shader_progress_is_visible_but_does_not_complete_the_action(self):
        events = [dict(event="shader_prepare", message="Preparing shaders", percent=50),
                  dict(event="shader_ready", message="Shaders are ready", percent=100)]
        for complete in (False, True):
            with self.subTest(complete=complete):
                process = Process(events + ([dict(event="result", message="Installed")] if complete else []))
                self.action_patches(process)
                messages = []
                self.assertEqual(linux.run_action(self.root, self.tools, "--import-iso", output=messages.append),
                                 0 if complete else 1)
                self.assertEqual(messages[:2], ["50%  Preparing shaders", "Shaders are ready"])

    def test_cancel_is_cooperative_unique_and_cleaned_after_process_finishes(self):
        process = Process()
        popen, signals = self.action_patches(process)
        unrelated = self.root / "GameData/.cancel-other-operation"
        self.write(unrelated, "do not touch")

        def output_events():
            handler = next(call.args[1] for call in signals.call_args_list if call.args[0] == signal.SIGINT)
            handler(signal.SIGINT, None)
            self.assertEqual(len(list((self.root / "GameData").glob(".cancel-*"))), 2)
            yield '{"event":"error","message":"Cancelled","cancelled":true}\n'

        process.stdout = output_events()
        self.assertEqual(linux.run_action(self.root, self.tools, "--import-iso", output=lambda _: None), 130)
        self.assertEqual(list((self.root / "GameData").glob(".cancel-*")), [unrelated])
        self.assertEqual(signals.call_count, 4)
        popen.assert_called_once()

    def test_incomplete_payload_or_missing_input_never_starts_proton(self):
        popen, _ = self.action_patches(Process())
        with self.assertRaisesRegex(linux.LauncherError, "File not found"):
            linux.run_action(self.root, self.tools, "--import-iso", self.root / "absent.iso")
        (self.root / "windows/package-manifest.json").unlink()
        with self.assertRaisesRegex(linux.LauncherError, "payload is incomplete"):
            linux.run_action(self.root, self.tools, "--status")
        popen.assert_not_called()

    def test_portable_data_refuses_symlink_or_file(self):
        with mock.patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(linux.LauncherError):
                linux.portable_directory(self.root / ".proton")
        self.write(self.root / "GameData", "not a folder")
        with self.assertRaises(linux.LauncherError):
            linux.portable_directory(self.root / "GameData")

    @unittest.skipUnless(os.name == "posix", "Native Linux symlink behavior")
    def test_shell_resolves_a_linked_entrypoint_and_preserves_arguments(self):
        shell = self.root / "Darkwatch.sh"
        self.write(shell, (ROOT / "launcher/linux/Darkwatch.sh").read_text(encoding="utf-8"))
        shell.chmod(0o755)
        self.write(self.root / "linux/launcher.py", "import json, sys; print(json.dumps(sys.argv[1:]))\n")
        shortcut = self.root.parent / "Darkwatch shortcut.sh"
        shortcut.symlink_to(shell)
        result = subprocess.run([str(shortcut), "--import-iso", "a disc's path.iso"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["--import-iso", "a disc's path.iso"])

    @unittest.skipUnless(os.name == "posix", "Native Linux symlink behavior")
    def test_native_preflight_rejects_linked_payload_and_gamedata_before_proton(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        self.write(outside / "file", "do not modify")
        popen, _ = self.action_patches(Process())
        for relative, directory in (("windows", True), ("windows/payload/linked", True),
                                    ("windows/payload/linked-file", False), ("GameData", True),
                                    ("GameData/linked", True), ("GameData/linked-file", False)):
            with self.subTest(path=relative):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                backup = path.with_name(path.name + "-saved") if path.exists() else None
                if backup:
                    path.rename(backup)
                path.symlink_to(outside if directory else outside / "file", target_is_directory=directory)
                try:
                    with self.assertRaisesRegex(linux.LauncherError, "linked file or folder"):
                        linux.run_action(self.root, self.tools, "--status")
                finally:
                    path.unlink()
                    if backup:
                        backup.rename(path)
        popen.assert_not_called()
        self.assertEqual((outside / "file").read_text(), "do not modify")

    @unittest.skipUnless(os.name == "posix", "Native Linux symlink behavior")
    def test_parent_steam_iso_aliases_and_proton_prefix_links_remain_supported(self):
        parent_alias = self.root.parent / "parent alias"
        parent_alias.symlink_to(self.root.parent, target_is_directory=True)
        steam_alias = self.root / "Steam alias"
        steam_alias.symlink_to(self.steam, target_is_directory=True)
        disc = self.root.parent / "actual disc.iso"
        self.write(disc, "disc fixture")
        disc_alias = self.root / "disc alias.iso"
        disc_alias.symlink_to(disc)
        prefix_link = self.root / ".proton/pfx/dosdevices/z:"
        prefix_link.parent.mkdir(parents=True)
        prefix_link.symlink_to("/", target_is_directory=True)
        tools = linux.steam_tools(steam_alias)
        self.assertEqual(tools, self.tools)
        popen, _ = self.action_patches(Process([dict(event="result", message="Installed")]))
        self.assertEqual(linux.run_action(parent_alias / self.root.name, tools, "--import-iso", disc_alias, lambda _: None), 0)
        self.assertEqual(popen.call_args.args[0][-1], WINE_PATH(disc))
        self.assertEqual(popen.call_args.kwargs["env"]["STEAM_COMPAT_DATA_PATH"], str(self.root / ".proton"))
        self.assertTrue(prefix_link.is_symlink())

    @unittest.skipUnless(os.name == "posix", "Native Linux symlink behavior")
    def test_cyclic_input_path_reports_launcher_error_before_proton(self):
        cycle = self.root / "cycle.iso"
        cycle.symlink_to(cycle.name)
        popen, _ = self.action_patches(Process())
        with self.assertRaisesRegex(linux.LauncherError, "Could not resolve path"):
            linux.run_action(self.root, self.tools, "--import-iso", cycle)
        with self.assertRaisesRegex(linux.LauncherError, "Could not resolve path"):
            linux.steam_tools(self.steam, cycle)
        popen.assert_not_called()

    def test_native_lock_is_nonblocking_and_released_even_on_error(self):
        fcntl = SimpleNamespace(flock=mock.Mock(), LOCK_EX=2, LOCK_NB=4, LOCK_UN=8)
        with mock.patch.dict("sys.modules", {"fcntl": fcntl}):
            with self.assertRaisesRegex(ValueError, "failed"):
                with linux.action_lock(self.root / "operation.lock"):
                    raise ValueError("failed")
        self.assertEqual([call.args[1] for call in fcntl.flock.call_args_list], [6, 8])

    def test_busy_native_lock_prevents_proton_start(self):
        popen, _ = self.action_patches(Process())
        with mock.patch.object(linux, "action_lock", side_effect=linux.LauncherError("Already running")):
            with self.assertRaisesRegex(linux.LauncherError, "Already running"):
                linux.run_action(self.root, self.tools, "--play")
        popen.assert_not_called()

    def test_busy_lock_reports_actionable_error(self):
        fcntl = SimpleNamespace(flock=mock.Mock(side_effect=BlockingIOError), LOCK_EX=2, LOCK_NB=4, LOCK_UN=8)
        with mock.patch.dict("sys.modules", {"fcntl": fcntl}):
            with self.assertRaisesRegex(linux.LauncherError, "Close it first"):
                with linux.action_lock(self.root / "operation.lock"):
                    self.fail("Busy lock must not enter")

    def test_adapter_waits_for_successful_game_and_returns_natural_exit(self):
        backend = SimpleNamespace(main=mock.Mock(return_value=0), game_running=mock.Mock(side_effect=[True, True, False]))
        with mock.patch.object(adapter.time, "sleep") as sleep:
            self.assertEqual(adapter.run(backend, ["--package", "Z:\\game\\windows", "--play"]), 0)
        backend.main.assert_called_once_with(["--package", "Z:\\game\\windows", "--play"])
        self.assertEqual(sleep.call_args_list, [mock.call(1), mock.call(1)])

    def test_adapter_never_waits_after_error_or_nonplay_action(self):
        for code, action in ((1, "--play"), (0, "--status"), (0, "--verify"), (0, "--import-iso"), (0, "--install-hd-textures")):
            backend = SimpleNamespace(main=mock.Mock(return_value=code), game_running=mock.Mock())
            self.assertEqual(adapter.run(backend, [action]), code)
            backend.main.assert_called_once_with([action])
            backend.game_running.assert_not_called()

    def test_cli_calls_only_requested_action_and_returns_failure(self):
        with mock.patch.object(linux.sys, "platform", "linux"), \
             mock.patch.object(linux, "steam_tools", return_value=self.tools), \
             mock.patch.object(linux, "run_action", return_value=1) as run:
            self.assertEqual(linux.main(["--import-iso", "/tmp/own disc.iso"]), 1)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[2:], ("--import-iso", Path("/tmp/own disc.iso")))

    def test_menu_import_does_not_play_and_quit_does_not_run_backend(self):
        with mock.patch.object(linux.sys, "platform", "linux"), \
             mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(linux, "steam_tools", return_value=self.tools), \
             mock.patch.object(linux, "run_action", return_value=0) as run, \
             mock.patch("builtins.input", side_effect=["2", "1", "2", '"/tmp/My disc.iso"', "0", "0", "0"]), \
             mock.patch("builtins.print"):
            self.assertEqual(linux.main([]), 0)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[2:], ("--import-iso", Path("/tmp/My disc.iso")))

    def test_grouped_menu_keeps_home_short_and_back_has_no_side_effect(self):
        with mock.patch.object(linux.sys, "platform", "linux"), \
             mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(linux, "steam_tools", return_value=self.tools), \
             mock.patch.object(linux, "start_release_check", return_value=queue.Queue()), \
             mock.patch.object(linux, "run_action") as run, \
             mock.patch.object(linux, "check_releases") as check, \
             mock.patch.object(linux, "download_update") as download, \
             mock.patch("builtins.input", side_effect=["2", "0", "3", "0", "0"]), \
             mock.patch("builtins.print") as output:
            self.assertEqual(linux.main([]), 0)
        run.assert_not_called()
        check.assert_not_called()
        download.assert_not_called()
        home = output.call_args_list[0].args[0]
        self.assertEqual([line for line in home.splitlines() if line[:1].isdigit()],
                         ["1 Play", "2 Manage installation", "3 Check / Install Updates", "0 Exit"])
        self.assertIn("Manage installation → Select Game", home)
        self.assertIn("Manage installation → Use Existing Install", home)
        self.assertNotIn("Install HD", home)
        self.assertNotIn("Install Spanish", home)

    def test_direct_iso_cli_and_menu_keep_import_as_a_separate_choice(self):
        for arguments, answers in ((["--use-iso", "/tmp/My ISO.xiso"], []),
                                  ([], ["2", "1", "1", "/tmp/My ISO.xiso", "0", "0", "0"])):
            with self.subTest(arguments=arguments), mock.patch.object(linux.sys, "platform", "linux"), \
                 mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(linux, "steam_tools", return_value=self.tools), \
                 mock.patch.object(linux, "start_release_check", return_value=queue.Queue()), \
                 mock.patch.object(linux, "run_action", return_value=0) as run, \
                 mock.patch("builtins.input", side_effect=answers), mock.patch("builtins.print") as output:
                self.assertEqual(linux.main(arguments), 0)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[2:], ("--use-iso", Path("/tmp/My ISO.xiso")))
                if answers:
                    rendered = "\n".join(str(call.args[0]) for call in output.call_args_list)
                    self.assertIn("keep the ISO in place", rendered)
                    self.assertIn("ISO can be removed after setup", rendered)

    def test_manage_menu_keeps_verify_status_and_optional_installers_accessible(self):
        for answers, expected in ((["3"], ("--verify", None)), (["4"], ("--status", None)),
                                  (["6", "/tmp/HD.zip.001"], ("--install-hd-textures", Path("/tmp/HD.zip.001"))),
                                  (["7", "/tmp/Spanish.iso"], ("--install-spanish", Path("/tmp/Spanish.iso")))):
            with self.subTest(answers=answers), mock.patch.object(linux.sys, "platform", "linux"), \
                 mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(linux, "steam_tools", return_value=self.tools), \
                 mock.patch.object(linux, "start_release_check", return_value=queue.Queue()), \
                 mock.patch.object(linux, "run_action", return_value=0) as run, \
                 mock.patch("builtins.input", side_effect=["2", *answers, "0", "0"]), \
                 mock.patch("builtins.print"):
                self.assertEqual(linux.main([]), 0)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[2:], expected)

    def test_menu_language_saves_choice_without_play_and_cancel_does_nothing(self):
        for language in ("es", "en", ""):
            with self.subTest(language=language), \
                 mock.patch.object(linux.sys, "platform", "linux"), \
                 mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(linux, "steam_tools", return_value=self.tools), \
                 mock.patch.object(linux, "run_action", return_value=0) as run, \
                 mock.patch("builtins.input", side_effect=["2", "8", language, "0", "0"]), \
                 mock.patch("builtins.print"):
                self.assertEqual(linux.main([]), 0)
                if language:
                    run.assert_called_once()
                    self.assertEqual(run.call_args.args[2:], ("--set-language", language))
                else:
                    run.assert_not_called()

    def test_cli_and_menu_update_and_attach_do_not_import_or_play(self):
        for arguments, expected in ((["--update"], ("--update", None)),
                                    (["--use-installation", "/old/My Game"], ("--use-installation", Path("/old/My Game")))):
            with self.subTest(arguments=arguments), mock.patch.object(linux.sys, "platform", "linux"), \
                 mock.patch.object(linux, "steam_tools", return_value=self.tools), \
                 mock.patch.object(linux, "run_action", return_value=0) as run:
                self.assertEqual(linux.main(arguments), 0)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[2:], expected)
        for answers, expected in ((["2", "5", "0", "0"], ("--update", None)),
                                  (["2", "2", '"/old/My Game"', "0", "0"], ("--use-installation", Path("/old/My Game"))),
                                  (["2", "2", "", "0", "0"], None)):
            with self.subTest(answers=answers), mock.patch.object(linux.sys, "platform", "linux"), \
                 mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(linux, "steam_tools", return_value=self.tools), \
                 mock.patch.object(linux, "run_action", return_value=0) as run, \
                 mock.patch("builtins.input", side_effect=answers), mock.patch("builtins.print"):
                self.assertEqual(linux.main([]), 0)
                if expected:
                    run.assert_called_once()
                    self.assertEqual(run.call_args.args[2:], expected)
                else:
                    run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
