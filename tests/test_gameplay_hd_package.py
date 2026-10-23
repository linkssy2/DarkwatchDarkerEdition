"""Optional ZIP authoring removes private native bytes and pins all replacements."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('package_gameplay_hd', ROOT / 'tools/package_gameplay_hd.py')
pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


class GameplayHDPackTests(unittest.TestCase):
    def fixture(self, root):
        native = b'original palette and pixels'
        pixels = bytes(range(16)) + bytes(range(4))
        row = {'name': 'fixture', 'native_width': 2, 'native_height': 2, 'native_levels': 1,
               'native_format': 11, 'native_bytes': len(native) - 8, 'palette_bytes': 8,
               'width': 2, 'height': 2, 'dds_mips': 2,
               'native_fnv64': f'{fnv(native):016x}', 'native_sha256': hashlib.sha256(native).hexdigest()}
        data = b'DWGAME01' + struct.pack('<4I', 2, 2, 2, row['native_bytes']) + native + pixels
        data += struct.pack('<Q', fnv(data))
        source = root / 'private'
        source.mkdir()
        (source / 'fixture.dwt').write_bytes(data)
        metadata = root / 'assets.json'
        metadata.write_text(json.dumps({'textures': [row]}))
        compiled = root / 'assets.h'
        compiled.write_text('// Generated from gameplay_hd_assets.json; metadata only, no original pixels.\n'
                            'inline constexpr GameplayAsset kGameplayAssets[]{\n'
                            '    {"fixture.dwt",2,2,1,11,' + str(row['native_bytes']) + ',8,2,2,2,0x' +
                            row['native_fnv64'] + 'ull},\n};\n')
        return row, data, native, pixels, source, metadata, compiled

    def test_replacement_only_exact_format_and_private_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, data, native, pixels, *_ = self.fixture(Path(tmp))
            result = pack.convert(data, row, fnv)
            self.assertEqual(result[:32], b'DWGAME02' + struct.pack('<4IQ', 2, 2, 2, row['native_bytes'], fnv(native)))
            self.assertEqual(result[32:-8], pixels)
            self.assertNotIn(native, result)
            self.assertEqual(len(result), 40 + len(pixels))
            pack.verify_replacement(result, row, fnv)
            invalid = [data[:-1], data + b'junk', b'DWGAME02' + data[8:], data[:-8] + b'bad-hash']
            damaged = bytearray(data)
            damaged[24] ^= 1
            damaged[-8:] = struct.pack('<Q', fnv(damaged[:-8]))
            invalid.append(bytes(damaged))
            for corrupt in invalid:
                with self.assertRaises(ValueError):
                    pack.convert(corrupt, row, fnv)
            for wrong in (dict(row, native_fnv64='0' * 16), dict(row, native_sha256='0' * 64)):
                with self.assertRaises(ValueError):
                    pack.convert(data, wrong, fnv)
            with self.assertRaises(ValueError):
                pack.verify_replacement(result[:-1], row, fnv)

    def test_complete_zip_catalog_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row, _, native, pixels, source, metadata, compiled = self.fixture(root)
            output, trusted = root / 'hd.zip', root / 'trusted.json'
            result = pack.package(source, output, trusted, metadata, compiled, fnv)
            catalog = json.loads(trusted.read_bytes())
            self.assertEqual(result['files'], 1)
            self.assertEqual(catalog['kind'], 'darkwatch-gameplay-hd')
            self.assertEqual(catalog['version'], '1')
            self.assertEqual(catalog['texture_catalog_sha256'], hashlib.sha256(metadata.read_bytes()).hexdigest())
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {'pack.json', 'gameplay-hd/fixture.dwt'})
                self.assertEqual(archive.read('pack.json'), trusted.read_bytes())
                self.assertNotIn(native, archive.read('gameplay-hd/fixture.dwt'))
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                pack.package(source, output, trusted, metadata, compiled, fnv)
            self.assertEqual(original, output.read_bytes())
            for name, content in [('original.xbe', b'original'), ('pack.json', b'wrong')]:
                invalid = root / (name + '.zip')
                invalid.write_bytes(original)
                with warnings.catch_warnings(), zipfile.ZipFile(invalid, 'a') as archive:
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr(name, content)
                with self.assertRaises(ValueError):
                    pack.verify_archive(invalid, trusted.read_bytes(), [row], fnv)
            with zipfile.ZipFile(output) as archive:
                replacement = bytearray(archive.read('gameplay-hd/fixture.dwt'))
            replacement[32] ^= 1
            invalid = root / 'corrupt.zip'
            with zipfile.ZipFile(invalid, 'w') as archive:
                archive.writestr('pack.json', trusted.read_bytes())
                archive.writestr('gameplay-hd/fixture.dwt', replacement)
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                pack.verify_archive(invalid, trusted.read_bytes(), [row], fnv)
            with self.assertRaisesRegex(ValueError, 'Invalid replacement-only'):
                pack.verify_replacement(replacement, row, fnv)

    def test_catalog_and_unexpected_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row, _, _, _, source, metadata, compiled = self.fixture(root)
            pack.load_assets(metadata, compiled)
            original = compiled.read_text()
            compiled.write_text(original.replace(',2,2,2,', ',2,2,1,'))
            with self.assertRaisesRegex(ValueError, 'Compiled texture catalog'):
                pack.load_assets(metadata, compiled)
            compiled.write_text(original)
            (source / 'unexpected.dwt').write_bytes(b'data')
            with self.assertRaisesRegex(ValueError, 'directory differs'):
                pack.package(source, root / 'bad.zip', root / 'bad.json', metadata, compiled, fnv)
            self.assertFalse((root / 'bad.zip').exists())
            self.assertFalse((root / 'bad.json').exists())
            for unsafe in ('../escape', 'duplicate.dwt', ''):
                metadata.write_text(json.dumps({'textures': [dict(row, name=unsafe)]}))
                with self.assertRaises(ValueError):
                    pack.load_assets(metadata, compiled)

    def test_replacement_input_requires_pinned_identity_not_just_valid_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row, data, _, _, source, metadata, compiled = self.fixture(root)
            pinned = root / 'pinned.json'
            pack.package(source, root / 'original.zip', pinned, metadata, compiled, fnv)
            replacement = pack.convert(data, row, fnv)
            (source / 'fixture.dwt').write_bytes(replacement)
            with self.assertRaisesRegex(ValueError, 'Unsupported private texture'):
                pack.package(source, root / 'unpinned.zip', root / 'unpinned.json', metadata, compiled, fnv)
            damaged = bytearray(replacement)
            damaged[32] ^= 1
            damaged[-8:] = struct.pack('<Q', fnv(damaged[:-8]))
            pack.verify_replacement(damaged, row, fnv)  # A checksum cannot establish artwork identity.
            (source / 'fixture.dwt').write_bytes(damaged)
            with self.assertRaisesRegex(ValueError, 'differs from the pinned catalog'):
                pack.package(source, root / 'tampered.zip', root / 'tampered.json', metadata, compiled, fnv,
                             replacement_catalog=pinned)
            self.assertFalse((root / 'tampered.json').exists())
            self.assertFalse((root / 'tampered.zip.001').exists())

    def test_replacement_catalog_and_receipt_must_match_before_packaging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row, data, _, _, source, metadata, compiled = self.fixture(root)
            pinned = root / 'pinned.json'
            pack.package(source, root / 'original.zip', pinned, metadata, compiled, fnv)
            content = pinned.read_bytes()
            (source / 'fixture.dwt').write_bytes(pack.convert(data, row, fnv))
            catalog = json.loads(content)
            invalid = [dict(catalog, files=catalog['files'] * 2),
                       dict(catalog, files=[dict(catalog['files'][0], path='gameplay-hd/other.dwt')]),
                       dict(catalog, files=[dict(catalog['files'][0], size=1)]),
                       dict(catalog, texture_catalog_sha256='0' * 64)]
            for index, changed in enumerate(invalid):
                pinned.write_text(json.dumps(changed, indent=2) + '\n', encoding='utf-8')
                output = root / f'bad-{index}.zip'
                with self.assertRaises(ValueError):
                    pack.package(source, output, root / 'bad.json', metadata, compiled, fnv,
                                 replacement_catalog=pinned)
                self.assertFalse(output.exists())
            pinned.write_bytes(content)
            (source / 'pack.json').write_bytes(b'wrong receipt')
            with self.assertRaisesRegex(ValueError, 'receipt differs'):
                pack.package(source, root / 'receipt.zip', root / 'bad.json', metadata, compiled, fnv,
                             replacement_catalog=pinned)
            self.assertFalse((root / 'receipt.zip').exists())

    def test_extension_pins_exact_previous_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row, data, _, _, source, metadata, compiled = self.fixture(root)
            old = root / 'old.json'
            pack.package(source, root/'old.zip', old, metadata, compiled, fnv)
            prior = old.read_bytes()
            extra = dict(row, name='extension', pack_revision=2)
            (source/'extension.dwt').write_bytes(data)
            metadata.write_text(json.dumps({'textures': [row, extra], 'previous_catalog': prior.decode()}))
            lines = compiled.read_text().splitlines()
            lines.insert(-1, lines[-2].replace('"fixture.dwt"', '"extension.dwt"').replace('ull},', 'ull,2},'))
            compiled.write_text('\n'.join(lines) + '\n')
            trusted = root/'new.json'
            result = pack.package(source, root/'new.zip', trusted, metadata, compiled, fnv)
            self.assertEqual(result['files'], 2)
            new = json.loads(trusted.read_bytes())
            self.assertEqual(new['previous_catalog'].encode(), prior)
            self.assertEqual(new['files'][0], json.loads(prior)['files'][0])
            for asset in (row, extra):
                (source / (asset['name'] + '.dwt')).write_bytes(pack.convert(data, asset, fnv))
            (source / 'pack.json').write_bytes(trusted.read_bytes())
            copied = root / 'copied.json'
            result = pack.package(source, root / 'copied.zip', copied, metadata, compiled, fnv,
                                  replacement_catalog=trusted)
            self.assertEqual(result['files'], 2)
            self.assertEqual(copied.read_bytes(), trusted.read_bytes())
            with zipfile.ZipFile(root / 'new.zip') as original, zipfile.ZipFile(root / 'copied.zip') as repacked:
                self.assertEqual(original.namelist(), repacked.namelist())
                for name in original.namelist():
                    self.assertEqual(original.read(name), repacked.read(name))
            (source / 'pack.json').unlink()
            for asset in (row, extra):
                (source / (asset['name'] + '.dwt')).write_bytes(data)
            changed = json.loads(prior)
            changed['files'][0]['sha256'] = '0' * 64
            metadata.write_text(json.dumps({'textures': [row, extra], 'previous_catalog': json.dumps(changed)}))
            with self.assertRaisesRegex(ValueError, 'byte-for-byte compatible'):
                pack.package(source, root/'bad-extension.zip', root/'bad.json', metadata, compiled, fnv)

    def test_download_parts_exact_round_trip_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'textures.zip'
            data = bytes(range(256)) * 5
            archive.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            result = pack.split_archive(archive, digest, 300)
            self.assertEqual([item['size'] for item in result['parts']], [300, 300, 300, 300, 80])
            self.assertEqual(b''.join((root / item['file']).read_bytes() for item in result['parts']), data)
            self.assertTrue(all(item['file'].endswith(f'.{index:03d}') for index, item in enumerate(result['parts'], 1)))
            self.assertIn('Do not rename, extract or combine', archive.with_suffix('.README.txt').read_text())
            with self.assertRaisesRegex(ValueError, 'never overwritten'):
                pack.split_archive(archive, digest, 300)
            (root / result['parts'][2]['file']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'download part differs'):
                pack.verify_parts(root, result['parts'], digest)


if __name__ == '__main__':
    unittest.main()
