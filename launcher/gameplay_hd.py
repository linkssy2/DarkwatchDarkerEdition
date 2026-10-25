"""Validate and install the separately downloaded gameplay artwork pack.

The launcher supplies the trusted catalog; a download cannot choose its own files.
"""
from __future__ import annotations

import hashlib
import io
import bisect
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import uuid
import zipfile
import zlib

import intake

CHUNK = 8 * 1024 * 1024
DIRECTORY = "gameplay-hd"
RECEIPT = "pack.json"
PART_SIZE = 1024 * 1024 * 1024


class PackError(ValueError):
    pass


def checked(root, name):
    path = intake.safe_destination(root, name)
    if path.exists() and path.is_file() and path.stat().st_nlink != 1:
        raise PackError("HD texture paths must not use links.")
    return path


def remove_tree(root, name):
    path = checked(root, name)
    if path.exists():
        for folder, dirs, files in os.walk(path, followlinks=False):
            for entry in dirs + files:
                checked(root, (Path(folder) / entry).relative_to(root).as_posix())
        shutil.rmtree(path)


class Archive(io.RawIOBase):
    """Seek over release ZIP parts without creating a second multi-GB archive."""
    def __init__(self, path, limit):
        self.parts, self.offsets, self.length, self.position = [], [], 0, 0
        path = Path(path).absolute()
        match = re.fullmatch(r"(.+\.zip)\.(\d{3})", path.name, re.IGNORECASE)
        if match:
            base, selected = match.groups()
            if selected != "001":
                raise PackError("Choose the first HD texture download part (.zip.001). Keep every part in the same folder.")
            members = {}
            for candidate in path.parent.iterdir():
                part = re.fullmatch(re.escape(base) + r"\.(\d{3})", candidate.name, re.IGNORECASE)
                if part:
                    index = int(part.group(1))
                    if index in members or not 1 <= index <= 32:
                        raise PackError("HD texture download has duplicate or unsupported parts.")
                    members[index] = candidate
            if not members or sorted(members) != list(range(1, len(members) + 1)):
                raise PackError("HD texture download parts are missing. Download all parts into the same folder and select .zip.001.")
            paths = [members[i] for i in sorted(members)]
        else:
            paths = [path]
        try:
            for index, member in enumerate(paths):
                if any(ord(c) < 32 or c in '/\\:' for c in member.name) or member.name[-1:] in (".", " "):
                    raise PackError("Invalid HD texture download filename.")
                member = checked(member.parent, member.name)
                if not member.is_file():
                    raise PackError("HD texture download is missing or is not a regular file.")
                source = member.open("rb")
                self.parts.append(source)
                size = os.fstat(source.fileno()).st_size
                if match and (not 0 < size <= PART_SIZE or (index < len(paths) - 1 and size != PART_SIZE)):
                    raise PackError("HD texture download parts are incomplete. Download all parts again and select .zip.001.")
                self.offsets.append(self.length)
                self.length += size
                if self.length > limit:
                    raise PackError("This is not the matching HD texture download.")
        except BaseException:
            self.close()
            raise

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (0 if whence == 0 else self.position if whence == 1 else self.length if whence == 2 else -1)
        if whence not in (0, 1, 2) or position < 0:
            raise OSError("Invalid HD texture archive seek.")
        self.position = position
        return position

    def read(self, size=-1):
        size = max(0, self.length - self.position) if size < 0 else min(size, max(0, self.length - self.position))
        # zipfile reads its directory in one allocation; malformed ZIPs cannot request GBs of metadata.
        if size > 2 * CHUNK:
            raise PackError("HD texture archive metadata is too large.")
        result = bytearray()
        while size:
            index = bisect.bisect_right(self.offsets, self.position) - 1
            end = self.offsets[index + 1] if index + 1 < len(self.offsets) else self.length
            source = self.parts[index]
            source.seek(self.position - self.offsets[index])
            block = source.read(min(size, end - self.position))
            if not block:
                raise PackError("HD texture download is truncated. Check that every part finished downloading.")
            result.extend(block)
            self.position += len(block)
            size -= len(block)
        return bytes(result)

    def close(self):
        for source in self.parts:
            source.close()
        super().close()


class Catalog:
    def __init__(self, content, *, previous_limit=2):
        if len(content) > 2 * 1024 * 1024:
            raise PackError("HD texture catalog is too large.")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise PackError("Duplicate HD texture catalog field.")
                result[key] = value
            return result
        data = json.loads(content, object_pairs_hook=unique)
        if (not isinstance(data, dict) or data.get("schema_version") != 1 or
                data.get("kind") != "darkwatch-gameplay-hd" or data.get("version") != "1" or
                not re.fullmatch("[0-9a-f]{64}", data.get("texture_catalog_sha256", "")) or
                not isinstance(data.get("files"), list) or not 0 < len(data["files"]) <= 5000):
            raise PackError("Unsupported HD texture catalog.")
        self.content, self.files = content, {}
        names = set()
        for item in data["files"]:
            if not isinstance(item, dict):
                raise PackError("Invalid HD texture catalog entry.")
            name, size, digest = item.get("path"), item.get("size"), item.get("sha256")
            if (not isinstance(name, str) or not re.fullmatch(r"gameplay-hd/[A-Za-z0-9_.-]+\.dwt", name) or
                    type(size) is not int or not 40 <= size <= 128 * 1024 * 1024 or
                    not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest)):
                raise PackError("Invalid HD texture catalog entry.")
            intake.safe_component(name.split("/")[1].encode("ascii"))
            if name.casefold() in names:
                raise PackError("Duplicate HD texture catalog path.")
            names.add(name.casefold())
            self.files[name] = (size, digest)
        self.total = sum(size for size, _ in self.files.values())
        if self.total > 32 * 1024 * 1024 * 1024:
            raise PackError("HD texture catalog exceeds its size limit.")
        self.previous = None
        if "previous_catalog" in data:
            previous = data["previous_catalog"]
            # Keep exact published receipts, including their older compatibility
            # receipt. The two released generations bound parsing and admission.
            if previous_limit <= 0 or not isinstance(previous, str):
                raise PackError("Unsupported previous HD texture catalog.")
            self.previous = Catalog(previous.encode("utf-8"), previous_limit=previous_limit - 1)
            if (len(self.previous.files) >= len(self.files) or
                    any(self.files.get(name) != record for name, record in self.previous.files.items())):
                raise PackError("Previous HD textures differ from the current catalog.")

    def generations(self):
        catalog = self
        while catalog is not None:
            yield catalog
            catalog = catalog.previous

    def matching(self, content):
        for catalog in self.generations():
            if catalog.content == content:
                return catalog
        raise PackError("HD texture pack is incomplete or incompatible. Install the matching texture download again.")

    def receipt_sizes(self):
        return {len(catalog.content) for catalog in self.generations()}

    @staticmethod
    def header(data, length):
        if len(data) != 32 or data[:8] != b"DWGAME02":
            raise PackError("HD texture file has an unsupported header.")
        width, height, levels, native_bytes = struct.unpack_from("<4I", data, 8)
        if not (0 < width <= 8192 and 0 < height <= 8192 and 0 < levels <= 14 and native_bytes):
            raise PackError("HD texture dimensions are invalid.")
        expected = 40 + sum(max(width >> i, 1) * max(height >> i, 1) * 4 for i in range(levels))
        if length != expected:
            raise PackError("HD texture mip data is incomplete.")

    def validate(self, current, cancel, notify, full=False):
        folder = checked(current, DIRECTORY)
        if not folder.exists():
            return False
        receipt = checked(folder, RECEIPT)
        if not receipt.is_file() or receipt.stat().st_size not in self.receipt_sizes():
            raise PackError("HD texture pack is incomplete or incompatible. Install the matching texture download again.")
        selected = self.matching(receipt.read_bytes())
        if selected is not self:
            return selected.validate(current, cancel, notify, full)
        expected = {Path(name).name for name in self.files} | {RECEIPT}
        if {path.name for path in folder.iterdir()} != expected:
            raise PackError("HD texture pack contains missing or unexpected files. Install the texture download again.")
        done = 0
        for name, (size, digest) in self.files.items():
            cancel()
            path = checked(current, name)
            if not path.is_file() or path.stat().st_size != size:
                raise PackError("HD texture pack is damaged. Install the texture download again.")
            with path.open("rb") as source:
                header = source.read(32)
                self.header(header, size)
                if full:
                    result = hashlib.sha256(header)
                    while block := source.read(CHUNK):
                        cancel()
                        result.update(block)
                    if result.hexdigest() != digest:
                        raise PackError("HD texture pack is damaged. Install the texture download again.")
            done += size
            if full:
                notify("progress", "Verifying optional HD textures", percent=100 * done / self.total)
        return True

    def extract(self, archive, stage, cancel, notify):
        # Bound both declared expansion and actual reads by the shipped catalog.
        try:
            with Archive(archive, self.total * 1.01 + 4 * 1024 * 1024) as stream, zipfile.ZipFile(stream) as source:
                entries = source.infolist()
                receipts = [entry for entry in entries if entry.filename == RECEIPT]
                if len(receipts) != 1 or receipts[0].file_size not in self.receipt_sizes():
                    raise PackError("HD texture download has a missing or incompatible catalog.")
                selected = self.matching(source.read(receipts[0]))
                if selected is not self:
                    return selected.extract(archive, stage, cancel, notify)
                expected = {**self.files, RECEIPT: (len(self.content), hashlib.sha256(self.content).hexdigest())}
                if len(entries) != len(expected):
                    raise PackError("HD texture download has missing or unexpected files.")
                names = set()
                for entry in entries:
                    mode = entry.external_attr >> 16
                    if (entry.orig_filename != entry.filename or entry.filename not in expected or
                            entry.filename.casefold() in names or entry.is_dir() or
                            stat.S_IFMT(mode) not in (0, stat.S_IFREG) or entry.external_attr & 0x410 or
                            entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or
                            entry.file_size != expected[entry.filename][0]):
                        raise PackError("HD texture download contains unsafe or incompatible entries.")
                    names.add(entry.filename.casefold())
                if source.read(RECEIPT) != self.content:
                    raise PackError("This HD texture download belongs to a different build.")
                done = 0
                for name, (size, digest) in self.files.items():
                    cancel()
                    target = checked(stage, Path(name).name)
                    result, remaining = hashlib.sha256(), size
                    with source.open(name) as original, target.open("xb") as output:
                        while remaining:
                            cancel()
                            block = original.read(min(CHUNK, remaining))
                            if not block:
                                raise PackError("HD texture download is truncated.")
                            output.write(block)
                            result.update(block)
                            remaining -= len(block)
                            done += len(block)
                            notify("progress", "Installing optional HD textures", percent=95 * done / self.total)
                        if original.read(1) or result.hexdigest() != digest:
                            raise PackError("HD texture download is damaged. Download a fresh copy.")
                    with target.open("rb") as original:
                        self.header(original.read(32), size)
                checked(stage, RECEIPT).write_bytes(self.content)
        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, EOFError, zlib.error) as error:
            raise PackError("HD texture download is not a valid complete ZIP. For a multipart download, keep all parts in the same folder and select .zip.001.") from error

    def install(self, archive, current, cancel, notify, require_closed):
        token = uuid.uuid4().hex
        stage_name, backup_name = ".gameplay-hd-stage-" + token, ".gameplay-hd-backup-" + token
        stage, backup, target = checked(current, stage_name), checked(current, backup_name), checked(current, DIRECTORY)
        if target.exists() and not target.is_dir():
            raise PackError("The HD texture destination is not a folder.")
        if shutil.disk_usage(current).free < self.total + 64 * 1024 * 1024:
            raise PackError("Not enough free space to install the HD texture pack and keep the previous copy safe.")
        stage.mkdir()
        moved_old, committed = False, False
        try:
            self.extract(Path(archive), stage, cancel, notify)
            cancel()
            require_closed()
            if target.exists():
                # Validate destinations before moving or recursively cleaning an old pack.
                for path in target.iterdir():
                    if not checked(target, path.name).is_file() or (path.name != RECEIPT and path.suffix != ".dwt"):
                        raise PackError("The HD texture folder contains unrelated files; keep them elsewhere before installing.")
                os.replace(target, backup)
                moved_old = True
            try:
                os.replace(stage, target)
                committed = True
            except OSError:
                if moved_old:
                    os.replace(backup, target)
                    moved_old = False
                raise
        finally:
            if stage.exists():
                remove_tree(current, stage_name)
            if committed and moved_old:
                remove_tree(current, backup_name)

    def preserve(self, previous, stage, cancel, notify, copy):
        if not previous:
            return False
        try:
            if not self.validate(previous, cancel, notify):
                return False
            selected = self.matching(checked(checked(previous, DIRECTORY), RECEIPT).read_bytes())
        except (OSError, intake.IntakeError) as error:
            raise PackError("The previous optional HD texture pack could not be verified.") from error
        if selected is not self:
            return selected.preserve(previous, stage, cancel, notify, copy)
        target = checked(stage, DIRECTORY)
        target.mkdir()
        for name in self.files:
            cancel()
            copy(checked(previous, name), checked(stage, name))
        checked(target, RECEIPT).write_bytes(self.content)
        self.validate(stage, cancel, notify, full=True)
        return True
