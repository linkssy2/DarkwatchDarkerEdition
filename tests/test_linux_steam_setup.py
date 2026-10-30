"""Steam adapter feedback with synthetic workers; no dialogs, Wine or game runs."""

import argparse
from contextlib import ExitStack
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("linux_steam_adapter", ROOT / "launcher/linux/run_backend.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class SteamSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = (Path(temporary.name) / "Darkwatch café's folder").resolve()
        (self.root / "linux").mkdir(parents=True)
        self.script = self.root / "linux/run_backend.py"
        self.script.touch()

    def worker(self, events=(), code=0):
        def emit(event, message, **fields):
            print(json.dumps(dict(event=event, message=message, **fields)), flush=True)

        backend = SimpleNamespace(emit=emit, game_running=mock.Mock(return_value=False))

        def main(arguments):
            for event in events:
                backend.emit(**event)
            return code

        backend.main = mock.Mock(side_effect=main)
        return backend

    def command(self, backend, *arguments, stdout=None, stderr=None, import_error=None, dialog_responses=None):
        output = io.StringIO() if stdout is None else stdout
        errors = io.StringIO() if stderr is None else stderr
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(adapter, "__file__", str(self.script)))
            stack.enter_context(mock.patch.object(adapter.importlib, "import_module",
                                                 return_value=backend, side_effect=import_error))
            dialogs = stack.enter_context(mock.patch.object(adapter, "notify", return_value=True, side_effect=dialog_responses))
            stack.enter_context(mock.patch.object(sys, "stdout", output))
            stack.enter_context(mock.patch.object(sys, "stderr", errors))
            result = adapter.main(arguments)
        return result, output, errors, dialogs.call_args_list

    def test_import_acknowledges_start_and_result_preserving_json(self):
        events = [dict(event="progress", message="Checking disc", percent=2),
                  dict(event="shader_prepare", message="Preparing shaders", percent=50),
                  dict(event="result", message="Imported successfully", ready=True, percent=100)]
        backend = self.worker(events)
        original = backend.emit
        code, output, _, dialogs = self.command(backend, "--interactive", "--import-iso", "game.iso")
        self.assertEqual(code, 0)
        self.assertEqual([json.loads(line) for line in output.getvalue().splitlines()], events)
        self.assertEqual(len(dialogs), 2)
        self.assertIn("several minutes", dialogs[0].args[0])
        self.assertIn("Leave Steam running", dialogs[0].args[0])
        self.assertEqual(dialogs[1], mock.call("Imported successfully"))
        self.assertIs(backend.emit, original)
        backend.game_running.assert_not_called()
        self.assertFalse((self.root / adapter.ERROR_FILE).exists())
        self.assertFalse((self.root / "GameData").exists())

    def test_defaults_follow_script_location_and_explicit_paths_are_unchanged(self):
        backend = self.worker([dict(event="status", message="Ready")])
        before = sys.path[:]
        with mock.patch.object(os, "getcwd", return_value=str(self.root.parent)):
            self.assertEqual(self.command(backend, "--status")[0], 0)
        arguments = backend.main.call_args.args[0]
        self.assertEqual(arguments, ["--install-root", str(self.root / "GameData"),
                                     "--package", str(self.root / "windows"), "--status"])
        explicit = ["--package=another package", "--install-root", "my data", "--set-language", "es"]
        self.assertEqual(self.command(backend, *explicit)[0], 0)
        backend.main.assert_called_with(explicit)
        self.assertEqual(sys.path, before)

    def test_direct_iso_acknowledges_retained_disc_without_launching(self):
        event = dict(event="result", message="Ready from ISO", ready=True, source_mode="iso", iso_available=True)
        backend = self.worker([event])
        code, output, _, dialogs = self.command(backend, "--interactive", "--use-iso", "game.iso")
        self.assertEqual(code, 0)
        self.assertEqual(backend.main.call_args.args[0][-2:], ["--use-iso", "game.iso"])
        self.assertEqual(len(dialogs), 2)
        self.assertIn("leave it in place for every launch", dialogs[0].args[0])
        self.assertEqual(dialogs[-1], mock.call("Ready from ISO"))
        self.assertEqual(json.loads(output.getvalue()), event)
        backend.game_running.assert_not_called()

    def test_play_requests_fresh_drop_in_preparation_and_keeps_normal_play(self):
        events = [dict(event='progress', message='Found your disc in assets', percent=0, automatic_setup=True),
                  dict(event='result', message='Started', pid=123, installed=True, ready=True)]
        backend = self.worker(events)
        code, output, _, dialogs = self.command(backend, '--interactive', '--play')
        self.assertEqual(code, 0)
        arguments = backend.main.call_args.args[0]
        self.assertEqual(arguments[arguments.index('--auto-iso-folder') + 1], str(self.root / 'assets'))
        self.assertIn('--play', arguments)
        self.assertNotIn('--import-iso', arguments)
        self.assertEqual(len(dialogs), 1)
        self.assertIn('Leave Steam running', dialogs[0].args[0])
        self.assertIn('game will start', dialogs[0].args[0])
        self.assertEqual([json.loads(line) for line in output.getvalue().splitlines()], events)
        backend.game_running.assert_called_once()
        backend = self.worker([dict(event='error', message='Several disc images are in assets', ready=False)], code=1)
        code, _, _, dialogs = self.command(backend, '--interactive', '--play')
        self.assertEqual(code, 1)
        self.assertIn('Several disc images', dialogs[-1].args[0])
        backend.game_running.assert_not_called()

    def test_noninteractive_play_also_requests_drop_in_folder(self):
        backend = self.worker([dict(event='result', message='Started', pid=123)])
        code, _, _, dialogs = self.command(backend, '--play')
        self.assertEqual(code, 0)
        self.assertEqual(dialogs, [])
        arguments = backend.main.call_args.args[0]
        self.assertEqual(arguments[arguments.index('--auto-iso-folder') + 1], str(self.root / 'assets'))

    def test_steam_selected_compatibility_environment_reaches_backend_unchanged(self):
        selected = {"STEAM_COMPAT_TOOL_PATHS": "/installed/Chosen Proton",
                    "STEAM_COMPAT_DATA_PATH": "/steam/compatdata/1234",
                    "SteamAppId": "1234", "PROTON_LOG": "1",
                    "PROTON_NO_ESYNC": "1", "DXVK_HUD": "fps"}
        backend = self.worker()
        seen = []
        def main(arguments):
            seen.append({name: os.environ.get(name) for name in selected})
            backend.emit("result", "Started", pid=123)
            return 0
        backend.main.side_effect = main
        with mock.patch.dict(os.environ, selected, clear=True):
            code, _, _, dialogs = self.command(backend, "--interactive", "--play")
        self.assertEqual(code, 0)
        self.assertEqual(seen, [selected])
        self.assertEqual(dialogs, [])
        backend.game_running.assert_called_once()

    def test_release_check_bypasses_backend_and_reports_unavailable_without_error_file(self):
        for status in ("available", "current", "unavailable"):
            result = dict(status=status, current_version="0.6.1", message="Release " + status)
            release = SimpleNamespace(check_releases=mock.Mock(return_value=result),
                                      release_text=mock.Mock(return_value=result["message"]))
            with self.subTest(status=status), mock.patch.object(adapter, "release_tools", return_value=release):
                backend = self.worker()
                code, output, _, dialogs = self.command(backend, "--interactive", "--check-updates")
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output.getvalue()), dict(result, event="release_check"))
                self.assertEqual(dialogs, [mock.call(result["message"])])
                release.check_releases.assert_called_once_with(self.root)
                backend.main.assert_not_called()
                backend.game_running.assert_not_called()
                self.assertFalse((self.root / adapter.ERROR_FILE).exists())
                self.assertFalse((self.root / "GameData").exists())
        with mock.patch.object(adapter, "release_tools", side_effect=OSError("missing optional checker")):
            code, output, _, dialogs = self.command(None, "--interactive", "--check-updates", import_error=AssertionError("No backend import"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "unavailable")
        self.assertNotIn("error", dialogs[0].kwargs)
        self.assertFalse((self.root / adapter.ERROR_FILE).exists())

    def test_release_tools_loads_native_checker_and_passes_linux_platform(self):
        (self.root / "linux/launcher.py").write_text((ROOT / "launcher/linux/launcher.py").read_text(encoding="utf-8"), encoding="utf-8")
        payload = self.root / "windows/payload"
        payload.mkdir(parents=True)
        (self.root / "windows/package-manifest.json").write_text('{"version":"0.6.1"}')
        (payload / "release_check.py").write_text('def check(version, platform):\n    assert platform == "linux"\n    return dict(status="current", current_version=version, message="Current")\n')
        code, output, _, dialogs = self.command(None, "--check-updates", import_error=AssertionError("No backend"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), dict(event="release_check", status="current", current_version="0.6.1", message="Current"))
        self.assertEqual(dialogs, [])

    def test_steam_download_request_directs_to_native_update_without_installing(self):
        backend = self.worker()
        code, output, _, dialogs = self.command(backend, "--interactive", "--download-update")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["native_update_required"])
        self.assertIn("./Darkwatch.sh --download-update", dialogs[0].args[0])
        self.assertIn("same folder", dialogs[0].args[0])
        backend.main.assert_not_called()
        self.assertFalse((self.root / "GameData").exists())
        self.assertFalse((self.root / adapter.ERROR_FILE).exists())

    def test_steam_blocks_mixed_package_before_importing_backend_or_release_checker(self):
        journal = self.root / ".launcher-update/transaction.json"
        journal.parent.mkdir()
        for contents in ('{"phase":"prepared"}', '{"phase":"applying"}', '{bad', '[]', '{"phase":"unknown"}'):
            journal.write_text(contents)
            with self.subTest(contents=contents), mock.patch.object(adapter, "release_tools") as release:
                code, output, _, dialogs = self.command(None, "--interactive", "--play", import_error=AssertionError("No backend import"))
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue())["event"], "update_notice")
            self.assertIn("interrupted", dialogs[0].args[0])
            release.assert_not_called()
            self.assertEqual(journal.read_text(), contents)
            self.assertFalse((self.root / adapter.ERROR_FILE).exists())
        for phase in ("committed", "rolled_back"):
            journal.write_text(json.dumps(dict(phase=phase)))
            backend = self.worker([dict(event="status", message="Ready")])
            self.assertEqual(self.command(backend, "--status")[0], 0)
            backend.main.assert_called_once()

    def test_play_release_notice_waits_for_natural_exit_and_only_shows_available(self):
        for status in ("available", "current", "unavailable", "pending"):
            pending = queue.Queue()
            if status != "pending":
                pending.put(dict(status=status, message="New Linux release"))
            release = SimpleNamespace(start_release_check=mock.Mock(return_value=pending),
                                      release_text=mock.Mock(return_value="New Linux release\nhttps://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7"))
            backend = self.worker([dict(event="result", message="Started", pid=123)])
            state = iter([True, False])
            def still_running():
                adapter.notify.assert_not_called()
                return next(state)
            backend.game_running.side_effect = still_running
            with self.subTest(status=status), mock.patch.object(adapter, "release_tools", return_value=release), \
                 mock.patch.object(adapter.time, "sleep"):
                code, _, _, dialogs = self.command(backend, "--interactive", "--play")
            self.assertEqual(code, 0)
            release.start_release_check.assert_called_once_with(self.root)
            self.assertEqual(backend.game_running.call_count, 2)
            self.assertEqual(len(dialogs), 1 if status == "available" else 0)
            if dialogs:
                self.assertIn("https://github.com/", dialogs[0].args[0])
            self.assertFalse((self.root / adapter.ERROR_FILE).exists())

    def test_update_and_attach_forward_to_shared_backend_without_import_or_play(self):
        backend = self.worker([dict(event="result", message="Updated", ready=True)])
        code, output, _, dialogs = self.command(backend, "--interactive", "--update")
        self.assertEqual(code, 0)
        self.assertEqual(backend.main.call_args.args[0][-1:], ["--update"])
        self.assertIn("Import the Xbox disc once", dialogs[0].args[0])
        self.assertEqual(dialogs[-1], mock.call("Updated"))
        self.assertEqual(json.loads(output.getvalue())["message"], "Updated")
        backend.game_running.assert_not_called()
        event = dict(event="status", message="Existing installation selected", ready=False, update_available=True)
        backend = self.worker([event])
        folder = "Z:\\old\\My café game\\GameData"
        code, output, _, dialogs = self.command(backend, "--interactive", "--use-installation", folder)
        self.assertEqual(code, 0)
        self.assertEqual(backend.main.call_args.args[0][-2:], ["--use-installation", folder])
        self.assertEqual(json.loads(output.getvalue()), event)
        self.assertEqual(len(dialogs), 1)
        self.assertIn("Choose Update Installation", dialogs[0].args[0])
        self.assertIn("does not need to be imported again", dialogs[0].args[0])
        backend.game_running.assert_not_called()

    def test_noninteractive_preserves_json_no_dialog_or_error_report(self):
        event = dict(event="error", message="Bad disc", ready=False)
        backend = self.worker([event], code=1)
        code, output, _, dialogs = self.command(backend, "--import-iso", "bad.iso")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), event)
        self.assertEqual(dialogs, [])
        self.assertFalse((self.root / adapter.ERROR_FILE).exists())

    def test_ps2_spanish_iso_uses_shared_backend_without_game_launch(self):
        backend = self.worker([dict(event="result", message="Spanish voices installed", ready=True)])
        path = "Z:\\Games\\PS2 Español's disc.iso"
        code, output, _, dialogs = self.command(backend, "--interactive", "--install-spanish", path)
        self.assertEqual(code, 0)
        self.assertEqual(backend.main.call_args.args[0][-2:], ["--install-spanish", path])
        self.assertEqual(json.loads(output.getvalue())["message"], "Spanish voices installed")
        self.assertEqual(len(dialogs), 2)
        backend.game_running.assert_not_called()
        self.assertFalse((self.root / "GameData").exists())

    def test_failure_retains_backend_error_and_does_not_wait_or_create_data(self):
        backend = self.worker([dict(event="error", message="Unsupported disc", ready=False)], code=1)
        original = backend.emit
        code, output, _, dialogs = self.command(backend, "--interactive", "--import-iso", "bad.iso")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["message"], "Unsupported disc")
        self.assertIn("Unsupported disc", dialogs[-1].args[0])
        self.assertEqual(dialogs[-1].kwargs, {"error": True})
        self.assertEqual((self.root / adapter.ERROR_FILE).read_text(), "Setup failed: Unsupported disc\n")
        self.assertFalse((self.root / "GameData").exists())
        self.assertIs(backend.emit, original)
        backend.game_running.assert_not_called()

    def test_import_failure_and_argument_system_exit_are_visible(self):
        code, _, _, dialogs = self.command(None, "--interactive", "--status",
                                          import_error=ImportError("missing fixture dependency"))
        self.assertEqual(code, 1)
        self.assertEqual(len(dialogs), 1)
        self.assertIn("missing fixture dependency", dialogs[0].args[0])
        backend = self.worker()

        def invalid_arguments(arguments):
            parser = argparse.ArgumentParser()
            parser.add_argument("--required-fixture", required=True)
            parser.parse_args([])

        backend.main.side_effect = invalid_arguments
        code, _, _, dialogs = self.command(backend, "--interactive", "--unknown")
        self.assertEqual(code, 2)
        self.assertEqual(len(dialogs), 1)
        self.assertIn("--required-fixture", dialogs[0].args[0])
        self.assertIn("--required-fixture", (self.root / adapter.ERROR_FILE).read_text())

    def test_closed_stdout_does_not_abort_original_progress_emitter(self):
        backend = self.worker()
        original_emit = backend.emit

        def main(arguments):
            # Setup.__init__ retains its original default notify=emit function.
            original_emit("progress", "Preparing", percent=10)
            backend.emit("result", "Complete", ready=True)
            return 0

        backend.main.side_effect = main
        closed = io.StringIO()
        closed.close()
        code, _, _, dialogs = self.command(backend, "--interactive", "--verify", stdout=closed, stderr=closed)
        self.assertEqual(code, 0)
        self.assertEqual(dialogs, [mock.call("Complete")])
        self.assertFalse((self.root / adapter.ERROR_FILE).exists())
        backend.main.side_effect = lambda arguments: (_ for _ in ()).throw(ValueError("original error"))
        code, _, _, dialogs = self.command(backend, "--interactive", "--verify", stdout=closed, stderr=closed)
        self.assertEqual(code, 1)
        self.assertIn("original error", dialogs[-1].args[0])

    def test_play_waits_naturally_without_success_popup(self):
        backend = self.worker([dict(event="result", message="Started", pid=123)])
        backend.game_running.side_effect = [True, True, False]
        with mock.patch.object(adapter.time, "sleep") as sleep:
            code, _, _, dialogs = self.command(backend, "--interactive", "--play")
        self.assertEqual(code, 0)
        self.assertEqual(dialogs, [])
        self.assertEqual(sleep.call_args_list, [mock.call(1), mock.call(1)])

    def test_language_dialog_forwards_both_choices_without_starting_game(self):
        for choice, language in ((6, "es"), (7, "en")):
            with self.subTest(language=language):
                backend = self.worker([dict(event="result", message="Language saved", language=language)])
                code, _, _, dialogs = self.command(backend, "--interactive", "--language",
                                                  dialog_responses=[choice, True])
                self.assertEqual(code, 0)
                self.assertEqual(backend.main.call_args.args[0][-2:], ["--set-language", language])
                self.assertEqual(dialogs[0].kwargs, {"buttons": 0x203})
                self.assertIn("Español", dialogs[0].args[0])
                self.assertIn("English", dialogs[0].args[0])
                self.assertEqual(dialogs[1], mock.call("Language saved"))
                backend.game_running.assert_not_called()

    def test_language_cancel_does_not_change_settings_or_create_report(self):
        backend = self.worker()
        original = backend.emit
        code, _, _, dialogs = self.command(backend, "--interactive", "--language", dialog_responses=[2])
        self.assertEqual(code, 0)
        self.assertEqual(len(dialogs), 1)
        backend.main.assert_not_called()
        self.assertIs(backend.emit, original)
        self.assertFalse((self.root / adapter.ERROR_FILE).exists())

    def test_language_dialog_failure_does_not_default_to_a_language(self):
        backend = self.worker()
        code, _, _, dialogs = self.command(backend, "--interactive", "--language", dialog_responses=[0, True])
        self.assertEqual(code, 1)
        backend.main.assert_not_called()
        self.assertIn("Could not open the language selector", dialogs[-1].args[0])
        self.assertEqual(dialogs[-1].kwargs, {"error": True})

    def test_language_choice_preserves_backend_refusal(self):
        backend = self.worker([dict(event="error", message="Close Darkwatch before changing language.")], code=1)
        code, _, _, dialogs = self.command(backend, "--interactive", "--language", dialog_responses=[6, True])
        self.assertEqual(code, 1)
        self.assertIn("Close Darkwatch", dialogs[-1].args[0])
        self.assertEqual(dialogs[-1].kwargs, {"error": True})

    def test_broken_pipe_does_not_change_success_at_interpreter_shutdown(self):
        source = f'''
import importlib.util, os, sys
from pathlib import Path
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location("adapter", {str(ROOT / "launcher/linux/run_backend.py")!r})
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
backend = SimpleNamespace(game_running=lambda: False)
backend.emit = lambda event, message, **fields: print(message, flush=True)
def main(arguments):
    backend.emit("result", "Complete")
    return 0
backend.main = main
adapter.importlib.import_module = lambda name: backend
adapter.notify = lambda *args, **kwargs: True
read_fd, write_fd = os.pipe()
os.close(read_fd)
sys.stdout = os.fdopen(write_fd, "w")
raise SystemExit(adapter.run_interactive(Path({str(self.root)!r}), ["--verify"]))
'''
        result = subprocess.run([sys.executable, "-B", "-c", source], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertFalse((self.root / adapter.ERROR_FILE).exists())

    def test_nonzero_exit_without_event_and_help_exit(self):
        backend = self.worker(code=9)
        code, _, _, dialogs = self.command(backend, "--interactive", "--verify")
        self.assertEqual(code, 1)
        self.assertIn("exit 9", dialogs[0].args[0])
        backend.main.side_effect = SystemExit(0)
        code, _, _, dialogs = self.command(backend, "--interactive", "--help")
        self.assertEqual(code, 0)
        self.assertEqual(dialogs, [])

    def test_dialog_api_and_failure_fallback_preserve_original_error(self):
        box = mock.Mock(return_value=1)
        with mock.patch.object(ctypes, "WinDLL", return_value=SimpleNamespace(MessageBoxW=box), create=True), \
             mock.patch.object(sys, "stdout", new_callable=io.StringIO) as output:
            self.assertTrue(adapter.notify("Complete"))
            self.assertTrue(adapter.notify("Original error", error=True))
        self.assertEqual(output.getvalue(), "")
        self.assertEqual([call.args[-1] for call in box.call_args_list], [0x10040, 0x10010])
        box = mock.Mock(return_value=6)
        with mock.patch.object(ctypes, "WinDLL", return_value=SimpleNamespace(MessageBoxW=box), create=True):
            self.assertEqual(adapter.notify("Choose language", buttons=0x203), 6)
        self.assertEqual(box.call_args.args[-1], 0x10243)
        with mock.patch.object(ctypes, "WinDLL", side_effect=OSError("no UI"), create=True), \
             mock.patch.object(sys, "stderr", new_callable=io.StringIO) as output:
            self.assertFalse(adapter.notify("Original error", error=True))
        self.assertIn("Original error", output.getvalue())
        self.assertIn("no UI", output.getvalue())
        output.close()
        with mock.patch.object(ctypes, "WinDLL", side_effect=OSError("no UI"), create=True), \
             mock.patch.object(sys, "stderr", output):
            self.assertFalse(adapter.notify("Original error", error=True))

    def test_report_is_bounded_utf8_atomic_and_private(self):
        destination = self.root / adapter.ERROR_FILE
        destination.write_text("previous")
        replace = os.replace

        def check_replace(source, target):
            self.assertEqual(destination.read_text(), "previous")
            self.assertEqual(Path(source).parent, self.root)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(Path(source).stat().st_mode), 0o600)
            replace(source, target)

        with mock.patch.object(adapter.os, "replace", side_effect=check_replace):
            message = adapter.report_error(self.root, "é" * 20000)
        data = destination.read_bytes()
        self.assertLessEqual(len(data), adapter.MAX_ERROR_BYTES)
        self.assertTrue(data.decode("utf-8").startswith("Setup failed: "))
        self.assertIn("Details saved to:", message)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"linux", adapter.ERROR_FILE})

    def test_failed_report_write_retains_original_error_and_previous_file(self):
        destination = self.root / adapter.ERROR_FILE
        destination.write_text("previous")
        for method in ("replace", "mkstemp"):
            owner = adapter.os if method == "replace" else adapter.tempfile
            with self.subTest(method=method), mock.patch.object(owner, method, side_effect=PermissionError("unwritable")):
                message = adapter.report_error(self.root, "Original import error")
            self.assertIn("Original import error", message)
            self.assertIn("unwritable", message)
            self.assertEqual(destination.read_text(), "previous")
            self.assertEqual({p.name for p in self.root.iterdir()}, {"linux", adapter.ERROR_FILE})

    def test_report_refuses_hardlinked_nonregular_and_reparse_leaves(self):
        original = self.root / "keep.txt"
        original.write_text("untouched")
        destination = self.root / adapter.ERROR_FILE
        os.link(original, destination)
        self.assertIn("without links", adapter.report_error(self.root, "Original error"))
        self.assertEqual(original.read_text(), "untouched")
        destination.unlink()
        destination.mkdir()
        self.assertIn("without links", adapter.report_error(self.root, "Original error"))
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=1, st_file_attributes=0x400)
        with mock.patch.object(Path, "lstat", return_value=info):
            with self.assertRaisesRegex(ValueError, "without links"):
                adapter.check_error_destination(destination)

    @unittest.skipUnless(os.name == "posix", "Native Linux symbolic links")
    def test_report_refuses_symlink_and_defaults_resolve_script_alias(self):
        original = self.root / "keep.txt"
        original.write_text("untouched")
        (self.root / adapter.ERROR_FILE).symlink_to(original)
        self.assertIn("without links", adapter.report_error(self.root, "Original error"))
        self.assertEqual(original.read_text(), "untouched")
        alias = self.root.parent / "adapter alias.py"
        alias.symlink_to(self.script)
        self.script = alias
        backend = self.worker()
        self.assertEqual(self.command(backend, "--status")[0], 0)
        self.assertIn(str(self.root / "windows"), backend.main.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
