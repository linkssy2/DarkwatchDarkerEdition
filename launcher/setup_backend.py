"""Own-disc setup; JSONL status/progress/result/error events are the WPF contract.

Import stages a new version, preserves saves, then atomically switches active.json.
Play verifies installed bytes before starting the release runtime. The separate
release-check action reads public metadata and never changes installed data.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
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

# Refuse mixed package imports after an interrupted self-update. The independent
# runner is recovered by the launcher before this backend is used again.
if __name__ == '__main__':
    _package_root = Path(__file__).resolve().parent.parent
    for _update_root in (_package_root, _package_root.parent if _package_root.name == 'windows' else _package_root):
        _journal = _update_root / '.launcher-update/transaction.json'
        if _journal.exists():
            try:
                if _journal.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('Oversized update journal')
                _phase = json.loads(_journal.read_text(encoding='utf-8-sig'))['phase']
                if _phase not in ('committed', 'rolled_back'):
                    raise ValueError('Pending update')
            except (OSError, ValueError, KeyError, TypeError):
                print(json.dumps(dict(event='error', ready=False,
                    message='A launcher update is pending. Close this copy and restart the launcher to recover.')), flush=True)
                raise SystemExit(1)

import intake
import bonus_content
import gameplay_hd
import character_content
import character_preview
import language_pack
import installed_source

CHUNK = 8 * 1024 * 1024
# Same original-Xbox game partition locations supported by the pinned runtime.
PARTITIONS = (0, 0x18300000)
EXE = "darkwatch_xbe.exe"
SETTINGS = "darkwatch_xbe_settings.toml"
DISC_SOURCE = "disc-source.toml"
PACKAGE_VERSION = "0.7"
RELEASE_PROFILE = {"name": "release-candidate", "diagnostics": False, "strict_assets": True}
# Maximum time without a completed shader, not a limit on the whole preparation.
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
    def __init__(self, package, install_root, cancel_file=None, notify=emit, ignore_location=False):
        self.package = Path(package).absolute()
        self.local_root = Path(install_root).absolute()
        self.root = self.local_root
        location = safe_path(self.local_root, "installation-location.json")
        if location.exists() and not ignore_location:
            selected = read_json(location).get("root")
            if not isinstance(selected, str) or not Path(selected).is_absolute():
                raise SetupError("The saved installation location is invalid. Select your existing installation again.")
            self.root = Path(selected).absolute()
            if self.root != self.local_root and safe_path(self.root, "installation-location.json").exists():
                raise SetupError("Select the original GameData folder, not another linked launcher.")
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
        self.package_sha256 = self.digest(self.package / "package-manifest.json")
        self.artwork_sha256 = hashlib.sha256(json.dumps({path: digest for path, digest in self.files.items()
            if path.startswith("payload/hd_ui/") or path == "payload/runtime/darkwatch_hd_ui_builder.exe"},
            sort_keys=True).encode()).hexdigest()
        for path in ("payload/supported-disc.json", "payload/intake.py", "payload/bonus_content.py", "payload/installed_source.py",
                     "payload/gameplay_hd.py", "payload/gameplay-hd-catalog.json", "payload/hd_ui/overrides.toml",
                     "payload/character_content.py", "payload/character_animation.py", "payload/character_assets.py",
                     "payload/character_archive.py", "payload/character_repaint.py", "payload/character-catalog.json",
                     "payload/character_boss.py", "payload/character_boss_effects.py", "payload/character_spectral_hands.py",
                     "payload/character_hand_seams.py", "payload/character_secondary.py", "payload/character_preview.py",
                     "payload/character_roster.py", "payload/character_tala.py",
                     "payload/revolver_content.py", "payload/revolver_scripts.py",
                     "payload/character-art/cassidy-hands-1024.dds", "payload/character-art/cassidy-hands-256.dds",
                     "payload/character-art/tala-hands-1024.dds", "payload/character-art/tala-hands-256.dds",
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
        catalog = safe_path(self.package, "payload/gameplay-hd-catalog.json")
        if self.digest(catalog) != self.files["payload/gameplay-hd-catalog.json"]:
            raise SetupError("HD texture catalog is damaged. Extract a fresh launcher package.")
        self.hd_catalog = gameplay_hd.Catalog(catalog.read_bytes())
        self.hd_warning = ""
        self.hd_verified = False
        self.ps2_language_catalog = None
        ps2_catalog = "payload/ps2-spanish-catalog.json"
        if ps2_catalog in self.files:
            path = safe_path(self.package, ps2_catalog)
            if self.digest(path) != self.files[ps2_catalog]:
                raise SetupError("PS2 Spanish catalog is damaged. Extract a fresh launcher package.")
            self.ps2_language_catalog = language_pack.Catalog(path.read_bytes())

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
        if metadata.get("content_revision") != character_content.CONTENT_REVISION:
            raise SetupError("This installation needs the character content update. Choose Update Game in the launcher.")
        files = [("assets/" + f["path"], *character_content.INSTALLED.get(f["path"], (f["size"], f["sha256"])))
                 for f in self.assets if metadata.get("source_mode") != "iso" or
                 f["path"] == "default.xbe" or f["path"] in character_content.INSTALLED]
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

    def originals(self):
        return {item["path"]: item for item in self.assets if item["path"] in character_content.INSTALLED}

    def source_status(self, current):
        metadata = read_json(safe_path(current, "install.json"))
        mode = metadata.get("source_mode", "extracted")
        if mode not in ("iso", "extracted"):
            raise SetupError("The installed game source is invalid. Select your game source again.")
        if mode == "extracted":
            return dict(source_mode=mode, iso_path="", iso_available=False)
        path = metadata.get("iso_path", "")
        available = isinstance(path, str) and Path(path).is_absolute() and Path(path).is_file()
        return dict(source_mode=mode, iso_path=path, iso_available=available)

    @contextmanager
    def open_iso(self, iso, record=None):
        """Authenticate the mounted revision and refuse source changes during an operation."""
        iso = Path(iso)
        if not iso.is_absolute() or not iso.is_file():
            raise SetupError("The game ISO is unavailable. Reconnect its drive or select its new location with Use ISO directly.")
        with iso.open("rb") as source:
            before = os.fstat(source.fileno())
            if record is not None and (record.get("iso_size"), record.get("iso_mtime_ns")) != (before.st_size, before.st_mtime_ns):
                raise SetupError("The game ISO changed. Select it again with Use ISO directly to verify it; your saves are kept.")
            offset, entries = self.find_volume(source, before.st_size)
            yield source, offset, entries, dict(source_mode="iso", iso_path=str(iso),
                                               iso_size=before.st_size, iso_mtime_ns=before.st_mtime_ns)
            after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise SetupError("The source ISO changed while reading. Retry with an unchanged file.")

    def write_iso_marker(self, current, record):
        text = ("schema_version = 1\npath = " + json.dumps(record["iso_path"], ensure_ascii=False) +
                "\noverrides = " + json.dumps(list(character_content.INSTALLED)) + "\n")
        if len(text.encode("utf-8")) > 16 * 1024:
            raise SetupError("The selected ISO path is too long.")
        target = safe_path(current, DISC_SOURCE)
        temporary = safe_path(current, DISC_SOURCE + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def validate_iso_marker(self, current, record):
        marker = safe_path(current, DISC_SOURCE)
        if not marker.is_file() or marker.stat().st_size > 16 * 1024:
            raise SetupError("The ISO source record needs repair. Select your ISO again with Use ISO directly.")
        value = tomllib.loads(marker.read_text(encoding="utf-8"))
        if (value.get("schema_version") != 1 or value.get("path") != record.get("iso_path") or
                value.get("overrides") != list(character_content.INSTALLED)):
            raise SetupError("The ISO source record differs. Select your ISO again with Use ISO directly.")

    def read_iso_files(self, source, entries, target=None, names=None, verify_all=False):
        """Read directly from the disc; materialize only explicitly requested host files."""
        names = set(names or ())
        items = [item for item in self.assets if verify_all or item["path"] in names]
        total, done = sum(item["size"] for item in items), 0
        for item in items:
            entry = entries[item["path"].casefold()]
            with ExitStack() as stack:
                sink = None
                if target is not None and item["path"] in names:
                    path = safe_path(target, item["path"])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    sink = stack.enter_context(path.open("xb"))
                source.seek(entry.image_offset)
                remaining, digest = entry.size, hashlib.sha256()
                while remaining:
                    self.check_cancel()
                    chunk = source.read(min(CHUNK, remaining))
                    if not chunk:
                        raise SetupError("The ISO was truncated while reading.")
                    if sink is not None:
                        sink.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                    done += len(chunk)
                    self.notify("progress", f"Verifying disc {item['path']}", percent=5 + int(done * 80 / max(1, total)))
                if digest.hexdigest() != item["sha256"]:
                    raise SetupError(f"This ISO contains a damaged or unsupported {item['path']}. Your previous installation was kept.")

    def iso_preparation_names(self):
        # LvlMulti supplies player animation resources but remains on the ISO after conversion.
        return {"default.xbe", "LvlMulti.pck", *character_content.INSTALLED}

    def needs_update(self, current):
        metadata = read_json(safe_path(current, "install.json"))
        return (metadata.get("package_sha256") != self.package_sha256 or
                metadata.get("content_revision") != character_content.CONTENT_REVISION)

    def use_installation(self, folder):
        """Attach explicitly chosen existing data without copying it or its saves."""
        require_closed()
        folder = Path(folder).absolute()
        candidates = [folder, folder / "GameData"]
        if folder.parent.name == "versions":
            candidates.append(folder.parent.parent)
        selected = next((path for path in candidates if safe_path(path, "active.json").is_file()), None)
        if selected is None:
            raise SetupError("Choose the previous Darkwatch folder or its GameData folder.")
        if selected != self.local_root and safe_path(selected, "installation-location.json").exists():
            raise SetupError("Choose the original GameData folder, not another linked launcher.")
        with ExitStack() as locks:
            locks.enter_context(exclusive(self.local_root))
            if selected != self.local_root:
                locks.enter_context(exclusive(selected))
            current = self.active(selected)
            metadata = read_json(safe_path(current, "install.json"))
            if metadata.get("disc_sha256") != self.files["payload/supported-disc.json"]:
                raise SetupError("The selected installation uses a different disc revision.")
            if not safe_path(current, "assets/default.xbe").is_file():
                raise SetupError("The selected installation is incomplete. Keep its saves and repair it from your disc.")
            self.check_cancel()
            self.local_root.mkdir(parents=True, exist_ok=True)
            if selected == self.local_root:
                safe_path(self.local_root, "installation-location.json").unlink(missing_ok=True)
            else:
                write_json(self.local_root / "installation-location.json", dict(root=str(selected)))
        self.root = selected
        return self.status()

    def status(self):
        current = self.active()
        if not current:
            return dict(installed=False, ready=False, hd_textures_installed=False,
                        language="en", spanish_installed=False, update_available=False,
                        source_mode="", iso_path="", iso_available=False,
                        message="Select Game to use your Xbox ISO directly, import it once, or reuse an existing installation.")
        source_fields = {}
        try:
            source_fields = self.source_status(current)
            metadata = read_json(safe_path(current, "install.json"))
            if source_fields["source_mode"] == "iso":
                self.validate_iso_marker(current, metadata)
                with self.open_iso(metadata["iso_path"], metadata):
                    pass
            if self.needs_update(current):
                recoverable = (source_fields["source_mode"] == "iso" or
                               metadata.get("content_revision") == character_content.CONTENT_REVISION or
                               installed_source.has_recovery(safe_path(current, "source-recovery"), self.originals()))
                return dict(installed=True, ready=False, update_available=recoverable,
                            hd_textures_installed=self.hd_status(current), install_dir=str(current),
                            **source_fields, **self.language_status(current), message=(
                            "Update available. Your retained ISO, prepared game data, saves and add-ons will be reused."
                            if source_fields["source_mode"] == "iso" else
                            "Update available. Choose Update Game; your installed data, saves and add-ons will be reused without the ISO."
                            if recoverable else "This older installation needs one final ISO import for the content update. Future updates will reuse its installed data; saves and settings are kept."))
            for relative, size, _ in self.installed_files(current):
                path = safe_path(current, relative)
                if not path.is_file() or path.stat().st_size != size:
                    raise SetupError(f"Missing or damaged installed file: {relative}. Import your ISO again to repair it.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            return dict(installed=True, ready=False, update_available=False, hd_textures_installed=False,
                        **source_fields, message=str(error))
        hd = self.hd_status(current)
        return dict(installed=True, ready=True, update_available=False, hd_textures_installed=hd,
                    message=self.hd_warning or "Installed. Files are verified before every launch.", install_dir=str(current),
                    **source_fields, **self.language_status(current))

    def language_status(self, current):
        try:
            available = bool(self.ps2_language_catalog and
                             self.ps2_language_catalog.validate(current, self.check_cancel, full=False))
        except Cancelled:
            raise
        except (OSError, ValueError):
            available = False
        return dict(language=language_pack.selected(current), spanish_installed=available,
                    spanish_audio_installed=available)

    def prepare_previews(self, current):
        """Upgrade the local menu cache without requiring another ISO import."""
        metadata = read_json(safe_path(current, "install.json"))
        record = metadata.get("character_preview", {})
        path = safe_path(current, character_preview.NAME)
        if (isinstance(record, dict) and record.get("version") == character_preview.VERSION and
                isinstance(record.get("size"), int) and 16 < record["size"] <= character_preview.MAX_BYTES and
                isinstance(record.get("sha256"), str) and re.fullmatch("[0-9a-f]{64}", record["sha256"]) and
                path.is_file() and path.stat().st_size == record["size"] and self.digest(path) == record["sha256"]):
            return
        require_closed()
        self.notify("progress", "Preparing character previews from your disc", percent=98)
        record = character_preview.prepare(safe_path(current, "assets"), path, self.check_cancel)
        metadata["character_preview"] = record
        write_json(safe_path(current, "install.json"), metadata)

    def spanish_valid(self, current):
        return bool(self.ps2_language_catalog and
                    self.ps2_language_catalog.validate(current, self.check_cancel))

    def install_spanish(self, archive):
        require_closed()
        current = self.active()
        if not current or not self.status()["ready"]:
            raise SetupError("Import or repair your Darkwatch ISO before installing Spanish.")
        self.verify_package()
        archive = Path(archive).absolute()
        if archive.suffix.lower() != ".iso":
            raise SetupError("Choose your supported PS2 Darkwatch ISO to install Spanish. Older language ZIPs are no longer supported.")
        if not self.ps2_language_catalog or "payload/ps2_spanish.py" not in self.files:
            raise SetupError("This launcher does not support Spanish from a PS2 ISO. Update the launcher.")
        needed = 3 * sum(row["size"] for row in self.ps2_language_catalog.files.values()) + 128 * 1024 * 1024
        if shutil.disk_usage(self.root).free < needed:
            raise SetupError(f"Not enough free space. Keep at least {needed / (1024 ** 3):.1f} GB free to prepare Spanish.")
        import ps2_spanish
        record = read_json(current / "install.json")
        if record.get("source_mode") == "iso":
            needed += sum(item["size"] for item in self.assets if item["path"] in ps2_spanish.XBOX)
            needed += character_content.INSTALLED["packfile.pck"][0]
            if shutil.disk_usage(self.root).free < needed:
                raise SetupError(f"Not enough free space. Keep at least {needed / (1024 ** 3):.1f} GB free to prepare Spanish.")
        with tempfile.TemporaryDirectory(prefix=".spanish-ps2-", dir=self.root) as temporary:
            prepared = Path(temporary) / "Spanish.zip"
            assets = safe_path(current, "assets")
            if record.get("source_mode") == "iso":
                assets = Path(temporary) / "assets"
                with self.open_iso(record["iso_path"], record) as (source, _, entries, _):
                    self.read_iso_files(source, entries, assets, ps2_spanish.XBOX)
                self.copy_file(safe_path(current, "assets/packfile.pck"), assets / "packfile.pck")
            ps2_spanish.prepare(archive, assets, prepared,
                                self.check_cancel, self.notify)
            self.ps2_language_catalog.install(prepared, current, self.check_cancel, self.notify, require_closed)
        return dict(installed=True, ready=True, update_available=False, install_dir=str(current), **self.language_status(current),
                    message="Spanish installed. Choose Español before starting the game.")

    def set_language(self, value):
        require_closed()
        current = self.active()
        if not current or not self.status()["ready"]:
            raise SetupError("Import or repair your Darkwatch ISO before choosing a language.")
        if value == "es":
            self.verify_package()
            if not self.spanish_valid(current):
                raise SetupError("Spanish needs a supported PS2 ISO import. Import Spanish again or choose English; previous files are kept.")
        self.check_cancel()
        require_closed()
        language_pack.select(current, value)
        return dict(installed=True, ready=True, update_available=False, install_dir=str(current), **self.language_status(current),
                    message="Idioma: español. Se aplicará al iniciar el juego." if value == "es" else "Language: English. Applies on the next game launch.")

    def hd_status(self, current, full=False):
        self.hd_warning = ""
        try:
            return self.hd_catalog.validate(current, self.check_cancel, self.notify, full=full)
        except Cancelled:
            raise
        except (OSError, ValueError):
            self.hd_warning = "The optional HD texture pack needs repair. Install its download again; the base game is still ready."
            return False

    def install_hd_textures(self, archive):
        require_closed()
        current = self.active()
        if not current or not self.status()["ready"]:
            raise SetupError("Import or repair your Darkwatch ISO before installing optional HD textures.")
        self.verify_package()
        self.hd_catalog.install(Path(archive).absolute(), current, self.check_cancel, self.notify, require_closed)
        return dict(installed=True, ready=True, update_available=False, install_dir=str(current), hd_textures_installed=True,
                    message="HD gameplay textures installed. Enable HD Textures in Graphics.")

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

    def verify(self, optional=True):
        current = self.active()
        if not current:
            raise SetupError("Import your own Darkwatch ISO first.")
        record = read_json(safe_path(current, "install.json"))
        if record.get("source_mode") == "iso":
            self.validate_iso_marker(current, record)
            with self.open_iso(record["iso_path"], record) as (source, _, entries, _):
                self.read_iso_files(source, entries, verify_all=True)
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
        # Core files are verified before a missing/outdated private preview is repaired.
        self.prepare_previews(current)
        if optional:
            self.hd_verified = self.hd_status(current, full=True)
            if safe_path(current, language_pack.DIRECTORY).exists() and not self.spanish_valid(current):
                self.hd_warning = "Spanish needs a supported PS2 ISO import. Import Spanish again or choose English; previous files are kept."
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

    def build_hd(self, stage, assets=None):
        builder = safe_path(self.package, "payload/runtime/darkwatch_hd_ui_builder.exe")
        command = [str(builder), str((assets or stage / "assets") / "packfile.pck"), str(stage / "hd-ui.pack"), str(self.package / "payload/hd_ui")]
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
        language = language_pack.selected(current)
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
                        raise SetupError("Shader preparation made no progress for too long. Close other applications and try again.")
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
                        if done > completed and done > 0:
                            deadline = time.monotonic() + SHADER_PREPARE_TIMEOUT
                        completed, total = done, count
                        self.notify("shader_prepare", "Preparing shaders — %d of %d" % (done, count),
                                    percent=100 * done / count, completed=done, total=count, language=language)
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
                self.notify("shader_ready", "Shaders are ready", percent=100, language=language)
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

    def update(self):
        """Replace prepared files in place; user data and optional packs stay put."""
        require_closed()
        self.verify_package()
        current = self.active()
        if not current:
            raise SetupError("Choose Use Existing Install or import your Xbox ISO once.")
        metadata = read_json(safe_path(current, "install.json"))
        if metadata.get("disc_sha256") != self.files["payload/supported-disc.json"]:
            raise SetupError("The installed disc revision does not match this update.")
        rebuild = metadata.get("content_revision") != character_content.CONTENT_REVISION
        direct = metadata.get("source_mode") == "iso"
        if direct:
            self.validate_iso_marker(current, metadata)
            with self.open_iso(metadata["iso_path"], metadata):
                pass
        recovery = safe_path(current, "source-recovery")
        if rebuild and not direct and not installed_source.has_recovery(recovery, self.originals()):
            raise SetupError("This older installation needs one final ISO import for the content update. Future updates will reuse its installed data; saves and settings are kept.")
        self.notify("progress", "Checking installed game data for update", percent=5)
        for item in self.assets:
            name = item["path"]
            if direct and name != "default.xbe" and name not in character_content.INSTALLED:
                continue  # Unmodified data stays in the authenticated ISO.
            if rebuild and name in character_content.INSTALLED:
                continue  # Restored originals are authenticated before conversion below.
            size, digest = character_content.INSTALLED.get(name, (item["size"], item["sha256"]))
            source = safe_path(current, "assets/" + name)
            if not source.is_file() or source.stat().st_size != size or self.digest(source) != digest:
                raise SetupError(f"Installed game data is damaged: {name}. Repair from your ISO; your saves are kept.")
        needed = 512 * 1024 * 1024 + sum(safe_path(self.package, name).stat().st_size for name in self.files if name.startswith("payload/runtime/"))
        if rebuild:
            needed += sum(item["size"] for item in self.assets if item["path"] in self.iso_preparation_names())
            needed += (sum(size for size, _ in character_content.INSTALLED.values()) +
                       max(size for size, _ in character_content.INSTALLED.values()))
        if shutil.disk_usage(current).free < needed:
            raise SetupError(f"Not enough free space for the update. Keep at least {needed / (1024 ** 3):.1f} GB free; no installed files were changed.")
        with tempfile.TemporaryDirectory(prefix=".update-", dir=current) as temporary:
            stage = Path(temporary)
            replacements = []
            assets = safe_path(current, "assets")
            if rebuild:
                assets = stage / "assets"
                self.notify("progress", "Preparing updated game resources", percent=10)
                if direct:
                    with self.open_iso(metadata["iso_path"], metadata) as (source, _, entries, _):
                        self.read_iso_files(source, entries, assets, self.iso_preparation_names())
                else:
                    installed_source.restore(current / "assets", recovery, assets, self.originals(), self.check_cancel)
                    for item in self.assets:
                        # Conversion does not read movies or the other untouched archives.
                        if item["path"] in self.iso_preparation_names() - character_content.INSTALLED.keys():
                            self.copy_file(safe_path(current, "assets/" + item["path"]), safe_path(assets, item["path"]))
                character_content.prepare(assets, self.package / "payload", self.check_cancel,
                                          lambda message: self.notify("progress", message, percent=40))
                for name, (size, digest) in character_content.INSTALLED.items():
                    path = safe_path(assets, name)
                    if path.stat().st_size != size or self.digest(path) != digest:
                        raise SetupError("Updated character data failed verification; no installed files were changed.")
                    replacements.append("assets/" + name)
                metadata["character_preview"] = character_preview.prepare(assets, stage / character_preview.NAME, self.check_cancel)
                replacements.append(character_preview.NAME)
            for name, digest in self.files.items():
                if not name.startswith("payload/runtime/") or name.endswith("/darkwatch_hd_ui_builder.exe"):
                    continue
                relative = name.removeprefix("payload/runtime/")
                existing = safe_path(current, relative)
                if existing.is_file() and self.digest(existing) == digest:
                    continue
                destination = safe_path(stage, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                self.copy_file(safe_path(self.package, name), destination)
                if self.digest(destination) != digest:
                    raise SetupError("Runtime changed during update; no installed files were changed.")
                replacements.append(relative)
            artwork = safe_path(current, "hd-ui.pack")
            hd = metadata.get("hd_ui", {})
            if (rebuild or metadata.get("artwork_sha256") != self.artwork_sha256 or not artwork.is_file()
                    or artwork.stat().st_size != hd.get("size") or self.digest(artwork) != hd.get("sha256")):
                self.notify("progress", "Updating HD interface", percent=90)
                self.build_hd(stage, assets)
                artwork = stage / "hd-ui.pack"
                metadata["hd_ui"] = dict(size=artwork.stat().st_size, sha256=self.digest(artwork))
                replacements.append("hd-ui.pack")
            self.check_cancel()
            require_closed()
            self.notify("progress", "Applying update; saves and add-ons stay in place", percent=98)
            # Each file replaces atomically; the receipt commits last. If interrupted,
            # the old receipt requires retrying the update before Play can proceed.
            for relative in replacements:
                destination = safe_path(current, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(safe_path(stage, relative), destination)
            metadata.update(content_revision=character_content.CONTENT_REVISION,
                            package_sha256=self.package_sha256, artwork_sha256=self.artwork_sha256)
            write_json(current / "install.json", metadata)
        result = self.status()
        result["message"] = ("Game updated. Your ISO, prepared resources, saves, settings and add-ons were reused."
                             if direct else "Game updated. Your installed data, saves, settings and add-ons were reused; no ISO was needed.")
        return result

    def use_drop_in_iso(self, directory):
        """Steam/Proton first launch can prepare a single user-provided image."""
        if self.active():
            return False  # Never replace an existing or repairable installation.
        directory = Path(directory)
        candidates = [path for path in directory.iterdir()
                      if path.is_file() and path.suffix.lower() in (".iso", ".xiso")] if directory.is_dir() else []
        if not candidates:
            return False
        if len(candidates) != 1:
            raise SetupError("Several disc images are in assets. Choose one with Select Game or --use-iso FILE; no installation was changed.")
        self.notify("progress", "Found your disc in assets. Preparing direct ISO playback; keep the ISO in place.",
                    percent=0, automatic_setup=True)
        self.use_iso(candidates[0])
        return True

    def use_iso(self, iso):
        """Select a read-only ISO, or repair its location without preparing a second install."""
        iso = Path(iso).absolute()
        require_closed()
        self.verify_package()
        current = self.active()
        metadata = read_json(current / "install.json") if current else {}
        if metadata.get("source_mode") != "iso":
            return self.import_iso(iso, direct=True)
        # Reconnection authenticates the new source before changing either source record.
        with self.open_iso(iso) as (source, offset, entries, record):
            self.read_iso_files(source, entries, verify_all=True)
        files = (self.installed_files(current) if metadata.get("content_revision") == character_content.CONTENT_REVISION else
                 [("assets/" + item["path"], item["size"], item["sha256"]) for item in self.assets if item["path"] == "default.xbe"])
        for relative, size, digest in files:
            if not relative.startswith("assets/"):
                continue  # Package files are replaced by update() if required.
            path = safe_path(current, relative)
            if not path.is_file() or path.stat().st_size != size or self.digest(path) != digest:
                return self.import_iso(iso, direct=True)
        self.check_cancel()
        require_closed()
        self.write_iso_marker(current, record)
        metadata.update(record, partition_offset=offset)
        write_json(current / "install.json", metadata)
        if self.needs_update(current):
            return self.update()
        return self.status()

    def import_iso(self, iso, direct=False):
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
                # Streamed archive conversion retains its input until the next
                # output is verified, in addition to the final staged files.
                names = self.iso_preparation_names() if direct else {item["path"] for item in self.assets}
                needed = (sum(f["size"] for f in self.assets if f["path"] in names) +
                          sum(size for size, _ in character_content.INSTALLED.values()) +
                          max(size for size, _ in character_content.INSTALLED.values()) + 512 * 1024 * 1024)
                if previous and safe_path(previous, gameplay_hd.DIRECTORY).exists():
                    needed += self.hd_catalog.total
                if previous and safe_path(previous, language_pack.DIRECTORY).exists():
                    needed += sum(row["size"] for row in self.ps2_language_catalog.files.values()) if self.ps2_language_catalog else 0
                if shutil.disk_usage(self.root).free < needed:
                    raise SetupError(f"Not enough free space. Keep at least {needed / (1024 ** 3):.1f} GB free for installation, plus space for your saved data and cache.")
                self.read_iso_files(source, entries, stage / "assets", names, verify_all=True)
                final_stat = os.fstat(source.fileno())
                if (original_stat.st_size, original_stat.st_mtime_ns) != (final_stat.st_size, final_stat.st_mtime_ns):
                    raise SetupError("The source ISO changed during import. Please retry with an unchanged file.")
            source_record = dict(source_mode="extracted")
            if direct:
                source_record = dict(source_mode="iso", iso_path=str(iso),
                                     iso_size=original_stat.st_size, iso_mtime_ns=original_stat.st_mtime_ns)
            else:
                installed_source.capture(stage / "assets", stage / "source-recovery", self.originals(), self.check_cancel)
            character_content.prepare(stage / "assets", self.package / "payload", self.check_cancel,
                                      lambda message: self.notify("progress", message, percent=86))
            if direct:
                for name in names - {"default.xbe", *character_content.INSTALLED}:
                    safe_path(stage, "assets/" + name).unlink(missing_ok=True)
                self.write_iso_marker(stage, source_record)
            for relative, digest in self.files.items():
                if relative.startswith("payload/runtime/") and not relative.endswith("/darkwatch_hd_ui_builder.exe"):
                    target = safe_path(stage, relative.removeprefix("payload/runtime/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(safe_path(self.package, relative), target)
                    if self.digest(target) != digest:
                        raise SetupError("Runtime file changed during installation.")
            self.notify("progress", "Preparing HD artwork from your disc", percent=87)
            self.build_hd(stage)
            self.notify("progress", "Preparing character previews from your disc", percent=88)
            preview = character_preview.prepare(stage / "assets", stage / character_preview.NAME, self.check_cancel)
            self.check_cancel()
            require_closed()
            self.notify("progress", "Preserving saves, controls, and shader cache", percent=97)
            with self.user_data_source(previous) as user_data:
                self.copy_user_data(user_data, stage)
                if self.ps2_language_catalog:
                    try:
                        preserved = self.ps2_language_catalog.preserve(user_data, stage, self.check_cancel, self.copy_file)
                        if not preserved and user_data and safe_path(user_data, language_pack.DIRECTORY).exists():
                            self.notify("progress", "Previous Spanish files were kept in the old installation. Import your PS2 ISO or choose English.", percent=97)
                    except Cancelled:
                        raise
                    except (OSError, ValueError):
                        gameplay_hd.remove_tree(stage, language_pack.DIRECTORY)
                        self.notify("progress", "Previous Spanish files were kept in the old installation. Import your PS2 ISO or choose English.", percent=97)
                try:
                    self.hd_catalog.preserve(user_data, stage, self.check_cancel, self.notify, self.copy_file)
                except Cancelled:
                    raise
                except gameplay_hd.PackError as error:
                    # Optional damaged artwork must not prevent repairing the base game.
                    gameplay_hd.remove_tree(stage, gameplay_hd.DIRECTORY)
                    self.notify("progress", str(error) + " The previous copy was kept; reinstall the optional pack afterward.", percent=97)
                self.prepare_shaders(stage)
                if direct:
                    with self.open_iso(iso, source_record):
                        pass
                hd = stage / "hd-ui.pack"
                write_json(stage / "install.json", dict(schema_version=1, disc_sha256=self.files["payload/supported-disc.json"],
                           **source_record,
                           content_revision=character_content.CONTENT_REVISION, partition_offset=offset,
                           package_sha256=self.package_sha256, artwork_sha256=self.artwork_sha256,
                           character_preview=preview,
                           hd_ui=dict(size=hd.stat().st_size, sha256=self.digest(hd))))
                self.check_cancel()
                require_closed()
                write_json(self.root / "active.json", dict(version=version))
                committed = True
            return dict(installed=True, ready=True, update_available=False, install_dir=str(stage), hd_textures_installed=self.hd_status(stage),
                        **self.source_status(stage), **self.language_status(stage),
                        message=("Darkwatch is ready. Keep the selected ISO available; only prepared resources were copied."
                                 if direct else "Darkwatch: Darker Edition is installed. Your original ISO was not changed."))
        finally:
            if not committed:
                checked = safe_path(versions, version)
                if checked.exists():
                    shutil.rmtree(checked)

    def play(self):
        require_closed()
        current = self.active()
        if current and self.needs_update(current):
            self.update()
        current = self.verify(optional=False)
        if language_pack.selected(current) == "es":
            if not self.spanish_valid(current):
                raise SetupError("Spanish needs a supported PS2 ISO import. Import Spanish again or choose English; previous files are kept.")
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
        return dict(installed=True, ready=True, update_available=False, pid=process.pid, **self.language_status(current),
                    **self.source_status(current),
                    message="Darkwatch: Darker Edition started.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--cancel-file", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true")
    action.add_argument("--check-updates", action="store_true")
    action.add_argument("--download-update", action="store_true")
    parser.add_argument("--launcher-pid", type=int)
    parser.add_argument("--platform", choices=("windows", "linux"), default="windows")
    parser.add_argument("--auto-iso-folder", type=Path, help="on first Play, prepare one ISO from this folder")
    action.add_argument("--import-iso", type=Path)
    action.add_argument("--use-iso", type=Path)
    action.add_argument("--use-installation", type=Path)
    action.add_argument("--update", action="store_true")
    action.add_argument("--install-hd-textures", type=Path)
    action.add_argument("--install-spanish", type=Path)
    action.add_argument("--set-language", choices=("en", "es"))
    action.add_argument("--verify", action="store_true")
    action.add_argument("--play", action="store_true")
    args = parser.parse_args(argv)
    if args.auto_iso_folder and not args.play:
        parser.error("--auto-iso-folder is only available with --play.")
    try:
        if args.check_updates:
            import release_check
            emit("release_check", **release_check.check(PACKAGE_VERSION, args.platform))
            return 0
        setup = Setup(args.package, args.install_root, args.cancel_file, ignore_location=bool(args.use_installation))
        if args.download_update:
            if os.name != 'nt' or args.platform != 'windows' or not args.launcher_pid or args.launcher_pid <= 0:
                raise SetupError('Start the update using the launcher Update button.')
            import release_update
            with exclusive(setup.root), release_update.exclusive(setup.package / '.release-update.lock'):
                require_closed()
                result = release_update.prepare(setup.package, PACKAGE_VERSION, 'windows', emit, setup.check_cancel)
                try:
                    setup.check_cancel()
                    release_update.launch_worker(setup.package, setup.root, args.launcher_pid)
                except Exception:
                    release_update.recover(setup.package)
                    raise
            emit('release_ready', 'Download verified. Restarting the launcher to apply the update.',
                 version=result['version'], percent=100)
            return 0
        if args.status:
            emit("status", **setup.status())
            import release_update
            release_update.cleanup(setup.package.parent if setup.package.name == 'windows' else setup.package)
            return 0
        if args.use_installation:
            result = setup.use_installation(args.use_installation)
            emit("result", **result, percent=100)
            return 0
        with exclusive(setup.root):
            if args.import_iso:
                result = setup.import_iso(args.import_iso)
            elif args.use_iso:
                result = setup.use_iso(args.use_iso)
            elif args.update:
                result = setup.update()
            elif args.install_hd_textures:
                result = setup.install_hd_textures(args.install_hd_textures)
            elif args.install_spanish:
                result = setup.install_spanish(args.install_spanish)
            elif args.set_language:
                result = setup.set_language(args.set_language)
            elif args.play:
                if args.auto_iso_folder:
                    setup.use_drop_in_iso(args.auto_iso_folder)
                result = setup.play()
            else:
                current = setup.verify()
                result = dict(installed=True, ready=True, update_available=False, install_dir=str(current), hd_textures_installed=setup.hd_verified,
                              **setup.language_status(current),
                              message=setup.hd_warning or "All installed files verified.")
            current = setup.active()
            if current:
                result.update(setup.source_status(current))
            emit("result", **result, percent=100)
        return 0
    except (SetupError, intake.IntakeError, OSError, ValueError, KeyError, TypeError) as error:
        state = dict(ready=False)
        if (args.install_hd_textures or args.install_spanish or args.set_language or args.download_update) and "setup" in locals():
            try:
                # Optional artwork failure must not disable an otherwise playable install.
                setup.cancel_file = None
                state = setup.status()
                state.pop("message", None)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        emit("error", str(error), **state, cancelled=isinstance(error, Cancelled))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
