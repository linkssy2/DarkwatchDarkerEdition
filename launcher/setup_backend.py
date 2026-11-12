"""Own-disc setup; JSONL status/progress/result/error events are the WPF contract.

Import stages a new version, preserves saves, then atomically switches active.json.
Play reuses unchanged verified files before starting the release runtime. The separate
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
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid
import traceback

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
# Exact reviewed local campaign builds; arbitrary installation-provided hashes are never trusted.
CAMPAIGN_BUILDS = {'b96f88fd964f149c11915794a595f9597ab29a8209166d54d4f05a5cc2bf3c04': {'packfile.pck': (199254290, '7f520632e0f2ceac93b3d0cccdf91af8011907d399ae85dec01e2c3c6fe68a83'), 'LvlSingl.pck': (3012989507, '0afa41525e9983e6df7580b27caba1824f4a0c8a23a5030abc0422fa14e58f94'), 'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285')}, 'd5880fb87e6f12dab0faeb5f5a1b2b9f8fa53df304624ed7a17885df3688ad37': {'packfile.pck': (200704954, '656c752a29c0dfa52bfb557f911a40233ef53c13bdaa67b56c6b38ffbf3b38df'), 'LvlSingl.pck': (3045288515, '6553332771df115b726b9e2b7d3dba2f7a24ae59134f3cfdb41ca0f886eb1692'), 'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285')}, 'dcddfb265d8578e3dedb9651db05dd2681c192ec3cd8cbb40f666a24869749c4': {'packfile.pck': (200704954, 'a414e23dae485790f1aba7e36e63746c0f7cb6eb66a69ca0861db705d8146719'), 'LvlSingl.pck': (3045288515, 'a2724db84e595461b5ed4c2e35613fb925f2cdf6233692c9e1859e6f96cf6f9f'), 'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285')}, 'e918d35dc34a1e6718af978828dff8ea32efe5dcf7f2f556c073f33c8b5e26cf': {'packfile.pck': (200704954, '5204b0dce560336ba80cb65d6dfc4e73a0504f73d5742dc2c6e837c03f215fac'), 'LvlSingl.pck': (3045288515, '797f73cab89874e431ea94996b158b19afa77eb940e03c3266ab9079e2b07bfb'), 'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285')}, '5eefd4a5a7406b2d30b5ff0ddec8d31e8eaf2151d966a5e2b06c0481883cadbe': {'packfile.pck': (200704954, '02774c265a1f838adf99db7ee946b59695ac6d6638e86c4b3b6db3179e848907'), 'LvlSingl.pck': (3045288515, '7d81366ee928f4db9e328a47ce42b9057378656a71059f586e15d85591ea7631'), 'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285')}, '4a2be3fee76f967a76f98c5c3ce8bba48ba133f4130f0a230d4d2e7304180646': {'packfile.pck': (200442226, '3736a8837f9d36e83216aae940118a7944d19e81b9a30794f7799779fe6b9206'), 'LvlSingl.pck': (3031343683, '19bf1ec7de1dd65eaee13c98fef01aebb6c48fe496c7ec1214309fa3c6514ed6'), 'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285')}, 'ed8ca59ef3abb0c3cb5ecece02d15379d9ce9f594bf0692acb90a34a21d287cc': {'packfile.pck': (200442226, '02bef06ae69fb66e6358d16fef1eeb494060ad1da7f23b2e951c8c2392092067'), 'LvlSingl.pck': (3031343683, '6d93ed66a681d77987736a69cc53ac2df2dc9372104022243a492eb57a04d0e4'), 'audio.pck': (152395109, '33226641a88f2323465ad2fc2b9fd1642d8346a304f7ff38779688820775a285')}}

DISC_SOURCE = "disc-source.toml"
PACKAGE_VERSION = "0.7.9"
RELEASE_PROFILE = {"name": "release-candidate", "diagnostics": False, "strict_assets": True}
# Maximum time without a completed shader, not a limit on the whole preparation.
SHADER_PREPARE_TIMEOUT = 15 * 60
VERIFIED_FILES = ".verified-files.json"


def file_identity(source):
    """Bind a verified byte stream to the filesystem's identity and change clock."""
    value = os.fstat(source.fileno())
    change = value.st_ctime_ns
    if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or not value.st_ino or
            getattr(value, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        change = None
    elif os.name == "nt":
        # Windows st_ctime is creation time, so it cannot detect a same-size edit
        # with restored mtime. FileBasicInfo supplies the actual metadata clock.
        import msvcrt
        class BasicInfo(ctypes.Structure):
            _fields_ = [(name, ctypes.c_longlong) for name in
                        ("creation", "access", "write", "change")] + [("attributes", ctypes.c_ulong)]
        info = BasicInfo()
        try:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            query = kernel.GetFileInformationByHandleEx
            volume = kernel.GetVolumeInformationByHandleW
        except (AttributeError, OSError):
            return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, None]
        handle = msvcrt.get_osfhandle(source.fileno())
        query.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)
        query.restype = ctypes.c_int
        filesystem = ctypes.create_unicode_buffer(32)
        volume.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_void_p,
                           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong)
        volume.restype = ctypes.c_int
        # FAT/exFAT do not provide a reliable metadata change clock. Unknown
        # filesystems (including unsupported Wine calls) keep full verification.
        reliable = volume(handle, None, 0, None, None, None, filesystem, len(filesystem))
        change = (info.change if reliable and filesystem.value.upper() in ("NTFS", "REFS") and
                  query(handle, 0, ctypes.byref(info), ctypes.sizeof(info)) and info.change > 0 else None)
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, change]


def hash_stream(source, cancel):
    digest = hashlib.sha256()
    while chunk := source.read(CHUNK):
        cancel()
        digest.update(chunk)
    return digest.hexdigest()


def game_environment():
    # Neither preparation nor normal play inherits workstation-only diagnostics.
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith(("XBE_", "DARKWATCH_"))}


class SetupError(ValueError):
    pass


class Cancelled(SetupError):
    pass


def emit(event, message, **fields):
    line = json.dumps(dict(event=event, message=message, **fields))
    diagnostic(line)
    print(line, flush=True)


_diagnostic_path = None


def start_diagnostics(root, action):
    global _diagnostic_path
    _diagnostic_path = None
    try:
        if not safe_path(root, ".diagnostic-logging").is_file():
            return
        folder = safe_path(root, "logs")
        folder.mkdir(parents=True, exist_ok=True)
        prior = sorted(folder.glob("launcher-session-*.log"))
        for old in prior[:-29]:
            safe_path(root, "logs/" + old.name).unlink(missing_ok=True)
        _diagnostic_path = safe_path(root, "logs/launcher-session-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + str(os.getpid()) + ".log")
        diagnostic("Launcher version=" + PACKAGE_VERSION + " action=" + action + " Python=" + sys.version + " platform=" + sys.platform)
    except (OSError, ValueError):
        _diagnostic_path = None


def diagnostic(message):
    if _diagnostic_path is None:
        return
    try:
        if _diagnostic_path.exists() and _diagnostic_path.stat().st_size >= 8 * 1024 * 1024:
            return
        with _diagnostic_path.open("a", encoding="utf-8") as output:
            output.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + str(message) + "\n")
    except OSError:
        pass  # A diagnostic write failure must not prevent playing or repairing the game.


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
        self.verified_files = {}
        self.verified_iso = None
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
                     "payload/character_content.py", "payload/character_update.py", "payload/character-update.json.gz",
                     "payload/character_campaign.py", "payload/character_campaign_pose.py",
                     "payload/character_dropped_clips.py", "payload/character-campaign-angles.json",
                     "payload/character_animation.py", "payload/character_assets.py",
                     "payload/character_archive.py", "payload/character_repaint.py", "payload/character-catalog.json",
                     "payload/character_boss.py", "payload/character_boss_effects.py", "payload/character_spectral_hands.py",
                     "payload/character_hand_seams.py", "payload/character_secondary.py", "payload/character_preview.py",
                     "payload/character_roster.py", "payload/character_tala.py",
                     "payload/revolver_content.py", "payload/revolver_scripts.py", "payload/player_corpses.py", "payload/enemy_blood.py", "payload/character_cinematic.py",
                     "payload/third_person_animation.py", "payload/character_reload.py", "payload/character_weapon_pose.py",
                     "payload/character_weapon_hold.py", "payload/character_weapon_shoulder.py", "payload/character_starter_reload.py",
                     "payload/body_weapon_grips.inc",
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
        self.disc_language_catalogs = {}
        self.portuguese_catalog = None
        for language, label in language_pack.DISC_LANGUAGES.items():
            ps2_catalog = f"payload/ps2-{label.lower()}-catalog.json"
            if ps2_catalog in self.files:
                path = safe_path(self.package, ps2_catalog)
                if self.digest(path) != self.files[ps2_catalog]:
                    raise SetupError(f"PS2 {label} catalog is damaged. Extract a fresh launcher package.")
                catalog = language_pack.Catalog(path.read_bytes())
                if catalog.language != language:
                    raise SetupError(f"Invalid {label} catalog language.")
                self.disc_language_catalogs[language] = catalog
        self.ps2_language_catalog = self.disc_language_catalogs.get("es")
        portuguese_catalog = "payload/portuguese-catalog.json"
        if portuguese_catalog in self.files:
            path = safe_path(self.package, portuguese_catalog)
            if self.digest(path) != self.files[portuguese_catalog]:
                raise SetupError("Portuguese catalog is damaged. Extract a fresh launcher package.")
            self.portuguese_catalog = language_pack.Catalog(path.read_bytes())
            if self.portuguese_catalog.language != "pt-BR":
                raise SetupError("Invalid Portuguese catalog language.")

    def check_cancel(self):
        if self.cancel_file and self.cancel_file.exists():
            raise Cancelled("Cancelled. Your previous installation and saves were kept.")

    def digest(self, path, cached=False):
        key = str(path.absolute())
        with path.open("rb") as source:
            before = file_identity(source)
            record = self.verified_files.get(key, {}) if cached and before[-1] is not None else {}
            result = record.get("sha256") if record.get("identity") == before else None
            if not isinstance(result, str) or not re.fullmatch("[0-9a-f]{64}", result):
                result = hash_stream(source, self.check_cancel)
            if file_identity(source) != before:
                raise SetupError(f"File changed while verifying: {path.name}. Please retry.")
        self.check_cancel()
        self.verified_files[key] = dict(identity=before, sha256=result)
        return result

    def remember_verified(self, path, digest):
        """Record a just-authenticated transaction output without reading it twice."""
        with path.open("rb") as source:
            self.verified_files[str(path.absolute())] = dict(identity=file_identity(source), sha256=digest)

    def verification_binding(self, current):
        metadata = read_json(safe_path(current, "install.json"))
        return dict(install=str(current.absolute()), package_sha256=self.package_sha256,
                    disc_sha256=self.files["payload/supported-disc.json"],
                    content_revision=character_content.CONTENT_REVISION,
                    source={key: metadata.get(key) for key in
                            ("source_mode", "iso_path", "iso_size", "iso_mtime_ns", "campaign_feedback_sha256")})

    def load_verification(self, current, installed=False):
        self.verified_files = {}
        self.verified_iso = None
        try:
            receipt = read_json(safe_path(current, VERIFIED_FILES))
            binding = self.verification_binding(current)
            if installed:
                metadata = read_json(safe_path(current, "install.json"))
                binding.update(package_sha256=metadata.get("package_sha256"), content_revision=metadata.get("content_revision"))
            if (receipt.get("schema_version") != 1 or receipt.get("binding") != binding or
                    not isinstance(receipt.get("files"), dict) or len(receipt["files"]) > 4096):
                return
            # Keys are never opened from this receipt. Only independently selected
            # installed/catalog paths may look up their matching prior identity.
            self.verified_files = {key: value for key, value in receipt["files"].items() if isinstance(value, dict)}
            self.verified_iso = receipt.get("iso")
        except (OSError, ValueError, TypeError):
            pass  # Missing/stale cache means a full byte check, never acceptance.

    def save_verification(self, current):
        try:
            relative = [name for name, _, _ in self.installed_files(current)] + [character_preview.NAME]
            catalogs = [self.disc_catalog(code) for code in language_pack.DISC_LANGUAGES]
            catalogs.append(getattr(self, "portuguese_catalog", None))
            relative.extend(catalog.directory + "/" + name for catalog in catalogs if catalog for name in catalog.files)
            allowed = {str(safe_path(current, name).absolute()) for name in relative}
            files = {key: value for key, value in self.verified_files.items()
                     if key in allowed}
            write_json(safe_path(current, VERIFIED_FILES), dict(schema_version=1,
                       binding=self.verification_binding(current), files=files, iso=self.verified_iso))
        except (OSError, ValueError, TypeError):
            pass  # Read-only installs may still play after successful verification.

    def verify_iso(self, current, record, cached=False):
        self.validate_iso_marker(current, record)
        with self.open_iso(record["iso_path"], record) as (source, _, entries, _):
            identity = file_identity(source)
            receipt = dict(path=record["iso_path"], identity=identity,
                           disc_sha256=self.files["payload/supported-disc.json"])
            if not cached or identity[-1] is None or self.verified_iso != receipt:
                self.read_iso_files(source, entries, verify_all=True)
            if file_identity(source) != identity:
                raise SetupError("The source ISO changed while verifying. Retry with an unchanged file.")
            self.verified_iso = receipt

    def active(self, root=None):
        root = self.root if root is None else root
        pointer = safe_path(root, "active.json")
        if not pointer.exists():
            versions = safe_path(root, "versions")
            if versions.is_dir() and any(re.fullmatch("[0-9a-f]{32}", path.name) and
                                         safe_path(root, "versions/" + path.name + "/install.json").exists()
                                         for path in versions.iterdir()):
                raise SetupError("Existing game folders were found, but the active installation record is missing. Choose Use Existing Install and select the folder inside GameData/versions that you want to keep using. No files were changed.")
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

    def content_files(self, metadata):
        variant = metadata.get("campaign_feedback_sha256")
        if variant is None:
            return character_content.INSTALLED
        if not isinstance(variant, str) or variant not in CAMPAIGN_BUILDS:
            raise SetupError("This campaign build is not recognized by this launcher. Keep the existing installation.")
        return CAMPAIGN_BUILDS[variant]

    def installed_files(self, current):
        metadata = read_json(safe_path(current, "install.json"))
        if metadata.get("disc_sha256") != self.files["payload/supported-disc.json"]:
            raise SetupError("Installed disc version differs. Import the supported ISO again.")
        if metadata.get("content_revision") != character_content.CONTENT_REVISION:
            raise SetupError("This installation needs the character content update. Choose Update Game in the launcher.")
        content = self.content_files(metadata)
        files = [("assets/" + f["path"], *content.get(f["path"], (f["size"], f["sha256"])))
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
            if target is not None and item["path"] in names:
                self.remember_verified(safe_path(target, item["path"]), item["sha256"])

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
        explicit_version = folder.parent.name == "versions" and re.fullmatch("[0-9a-f]{32}", folder.name)
        selected = (folder.parent.parent if explicit_version else
                    next((path for path in candidates if safe_path(path, "active.json").is_file()), None))
        if selected is None:
            raise SetupError("Choose the previous Darkwatch folder or its GameData folder.")
        if selected != self.local_root and safe_path(selected, "installation-location.json").exists():
            raise SetupError("Choose the original GameData folder, not another linked launcher.")
        with ExitStack() as locks:
            locks.enter_context(exclusive(self.local_root))
            if selected != self.local_root:
                locks.enter_context(exclusive(selected))
            current = safe_path(selected, "versions/" + folder.name) if explicit_version else self.active(selected)
            metadata = read_json(safe_path(current, "install.json"))
            if metadata.get("disc_sha256") != self.files["payload/supported-disc.json"]:
                raise SetupError("The selected installation uses a different disc revision.")
            if not safe_path(current, "assets/default.xbe").is_file():
                raise SetupError("The selected installation is incomplete. Keep its saves and repair it from your disc.")
            self.check_cancel()
            self.local_root.mkdir(parents=True, exist_ok=True)
            if explicit_version:
                write_json(safe_path(selected, "active.json"), dict(version=current.name))
            if selected == self.local_root:
                safe_path(self.local_root, "installation-location.json").unlink(missing_ok=True)
            else:
                write_json(self.local_root / "installation-location.json", dict(root=str(selected)))
        self.root = selected
        return self.status()

    def status(self):
        return dict(self.installation_status(), skip_intro=self.skip_intro(), diagnostic_logging=self.diagnostic_logging(), diagnostics_dir=str(self.local_root / "logs"))

    def skip_intro(self):
        return safe_path(self.local_root, ".skip-intro").is_file()

    def set_skip_intro(self, value):
        if value not in ("on", "off"):
            raise SetupError("Choose skip intro on or off.")
        self.local_root.mkdir(parents=True, exist_ok=True)
        path = safe_path(self.local_root, ".skip-intro")
        if value == "on":
            path.touch()
        else:
            path.unlink(missing_ok=True)
        return dict(self.status(), message="Skip intro applies to the next game session.")

    def diagnostic_logging(self):
        return safe_path(self.local_root, ".diagnostic-logging").is_file()

    def set_diagnostics(self, value):
        if value not in ("on", "off"):
            raise SetupError("Choose diagnostic logging on or off.")
        self.local_root.mkdir(parents=True, exist_ok=True)
        path = safe_path(self.local_root, ".diagnostic-logging")
        if value == "on":
            path.touch()
        else:
            path.unlink(missing_ok=True)
        return dict(self.status(), message="Diagnostic logging applies to the next game session. Logs are saved in the game's logs folder.")

    def installation_status(self):
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
                    message=self.hd_warning or "Ready to play. Use Verify Files for a full check.", install_dir=str(current),
                    **source_fields, **self.language_status(current))

    def language_status(self, current):
        installed = {}
        for language, label in language_pack.DISC_LANGUAGES.items():
            try:
                catalog = self.disc_catalog(language)
                installed[label.lower() + "_installed"] = bool(catalog and catalog.validate(current, self.check_cancel, full=False))
            except Cancelled:
                raise
            except (OSError, ValueError):
                installed[label.lower() + "_installed"] = False
        available = installed["spanish_installed"]
        try:
            catalog = getattr(self, "portuguese_catalog", None)
            portuguese = bool(catalog and catalog.validate(current, self.check_cancel, full=False))
        except Cancelled:
            raise
        except (OSError, ValueError):
            portuguese = False
        return dict(language=language_pack.selected(current), **installed,
                    spanish_audio_installed=available, portuguese_installed=portuguese)

    def prepare_previews(self, current, cached=False):
        """Upgrade the local menu cache without requiring another ISO import."""
        metadata = read_json(safe_path(current, "install.json"))
        record = metadata.get("character_preview", {})
        path = safe_path(current, character_preview.NAME)
        if (isinstance(record, dict) and record.get("version") == character_preview.VERSION and
                isinstance(record.get("size"), int) and 16 < record["size"] <= character_preview.MAX_BYTES and
                isinstance(record.get("sha256"), str) and re.fullmatch("[0-9a-f]{64}", record["sha256"]) and
                path.is_file() and path.stat().st_size == record["size"] and self.digest(path, cached=cached) == record["sha256"]):
            return
        require_closed()
        self.notify("progress", "Preparing character previews from your disc", percent=98, preparing=True)
        record = character_preview.prepare(safe_path(current, "assets"), path, self.check_cancel)
        self.remember_verified(path, record["sha256"])
        metadata["character_preview"] = record
        write_json(safe_path(current, "install.json"), metadata)

    def language_valid(self, current, catalog, cached=False):
        if not catalog or not catalog.validate(current, self.check_cancel, full=False):
            return False
        return all(self.digest(language_pack.checked(current, catalog.directory + "/" + name), cached=cached) == row["sha256"]
                   for name, row in catalog.files.items())

    def remember_language(self, current, catalog):
        for name, row in catalog.files.items():
            self.remember_verified(language_pack.checked(current, catalog.directory + "/" + name), row["sha256"])

    def spanish_valid(self, current, cached=False):
        return self.language_valid(current, self.ps2_language_catalog, cached)

    def disc_catalog(self, language):
        # Retain the Spanish attribute for older setup callers and fixtures.
        return self.ps2_language_catalog if language == "es" else getattr(self, "disc_language_catalogs", {}).get(language)

    def disc_language_valid(self, current, language, cached=False):
        catalog = self.disc_catalog(language)
        return self.language_valid(current, catalog, cached)

    def portuguese_valid(self, current, cached=False):
        catalog = getattr(self, "portuguese_catalog", None)
        return self.language_valid(current, catalog, cached)

    def install_portuguese(self):
        require_closed()
        current = self.active()
        if not current or not self.status()["ready"]:
            raise SetupError("Import or repair your Darkwatch ISO before installing Portuguese.")
        self.load_verification(current)
        self.verify_package()
        archive = "payload/portuguese-text.zip"
        catalog = getattr(self, "portuguese_catalog", None)
        if not catalog or archive not in self.files:
            raise SetupError("This launcher does not include the Portuguese translation. Update the launcher.")
        needed = 2 * sum(row["size"] for row in catalog.files.values()) + 16 * 1024 * 1024
        if shutil.disk_usage(self.root).free < needed:
            raise SetupError("Not enough free space to install the Portuguese translation.")
        catalog.install(safe_path(self.package, archive), current, self.check_cancel, self.notify, require_closed)
        self.remember_language(current, catalog)
        self.save_verification(current)
        return dict(installed=True, ready=True, update_available=False, install_dir=str(current),
                    **self.language_status(current),
                    message="Portuguese installed. Choose Português (Brasil) before starting. Spanish voices use the optional PS2 Spanish install.")

    def install_spanish(self, archive):
        return self.install_disc_language(archive)

    def install_disc_language(self, archive, language="es"):
        if language not in language_pack.DISC_LANGUAGES:
            raise SetupError("Choose a supported PS2 disc language.")
        label = language_pack.DISC_LANGUAGES[language]
        catalog = self.disc_catalog(language)
        require_closed()
        current = self.active()
        if not current or not self.status()["ready"]:
            raise SetupError(f"Import or repair your Darkwatch ISO before installing {label}.")
        self.load_verification(current)
        self.verify_package()
        archive = Path(archive).absolute()
        if archive.suffix.lower() != ".iso":
            raise SetupError(f"Choose your supported PS2 Darkwatch ISO to install {label}. Older language ZIPs are no longer supported.")
        if not catalog or "payload/ps2_spanish.py" not in self.files:
            raise SetupError(f"This launcher does not support {label} from a PS2 ISO. Update the launcher.")
        needed = 3 * sum(row["size"] for row in catalog.files.values()) + 128 * 1024 * 1024
        if shutil.disk_usage(self.root).free < needed:
            raise SetupError(f"Not enough free space. Keep at least {needed / (1024 ** 3):.1f} GB free to prepare {label}.")
        import ps2_spanish
        record = read_json(current / "install.json")
        if record.get("source_mode") == "iso":
            needed += sum(item["size"] for item in self.assets if item["path"] in ps2_spanish.XBOX)
            needed += character_content.INSTALLED["packfile.pck"][0]
            if shutil.disk_usage(self.root).free < needed:
                raise SetupError(f"Not enough free space. Keep at least {needed / (1024 ** 3):.1f} GB free to prepare {label}.")
        with tempfile.TemporaryDirectory(prefix=f".{label.lower()}-ps2-", dir=self.root) as temporary:
            prepared = Path(temporary) / (label + ".zip")
            assets = safe_path(current, "assets")
            if record.get("source_mode") == "iso":
                assets = Path(temporary) / "assets"
                with self.open_iso(record["iso_path"], record) as (source, _, entries, _):
                    self.read_iso_files(source, entries, assets, ps2_spanish.XBOX)
                self.copy_file(safe_path(current, "assets/packfile.pck"), assets / "packfile.pck")
            options = {} if language == "es" else {"language": language}
            ps2_spanish.prepare(archive, assets, prepared, self.check_cancel, self.notify, **options)
            catalog.install(prepared, current, self.check_cancel, self.notify, require_closed)
        self.remember_language(current, catalog)
        self.save_verification(current)
        return dict(installed=True, ready=True, update_available=False, install_dir=str(current), **self.language_status(current),
                    message=("Spanish installed. Choose Español before starting the game." if language == "es" else
                             f"{label} installed. Choose the language before starting the game."))

    def set_language(self, value):
        require_closed()
        current = self.active()
        if not current or not self.status()["ready"]:
            raise SetupError("Import or repair your Darkwatch ISO before choosing a language.")
        self.load_verification(current)
        if value in language_pack.DISC_LANGUAGES:
            self.verify_package()
            if not self.disc_language_valid(current, value):
                label = language_pack.DISC_LANGUAGES[value]
                raise SetupError(f"{label} needs a supported PS2 ISO import. Import {label} again or choose English; previous files are kept.")
        elif value == "pt-BR":
            self.verify_package()
            if not self.portuguese_valid(current):
                raise SetupError("Install the Portuguese translation first, or choose English; previous files are kept.")
        self.check_cancel()
        require_closed()
        language_pack.select(current, value)
        self.save_verification(current)
        return dict(installed=True, ready=True, update_available=False, install_dir=str(current), **self.language_status(current),
                    message=("Idioma: español. Se aplicará al iniciar el juego." if value == "es" else
                             "Idioma: português do Brasil. Será aplicado ao iniciar o jogo." if value == "pt-BR" else
                             f"Language: {language_pack.DISC_LANGUAGES[value]}. Applies on the next game launch." if value in language_pack.DISC_LANGUAGES else
                             "Language: English. Applies on the next game launch."))

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

    def verify(self, optional=True, cached=False):
        current = self.active()
        if not current:
            raise SetupError("Import your own Darkwatch ISO first.")
        if cached:
            self.load_verification(current)
        record = read_json(safe_path(current, "install.json"))
        if record.get("source_mode") == "iso":
            self.verify_iso(current, record, cached)
        files = self.installed_files(current)
        total = sum(size for _, size, _ in files)
        done = 0
        for relative, size, digest in files:
            self.check_cancel()
            self.notify("progress", f"Verifying {relative}", percent=int(done * 100 / max(1, total)))
            path = safe_path(current, relative)
            if not path.is_file() or path.stat().st_size != size or self.digest(path, cached=cached) != digest:
                raise SetupError(f"Missing or damaged installed file: {relative}. Import your ISO again to repair it.")
            done += size
        # Core files are verified before a missing/outdated private preview is repaired.
        self.prepare_previews(current, cached)
        if optional:
            self.hd_verified = self.hd_status(current, full=True)
            for language, label in language_pack.DISC_LANGUAGES.items():
                if safe_path(current, "language/" + language).exists() and not self.disc_language_valid(current, language):
                    self.hd_warning = f"{label} needs a supported PS2 ISO import. Import {label} again or choose English; previous files are kept."
            if safe_path(current, "language/pt-BR").exists() and not self.portuguese_valid(current):
                self.hd_warning = "The Portuguese translation needs repair. Install Portuguese again; previous files are kept."
        self.notify("progress", "Installed files verified", percent=100)
        self.save_verification(current)
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
                if _diagnostic_path is not None:
                    errors.seek(0)
                    diagnostic("Shader preparation exit=" + str(process.returncode) + " stderr=" + errors.read(1024 * 1024).decode("utf-8", errors="replace"))

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
        self.notify("progress", "Preparing game update", percent=0, preparing=True)
        self.verify_package()
        current = self.active()
        if not current:
            raise SetupError("Choose Use Existing Install or import your Xbox ISO once.")
        self.load_verification(current, installed=True)
        metadata = read_json(safe_path(current, "install.json"))
        if metadata.get("disc_sha256") != self.files["payload/supported-disc.json"]:
            raise SetupError("The installed disc revision does not match this update.")
        rebuild = metadata.get("content_revision") != character_content.CONTENT_REVISION
        content = self.content_files(metadata)
        if rebuild and metadata.get("campaign_feedback_sha256"):
            raise SetupError("Keep this campaign build while its content update is prepared. No installed files were changed.")
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
            size, digest = content.get(name, (item["size"], item["sha256"]))
            source = safe_path(current, "assets/" + name)
            if not source.is_file() or source.stat().st_size != size or self.digest(source, cached=True) != digest:
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
                                          lambda message: self.notify("progress", message, percent=40),
                                          previous_assets=safe_path(current, "assets"))
                for name, (size, digest) in character_content.INSTALLED.items():
                    path = safe_path(assets, name)
                    if path.stat().st_size != size or self.digest(path) != digest:
                        raise SetupError("Updated character data failed verification; no installed files were changed.")
                    replacements.append("assets/" + name)
                metadata["character_preview"] = character_preview.prepare(assets, stage / character_preview.NAME, self.check_cancel)
                self.remember_verified(stage / character_preview.NAME, metadata["character_preview"]["sha256"])
                replacements.append(character_preview.NAME)
            for name, digest in self.files.items():
                if not name.startswith("payload/runtime/") or name.endswith("/darkwatch_hd_ui_builder.exe"):
                    continue
                relative = name.removeprefix("payload/runtime/")
                existing = safe_path(current, relative)
                if existing.is_file() and self.digest(existing, cached=True) == digest:
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
                    or artwork.stat().st_size != hd.get("size") or self.digest(artwork, cached=True) != hd.get("sha256")):
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
                source = safe_path(stage, relative)
                verified = self.verified_files[str(source.absolute())]["sha256"]
                os.replace(source, destination)
                self.remember_verified(destination, verified)
            metadata.update(content_revision=character_content.CONTENT_REVISION,
                            package_sha256=self.package_sha256, artwork_sha256=self.artwork_sha256)
            write_json(current / "install.json", metadata)
        self.save_verification(current)
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
        self.notify("progress", "Preparing your game", percent=0, preparing=True)
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
                original_identity = file_identity(source)
                offset, entries = self.find_volume(source, original_stat.st_size)
                # Streamed archive conversion retains its input until the next
                # output is verified, in addition to the final staged files.
                names = self.iso_preparation_names() if direct else {item["path"] for item in self.assets}
                needed = (sum(f["size"] for f in self.assets if f["path"] in names) +
                          sum(size for size, _ in character_content.INSTALLED.values()) +
                          max(size for size, _ in character_content.INSTALLED.values()) + 512 * 1024 * 1024)
                if previous and safe_path(previous, gameplay_hd.DIRECTORY).exists():
                    needed += self.hd_catalog.total
                for language in language_pack.DISC_LANGUAGES:
                    catalog = self.disc_catalog(language)
                    if previous and catalog and safe_path(previous, catalog.directory).exists():
                        needed += sum(row["size"] for row in catalog.files.values())
                portuguese = getattr(self, "portuguese_catalog", None)
                if previous and portuguese and safe_path(previous, portuguese.directory).exists():
                    needed += sum(row["size"] for row in portuguese.files.values())
                if shutil.disk_usage(self.root).free < needed:
                    raise SetupError(f"Not enough free space. Keep at least {needed / (1024 ** 3):.1f} GB free for installation, plus space for your saved data and cache.")
                self.read_iso_files(source, entries, stage / "assets", names, verify_all=True)
                if original_identity != file_identity(source):
                    raise SetupError("The source ISO changed during import. Please retry with an unchanged file.")
            source_record = dict(source_mode="extracted")
            if direct:
                source_record = dict(source_mode="iso", iso_path=str(iso),
                                     iso_size=original_stat.st_size, iso_mtime_ns=original_stat.st_mtime_ns)
                self.verified_iso = dict(path=str(iso), identity=original_identity,
                                         disc_sha256=self.files["payload/supported-disc.json"])
            else:
                self.verified_iso = None
                installed_source.capture(stage / "assets", stage / "source-recovery", self.originals(), self.check_cancel)
            character_content.prepare(stage / "assets", self.package / "payload", self.check_cancel,
                                      lambda message: self.notify("progress", message, percent=86))
            for name, (_, digest) in character_content.INSTALLED.items():
                self.remember_verified(stage / "assets" / name, digest)
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
            self.remember_verified(stage / character_preview.NAME, preview["sha256"])
            self.check_cancel()
            require_closed()
            self.notify("progress", "Preserving saves, controls, and shader cache", percent=97)
            with self.user_data_source(previous) as user_data:
                self.copy_user_data(user_data, stage)
                for language, label in language_pack.DISC_LANGUAGES.items():
                    catalog = self.disc_catalog(language)
                    if not catalog:
                        continue
                    try:
                        preserved = catalog.preserve(user_data, stage, self.check_cancel, self.copy_file)
                        if preserved:
                            self.remember_language(stage, catalog)
                        if not preserved and user_data and safe_path(user_data, catalog.directory).exists():
                            self.notify("progress", f"Previous {label} files were kept in the old installation. Import your PS2 ISO or choose English.", percent=97)
                    except Cancelled:
                        raise
                    except (OSError, ValueError):
                        gameplay_hd.remove_tree(stage, catalog.directory)
                        self.notify("progress", f"Previous {label} files were kept in the old installation. Import your PS2 ISO or choose English.", percent=97)
                portuguese = getattr(self, "portuguese_catalog", None)
                if portuguese:
                    try:
                        preserved = portuguese.preserve(user_data, stage, self.check_cancel, self.copy_file)
                        if preserved:
                            self.remember_language(stage, portuguese)
                        if not preserved and user_data and safe_path(user_data, portuguese.directory).exists():
                            self.notify("progress", "Previous Portuguese files were kept in the old installation. Install Portuguese again or choose English.", percent=97)
                    except Cancelled:
                        raise
                    except (OSError, ValueError):
                        gameplay_hd.remove_tree(stage, portuguese.directory)
                        self.notify("progress", "Previous Portuguese files were kept in the old installation. Install Portuguese again or choose English.", percent=97)
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
                self.save_verification(stage)
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
        current = self.verify(optional=False, cached=True)
        language = language_pack.selected(current)
        if language in language_pack.DISC_LANGUAGES:
            if not self.disc_language_valid(current, language, cached=True):
                label = language_pack.DISC_LANGUAGES[language]
                raise SetupError(f"{label} needs a supported PS2 ISO import. Import {label} again or choose English; previous files are kept.")
        elif language == "pt-BR":
            if not self.portuguese_valid(current, cached=True):
                raise SetupError("The Portuguese translation needs repair. Install Portuguese again or choose English; previous files are kept.")
            if safe_path(current, "language/es/assets").exists() and not self.spanish_valid(current, cached=True):
                raise SetupError("The optional Spanish voices need repair. Import Spanish again or choose English; previous files are kept.")
        self.save_verification(current)
        self.prepare_shaders(current)
        self.check_cancel()
        require_closed()
        environment = game_environment()
        if self.skip_intro():
            environment["DARKWATCH_SKIP_INTRO"] = "1"
        if self.diagnostic_logging():
            environment["XBE_SESSION_LOG"] = "1"
            environment["XBE_SESSION_LOG_DIR"] = str(safe_path(self.local_root, "logs"))
            diagnostic("Game runtime=" + str(current / EXE) + " package_sha256=" + self.package_sha256)
        process = subprocess.Popen([str(current / EXE)], cwd=current,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=environment,
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
    action.add_argument("--set-diagnostics", choices=("on", "off"))
    action.add_argument("--set-skip-intro", choices=("on", "off"))
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
    action.add_argument("--install-french", type=Path)
    action.add_argument("--install-german", type=Path)
    action.add_argument("--install-italian", type=Path)
    action.add_argument("--install-portuguese", action="store_true")
    action.add_argument("--set-language", choices=("en", *language_pack.LANGUAGES))
    action.add_argument("--verify", action="store_true")
    action.add_argument("--play", action="store_true")
    args = parser.parse_args(argv)
    start_diagnostics(args.install_root, " ".join(sys.argv[1:] if argv is None else map(str, argv)))
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
            elif args.install_french or args.install_german or args.install_italian:
                language, archive = next((code, path) for code, path in
                                         (("fr", args.install_french), ("de", args.install_german), ("it", args.install_italian)) if path)
                result = setup.install_disc_language(archive, language)
            elif args.install_portuguese:
                result = setup.install_portuguese()
            elif args.set_language:
                result = setup.set_language(args.set_language)
            elif args.set_skip_intro:
                result = setup.set_skip_intro(args.set_skip_intro)
            elif args.set_diagnostics:
                result = setup.set_diagnostics(args.set_diagnostics)
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
            result["diagnostic_logging"] = setup.diagnostic_logging()
            result["diagnostics_dir"] = str(setup.local_root / "logs")
            if current:
                result.update(setup.source_status(current))
            emit("result", **result, percent=100)
        return 0
    except (SetupError, intake.IntakeError, OSError, ValueError, KeyError, TypeError) as error:
        diagnostic(traceback.format_exc())
        state = dict(ready=False)
        if (args.install_hd_textures or args.install_spanish or args.install_french or args.install_german or args.install_italian or args.install_portuguese or args.set_language or args.download_update) and "setup" in locals():
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
