"""Build the optional replacement-only gameplay texture ZIP; never ship DWGAME01."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / 'xbexbe/config/gameplay_hd_assets.json'
COMPILED = ROOT / 'xbexbe/src/common/gameplay_texture_assets.h'
TRUSTED = ROOT / 'launcher/gameplay-hd-catalog.json'
PART_BYTES = 1 << 30  # GitHub release assets must remain below 2 GiB.


def load_hash(path):
    library = ctypes.CDLL(str(path.resolve()))
    function = library.gameplay_hash
    function.argtypes = (ctypes.c_char_p, ctypes.c_size_t)
    function.restype = ctypes.c_uint64
    return lambda data: function(data, len(data))


def load_assets(metadata, compiled):
    data = metadata.read_bytes()
    rows = json.loads(data)['textures']
    lines = ['// Generated from gameplay_hd_assets.json; metadata only, no original pixels.',
             'inline constexpr GameplayAsset kGameplayAssets[]{']
    seen = set()
    for row in rows:
        name = row['name']
        if not re.fullmatch(r'[a-z0-9-]+', name) or name in seen:
            raise ValueError('Invalid or repeated texture name')
        seen.add(name)
        numbers = [row['native_width'], row.get('native_height', row['native_width']),
                   row['native_levels'], row.get('native_format', 11), row['native_bytes'],
                   row.get('palette_bytes', 1024), row['width'], row['height'], row['dds_mips']]
        if (any(type(number) is not int or number < 0 for number in numbers) or
                not 0 < row['width'] <= 4096 or not 0 < row['height'] <= 4096 or
                not 0 < row['native_levels'] <= row['dds_mips'] <= max(row['width'], row['height']).bit_length() or
                not row['native_bytes'] or
                type(row.get('pack_revision', 1)) is not int or row.get('pack_revision', 1) not in (1, 2) or
                not re.fullmatch(r'[0-9a-f]{16}', row['native_fnv64']) or
                not re.fullmatch(r'[0-9a-f]{64}', row['native_sha256'])):
            raise ValueError('Invalid texture metadata: ' + name)
        lines.append('    {' + json.dumps(name + '.dwt') + ',' + ','.join(map(str, numbers)) +
                     ',0x' + row['native_fnv64'] + 'ull' + (',2' if row.get('pack_revision', 1) == 2 else '') + '},')
    expected = '\n'.join(lines + ['};', ''])
    if not rows or compiled.read_text(encoding='utf-8') != expected:
        raise ValueError('Compiled texture catalog differs from the source metadata')
    return rows, hashlib.sha256(data).hexdigest()


def pixel_bytes(row):
    return sum(max(row['width'] >> level, 1) * max(row['height'] >> level, 1) * 4
               for level in range(row['dds_mips']))


def convert(data, row, fnv):
    native_size = row['native_bytes'] + row.get('palette_bytes', 1024)
    header = struct.pack('<4I', row['width'], row['height'], row['dds_mips'], row['native_bytes'])
    if (len(data) != 24 + native_size + pixel_bytes(row) + 8 or
            data[:24] != b'DWGAME01' + header):
        raise ValueError('Unsupported private texture shape: ' + row['name'])
    native = data[24:24 + native_size]
    if (hashlib.sha256(native).hexdigest() != row['native_sha256'] or
            fnv(native) != int(row['native_fnv64'], 16) or
            fnv(data[:-8]) != struct.unpack_from('<Q', data, len(data) - 8)[0]):
        raise ValueError('Private texture identity or checksum failed: ' + row['name'])
    # Only the native fingerprint survives; original palette and texture bytes do not.
    content = b'DWGAME02' + header + struct.pack('<Q', int(row['native_fnv64'], 16)) + data[24 + native_size:-8]
    return content + struct.pack('<Q', fnv(content))


def verify_replacement(data, row, fnv):
    header = b'DWGAME02' + struct.pack('<4IQ', row['width'], row['height'], row['dds_mips'],
                                     row['native_bytes'], int(row['native_fnv64'], 16))
    if (len(data) != 40 + pixel_bytes(row) or data[:32] != header or
            fnv(data[:-8]) != struct.unpack_from('<Q', data, len(data) - 8)[0]):
        raise ValueError('Invalid replacement-only texture: ' + row['name'])


def encode_catalog(rows, records, metadata_sha, previous):
    catalog = {'schema_version': 1, 'kind': 'darkwatch-gameplay-hd', 'version': '1',
               'texture_catalog_sha256': metadata_sha, 'files': records}
    if previous is not None:
        old = json.loads(previous)
        if ('previous_catalog' in old or
                {r['path']: r for r in old['files']} !=
                {r['path']: r for r, a in zip(records, rows) if a.get('pack_revision', 1) == 1}):
            raise ValueError('Original HD pack catalog must remain byte-for-byte compatible')
        catalog['previous_catalog'] = previous
    return (json.dumps(catalog, indent=2) + '\n').encode('utf-8')


def load_replacement_catalog(path, rows, metadata_sha, previous):
    content = path.read_bytes()
    catalog = json.loads(content)
    records = catalog.get('files') if isinstance(catalog, dict) else None
    if not isinstance(records, list) or len(records) != len(rows):
        raise ValueError('Replacement catalog differs from the source metadata')
    for row, record in zip(rows, records):
        if (not isinstance(record, dict) or set(record) != {'path', 'size', 'sha256'} or
                record['path'] != 'gameplay-hd/' + row['name'] + '.dwt' or
                type(record['size']) is not int or record['size'] != 40 + pixel_bytes(row) or
                not isinstance(record['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])):
            raise ValueError('Invalid pinned replacement catalog entry')
    # Preserve the exact installer receipt, including its previous-download compatibility.
    if content != encode_catalog(rows, records, metadata_sha, previous):
        raise ValueError('Replacement catalog differs from the source metadata or canonical receipt')
    return content, {record['path']: record for record in records}


def verify_archive(path, catalog_bytes, assets, fnv):
    catalog = json.loads(catalog_bytes)
    records = {record['path']: record for record in catalog['files']}
    rows = {'gameplay-hd/' + row['name'] + '.dwt': row for row in assets}
    if set(records) != set(rows):
        raise ValueError('Optional pack texture catalog mismatch')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(records) | {'pack.json'}:
            raise ValueError('Optional ZIP contains missing, repeated or unexpected files')
        if archive.read('pack.json') != catalog_bytes:
            raise ValueError('Optional pack manifest differs from the trusted catalog')
        for name, record in records.items():
            data = archive.read(name)
            if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Optional pack file identity mismatch: ' + name)
            verify_replacement(data, rows[name], fnv)
    return {'files': len(records), 'replacement_bytes': sum(row['size'] for row in records.values()),
            'catalog_sha256': hashlib.sha256(catalog_bytes).hexdigest()}


def verify_parts(folder, records, expected_sha):
    combined = hashlib.sha256()
    for record in records:
        digest = hashlib.sha256()
        count = 0
        with (folder / record['file']).open('rb') as stream:
            while block := stream.read(1 << 20):
                digest.update(block)
                combined.update(block)
                count += len(block)
        if count != record['size'] or digest.hexdigest() != record['sha256']:
            raise ValueError('Optional pack download part differs: ' + record['file'])
    if combined.hexdigest() != expected_sha:
        raise ValueError('Optional pack download parts do not reproduce the verified ZIP')


def split_archive(path, expected_sha, part_bytes=PART_BYTES):
    if part_bytes <= 0 or path.stat().st_size == 0:
        raise ValueError('Invalid archive or download part size')
    count = (path.stat().st_size + part_bytes - 1) // part_bytes
    targets = [path.with_name(path.name + f'.{index:03d}') for index in range(1, count + 1)]
    inventory = path.with_suffix('.parts.json')
    readme = path.with_suffix('.README.txt')
    if any(target.exists() for target in [*targets, inventory, readme]):
        raise ValueError('Use a new download-part destination; previous parts are never overwritten')
    records = []
    with path.open('rb') as source:
        for target in targets:
            digest = hashlib.sha256()
            size = 0
            with target.open('xb') as output:
                while size < part_bytes and (block := source.read(min(1 << 20, part_bytes - size))):
                    output.write(block)
                    digest.update(block)
                    size += len(block)
            records.append({'file': target.name, 'size': size, 'sha256': digest.hexdigest()})
    verify_parts(path.parent, records, expected_sha)
    result = {'archive': path.name, 'sha256': expected_sha, 'part_bytes': part_bytes, 'parts': records}
    inventory.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    readme.write_text('Darkwatch: Darker Edition - Optional HD Textures\n\n'
                      f'Download all {count} files named {path.name}.001 through .{count:03d}\n'
                      'into the same folder. Do not rename, extract or combine them.\n'
                      'In the Darker Edition launcher, select Install HD Textures and choose\n'
                      f'{targets[0].name}. The launcher reads the remaining parts automatically.\n'
                      'The game must be closed during installation. After installation, enable\n'
                      'HD Textures in Graphics. Menus, fonts and HUD are separate\n'
                      'and stay included with the base game installation.\n', encoding='utf-8')
    return result


def package(source, output, trusted, metadata=METADATA, compiled=COMPILED, fnv=None,
            replacement_catalog=None):
    rows, metadata_sha = load_assets(metadata, compiled)
    fnv = fnv or load_hash(ROOT / 'build/tools/gameplay_hash.dll')
    previous = json.loads(metadata.read_bytes()).get('previous_catalog')
    pinned = None
    if replacement_catalog is not None:
        pinned_bytes, pinned = load_replacement_catalog(replacement_catalog, rows, metadata_sha, previous)
    expected = {row['name'] + '.dwt' for row in rows}
    actual = set()
    for path in source.iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError('Linked or non-file private texture input: ' + str(path))
        actual.add(path.name)
    if pinned is not None and 'pack.json' in actual:
        if (source / 'pack.json').read_bytes() != pinned_bytes:
            raise ValueError('Source pack receipt differs from the pinned replacement catalog')
        actual.remove('pack.json')
    if source.is_symlink() or source.is_junction() or actual != expected:
        raise ValueError('Private texture directory differs from the catalog')
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
        for index, row in enumerate(rows, 1):
            name = row['name'] + '.dwt'
            member = 'gameplay-hd/' + name
            data = (source / name).read_bytes()
            if pinned is None:
                data = convert(data, row, fnv)
            else:
                verify_replacement(data, row, fnv)
                if hashlib.sha256(data).hexdigest() != pinned[member]['sha256']:
                    raise ValueError('Replacement texture differs from the pinned catalog: ' + name)
            archive.writestr(member, data)
            records.append({'path': member, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            if index % 50 == 0:
                print(f'Packaged {index}/{len(rows)} textures', flush=True)
        catalog_bytes = encode_catalog(rows, records, metadata_sha, previous)
        archive.writestr('pack.json', catalog_bytes)
    result = verify_archive(output, catalog_bytes, rows, fnv)
    trusted.parent.mkdir(parents=True, exist_ok=True)
    temporary = trusted.with_suffix('.tmp')
    temporary.write_bytes(catalog_bytes)
    temporary.replace(trusted)
    with output.open('rb') as stream:
        result['zip_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    result['download'] = split_archive(output, result['zip_sha256'])
    return dict(result, zip=str(output), zip_bytes=output.stat().st_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/xbexbe-release/gameplay-hd')
    parser.add_argument('--output', type=Path, required=True, help='New optional texture ZIP; never overwritten')
    parser.add_argument('--catalog-output', type=Path, default=TRUSTED)
    parser.add_argument('--replacement-catalog', type=Path,
                        help='Independently validated catalog required for DWGAME02 input; never trust its receipt alone')
    args = parser.parse_args()
    print(json.dumps(package(args.source, args.output, args.catalog_output,
                             replacement_catalog=args.replacement_catalog), indent=2))


if __name__ == '__main__':
    main()
