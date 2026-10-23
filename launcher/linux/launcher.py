#!/usr/bin/env python3
"""Experimental Linux entry point; installation remains owned by the Windows backend."""

import argparse
from collections import deque
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid


class LauncherError(Exception):
    pass


def resolve_path(path):
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError) as error:
        raise LauncherError("Could not resolve path: " + str(path) + ". " + str(error)) from None


def check_native_links(root):
    # Wine can report Linux symlinks as ordinary files and directories.
    pending = [root]
    while pending:
        path = pending.pop()
        if path.is_symlink():
            raise LauncherError("A linked file or folder inside the Windows payload or GameData is not supported: " + str(path))
        if path.is_dir():
            pending.extend(path.iterdir())


def vdf_values(path, key):
    """Read quoted scalar fields from Steam's local manifests, without executing them."""
    if not path.is_file():
        return []
    if path.stat().st_size > 2 * 1024 * 1024:
        raise LauncherError("Steam manifest is unexpectedly large: " + str(path))
    data = path.read_text(encoding="utf-8-sig", errors="replace")
    values = re.findall(r'"' + re.escape(key) + r'"\s*"((?:\\.|[^"\\])*)"', data)
    return [re.sub(r'\\([\\"])', r'\1', value) for value in values]


def steam_tools(steam_root=None, proton_path=None):
    candidates = [Path(steam_root).expanduser()] if steam_root else [
        Path(os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH", "~/.local/share/Steam")).expanduser(),
        Path("~/.steam/steam").expanduser(), Path("~/.steam/root").expanduser(),
    ]
    steam = next((resolve_path(p) for p in candidates if (p / "steamapps").is_dir()), None)
    if steam is None:
        raise LauncherError("Native Linux Steam was not found. Use --steam-root with its installed folder.")
    libraries = [steam]
    for value in vdf_values(steam / "steamapps/libraryfolders.vdf", "path"):
        path = resolve_path(value)
        if path not in libraries and (path / "steamapps").is_dir():
            libraries.append(path)
    if proton_path:
        proton = resolve_path(proton_path)
        if proton.is_dir():
            proton /= "proton"
    else:
        proton = next((p / "steamapps/common/Proton - Experimental/proton" for p in libraries
                       if (p / "steamapps/common/Proton - Experimental/proton").is_file()), None)
    if proton is None or not proton.is_file() or not os.access(proton, os.X_OK):
        raise LauncherError("Install Proton Experimental in Steam, or select an installed tool with --proton.")
    # Experimental can change runtime generations; use its declared dependency.
    manifests = [proton.parent / "toolmanifest.vdf", proton.parent / "toolmanifest_x86_64.vdf"]
    manifest = next((p for p in manifests if p.is_file()), manifests[0])
    required = vdf_values(manifest, "require_tool_appid")
    if len(required) != 1 or not re.fullmatch(r"[0-9]+", required[0]):
        raise LauncherError("This Proton tool does not declare one supported Steam Linux Runtime dependency.")
    for library in libraries:
        names = vdf_values(library / ("steamapps/appmanifest_" + required[0] + ".acf"), "installdir")
        if len(names) != 1 or names[0] in ("", ".", "..") or any(c in names[0] for c in "/\\"):
            continue
        entry = library / "steamapps/common" / names[0] / "_v2-entry-point"
        if entry.is_file() and os.access(entry, os.X_OK):
            return steam, resolve_path(proton), resolve_path(entry)
    raise LauncherError("Install the Steam Linux Runtime required by this Proton tool in Steam (app " +
                        required[0] + "). Nothing was downloaded or installed by this launcher.")


def mount_paths(paths):
    values = []
    for path in paths:
        value = str(path)
        if ":" in value or "\n" in value or "\r" in value or "\\" in value:
            raise LauncherError("Use Linux folders without colons, backslashes or line breaks: " + value)
        if value not in values:
            values.append(value)
    return ":".join(values)


def wine_path(path):
    # A new Proton prefix maps Z: to /. Keep each path a single argv element.
    value = str(path)
    mount_paths([value])
    if not value.startswith("/"):
        raise LauncherError("Expected an absolute Linux path: " + value)
    return "Z:" + value.replace("/", "\\")


def portable_directory(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise LauncherError("Portable data must be a real folder inside this installation: " + str(path))
    path.mkdir(parents=True, exist_ok=True)


@contextmanager
def action_lock(path):
    import fcntl

    if path.is_symlink():
        raise LauncherError("The portable launcher lock must not be a symbolic link.")
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LauncherError("Another Darkwatch launcher or game is using this folder. Close it first.") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def launch_environment(root, steam, proton, runtime, input_path=None):
    env = dict(os.environ)
    # The small adapter owns game lifetime; avoid Steam helper's unrelated app/session setup.
    env.pop("SteamGameId", None)
    env.pop("SteamAppId", None)
    writable = [root, proton.parent]
    readonly = [steam, runtime.parent] + ([input_path.parent] if input_path else [])
    readonly = [path for path in readonly if not any(path == parent or parent in path.parents for parent in writable)]
    env.update({
        "STEAM_COMPAT_DATA_PATH": str(root / ".proton"),
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(steam),
        "STEAM_COMPAT_INSTALL_PATH": str(root / "windows"),
        "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
        "PROTON_LOG": "0", "WINEDEBUG": "-all", "VKD3D_DEBUG": "none", "DXVK_LOG_LEVEL": "none",
        "XDG_CACHE_HOME": str(root / ".proton/cache"),
        "VKD3D_SHADER_CACHE_PATH": str(root / ".proton/cache"),
        # Proton itself needs dist.lock and one-time SteamPipe fixups in its installed folder.
        "PRESSURE_VESSEL_FILESYSTEMS_RW": mount_paths(writable),
        "PRESSURE_VESSEL_FILESYSTEMS_RO": mount_paths(readonly),
    })
    return env


def run_action(root, tools, action, input_path=None, output=print):
    root = resolve_path(root)
    package = root / "windows"
    for folder in (package, root / "GameData"):
        check_native_links(folder)
    python = package / "payload/python/python.exe"
    backend = package / "payload/setup_backend.py"
    adapter = root / "linux/run_backend.py"
    for path in (python, backend, package / "package-manifest.json", adapter):
        if not path.is_file():
            raise LauncherError("The Windows payload is incomplete. Extract the entire Linux package again: " + str(path))
    if input_path:
        input_path = resolve_path(input_path)
        if not input_path.is_file():
            raise LauncherError("File not found: " + str(input_path))
    for folder in (root / "GameData", root / ".proton", root / ".proton/cache"):
        portable_directory(folder)
    steam, proton, runtime = tools
    cancel = root / "GameData" / (".cancel-" + uuid.uuid4().hex)
    env = launch_environment(root, steam, proton, runtime, input_path)
    command = [str(runtime), "--verb=run", "--", str(proton), "run", wine_path(python), "-B",
               wine_path(adapter), "--package", wine_path(package), "--install-root", wine_path(root / "GameData"),
               "--cancel-file", wine_path(cancel), action]
    if input_path:
        command.append(wine_path(input_path))
    cancelled = False
    playing = False

    def request_cancel(signum, frame):
        nonlocal cancelled
        if not cancelled:
            cancelled = True
            if playing:
                output("Close Darkwatch to end this play session. The launcher will wait for it.")
                return
            cancel.touch()
            output("Cancel requested. Waiting for the installer to safely finish or roll back...")

    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    terminal = False
    failed = False
    last = None
    noise = deque(maxlen=8)
    try:
        for sig in handlers:
            signal.signal(sig, request_cancel)
        # A separate session lets Ctrl+C reach the backend's cancellation protocol first.
        with action_lock(root / ".proton/launcher.lock"), subprocess.Popen(command, cwd=package, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", start_new_session=True) as process:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    noise.append(line.strip()[:1000])
                    continue
                if not isinstance(event, dict) or event.get("event") not in ("progress", "shader_prepare", "shader_ready", "result", "status", "error"):
                    continue
                kind = event["event"]
                message = str(event.get("message", ""))
                percent = event.get("percent")
                text = (str(percent) + "%  " if kind in ("progress", "shader_prepare") and percent is not None else "") + message
                if text and text != last:
                    output(text)
                    last = text
                if kind == "status":
                    output("Ready to play: " + ("yes" if event.get("ready") else "no") +
                           ". HD textures: " + ("installed" if event.get("hd_textures_installed") else "not installed") + ".")
                terminal |= kind in ("result", "status", "error")
                failed |= kind == "error"
                playing |= action == "--play" and kind == "result" and bool(event.get("pid"))
            code = process.wait()
        if cancelled:
            return 130
        if failed or code or not terminal:
            if not failed:
                output("Proton or the installer stopped before completing this action (exit " + str(code) + ").")
            for line in noise:
                if line:
                    output(line)
            return 1
        return 0
    finally:
        for sig, previous in handlers.items():
            signal.signal(sig, previous)
        cancel.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Darkwatch: Darker Edition — experimental Linux / Proton")
    parser.add_argument("--proton", type=Path, help="installed Proton folder or proton executable")
    parser.add_argument("--steam-root", type=Path, help="native Linux Steam installation folder")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--import-iso", type=Path, metavar="FILE")
    actions.add_argument("--install-hd-textures", type=Path, metavar="FILE")
    actions.add_argument("--verify", action="store_true")
    actions.add_argument("--play", action="store_true")
    actions.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        parser.error("Run this launcher on Linux. Use the Windows launcher on Windows.")
    try:
        root = resolve_path(__file__).parents[1]
        tools = steam_tools(args.steam_root, args.proton)
        for name in ("import_iso", "install_hd_textures", "verify", "play", "status"):
            value = getattr(args, name)
            if value:
                return run_action(root, tools, "--" + name.replace("_", "-"), value if isinstance(value, Path) else None)
        if not sys.stdin.isatty():
            parser.error("Choose an action such as --status, --import-iso FILE, or --play.")
        choices = {"1": "--play", "2": "--import-iso", "3": "--install-hd-textures", "4": "--verify", "5": "--status"}
        while True:
            print("\nDarkwatch: Darker Edition\n1 Play\n2 Import ISO / XISO\n3 Install HD texture pack\n4 Verify files\n5 Status\n0 Quit")
            choice = input("> ").strip()
            if choice == "0":
                return 0
            if choice not in choices:
                continue
            path = None
            if choice in ("2", "3"):
                value = input("File path (blank to cancel): ").strip()
                if not value:
                    continue
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                path = Path(value)
            try:
                run_action(root, tools, choices[choice], path)
            except (LauncherError, OSError) as error:
                print(str(error), file=sys.stderr)
    except (LauncherError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
