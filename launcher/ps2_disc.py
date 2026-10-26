"""Read bounded ISO9660 files and compact PCK resources without extracting a disc."""
import hashlib
import os
import struct

from character_archive import canonical, lookup


def require(condition, message):
    if not condition:
        raise ValueError(message)


def both(raw, offset, width):
    little = int.from_bytes(raw[offset:offset + width], "little")
    big = int.from_bytes(raw[offset + width:offset + 2 * width], "big")
    require(little == big, "Inconsistent PS2 ISO directory field.")
    return little


class Iso:
    # shortcut: only root ISO9660 files; supported PAL media needs no nested paths.
    def __init__(self, path):
        self.stream = open(path, "rb")
        try:
            self.length = os.fstat(self.stream.fileno()).st_size
            pvd = self._read(16 * 2048, 2048)
            require(pvd[:7] == b"\x01CD001\x01" and both(pvd, 128, 2) == 2048,
                    "Choose a supported PS2 ISO9660 disc image.")
            self.volume = both(pvd, 80, 4) * 2048
            require(17 * 2048 <= self.volume <= self.length, "Truncated PS2 disc image.")
            self.system = pvd[8:40].rstrip(b" ").decode("ascii")
            self.label = pvd[40:72].rstrip(b" ").decode("ascii")
            root = pvd[156:156 + pvd[156]]
            offset, length = self._record(root, directory=True)
            require(0 < length <= 1024 * 1024, "Invalid PS2 root directory size.")
            raw, cursor, self.entries = self._read(offset, length), 0, {}
            while cursor < len(raw):
                size = raw[cursor]
                if not size:
                    cursor = (cursor // 2048 + 1) * 2048
                    continue
                require(cursor % 2048 + size <= 2048 and cursor + size <= len(raw),
                        "Truncated PS2 directory record.")
                record = raw[cursor:cursor + size]
                cursor += size
                require(len(record) >= 34 and 33 + record[32] <= len(record),
                        "Invalid PS2 directory name.")
                name = record[33:33 + record[32]]
                if name in (b"\x00", b"\x01") or record[25] & 2:
                    continue
                name = name.decode("ascii")
                require(name.endswith(";1") and "/" not in name and "\\" not in name,
                        "Unsupported PS2 directory name.")
                name = name[:-2]
                require(name and name not in self.entries, "Duplicate PS2 disc file.")
                self.entries[name] = self._record(record)
        except Exception:
            self.stream.close()
            raise

    def _read(self, offset, size):
        require(0 <= offset <= self.length and 0 <= size <= self.length - offset,
                "PS2 disc read exceeds its bounds.")
        self.stream.seek(offset)
        raw = self.stream.read(size)
        require(len(raw) == size, "PS2 disc changed or is truncated.")
        return raw

    def _record(self, raw, directory=False):
        require(len(raw) >= 34 and raw[0] == len(raw) and not raw[1]
                and raw[25] == (2 if directory else 0) and not raw[26] and not raw[27]
                and both(raw, 28, 2) == 1, "Unsupported PS2 directory record.")
        offset, size = both(raw, 2, 4) * 2048, both(raw, 10, 4)
        require(offset >= 17 * 2048 and offset + size <= self.volume,
                "PS2 file exceeds the disc volume.")
        return offset, size

    def size(self, name):
        require(name in self.entries, "Required PS2 disc file is missing: " + name)
        return self.entries[name][1]

    def read(self, name, offset=0, size=None):
        length = self.size(name)
        size = length - offset if size is None else size
        require(0 <= offset <= length and 0 <= size <= length - offset,
                "PS2 resource read exceeds its file.")
        return self._read(self.entries[name][0] + offset, size)

    def digest(self, name, cancel=lambda: None):
        digest = hashlib.sha256()
        length = self.size(name)
        for offset in range(0, length, 8 * 1024 ** 2):
            cancel()
            digest.update(self.read(name, offset, min(8 * 1024 ** 2, length - offset)))
        return digest.hexdigest()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.stream.close()


class Pck:
    def __init__(self, iso, name):
        self.iso, self.name = iso, name
        length = iso.size(name)
        require(length >= 56, "Truncated PS2 resource archive.")
        start, marker = struct.unpack("<II", iso.read(name, length - 8, 8))
        require(marker == 0xfffffffb and 0 < start <= length - 56,
                "Invalid PS2 resource archive footer.")
        capacity, count, mask, upper = struct.unpack("<4I", iso.read(name, start, 16))
        require(64 <= capacity <= mask + 1 <= 1048576 and not ((mask + 1) & mask)
                and not upper and count <= capacity - 2,
                "Invalid PS2 resource table bounds.")
        end = start + 16 + capacity * 16
        require(end <= length - 40 and length - end <= 16 * 1024 ** 2,
                "Invalid PS2 resource index size.")
        table = iso.read(name, start + 16, capacity * 16)
        rows = list(struct.iter_unpack("<QII", table))
        occupied = [(i, row) for i, row in enumerate(rows) if row[0]]
        require(len(occupied) == count, "PS2 resource count mismatch.")
        names, cursor, self.entries = iso.read(name, end, length - 40 - end), 0, {}
        for slot, (key, offset, size) in occupied:
            require(key & mask and offset + size <= start and cursor + 8 <= len(names),
                    "Invalid PS2 resource extent.")
            unused, name_size = struct.unpack_from("<II", names, cursor)
            cursor += 8
            require(0 < name_size < 260 and cursor + name_size <= len(names),
                    "Invalid PS2 resource name length.")
            resource = names[cursor:cursor + name_size].decode("ascii")
            cursor += name_size
            require(canonical(resource) == resource and resource not in self.entries
                    and lookup(rows, mask, resource) == slot,
                    "PS2 resource name does not match its archive record.")
            self.entries[resource] = dict(offset=offset, size=size)
        require(cursor == len(names), "Unexpected PS2 resource index trailer.")

    def read(self, name):
        require(name in self.entries, "Required PS2 resource is missing: " + name)
        row = self.entries[name]
        return self.iso.read(self.name, row["offset"], row["size"])
