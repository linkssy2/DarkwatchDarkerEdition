"""Steam adapter feedback with synthetic workers; no dialogs, Wine or game runs."""

import argparse
from contextlib import ExitStack
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
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

    def command(self, backend, *arguments, stdout=None, stderr=None, import_error=None):
        output = io.StringIO() if stdout is None else stdout
        errors = io.StringIO() if stderr is None else stderr
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(adapter, "__file__", str(self.script)))
            stack.enter_context(mock.patch.object(adapter.importlib, "import_module",
                                                 return_value=backend, side_effect=import_error))
            dialogs = stack.enter_context(mock.patch.object(adapter, "notify", return_value=True))
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
        explicit = ["--package=another package", "--install-root", "my data", "--import-iso", "game.iso"]
        self.assertEqual(self.command(backend, *explicit)[0], 0)
        backend.main.assert_called_with(explicit)
        self.assertEqual(sys.path, before)

    def test_noninteractive_preserves_json_no_dialog_or_error_report(self):
        event = dict(event="error", message="Bad disc", ready=False)
        backend = self.worker([event], code=1)
        code, output, _, dialogs = self.command(backend, "--import-iso", "bad.iso")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), event)
        self.assertEqual(dialogs, [])
        self.assertFalse((self.root / adapter.ERROR_FILE).exists())

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
