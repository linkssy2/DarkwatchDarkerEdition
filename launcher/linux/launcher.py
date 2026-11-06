#!/usr/bin/env python3
"""Experimental Linux entry point; installation remains owned by the Windows backend."""

import argparse
from collections import deque
from contextlib import contextmanager, ExitStack
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid


class LauncherError(Exception):
    pass


class UpdateCancelled(LauncherError):
    pass


def diagnostic(root, message):
    try:
        if not (root / "GameData/.diagnostic-logging").is_file():
            return
        folder = root / "GameData/logs"
        path = folder / "linux-launcher.log"
        if any(p.is_symlink() for p in (root / "GameData", folder, path)):
            return
        folder.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size < 8 * 1024 * 1024:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + str(message) + "\n")
    except (OSError, LauncherError):
        pass


def package_version(root):
    manifest = root / "windows/package-manifest.json"
    if manifest.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Oversized package manifest")
    value = json.loads(manifest.read_text(encoding="utf-8-sig"))["version"]
    if not isinstance(value, str):
        raise ValueError("Invalid package version")
    return value


def check_releases(root):
    version = ""
    try:
        package = root / "windows"
        version = package_version(root)
        spec = importlib.util.spec_from_file_location("darkwatch_release_check", package / "payload/release_check.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        return release.check(version, "linux")
    except Exception:
        return dict(status="unavailable", current_version=version, platform="linux",
                    message="Could not check for new releases. You can keep playing and try again later.")


def release_text(result):
    text = str(result.get("message", "Could not check for new releases."))
    if result.get("status") == "available" and result.get("release_url"):
        text += "\n" + result["release_url"]
    return text


def start_release_check(root):
    pending = queue.Queue(maxsize=1)
    worker = threading.Thread(target=lambda: pending.put(check_releases(root)), daemon=True)
    try:
        worker.start()
    except RuntimeError:
        pass
    return pending


def resolve_path(path):
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError) as error:
        raise LauncherError("Could not resolve path: " + str(path) + ". " + str(error)) from None


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


def umu_tools(proton_path=None):
    executable = shutil.which("umu-run")
    if executable is None:
        raise LauncherError("Install umu-launcher so umu-run is available on PATH, or use the Steam route.")
    selected = proton_path or os.environ.get("PROTONPATH")
    if not selected:
        raise LauncherError("Select your installed GE-Proton folder with --proton for --umu.")
    proton = resolve_path(selected)
    if proton.is_dir():
        proton /= "proton"
    if not proton.is_file() or not os.access(proton, os.X_OK):
        raise LauncherError("Choose an installed Proton folder or executable with --proton. Nothing was installed.")
    return None, resolve_path(proton), resolve_path(executable)


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


def check_native_links(root):
    # Wine can report Linux symlinks as ordinary files and directories.
    pending = [root]
    while pending:
        path = pending.pop()
        if path.is_symlink():
            raise LauncherError("A linked file or folder inside the Windows payload or GameData is not supported: " + str(path))
        if path.is_dir():
            pending.extend(path.iterdir())


def existing_installation(path):
    path = Path(path).expanduser().absolute()
    if (path / "GameData").is_dir():
        path /= "GameData"
    explicit_version = path.parent.name == "versions" and re.fullmatch("[0-9a-f]{32}", path.name)
    if not path.is_dir() or not (path / ("install.json" if explicit_version else "active.json")).is_file():
        raise LauncherError("Choose an existing launcher folder, its GameData folder, or its active version folder.")
    data = path.parent.parent if explicit_version else path
    if (data / "installation-location.json").exists():
        raise LauncherError("Choose the original GameData folder, not another linked launcher.")
    check_native_links(data)
    return resolve_path(path)


def native_wine_path(value):
    if not isinstance(value, str):
        raise LauncherError("The saved installation location is invalid. Use Existing Install to select it again.")
    path = PureWindowsPath(value)
    if path.drive.casefold() != "z:" or path.root != "\\":
        raise LauncherError("The saved installation must use Proton's Z: drive. Use Existing Install to select it again.")
    native = value[2:].replace("\\", "/")
    mount_paths([native])
    return Path(native)


def installation_root(root):
    folder = root / "GameData"
    location = folder / "installation-location.json"
    if not location.exists():
        return folder
    try:
        if not location.is_file() or location.stat().st_size > 65536:
            raise ValueError("Invalid installation location file")
        data = json.loads(location.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Invalid installation location")
        selected = native_wine_path(data.get("root"))
    except (OSError, ValueError) as error:
        raise LauncherError("Could not read the saved installation location. Use Existing Install to select it again: " + str(error)) from None
    return existing_installation(selected)


def saved_iso_path(installation):
    # The backend owns installation validation; this bounded read only exposes the
    # retained disc to Proton's container before that validation can run.
    try:
        if installation.parent.name == "versions" and re.fullmatch("[0-9a-f]{32}", installation.name):
            record = installation / "install.json"
        else:
            pointer = installation / "active.json"
            if not pointer.is_file() or pointer.stat().st_size > 65536:
                return None
            active = json.loads(pointer.read_text(encoding="utf-8-sig"))
            version = active.get("version") if isinstance(active, dict) else None
            if not isinstance(version, str) or not re.fullmatch("[0-9a-f]{32}", version):
                return None
            record = installation / "versions" / version / "install.json"
        if not record.is_file() or record.stat().st_size > 8 * 1024 * 1024:
            return None
        metadata = json.loads(record.read_text(encoding="utf-8-sig"))
        if not isinstance(metadata, dict) or metadata.get("source_mode") != "iso":
            return None
        disc = native_wine_path(metadata.get("iso_path"))
        # A removed drive must reach the backend's recoverable missing-ISO state,
        # rather than making the container refuse to start at all.
        return disc if disc.parent.is_dir() else None
    except (OSError, ValueError, LauncherError):
        return None


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


def require_game_closed(root, proc=None):
    proc = Path("/proc") if proc is None else proc
    if not proc.is_dir():
        raise LauncherError("Could not check running games. Close Darkwatch and Steam setup before updating.")
    uid = getattr(os, "getuid", lambda: None)()
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if uid is not None and process.stat().st_uid != uid:
                continue
            arguments = (process / "cmdline").read_bytes().decode("utf-8", "replace").split("\0")
            for argument in arguments:
                value = argument.replace("\\", "/")
                name = value.rsplit("/", 1)[-1].casefold()
                if name == "darkwatch_xbe.exe":
                    raise LauncherError("Close Darkwatch before downloading and installing an update.")
                if name in ("run_backend.py", "setup_backend.py"):
                    candidate = Path(value[2:] if value[:2].casefold() == "z:" else value)
                    if not candidate.is_absolute():
                        candidate = (process / "cwd").resolve() / candidate
                    if root in candidate.parents:
                        raise LauncherError("Close this installation's Steam setup or launcher before updating.")
        except FileNotFoundError:
            continue
        except PermissionError:
            raise LauncherError("Could not check a running process. Close Darkwatch and Steam setup before updating.") from None


@contextmanager
def update_locks(root):
    portable_directory(root / ".proton")
    with ExitStack() as locks:
        locks.enter_context(action_lock(root / ".proton/launcher.lock"))
        check_native_links(root / "GameData")
        data = installation_root(root)
        if data.exists():
            locks.enter_context(action_lock(data / ".launcher.lock"))
        require_game_closed(root)
        yield


def load_updater(root, recovery=False):
    runner = root / ".launcher-update/runner"
    folder = runner if recovery and (runner / "release_update.py").is_file() else root / "windows/payload"
    check_native_links(folder)
    spec = importlib.util.spec_from_file_location("darkwatch_release_update", folder / "release_update.py")
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    return updater


def recover_update(root, output=print):
    if not (root / ".launcher-update/transaction.json").exists():
        return False
    with update_locks(root):
        updater = load_updater(root, recovery=True)
        if updater.pending(root):
            output("Recovering the interrupted launcher update...")
            return updater.recover(root)
        updater.cleanup(root)
    return False


def restart_launcher(root, arguments):
    os.execv(sys.executable, [sys.executable, "-B", str(root / "linux/launcher.py"), *arguments])


def download_update(root, output=print):
    cancelled = False
    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True
        output("Cancel requested. Waiting for a safe stopping point...")
    def check_cancel():
        if cancelled:
            raise UpdateCancelled("Update cancelled. Your game data was kept.")
    def notify(event, message, **fields):
        percent = fields.get("percent")
        output((str(percent) + "%  " if percent is not None else "") + str(message))
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for sig in handlers:
            signal.signal(sig, cancel)
        with update_locks(root):
            updater = load_updater(root)
            previous = sys.path[:]
            sys.path.insert(0, str(root / "windows/payload"))
            try:
                updater.prepare(root, package_version(root), "linux", notify, check_cancel)
                check_cancel()
                require_game_closed(root)
                version = updater.apply(root)
            except Exception:
                if updater.pending(root):
                    updater.recover(root)
                raise
            finally:
                sys.path[:] = previous
            installed = (installation_root(root) / "active.json").is_file()
        output("Launcher updated to " + str(version) + ". Your game data and Steam shortcut location were kept.")
        return installed
    finally:
        for sig, previous in handlers.items():
            signal.signal(sig, previous)


def launch_environment(root, steam, proton, runtime, input_path=None, installation=None, saved_iso=None):
    env = dict(os.environ)
    # The small adapter owns game lifetime; avoid Steam helper's unrelated app/session setup.
    env.pop("SteamGameId", None)
    env.pop("SteamAppId", None)
    writable = [root, proton.parent]
    if installation and not any(installation == path or path in installation.parents for path in writable):
        writable.append(installation)
    readonly = ([steam, runtime.parent] if steam is not None else []) + [path.parent for path in (input_path, saved_iso) if path]
    readonly = [path for path in readonly if not any(path == parent or parent in path.parents for parent in writable)]
    env.update({
        "STEAM_COMPAT_DATA_PATH": str(root / ".proton"),
        "STEAM_COMPAT_INSTALL_PATH": str(root / "windows"),
        "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
        "XDG_CACHE_HOME": str(root / ".proton/cache"),
        "VKD3D_SHADER_CACHE_PATH": str(root / ".proton/cache"),
        # Proton itself needs dist.lock and one-time SteamPipe fixups in its installed folder.
        "PRESSURE_VESSEL_FILESYSTEMS_RW": mount_paths(writable),
        "PRESSURE_VESSEL_FILESYSTEMS_RO": mount_paths(readonly),
    })
    if steam is None:
        env.pop("STEAM_COMPAT_CLIENT_INSTALL_PATH", None)
        # umu manages its own pfx link; leave an existing Steam/Proton prefix untouched.
        env.update({"WINEPREFIX": str(root / ".proton/umu"), "PROTONPATH": str(proton.parent),
                    "GAMEID": "umu-default", "STORE": "none", "PROTON_VERB": "waitforexitandrun"})
    else:
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(steam)
    # Keep ordinary launches quiet without discarding explicit Proton/driver
    # troubleshooting options supplied by the player.
    for name, value in (("PROTON_LOG", "0"), ("WINEDEBUG", "-all"),
                        ("VKD3D_DEBUG", "none"), ("DXVK_LOG_LEVEL", "none")):
        env.setdefault(name, value)
    return env


def require_display(action):
    if (action in ("--import-iso", "--use-iso", "--play") and
            not any(os.environ.get(name, "").strip() for name in ("DISPLAY", "WAYLAND_DISPLAY"))):
        raise LauncherError("Setup and play need an active desktop display for shader preparation. "
                            "Open a terminal in your desktop session and retry; a headless SSH session cannot prepare shaders. "
                            "No installation files were changed.")


def run_action(root, tools, action, input_path=None, output=print, status=None):
    require_display(action)
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
    language = input_path if action in ("--set-language", "--set-diagnostics") else None
    if language is not None:
        if language not in (("on", "off") if action == "--set-diagnostics" else ("en", "es", "fr", "de", "it", "pt-BR")):
            raise LauncherError("Choose on or off." if action == "--set-diagnostics" else "Choose en, es, fr, de, it or pt-BR.")
        input_path = None
    if input_path:
        if action == "--use-installation":
            input_path = existing_installation(input_path)
        else:
            input_path = resolve_path(input_path)
            if not input_path.is_file():
                raise LauncherError("File not found: " + str(input_path))
    elif action == "--use-installation":
        raise LauncherError("Choose an existing installation folder.")
    installation = input_path if action == "--use-installation" else installation_root(root)
    if installation.parent.name == "versions" and re.fullmatch("[0-9a-f]{32}", installation.name):
        installation = installation.parent.parent
    for folder in (root / "GameData", root / ".proton", root / ".proton/cache"):
        portable_directory(folder)
    steam, proton, runtime = tools
    if steam is None:
        portable_directory(root / ".proton/umu")
    cancel = root / "GameData" / (".cancel-" + uuid.uuid4().hex)
    env = launch_environment(root, steam, proton, runtime,
                             None if action == "--use-installation" else input_path, installation,
                             None if action in ("--use-iso", "--import-iso") else saved_iso_path(input_path if action == "--use-installation" else installation))
    runner = [str(runtime)] if steam is None else [str(runtime), "--verb=run", "--", str(proton), "run"]
    command = runner + [wine_path(python), "-B",
               wine_path(adapter), "--package", wine_path(package), "--install-root", wine_path(root / "GameData"),
               "--cancel-file", wine_path(cancel), action]
    if input_path:
        command.append(wine_path(input_path))
    elif language is not None:
        command.append(language)
    diagnostic(root, "Action=" + action + " command=" + repr(command))
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
                diagnostic(root, line.rstrip())
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
                    if status is not None:
                        status.update(event)
                    output("Ready to play: " + ("yes" if event.get("ready") else "no") +
                           ". Update available: " + ("yes" if event.get("update_available") else "no") +
                           ". HD textures: " + ("installed" if event.get("hd_textures_installed") else "not installed") +
                           ". Language: " + str(event.get("language", "en")) +
                           ". Spanish text: " + ("available" if event.get("spanish_installed") else "unavailable") +
                           ". Portuguese text: " + ("available" if event.get("portuguese_installed") else "unavailable") +
                           ". French: " + ("available" if event.get("french_installed") else "unavailable") +
                           ". German: " + ("available" if event.get("german_installed") else "unavailable") +
                           ". Italian: " + ("available" if event.get("italian_installed") else "unavailable") +
                           ". Spanish voices: " + ("installed" if event.get("spanish_audio_installed") else "not installed") + ".")
                    if "diagnostic_logging" in event:
                        output("Diagnostic logging: " + ("on" if event["diagnostic_logging"] else "off") +
                               ". Logs: " + str(root / "GameData/logs"))
                    if event.get("source_mode") == "iso":
                        output("Game source: ISO (keep it in place). Disc available: " +
                               ("yes" if event.get("iso_available") else "no; select the ISO again") + ".")
                terminal |= kind in ("result", "status", "error")
                failed |= kind == "error"
                playing |= action == "--play" and kind == "result" and bool(event.get("pid"))
            code = process.wait()
        diagnostic(root, "Action=" + action + " exit=" + str(code))
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


def detect_assets_iso(root, tools, output=print):
    """Fresh-start convenience; the normal backend authenticates and prepares it."""
    assets = root / "assets"
    candidates = [path for path in assets.iterdir()
                  if path.is_file() and path.suffix.lower() in (".iso", ".xiso")] if assets.is_dir() else []
    if not candidates:
        return False
    status = {}
    if run_action(root, tools, "--status", output=output, status=status) or status.get("installed") is not False:
        return False
    if len(candidates) != 1:
        output("Several disc images are in assets. Select the Xbox ISO you want to use.")
        return True
    output("Found your disc in assets. Preparing direct ISO playback; keep the ISO in place.")
    # Returning True shows Select Game if validation rejects this image. It
    # never silently falls back to extraction or selects a different image.
    return run_action(root, tools, "--use-iso", candidates[0], output=output) != 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Darkwatch: Darker Edition — experimental Linux / Proton")
    parser.add_argument("--proton", type=Path, help="installed Proton folder or proton executable")
    parser.add_argument("--umu", action="store_true", help="use installed umu-run and Proton without Steam")
    parser.add_argument("--steam-root", type=Path, help="native Linux Steam installation folder")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--import-iso", type=Path, metavar="FILE")
    actions.add_argument("--use-iso", type=Path, metavar="FILE", help="play from an Xbox ISO kept in its current location")
    actions.add_argument("--install-hd-textures", type=Path, metavar="FILE")
    actions.add_argument("--install-spanish", type=Path, metavar="FILE")
    actions.add_argument("--install-french", type=Path, metavar="FILE")
    actions.add_argument("--install-german", type=Path, metavar="FILE")
    actions.add_argument("--install-italian", type=Path, metavar="FILE")
    actions.add_argument("--install-portuguese", action="store_true")
    actions.add_argument("--set-language", choices=("en", "es", "fr", "de", "it", "pt-BR"))
    actions.add_argument("--set-diagnostics", choices=("on", "off"))
    actions.add_argument("--use-installation", type=Path, metavar="FOLDER", help="reuse existing game data in place")
    actions.add_argument("--update", action="store_true", help="update installed game data without importing the ISO again")
    actions.add_argument("--check-updates", action="store_true", help="check GitHub for a newer Linux release without installing it")
    actions.add_argument("--download-update", action="store_true", help="download and install the latest Linux launcher in this folder")
    actions.add_argument("--verify", action="store_true")
    actions.add_argument("--play", action="store_true")
    actions.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if args.umu and args.steam_root:
        parser.error("Use either --umu or --steam-root.")
    if not sys.platform.startswith("linux"):
        parser.error("Run this launcher on Linux. Use the Windows launcher on Windows.")
    try:
        root = resolve_path(__file__).parents[1]
        diagnostic(root, "Linux launcher start Python=" + sys.version + " arguments=" + repr(argv))
        if recover_update(root):
            restart_launcher(root, list(sys.argv[1:] if argv is None else argv))
            return 0
        restart_options = ["--umu"] if args.umu else []
        for option in ("steam_root", "proton"):
            if getattr(args, option):
                restart_options += ["--" + option.replace("_", "-"), str(getattr(args, option))]
        if args.download_update:
            installed = download_update(root)
            restart_launcher(root, restart_options + (["--update"] if installed else []))
            return 0
        if args.check_updates:
            print(release_text(check_releases(root)))
            return 0
        tools = umu_tools(args.proton) if args.umu else steam_tools(args.steam_root, args.proton)
        for name in ("import_iso", "use_iso", "install_hd_textures", "install_spanish", "install_french", "install_german", "install_italian", "install_portuguese", "set_language", "set_diagnostics", "use_installation", "update", "verify", "play", "status"):
            value = getattr(args, name)
            if value:
                return run_action(root, tools, "--" + name.replace("_", "-"), value if isinstance(value, (Path, str)) else None)
        if not sys.stdin.isatty():
            parser.error("Choose an action such as --status, --update, --use-installation FOLDER, --use-iso FILE, --import-iso FILE, or --play.")
        choices = {"1": "--import-iso", "2": "--use-installation", "3": "--verify", "4": "--status",
                   "5": "--update", "6": "--install-hd-textures", "7": "--install-spanish", "8": "--set-language", "9": "--set-diagnostics", "10": "--install-portuguese"}
        menu = "home"
        pending_release = start_release_check(root)
        if detect_assets_iso(root, tools):
            menu = "source"
        while True:
            if pending_release is not None:
                try:
                    result = pending_release.get_nowait()
                    pending_release = None
                    if result.get("status") == "available":
                        print(release_text(result))
                except queue.Empty:
                    pass
            if menu == "home":
                print("\nDarkwatch: Darker Edition\n"
                      "First time? Put your Xbox ISO in assets and restart, or use Manage installation → Select Game.\n"
                      "Already installed elsewhere? Manage installation → Use Existing Install.\n\n"
                      "1 Play\n2 Manage installation\n3 Check / Install Updates\n0 Exit")
            elif menu == "manage":
                print("\nManage installation\nChoose an action below. Updates reuse your installed setup.\n\n"
                      "GAME FILES\n"
                      "1 Select Game\n2 Use Existing Install\n3 Verify files\n4 Status\n\n"
                      "TEXTURES & LANGUAGES\n"
                      "6 Install HD texture pack\n7 Install language from PS2 ISO\n"
                      "8 Language / Idioma\n10 Install Portuguese translation (HNNEWGAMES)\n\n"
                      "UPDATES & SUPPORT\n"
                      "5 Update Installation\n9 Diagnostic logging\n\n0 Back")
            elif menu == "source":
                print("\nSelect Game\n\n"
                      "1 Use ISO directly — keep the ISO in place for future launches\n"
                      "2 Import once — the ISO can be removed after setup\n"
                      "3 Use Existing Install — reuse previous game files, saves and add-ons\n0 Back")
            else:
                print("\nUpdates\nCheck for a newer Linux release, or download and install it in this folder.\n\n"
                      "1 Check for Updates\n2 Download and Update\n0 Back")
            choice = input("> ").strip()
            if choice == "0":
                if menu == "home":
                    return 0
                menu = "manage" if menu == "source" else "home"
                continue
            if menu == "home":
                if choice in ("2", "3"):
                    menu = "manage" if choice == "2" else "updates"
                    continue
                action = "--play" if choice == "1" else None
            elif menu == "updates":
                if choice == "1":
                    print(release_text(check_releases(root)))
                    pending_release = None
                elif choice == "2":
                    try:
                        installed = download_update(root)
                        restart_launcher(root, restart_options + (["--update"] if installed else []))
                        return 0
                    except (LauncherError, OSError, ValueError) as error:
                        diagnostic(root, repr(error))
                        print(str(error), file=sys.stderr)
                continue
            elif menu == "source":
                action = {"1": "--use-iso", "2": "--import-iso", "3": "--use-installation"}.get(choice)
            else:
                if choice == "1":
                    menu = "source"
                    continue
                action = choices.get(choice)
            if action is None:
                continue
            path = None
            if action == "--install-spanish":
                choice = input("PS2 language: Español es / Français fr / Deutsch de / Italiano it (blank to cancel): ").strip().lower()
                action = {"es": "--install-spanish", "fr": "--install-french", "de": "--install-german", "it": "--install-italian"}.get(choice)
                if action is None:
                    continue
            if action == "--set-diagnostics":
                path = input("Diagnostic logging on / off (next session; local logs only; blank to cancel): ").strip().lower()
                if path not in ("on", "off"):
                    continue
            if action == "--set-language":
                path = input("English en / Español es / Français fr / Deutsch de / Italiano it / Português (Brasil) pt-BR (blank to cancel): ").strip()
                path = "pt-BR" if path.lower() == "pt-br" else path.lower()
                if path not in ("en", "es", "fr", "de", "it", "pt-BR"):
                    continue
            if action in ("--import-iso", "--use-iso", "--install-hd-textures", "--install-spanish", "--install-french", "--install-german", "--install-italian", "--use-installation"):
                value = input(("Installation folder" if action == "--use-installation" else "File path") + " (blank to cancel): ").strip()
                if not value:
                    continue
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                path = Path(value)
            try:
                run_action(root, tools, action, path)
            except (LauncherError, OSError) as error:
                diagnostic(root, repr(error))
                print(str(error), file=sys.stderr)
    except UpdateCancelled as error:
        print(str(error), file=sys.stderr)
        return 130
    except (LauncherError, OSError, ValueError) as error:
        if "root" in locals():
            diagnostic(root, repr(error))
        print(str(error), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
