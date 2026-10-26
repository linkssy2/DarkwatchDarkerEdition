from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
from character_archive import path_hash
from ps2_disc import Iso, Pck


def endian(value, width):
    return value.to_bytes(width, "little") + value.to_bytes(width, "big")


def record(name, sector, size, flags=0):
    raw = bytearray(33 + len(name) + (len(name) % 2 == 0))
    raw[0] = len(raw)
    raw[2:10], raw[10:18] = endian(sector, 4), endian(size, 4)
    raw[25], raw[28:32], raw[32] = flags, endian(1, 2), len(name)
    raw[33:33 + len(name)] = name
    return raw


def disc(entries=None):
    entries = entries or [record(b"AUDIO.PCK;1", 24, 5)]
    raw = bytearray(26 * 2048)
    pvd = memoryview(raw)[16 * 2048:17 * 2048]
    pvd[:7], pvd[8:40], pvd[40:72] = b"\x01CD001\x01", b"PLAYSTATION".ljust(32), b"DRKWTCH".ljust(32)
    pvd[80:88], pvd[128:132] = endian(26, 4), endian(2048, 2)
    root = record(b"\x00", 20, 2048, 2)
    pvd[156:190] = root
    directory = root + record(b"\x01", 20, 2048, 2) + b"".join(entries)
    raw[20 * 2048:20 * 2048 + len(directory)] = directory
    raw[24 * 2048:24 * 2048 + 5] = b"hello"
    return raw


def compact_pck():
    name, start, capacity, mask = "audio/test.adx", 512, 64, 127
    slot = path_hash(name) & (mask >> 1)
    rows = [(0, 0, 0)] * capacity
    rows[slot] = (path_hash(name[::-1]) & ~mask | 1, 64, 5)
    raw = bytearray(start)
    raw[64:69] = b"hello"
    raw += struct.pack("<4I", capacity, 1, mask, 0)
    raw += b"".join(struct.pack("<QII", *r) for r in rows)
    raw += struct.pack("<II", 0, len(name)) + name.encode()
    footer = bytearray(40)
    struct.pack_into("<II", footer, 32, start, 0xfffffffb)
    return raw + footer


class MemoryIso:
    def __init__(self, raw):
        self.raw = raw

    def size(self, name):
        return len(self.raw)

    def read(self, name, offset=0, size=None):
        return bytes(self.raw[offset:None if size is None else offset + size])


class DiscTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "PS2 español.iso"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, raw):
        self.path.write_bytes(raw)
        return self.path

    def test_bounded_root_reads_and_trailing_disc_padding(self):
        with Iso(self.write(disc() + bytes(37))) as iso:
            self.assertEqual(iso.read("AUDIO.PCK"), b"hello")
            self.assertEqual(iso.read("AUDIO.PCK", 1, 3), b"ell")
            self.assertEqual(iso.size("AUDIO.PCK"), 5)
            for offset, size in ((-1, 1), (0, 6), (5, 1)):
                with self.assertRaises(ValueError):
                    iso.read("AUDIO.PCK", offset, size)
            with self.assertRaises(ValueError):
                iso.read("MISSING.PCK")

    def test_corrupt_iso_records_rejected(self):
        bad_endian = disc()
        bad_endian[16 * 2048 + 84] ^= 1
        bad_name = record(b"AUDIO.PCK;1", 24, 5)
        bad_name[32] = 200
        cases = [disc()[:-2048], bad_endian, disc([record(b"AUDIO.PCK;1", 25, 4096)]),
                 disc([record(b"AUDIO.PCK;1", 24, 5, 128)]), disc([bad_name]),
                 disc([record(b"AUDIO.PCK;1", 24, 5)] * 2)]
        for raw in cases:
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                Iso(self.write(raw))

    def test_digest_cancellation(self):
        with Iso(self.write(disc())) as iso:
            def cancel():
                raise InterruptedError()
            with self.assertRaises(InterruptedError):
                iso.digest("AUDIO.PCK", cancel)

    def test_compact_archive_checked_lookup(self):
        pck = Pck(MemoryIso(compact_pck()), "AUDIO.PCK")
        self.assertEqual(pck.read("audio/test.adx"), b"hello")
        with self.assertRaises(ValueError):
            pck.read("audio/absent.adx")

    def test_archive_bad_name_extent_and_footer_rejected(self):
        raw = compact_pck()
        name_at = raw.index(b"audio/test.adx")
        bad_name, bad_extent, bad_count, bad_footer = [bytearray(raw) for _ in range(4)]
        bad_name[name_at] = ord("b")
        slot = path_hash("audio/test.adx") & 63
        struct.pack_into("<I", bad_extent, 512 + 16 + slot * 16 + 8, 510)
        struct.pack_into("<I", bad_count, 516, 2)
        bad_footer[-1] = 0
        for data in (bad_name, bad_extent, bad_count, bad_footer, raw[:10]):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                Pck(MemoryIso(data), "AUDIO.PCK")


if __name__ == "__main__":
    unittest.main()
