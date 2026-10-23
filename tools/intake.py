#!/usr/bin/env python3
"""Read-only source intake for original Xbox XDVDFS images and XBE executables.

Examples:
  python tools/intake.py extract Darkwatch.iso --output game_files --analysis analysis
  python tools/intake.py xbe game_files/default.xbe --output analysis/default.xbe.json

Uses only Python's standard library. Existing extracted files are accepted only
when their size and SHA256 match the image. Source images are never modified.
Format references: https://github.com/antangelo/xdvdfs and
https://github.com/Cxbx-Reloaded/Cxbx-Reloaded/blob/master/src/common/xbe/Xbe.h
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from typing import BinaryIO

SECTOR_SIZE = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
CHUNK_SIZE = 8 * 1024 * 1024


class IntakeError(ValueError):
    """Invalid or unsafe source data, or an output that cannot be preserved."""


def checked_range(offset: int, size: int, limit: int, label: str) -> None:
    if offset < 0 or size < 0 or offset > limit or size > limit - offset:
        raise IntakeError(f"{label}: range {offset:#x}+{size:#x} exceeds {limit:#x}")


def safe_component(raw: bytes) -> str:
    # Preserve the source spelling; reject paths that Windows would reinterpret.
    name = raw.decode("ascii", errors="strict")
    if (not name or name in (".", "..") or name[-1] in ". "
            or any(ord(c) < 32 or c in '/\\:*?"<>|' for c in name)
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?", name)):
        raise IntakeError(f"Unsafe XDVDFS name: {raw!r}")
    return name


@dataclass(frozen=True)
class Entry:
    path: str
    sector: int
    size: int
    attributes: int
    image_offset: int

    @property
    def is_directory(self) -> bool:
        return bool(self.attributes & 0x10)


def parse_directory(data: bytes) -> list[tuple[str, int, int, int]]:
    """Parse reachable entries; child links are offsets in four-byte units."""
    if not data or data[:4] == b"\xff\xff\xff\xff":
        return []
    stack, visited, spans, entries = [0], set(), [], []
    names = set()
    while stack:
        offset = stack.pop()
        if offset in visited:
            raise IntakeError(f"Repeated/cyclic directory node at {offset:#x}")
        visited.add(offset)
        checked_range(offset, 14, len(data), "Directory node")
        left, right, sector, size, attributes, length = struct.unpack_from("<HHIIBB", data, offset)
        checked_range(offset + 14, length, len(data), "Directory name")
        try:
            name = safe_component(data[offset + 14:offset + 14 + length])
        except UnicodeDecodeError as exc:
            raise IntakeError("Non-ASCII source filename requires an explicit encoding policy") from exc
        if name.casefold() in names:
            raise IntakeError(f"Duplicate/case-colliding directory name: {name}")
        names.add(name.casefold())
        spans.append((offset, offset + 14 + length))
        entries.append((name, sector, size, attributes))
        stack.extend(link * 4 for link in (right, left) if link)
    spans.sort()
    for previous, current in zip(spans, spans[1:]):
        if previous[1] > current[0]:
            raise IntakeError("Overlapping directory nodes")
    return entries


class XDVDFS:
    def __init__(self, source: BinaryIO, size: int, partition_offset: int = 0):
        if partition_offset < 0:
            raise IntakeError("Partition offset must be nonnegative")
        self.source, self.size, self.partition_offset = source, size, partition_offset
        descriptor_offset = partition_offset + 0x10000
        descriptor = self.read_at(descriptor_offset, SECTOR_SIZE)
        if descriptor[:20] != MAGIC or descriptor[-20:] != MAGIC:
            raise IntakeError(f"No complete XDVDFS volume descriptor at {descriptor_offset:#x}; use --partition-offset for full-disc images")
        self.root_sector, self.root_size = struct.unpack_from("<II", descriptor, 20)

    def read_at(self, offset: int, size: int) -> bytes:
        checked_range(offset, size, self.size, "Image read")
        self.source.seek(offset)
        data = self.source.read(size)
        if len(data) != size:
            raise IntakeError("Source image was truncated while reading")
        return data

    def inventory(self) -> list[Entry]:
        pending = [("", self.root_sector, self.root_size, 0)]
        directory_extents, entries = set(), []
        while pending:
            parent, sector, size, depth = pending.pop()
            if depth > 128:
                raise IntakeError("Directory nesting exceeds 128 levels")
            if not size:
                continue
            # The on-disc child field addresses at most 256 KiB; cap allocation.
            if size > 64 * 1024 * 1024:
                raise IntakeError("Directory table exceeds 64 MiB safety limit")
            if sector in directory_extents:
                raise IntakeError("Repeated/cyclic directory extent")
            directory_extents.add(sector)
            offset = self.partition_offset + sector * SECTOR_SIZE
            table = self.read_at(offset, size)
            for name, child_sector, child_size, attributes in parse_directory(table):
                path = f"{parent}/{name}" if parent else name
                child_offset = self.partition_offset + child_sector * SECTOR_SIZE
                checked_range(child_offset, child_size, self.size, f"Entry {path}")
                entry = Entry(path, child_sector, child_size, attributes, child_offset)
                entries.append(entry)
                if entry.is_directory:
                    pending.append((path, child_sector, child_size, depth + 1))
        return sorted(entries, key=lambda e: e.path.casefold())


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def safe_destination(root: Path, relative: str) -> Path:
    root = root.absolute()
    candidate = root.joinpath(*relative.split("/"))
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise IntakeError(f"Destination escapes extraction directory: {candidate}")
    for ancestor in [candidate, *candidate.parents]:
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise IntakeError(f"Destination uses a symbolic link or junction: {ancestor}")
        # Wine's mapped drive ancestors are outside the managed output tree.
        if ancestor == root:
            break
    return candidate


def same_file(first: Path, second: Path) -> bool:
    return first.resolve() == second.resolve() or (first.exists() and second.exists() and first.samefile(second))


def protect_source(destination: Path, sources: list[Path]) -> None:
    for source in sources:
        if same_file(destination, source):
            raise IntakeError(f"Output would replace source data: {destination}")


def write_json(path: Path, value: object) -> None:
    path = safe_destination(path.absolute().parent, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_image(iso: Path, output: Path, analysis: Path, partition_offset: int = 0) -> dict:
    iso = iso.resolve()
    output = output.absolute()
    analysis = analysis.absolute()
    size = iso.stat().st_size
    with iso.open("rb") as source:
        volume = XDVDFS(source, size, partition_offset)
        entries = volume.inventory()  # Validate the entire tree before writes.
        for entry in entries:
            destination = safe_destination(output, entry.path)
            protect_source(destination, [iso])
        files = [entry for entry in entries if not entry.is_directory]
        protected = [iso] + [output / entry.path for entry in files]
        for report in ("disc_manifest.json", "files.sha256", "default.xbe.json"):
            protect_source(safe_destination(analysis, report), protected)
        print(f"Validated {len(files)} files and {len(entries) - len(files)} directories", flush=True)
        manifest_entries = []
        for entry in entries:
            destination = safe_destination(output, entry.path)
            if entry.is_directory:
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            existed = destination.exists()
            if existed and (not destination.is_file() or destination.stat().st_size != entry.size):
                raise IntakeError(f"Existing destination differs; preserve or move it before retrying: {destination}")
            source.seek(entry.image_offset)
            remaining, digest = entry.size, hashlib.sha256()
            sink = None if existed else destination.open("xb")
            try:
                while remaining:
                    chunk = source.read(min(remaining, CHUNK_SIZE))
                    if not chunk:
                        raise IntakeError(f"Truncated file data: {entry.path}")
                    digest.update(chunk)
                    if sink is not None:
                        sink.write(chunk)
                    remaining -= len(chunk)
            finally:
                if sink is not None:
                    sink.close()
            checksum = digest.hexdigest()
            if existed and digest_file(destination) != checksum:
                raise IntakeError(f"Existing destination checksum differs: {destination}")
            manifest_entries.append({**asdict(entry), "sha256": checksum})
            print(f"{'Verified' if existed else 'Extracted'} {entry.path} ({entry.size:,} bytes)", flush=True)
        print("Hashing source image...", flush=True)
    manifest = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"name": iso.name, "size": size, "sha256": digest_file(iso)},
        "filesystem": "XDVDFS", "partition_offset": partition_offset,
        "root_sector": volume.root_sector, "root_size": volume.root_size,
        "file_count": len(files), "total_file_bytes": sum(e.size for e in files),
        "directories": [e.path for e in entries if e.is_directory],
        "files": manifest_entries,
    }
    write_json(analysis / "disc_manifest.json", manifest)
    (analysis / "files.sha256").write_text("".join(f"{e['sha256']}  {e['path']}\n" for e in manifest_entries), encoding="utf-8")
    for entry in files:
        if entry.path.casefold() == "default.xbe":
            result = analyze_xbe(output / entry.path)
            write_json(analysis / "default.xbe.json", result)
            print(f"XBE: {result['certificate']['title_name']} ({result['certificate']['title_id']}), entry {result['entry_point']}", flush=True)
    return manifest


def analyze_xbe(path: Path) -> dict:
    data = path.read_bytes()
    checked_range(0, 0x178, len(data), "XBE header")
    if data[:4] != b"XBEH":
        raise IntakeError("Missing XBEH magic")
    def u32(offset: int) -> int:
        checked_range(offset, 4, len(data), "XBE field")
        return struct.unpack_from("<I", data, offset)[0]
    base, header_size, image_size = u32(0x104), u32(0x108), u32(0x10c)
    checked_range(0, header_size, len(data), "XBE headers")
    sections = []
    def address_offset(address: int, size: int = 1) -> int:
        if base <= address and address + size <= base + header_size:
            return address - base
        for section in sections:
            delta = address - section["virtual_address"]
            if 0 <= delta and delta + size <= section["raw_size"]:
                return section["raw_offset"] + delta
        raise IntakeError(f"Unmapped XBE address {address:#x} (+{size:#x})")
    def cstring(address: int, maximum: int = 512) -> str:
        result = bytearray()
        for index in range(maximum):
            value = data[address_offset(address + index)]
            if value == 0:
                return result.decode("ascii", errors="replace")
            result.append(value)
        raise IntakeError("Unterminated XBE string")
    count = u32(0x11c)
    if count > 4096:
        raise IntakeError("Unreasonable XBE section count")
    table = address_offset(u32(0x120), count * 56)
    for index in range(count):
        offset = table + index * 56
        flags, va, vs, raw, rs, name = struct.unpack_from("<6I", data, offset)
        checked_range(raw, rs, len(data), "XBE section data")
        checked_range(va, vs, 1 << 32, "XBE virtual section")
        sections.append({"index": index, "flags": flags, "virtual_address": va,
                         "virtual_size": vs, "raw_offset": raw, "raw_size": rs,
                         "name_address": name, "executable": bool(flags & 4),
                         "writable": bool(flags & 1), "sha256": hashlib.sha256(data[raw:raw + rs]).hexdigest()})
    for section in sections:
        section["name"] = cstring(section.pop("name_address"))
    candidates = []
    for kind, entry_key, kernel_key in (("retail", 0xa8fc57ab, 0x5b6d40b6),
                                       ("debug", 0x94859d4b, 0xefb1f152),
                                       ("chihiro", 0x40b5c16e, 0x2290059d)):
        entry, kernel = u32(0x128) ^ entry_key, u32(0x158) ^ kernel_key
        try:
            address_offset(entry)
            address_offset(kernel, 4)
        except IntakeError:
            continue
        if any(s["executable"] and s["virtual_address"] <= entry < s["virtual_address"] + s["virtual_size"] for s in sections):
            candidates.append((kind, entry, kernel))
    if len(candidates) != 1:
        raise IntakeError(f"XBE key family could not be uniquely decoded: {candidates}")
    kind, entry, kernel = candidates[0]
    imports = []
    for index in range(4096):
        thunk = u32(address_offset(kernel + index * 4, 4))
        if thunk == 0:
            break
        if not thunk & 0x80000000:
            raise IntakeError(f"Invalid kernel ordinal thunk: {thunk:#x}")
        imports.append({"table_address": f"0x{kernel + index * 4:08x}", "ordinal": thunk & 0x7fffffff})
    else:
        raise IntakeError("Kernel thunk table has no terminator")
    certificate_offset = address_offset(u32(0x118), 0xb0)
    certificate = {
        "title_name": data[certificate_offset + 12:certificate_offset + 92].decode("utf-16le").split("\0", 1)[0],
        "title_id": f"0x{u32(certificate_offset + 8):08x}",
        "timestamp": u32(certificate_offset + 4), "allowed_media": u32(certificate_offset + 0x9c),
        "game_region": u32(certificate_offset + 0xa0), "disc_number": u32(certificate_offset + 0xa8),
        "version": u32(certificate_offset + 0xac),
    }
    libraries = []
    library_count = u32(0x160)
    if library_count > 4096:
        raise IntakeError("Unreasonable XBE library count")
    if library_count:
        library_offset = address_offset(u32(0x164), library_count * 16)
        for index in range(library_count):
            name, major, minor, build, flags = struct.unpack_from("<8s4H", data, library_offset + index * 16)
            libraries.append({"name": name.rstrip(b"\0").decode("ascii", errors="replace"),
                              "major": major, "minor": minor, "build": build, "qfe": flags & 0x1fff,
                              "approval": (flags >> 13) & 3, "debug": bool(flags & 0x8000)})
    tls = None
    if u32(0x12c):
        values = struct.unpack_from("<6I", data, address_offset(u32(0x12c), 24))
        tls = dict(zip(("data_start", "data_end", "index_address", "callback_address", "zero_fill_size", "characteristics"), values))
    return {"schema_version": 1, "source_file": path.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "certificate": certificate, "image_kind": kind, "base_address": f"0x{base:08x}", "header_size": header_size,
            "image_size": image_size, "timestamp": u32(0x114), "entry_point": f"0x{entry:08x}",
            "kernel_thunk_address": f"0x{kernel:08x}", "initialization_flags": u32(0x124),
            "stack_commit": u32(0x130), "heap_reserve": u32(0x134), "heap_commit": u32(0x138),
            "tls_address": f"0x{u32(0x12c):08x}", "tls": tls,
            "sections": sections, "libraries": libraries, "kernel_import_count": len(imports), "kernel_imports": imports,
            "debug_path": cstring(u32(0x14c)) if u32(0x14c) else None,
            "non_kernel_import_address": f"0x{u32(0x15c):08x}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="Extract an XDVDFS image and record source/file SHA256 hashes")
    extract.add_argument("iso", type=Path)
    extract.add_argument("--output", type=Path, default=Path("game_files"))
    extract.add_argument("--analysis", type=Path, default=Path("analysis"))
    extract.add_argument("--partition-offset", type=lambda s: int(s, 0), default=0, help="Game partition byte offset; default 0 for a trimmed XISO")
    xbe = commands.add_parser("xbe", help="Analyze XBE sections, title identity, library versions and kernel imports")
    xbe.add_argument("xbe", type=Path)
    xbe.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "extract":
            extract_image(args.iso, args.output, args.analysis, args.partition_offset)
        else:
            protect_source(args.output, [args.xbe])
            write_json(args.output, analyze_xbe(args.xbe))
    except (IntakeError, OSError, UnicodeError, struct.error) as exc:
        print(f"Intake failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
