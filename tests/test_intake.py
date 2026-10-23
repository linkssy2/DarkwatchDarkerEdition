"""Adversarial source parsing tests; no game files or external dependencies needed."""
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from intake import IntakeError, MAGIC, SECTOR_SIZE, XDVDFS, extract_image, parse_directory, protect_source, safe_destination


def node(name=b"file", left=0, right=0, sector=50, size=0, attributes=0x20):
    return struct.pack("<HHIIBB", left, right, sector, size, attributes, len(name)) + name


def image_with_root(table):
    image = bytearray(64 * SECTOR_SIZE)
    image[0x10000:0x10000 + 20] = MAGIC
    image[0x10000 + SECTOR_SIZE - 20:0x10000 + SECTOR_SIZE] = MAGIC
    struct.pack_into("<II", image, 0x10000 + 20, 40, len(table))
    image[40 * SECTOR_SIZE:40 * SECTOR_SIZE + len(table)] = table
    return image


class DirectoryTests(unittest.TestCase):
    def test_four_byte_links_find_non_contiguous_entries(self):
        table = bytearray(100)
        table[:18] = node(b"root", right=20)
        table[80:98] = node(b"leaf")
        self.assertEqual([e[0] for e in parse_directory(table)], ["root", "leaf"])

    def test_pointer_beyond_directory_is_rejected(self):
        with self.assertRaisesRegex(IntakeError, "exceeds"):
            parse_directory(node(right=65535))

    def test_cyclic_child_is_rejected(self):
        table = bytearray(100)
        table[:18] = node(right=20)
        table[80:98] = node(b"leaf", right=20)
        with self.assertRaisesRegex(IntakeError, "cyclic"):
            parse_directory(table)

    def test_truncated_name_is_rejected(self):
        with self.assertRaisesRegex(IntakeError, "exceeds"):
            parse_directory(node()[:-1])

    def test_path_traversal_and_windows_special_names_are_rejected(self):
        for name in (b"..", b"../bad", b"x\\bad", b"x:ads", b"C:", b"NUL.txt", b"a.", b"a ", b"x\0"):
            with self.subTest(name=name), self.assertRaises(IntakeError):
                parse_directory(node(name))

    def test_case_collisions_are_rejected(self):
        table = bytearray(100)
        table[:18] = node(b"FILE", right=20)
        table[80:98] = node(b"file")
        with self.assertRaisesRegex(IntakeError, "colliding"):
            parse_directory(table)

    def test_out_of_image_extent_is_rejected_before_extraction(self):
        raw = image_with_root(node(size=SECTOR_SIZE, sector=64))
        with self.assertRaisesRegex(IntakeError, "exceeds"):
            XDVDFS(io.BytesIO(raw), len(raw)).inventory()

    def test_directory_extent_cycle_is_rejected(self):
        table = node(b"sub", sector=40, size=17, attributes=0x10)
        raw = image_with_root(table)
        with self.assertRaisesRegex(IntakeError, "cyclic"):
            XDVDFS(io.BytesIO(raw), len(raw)).inventory()

    def test_incomplete_descriptor_is_rejected(self):
        raw = image_with_root(node())
        raw[0x10000 + SECTOR_SIZE - 1] = 0
        with self.assertRaisesRegex(IntakeError, "descriptor"):
            XDVDFS(io.BytesIO(raw), len(raw))

    def test_destination_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(IntakeError, "escapes"):
                safe_destination(Path(directory), "../outside")

    def test_symbolic_link_in_output_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside").mkdir()
            try:
                (root / "link").symlink_to(root / "outside", target_is_directory=True)
            except OSError:
                self.skipTest("Creating symlinks is not permitted on this host")
            with self.assertRaisesRegex(IntakeError, "symbolic link"):
                safe_destination(root, "link/file")

    def test_mount_or_junction_above_managed_root_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "installation"
            with mock.patch.object(Path, "is_junction", lambda path: path == parent, create=True):
                self.assertEqual(safe_destination(root, "assets/file"), root / "assets/file")

    def test_managed_root_and_child_junctions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "installation"
            for linked in (root, root / "assets", root / "assets/file"):
                with self.subTest(linked=linked), mock.patch.object(
                        Path, "is_junction", lambda path: path == linked, create=True):
                    with self.assertRaisesRegex(IntakeError, "symbolic link or junction"):
                        safe_destination(root, "assets/file")

    def test_real_linked_parent_allows_extraction_but_linked_root_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            actual = parent / "actual"
            actual.mkdir()
            alias = parent / "alias"
            try:
                alias.symlink_to(actual, target_is_directory=True)
            except OSError:
                self.skipTest("Creating symlinks is not permitted on this host")
            raw = image_with_root(node(size=4))
            raw[50 * SECTOR_SIZE:50 * SECTOR_SIZE + 4] = b"good"
            disc = parent / "disc.iso"
            disc.write_bytes(raw)
            extract_image(disc, alias / "files", alias / "analysis")
            self.assertEqual((actual / "files/file").read_bytes(), b"good")
            self.assertEqual(disc.read_bytes(), raw)
            with self.assertRaisesRegex(IntakeError, "symbolic link"):
                safe_destination(alias, "file")

    def test_direct_output_source_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xbe"
            source.write_bytes(b"preserve")
            with self.assertRaisesRegex(IntakeError, "replace source"):
                protect_source(source, [source])
            self.assertEqual(source.read_bytes(), b"preserve")

    def test_hard_link_to_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xbe"
            source.write_bytes(b"preserve")
            alias = Path(directory) / "other.xbe"
            try:
                alias.hardlink_to(source)
            except OSError:
                self.skipTest("Creating hard links is not permitted on this host")
            with self.assertRaisesRegex(IntakeError, "replace source"):
                protect_source(alias, [source])
            self.assertEqual(source.read_bytes(), b"preserve")

    def test_existing_changed_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = image_with_root(node(size=4))
            raw[50 * SECTOR_SIZE:50 * SECTOR_SIZE + 4] = b"good"
            source = root / "disc.iso"
            source.write_bytes(raw)
            output = root / "files"
            output.mkdir()
            (output / "file").write_bytes(b"user")
            with self.assertRaisesRegex(IntakeError, "checksum differs"):
                extract_image(source, output, root / "analysis")
            self.assertEqual((output / "file").read_bytes(), b"user")
            self.assertEqual(source.read_bytes(), raw)

    def test_manifest_cannot_replace_extracted_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = image_with_root(node(b"disc_manifest.json"))
            source = root / "disc.iso"
            source.write_bytes(raw)
            with self.assertRaisesRegex(IntakeError, "replace source"):
                extract_image(source, root / "files", root / "files")
            self.assertFalse((root / "files").exists())


if __name__ == "__main__":
    unittest.main()
