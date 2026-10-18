"""Own-disc setup; JSONL status/progress/result/error events are the WPF contract.

Import stages a new version, preserves saves, then atomically switches active.json.
Play verifies installed bytes before starting the release runtime. No network I/O.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid

import intake
import bonus_content

CHUNK = 8 * 1024 * 1024
# Same original-Xbox game partition locations supported by the pinned runtime.
PARTITIONS = (0, 0x18300000)
EXE = "darkwatch_xbe.exe"
SETTINGS = "darkwatch_xbe_settings.toml"
PACKAGE_VERSION = "0.2"
RELEASE_PROFILE = {"name": "release-candidate", "diagnostics": False, "strict_assets": True}
SHADER_PREPARE_TIMEOUT = 15 * 60


def game_environment():
    # Neither preparation nor normal play inherits workstation-only diagnostics.
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith(("XBE_", "DARKWATCH_"))}


class SetupError(ValueError):
    pass


class Cancelled(SetupError):
    pass


def emit(event, message, **fields):
    print(json.dumps(dict(event=event, message=message, **fields)), flush=True)


def safe_path(root, relative):
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        raise SetupError("Invalid package or installation path.")
    for part in relative.split("/"):
        intake.safe_component(part.encode("ascii"))
    return intake.safe_destination(root, relative)


def read_json(path):
    if path.stat().st_size > 8 * 1024 * 1024:
        raise SetupError(f"Metadata is too large: {path.name}")
    with path.open(encoding="utf-8-sig") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise SetupError(f"Invalid metadata: {path.name}")
    return value


def write_json(path, value):
    temporary = safe_path(path.parent, path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as target:
        json.dump(value, target, indent=2)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


@contextmanager
def exclusive(root):
    root.mkdir(parents=True, exist_ok=True)
    lock = safe_path(root, ".launcher.lock").open("a+b")
    try:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise SetupError("Another setup or launch is already in progress.") from error
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise SetupError("Another setup or launch is already in progress.") from error
        yield
    finally:
        lock.close()


def game_running():
    """Refuse updates while any Darkwatch runtime is open, including a dev build."""
    if os.name != "nt":
        return False
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise SetupError("Could not check whether Darkwatch is running.")
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.casefold() == EXE:
                return True
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() not in (0, 18):
            raise SetupError("Could not finish checking running applications.")
        return False
    finally:
        kernel.CloseHandle(snapshot)


def require_closed():
    if game_running():
        raise SetupError("Close Darkwatch before installing, repairing, or starting another copy.")


class Setup:
    def __init__(self, package, install_root, cancel_file=None, notify=emit):
        self.package = Path(package).absolute()
        self.root = Path(install_root).absolute()
        safe_path(self.package, "package-manifest.json")
        safe_path(self.root, "active.json")
        self.cancel_file = Path(cancel_file) if cancel_file else None
        self.notify = notify
        manifest = read_json(self.package / "package-manifest.json")
        if manifest.get("complete") is not True or manifest.get("version") != PACKAGE_VERSION:
            raise SetupError("This launcher package is incomplete or incompatible. Extract a fresh complete package.")
        if manifest.get("release_profile") != RELEASE_PROFILE:
            raise SetupError("This package does not contain the required release runtime.")
        self.files = manifest.get("files")
        if not isinstance(self.files, dict) or not self.files:
            raise SetupError("The launcher package manifest is missing its files.")
        for path, digest in self.files.items():
            safe_path(self.package, path)
            if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
                raise SetupError("Invalid package checksum.")
        for path in ("payload/supported-disc.json", "payload/intake.py", "payload/bonus_content.py", "payload/hd_ui/overrides.toml",
                     "payload/runtime/" + EXE, "payload/runtime/darkwatch_hd_ui_builder.exe"):
            if path not in self.files:
                raise SetupError(f"Required package file is missing: {path}")
        if manifest.get("runtime_sha256") != self.files["payload/runtime/" + EXE]:
            raise SetupError("The packaged runtime identity is inconsistent.")
        disc_path = safe_path(self.package, "payload/supported-disc.json")
        if self.digest(disc_path) != self.files["payload/supported-disc.json"]:
            raise SetupError("Supported disc metadata is damaged. Extract a fresh launcher package.")
        self.disc = read_json(disc_path)
        self.assets = self.disc.get("files", [])
        names = set()
        for item in self.assets:
            name, size, digest = item["path"], item["size"], item["sha256"]
            safe_path(self.root, name)
            if name.casefold() in names or not isinstance(size, int) or size < 0 or not re.fullmatch("[0-9a-f]{64}", digest):
                raise SetupError("Invalid supported disc file list.")
            names.add(name.casefold())
        xbe = next((f for f in self.assets if f["path"].casefold() == "default.xbe"), None)
        if not xbe or "packfile.pck" not in names or xbe["sha256"] != self.disc.get("xbe_sha256"):
            raise SetupError("Supported disc does not match this runtime.")
        pack = next(f for f in self.assets if f["path"].casefold() == "packfile.pck")
        if pack["sha256"] != bonus_content.ORIGINAL_SHA256:
            raise SetupError("Supported disc does not match this bonus-content revision.")

    def check_cancel(self):
        if self.cancel_file and self.cancel_file.exists():
            raise Cancelled("Cancelled. Your previous installation and saves were kept.")

    def digest(self, path):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(CHUNK):
                self.check_cancel()
                digest.update(chunk)
        return digest.hexdigest()

    def active(self, root=None):
        root = self.root if root is None else root
        pointer = safe_path(root, "active.json")
        if not pointer.exists():
            return None
        version = read_json(pointer).get("version", "")
        if not isinstance(version, str) or not re.fullmatch("[0-9a-f]{32}", version):
            raise SetupError("Installation record is damaged. Your saved data has not been changed.")
        return safe_path(root, "versions/" + version)

    @contextmanager
    def user_data_source(self, previous):
        # Only the first portable import adopts prior launcher saves; Play never uses AppData.
        local = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
        if previous or not local or not Path(local).is_absolute():
            yield previous
            return
        legacy = Path(local) / "DarkwatchDarkerEdition"
        if legacy.absolute() == self.root or not safe_path(legacy, "active.json").exists():
            yield None
            return
        with exclusive(legacy):
            try:
                current = self.active(legacy)
                metadata = read_json(safe_path(current, "install.json")) if current else {}
                if metadata.get("disc_sha256") != self.files["payload/supported-disc.json"]:
                    raise SetupError("The previous installation does not match this disc revision.")
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise SetupError("Could not preserve saves from the previous launcher installation. "
                                 "Its installation record needs repair; no installed data was changed. " + str(error)) from error
            self.notify("progress", "Copying prior launcher saves into this portable folder", percent=97)
            yield current

    def installed_files(self, current):
        metadata = read_json(safe_path(current, "install.json"))
        if metadata.get("disc_sha256") != self.files["payload/supported-disc.json"]:
            raise SetupError("Installed disc version differs. Import the supported ISO again.")
        if metadata.get("content_revision") != bonus_content.CONTENT_REVISION:
            raise SetupError("This installation needs the bonus content update. Import your original ISO again; saves and settings will be kept.")
        files = [("assets/" + f["path"], f["size"],
                  bonus_content.INSTALLED_SHA256 if f["path"].casefold() == "packfile.pck" else f["sha256"])
                 for f in self.assets]
        for path, digest in self.files.items():
            if path.startswith("payload/runtime/") and not path.endswith("/darkwatch_hd_ui_builder.exe"):
                relative = path.removeprefix("payload/runtime/")
                size = safe_path(self.package, path).stat().st_size
                files.append((relative, size, digest))
        hd = metadata.get("hd_ui", {})
        if not isinstance(hd.get("size"), int) or hd["size"] < 1 or not re.fullmatch("[0-9a-f]{64}", hd.get("sha256", "")):
            raise SetupError("Installed HD artwork record is damaged. Import your ISO again to repair it.")
        files.append(("hd-ui.pack", hd["size"], hd["sha256"]))
        return files

    def status(self):
        current = self.active()
        if not current:
            return dict(installed=False, ready=False, message="Import your own supported Darkwatch ISO to begin.")
        try:
            for relative, size, _ in self.installed_files(current):
                path = safe_path(current, relative)
                if not path.is_file() or path.stat().st_size != size:
                    raise SetupError(f"Missing or damaged installed file: {relative}. Import your ISO again to repair it.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            return dict(installed=True, ready=False, message=str(error))
        return dict(installed=True, ready=True, message="Installed. Files are verified before every launch.", install_dir=str(current))

    def verify_package(self):
        for index, (relative, digest) in enumerate(self.files.items()):
            self.check_cancel()
            self.notify("progress", "Checking launcher files", percent=int(index * 5 / len(self.files)))
            if self.digest(safe_path(self.package, relative)) != digest:
                raise SetupError(f"Launcher file is damaged: {relative}. Extract a fresh launcher package.")
        artwork = tomllib.loads((self.package / "payload/hd_ui/overrides.toml").read_text(encoding="utf-8"))
        for texture in artwork.get("texture", []):
            for region in [texture, *texture.get("region", [])]:
                if "file" in region and "payload/hd_ui/" + region["file"] not in self.files:
                    raise SetupError("The HD artwork package is incomplete.")

    def verify(self):
        current = self.active()
        if not current:
            raise SetupError("Import your own Darkwatch ISO first.")
        files = self.installed_files(current)
        total = sum(size for _, size, _ in files)
        done = 0
        for relative, size, digest in files:
            self.check_cancel()
            self.notify("progress", f"Verifying {relative}", percent=int(done * 100 / max(1, total)))
            path = safe_path(current, relative)
            if not path.is_file() or path.stat().st_size != size or self.digest(path) != digest:
                raise SetupError(f"Missing or damaged installed file: {relative}. Import your ISO again to repair it.")
            done += size
        self.notify("progress", "Installed files verified", percent=100)
        return current

    def find_volume(self, source, size):
        expected = {f["path"].casefold(): f for f in self.assets}
        for offset in PARTITIONS:
            self.check_cancel()
            try:
                volume = intake.XDVDFS(source, size, offset)
                # This revision has only root-level files; reject unrelated trees before walking them.
                if not 0 < volume.root_size <= 1024 * 1024:
                    continue
                root = intake.parse_directory(volume.read_at(offset + volume.root_sector * intake.SECTOR_SIZE, volume.root_size))
                if len(root) != len(expected) or any(attributes & 0x10 for _, _, _, attributes in root):
                    continue
                entries = volume.inventory()
            except (intake.IntakeError, UnicodeError):
                continue
            found = {e.path.casefold(): e for e in entries if not e.is_directory}
            if set(found) != set(expected) or any(found[name].size != f["size"] for name, f in expected.items()):
                continue
            xbe = found["default.xbe"]
            if hashlib.sha256(volume.read_at(xbe.image_offset, xbe.size)).hexdigest() != self.disc["xbe_sha256"]:
                continue
            return offset, found
        raise SetupError("This is not the supported Darkwatch Xbox disc revision. Supply an XISO or a full original-Xbox disc image; extracted folders and other editions are not supported.")

    def build_hd(self, stage):
        builder = safe_path(self.package, "payload/runtime/darkwatch_hd_ui_builder.exe")
        command = [str(builder), str(stage / "assets/packfile.pck"), str(stage / "hd-ui.pack"), str(self.package / "payload/hd_ui")]
        # Keep useful builder errors, without leaving setup diagnostics in the install.
        with tempfile.TemporaryFile(dir=stage) as log:
            process = subprocess.Popen(command, cwd=stage, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                while process.poll() is None:
                    self.check_cancel()
                    time.sleep(0.1)
                if process.returncode:
                    log.seek(0, os.SEEK_END)
                    log.seek(max(0, log.tell() - 512))
                    detail = log.read().decode("utf-8", errors="replace").strip()
                    raise SetupError("HD artwork preparation failed. The previous installation was kept." +
                                     (" " + detail if detail else ""))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
        output = stage / "hd-ui.pack"
        if not output.is_file() or output.stat().st_size < 1:
            raise SetupError("HD artwork preparation did not produce its required output.")

    def copy_user_data(self, previous, stage):
        if not previous or not previous.is_dir():
            return
        for path in previous.iterdir():
            # Historical diagnostics remain in the retained old version, not the new install.
            if path.name != SETTINGS and path.name != "cache" and not re.fullmatch(r"hdd\d*", path.name):
                continue
            source = safe_path(previous, path.name)
            if source.is_dir():
                for folder, dirs, files in os.walk(source, followlinks=False):
                    self.check_cancel()
                    for name in dirs + files:
                        safe_path(previous, (Path(folder) / name).relative_to(previous).as_posix())
                shutil.copytree(source, stage / path.name, copy_function=self.copy_file)
            elif source.is_file():
                self.copy_file(source, stage / path.name)

    def prepare_shaders(self, current):
        self.check_cancel()
        require_closed()
        events = queue.Queue(maxsize=64)
        stopped = threading.Event()
        ready, completed, total = False, -1, None
        with tempfile.TemporaryFile(dir=current) as errors:
            process = subprocess.Popen([str(current / EXE), "--prepare-shaders"], cwd=current,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
                                       env=game_environment(),
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

            def read_events():
                try:
                    while not stopped.is_set():
                        line = process.stdout.readline(16385)
                        while not stopped.is_set():
                            try:
                                events.put(line, timeout=0.1)
                                break
                            except queue.Full:
                                pass
                        if not line or len(line) > 16384:
                            break
                finally:
                    process.stdout.close()

            reader = threading.Thread(target=read_events, daemon=True)
            reader.start()
            deadline = time.monotonic() + SHADER_PREPARE_TIMEOUT
            try:
                while True:
                    self.check_cancel()
                    if time.monotonic() >= deadline:
                        raise SetupError("Shader preparation took too long. Close other applications and try again.")
                    try:
                        line = events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if not line:
                        break
                    if len(line) > 16384:
                        raise SetupError("Shader preparation returned an invalid response.")
                    try:
                        item = json.loads(line)
                    except (ValueError, UnicodeError) as error:
                        raise SetupError("Shader preparation returned an invalid response.") from error
                    if not isinstance(item, dict):
                        raise SetupError("Shader preparation returned an invalid response.")
                    state = item.get("state")
                    if state == "shader_prepare":
                        done, count, progress = item.get("completed"), item.get("total"), item.get("progress")
                        if (ready or type(done) is not int or type(count) is not int or not 0 <= done <= count or
                            count <= 0 or done < completed or (total is not None and total != count) or
                            type(progress) not in (int, float) or not 0 <= progress <= 100):
                            raise SetupError("Shader preparation returned invalid progress.")
                        completed, total = done, count
                        self.notify("shader_prepare", "Preparing shaders — %d of %d" % (done, count),
                                    percent=100 * done / count, completed=done, total=count)
                    elif state == "shader_ready":
                        if ready or (total is not None and completed != total):
                            raise SetupError("Shader preparation finished before every shader was ready.")
                        ready = True
                    elif state == "error":
                        message = item.get("message")
                        raise SetupError("Shader preparation failed. " + (message[:512] if isinstance(message, str) else "Try again."))
                    else:
                        raise SetupError("Shader preparation returned an unknown response.")
                while process.poll() is None:
                    self.check_cancel()
                    if time.monotonic() >= deadline:
                        raise SetupError("Shader preparation did not finish. Please try again.")
                    time.sleep(0.1)
                code = process.returncode
                self.check_cancel()
                if code or not ready:
                    errors.seek(0, os.SEEK_END)
                    errors.seek(max(0, errors.tell() - 512))
                    detail = errors.read().decode("utf-8", errors="replace").strip()
                    raise SetupError("Shader preparation failed. Please try again." +
                                     (" " + detail if detail else ""))
                self.notify("shader_ready", "Shaders are ready", percent=100)
            finally:
                stopped.set()
                if process.poll() is None:
                    process.kill()
                process.wait()
                reader.join(timeout=5)

    def copy_file(self, source, destination):
        with Path(source).open("rb") as original, Path(destination).open("xb") as target:
            while chunk := original.read(CHUNK):
                self.check_cancel()
                target.write(chunk)
        shutil.copystat(source, destination)
        return str(destination)

    def import_iso(self, iso):
        iso = Path(iso).absolute()
        require_closed()
        self.verify_package()
        previous = self.active()
        versions = safe_path(self.root, "versions")
        versions.mkdir(parents=True, exist_ok=True)
        version = uuid.uuid4().hex
        stage = safe_path(versions, version)
        stage.mkdir()
        committed = False
        try:
            with iso.open("rb") as source:
                original_stat = os.fstat(source.fileno())
                offset, entries = self.find_volume(source, original_stat.st_size)
                needed = sum(f["size"] for f in self.assets) + 512 * 1024 * 1024
                if shutil.disk_usage(self.root).free < needed:
                    raise SetupError("Not enough free space. Keep at least 4.5 GB free for a new installation, plus space for your saved data and cache.")
                total = sum(f["size"] for f in self.assets)
                done = 0
                for item in self.assets:
                    entry = entries[item["path"].casefold()]
                    target = safe_path(stage, "assets/" + item["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source.seek(entry.image_offset)
                    remaining, digest = entry.size, hashlib.sha256()
                    with target.open("xb") as sink:
                        while remaining:
                            self.check_cancel()
                            chunk = source.read(min(CHUNK, remaining))
                            if not chunk:
                                raise SetupError("The ISO was truncated while reading.")
                            sink.write(chunk)
                            digest.update(chunk)
                            remaining -= len(chunk)
                            done += len(chunk)
                            self.notify("progress", f"Importing {item['path']}", percent=5 + int(done * 80 / max(1, total)))
                    if digest.hexdigest() != item["sha256"]:
                        raise SetupError(f"This ISO contains a damaged or unsupported {item['path']}. The previous installation was kept.")
                final_stat = os.fstat(source.fileno())
                if (original_stat.st_size, original_stat.st_mtime_ns) != (final_stat.st_size, final_stat.st_mtime_ns):
                    raise SetupError("The source ISO changed during import. Please retry with an unchanged file.")
            self.notify("progress", "Preparing War Train and Splitter grenades from your disc", percent=86)
            self.check_cancel()
            pack = safe_path(stage, "assets/packfile.pck")
            candidate = bonus_content.patch_pack(pack.read_bytes())
            self.check_cancel()
            pack.write_bytes(candidate)
            del candidate
            if self.digest(pack) != bonus_content.INSTALLED_SHA256:
                raise SetupError("Prepared bonus content is damaged. The previous installation was kept.")
            for relative, digest in self.files.items():
                if relative.startswith("payload/runtime/") and not relative.endswith("/darkwatch_hd_ui_builder.exe"):
                    target = safe_path(stage, relative.removeprefix("payload/runtime/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(safe_path(self.package, relative), target)
                    if self.digest(target) != digest:
                        raise SetupError("Runtime file changed during installation.")
            self.notify("progress", "Preparing HD artwork from your disc", percent=87)
            self.build_hd(stage)
            self.check_cancel()
            require_closed()
            self.notify("progress", "Preserving saves, controls, and shader cache", percent=97)
            with self.user_data_source(previous) as user_data:
                self.copy_user_data(user_data, stage)
                self.prepare_shaders(stage)
                hd = stage / "hd-ui.pack"
                write_json(stage / "install.json", dict(schema_version=1, disc_sha256=self.files["payload/supported-disc.json"],
                           content_revision=bonus_content.CONTENT_REVISION, partition_offset=offset,
                           hd_ui=dict(size=hd.stat().st_size, sha256=self.digest(hd))))
                self.check_cancel()
                require_closed()
                write_json(self.root / "active.json", dict(version=version))
                committed = True
            return dict(installed=True, ready=True, install_dir=str(stage), message="Darkwatch: Darker Edition is installed. Your original ISO was not changed.")
        finally:
            if not committed:
                checked = safe_path(versions, version)
                if checked.exists():
                    shutil.rmtree(checked)

    def play(self):
        require_closed()
        current = self.verify()
        self.prepare_shaders(current)
        self.check_cancel()
        require_closed()
        process = subprocess.Popen([str(current / EXE)], cwd=current,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=game_environment(),
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        # Catch immediate loader/startup failures without imposing a play-session timer.
        try:
            code = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            code = None
        if code:
            raise SetupError(f"Darkwatch could not start (exit 0x{code & 0xffffffff:08X}). Check the system requirements in README.txt and verify your files.")
        return dict(installed=True, ready=True, pid=process.pid, message="Darkwatch: Darker Edition started.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--cancel-file", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true")
    action.add_argument("--import-iso", type=Path)
    action.add_argument("--verify", action="store_true")
    action.add_argument("--play", action="store_true")
    args = parser.parse_args(argv)
    try:
        setup = Setup(args.package, args.install_root, args.cancel_file)
        if args.status:
            emit("status", **setup.status())
            return 0
        with exclusive(setup.root):
            if args.import_iso:
                result = setup.import_iso(args.import_iso)
            elif args.play:
                result = setup.play()
            else:
                current = setup.verify()
                result = dict(installed=True, ready=True, install_dir=str(current), message="All installed files verified.")
            emit("result", **result, percent=100)
        return 0
    except (SetupError, intake.IntakeError, OSError, ValueError, KeyError, TypeError) as error:
        emit("error", str(error), ready=False, cancelled=isinstance(error, Cancelled))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
