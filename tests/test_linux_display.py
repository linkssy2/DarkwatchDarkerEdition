"""Linux display admission only; no display server, Proton or game is started."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("linux_display_launcher", ROOT / "launcher/linux/launcher.py")
linux = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(linux)


class LinuxDisplayTests(unittest.TestCase):
    def test_headless_render_actions_stop_before_paths_or_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "untouched"
            for action in ("--import-iso", "--use-iso", "--play"):
                for environment in ({}, {"DISPLAY": "", "WAYLAND_DISPLAY": " "}):
                    with self.subTest(action=action, environment=environment), \
                            mock.patch.dict(os.environ, environment, clear=True), \
                            mock.patch.object(linux, "resolve_path") as resolve, \
                            mock.patch.object(linux.subprocess, "Popen") as process:
                        with self.assertRaisesRegex(linux.LauncherError, "active desktop display"):
                            linux.run_action(root, None, action)
                        resolve.assert_not_called()
                        process.assert_not_called()
                        self.assertFalse(root.exists())

    def test_x11_and_wayland_sessions_admit_render_actions_without_rewriting_environment(self):
        for environment in ({"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "wayland-0"},
                            {"DISPLAY": ":1", "WAYLAND_DISPLAY": "wayland-1"}):
            with self.subTest(environment=environment), mock.patch.dict(os.environ, environment, clear=True):
                before = dict(os.environ)
                for action in ("--import-iso", "--use-iso", "--play"):
                    linux.require_display(action)
                self.assertEqual(dict(os.environ), before)

    def test_non_render_actions_remain_available_headless(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            for action in ("--status", "--verify", "--update", "--use-installation",
                           "--check-updates", "--download-update", "--set-language", "--set-diagnostics",
                           "--install-hd-textures", "--install-spanish", "--install-french",
                           "--install-german", "--install-italian", "--install-portuguese"):
                with self.subTest(action=action):
                    linux.require_display(action)


if __name__ == "__main__":
    unittest.main()
