"""Synthetic Proton orchestration only: no Wine, installation or game is launched."""

from contextlib import ExitStack, nullcontext
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import tempfile
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
        self.write(self.proton.parent / "toolmanifest.vdf", '"require_tool_appid" "1628350"')
        self.write(self.library / "steamapps/appmanifest_1628350.acf", '"installdir" "SteamLinuxRuntime_sniper"')
        sniper = self.library / "steamapps/common/SteamLinuxRuntime_sniper/_v2-entry-point"
        self.write(sniper, "installed")
        sniper.chmod(0o755)
        self.assertEqual(linux.steam_tools(self.steam, self.proton.parent)[2], sniper.resolve())

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
        self.assertEqual(kwargs["env"]["PROTON_LOG"], "0")
        self.assertEqual(kwargs["env"]["WINEDEBUG"], "-all")
        self.assertEqual(kwargs["env"]["STEAM_COMPAT_DATA_PATH"], str(self.root / ".proton"))
        self.assertEqual(kwargs["env"]["STEAM_COMPAT_INSTALL_PATH"], str(self.root / "windows"))
        self.assertEqual(kwargs["env"]["XDG_CACHE_HOME"], str(self.root / ".proton/cache"))
        self.assertEqual(kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RW"], linux_spelling(self.root) + ":" + linux_spelling(self.proton.parent))
        self.assertIn(linux_spelling(disc.parent), kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RO"])
        self.assertNotIn("SteamGameId", kwargs["env"])
        self.assertNotIn("SteamAppId", kwargs["env"])
        self.assertIn("20%  Preparing", messages)
        self.assertFalse(list((self.root / "GameData").glob(".cancel-*")))

    def test_iso_inside_portable_folder_is_not_remounted_readonly(self):
        disc = self.root / "My disc.iso"
        self.write(disc, "disc fixture")
        popen, _ = self.action_patches(Process([{"event": "result", "message": "OK"}]))
        self.assertEqual(linux.run_action(self.root, self.tools, "--import-iso", disc, lambda _: None), 0)
        self.assertEqual(popen.call_args.kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RO"], "")
        self.assertIn(linux_spelling(self.root), popen.call_args.kwargs["env"]["PRESSURE_VESSEL_FILESYSTEMS_RW"])

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
                popen, _ = self.action_patches(Process([{"event": event, "message": "OK", "ready": True}]))
                self.assertEqual(linux.run_action(self.root, self.tools, action, output=lambda _: None), 0)
                popen.assert_called_once()
                self.assertEqual(popen.call_args.args[0][-1], action)

    def test_status_reports_installed_spanish_resources(self):
        self.action_patches(Process([dict(event="status", message="Ready", ready=True,
                                         language="es", spanish_installed=True, spanish_audio_installed=True)]))
        messages = []
        self.assertEqual(linux.run_action(self.root, self.tools, "--status", output=messages.append), 0)
        self.assertIn("Language: es. Spanish text: available. Spanish voices: installed.", messages[-1])

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
             mock.patch("builtins.input", side_effect=["2", '"/tmp/My disc.iso"', "0"]), \
             mock.patch("builtins.print"):
            self.assertEqual(linux.main([]), 0)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[2:], ("--import-iso", Path("/tmp/My disc.iso")))

    def test_menu_language_saves_choice_without_play_and_cancel_does_nothing(self):
        for language in ("es", "en", ""):
            with self.subTest(language=language), \
                 mock.patch.object(linux.sys, "platform", "linux"), \
                 mock.patch.object(linux.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(linux, "steam_tools", return_value=self.tools), \
                 mock.patch.object(linux, "run_action", return_value=0) as run, \
                 mock.patch("builtins.input", side_effect=["7", language, "0"]), \
                 mock.patch("builtins.print"):
                self.assertEqual(linux.main([]), 0)
                if language:
                    run.assert_called_once()
                    self.assertEqual(run.call_args.args[2:], ("--set-language", language))
                else:
                    run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
