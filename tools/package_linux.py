"""Wrap a verified Windows release for experimental Proton use; include no install data."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('windows_package', ROOT / 'launcher/package.py')
windows_package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(windows_package)
WRAPPER_FILES = {
    'Darkwatch.sh': ('Darkwatch.sh', 0o755),
    'launcher.py': ('linux/launcher.py', 0o644),
    'run_backend.py': ('linux/run_backend.py', 0o644),
    'README-LINUX.md': ('README-LINUX.md', 0o644),
}


def package(windows, wrapper, output):
    windows, wrapper, output = map(Path, (windows, wrapper, output))
    if output.exists():
        raise FileExistsError('Preserve the previous archive; choose a new output')
    verified = windows_package.verify(windows)
    members = {
        'windows/' + name: (windows / name, digest, 0o644)
        for name, digest in verified.items()
    }
    manifest = windows / 'package-manifest.json'
    members['windows/package-manifest.json'] = (manifest, windows_package.sha(manifest), 0o644)
    for source, (destination, mode) in WRAPPER_FILES.items():
        path = wrapper / source
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked wrapper file: ' + source)
        if b'\r' in path.read_bytes():
            raise ValueError('Linux wrapper files must use LF line endings: ' + source)
        members[destination] = (path, windows_package.sha(path), mode)
    prefix = f'Darkwatch-Darker-Edition-{windows_package.VERSION}-Linux-Proton-Experimental/'
    for name, (path, digest, mode) in members.items():
        windows_package.safe_relative(name)
        if path.is_symlink() or not path.is_file() or windows_package.sha(path) != digest:
            raise ValueError('Package member changed or is linked: ' + name)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves a previous release even if a competing task finishes first.
    with output.open('xb') as destination, tarfile.open(fileobj=destination, mode='w:gz', compresslevel=6) as archive:
        for name, (path, digest, mode) in sorted(members.items()):
            info = tarfile.TarInfo(prefix + name)
            info.size, info.mode = path.stat().st_size, mode
            with path.open('rb') as source:
                archive.addfile(info, source)
    expected = {prefix + name: (digest, mode) for name, (_, digest, mode) in members.items()}
    seen = set()
    with tarfile.open(output, 'r:gz') as archive:
        for entry in archive:
            if entry.name not in expected or entry.name in seen or not entry.isfile():
                raise ValueError('Unexpected archive member: ' + entry.name)
            seen.add(entry.name)
            digest, mode = expected[entry.name]
            with archive.extractfile(entry) as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != digest or entry.mode != mode:
                    raise ValueError('Archived member failed verification: ' + entry.name)
    if seen != set(expected) or windows_package.verify(windows) != verified:
        raise ValueError('Archive is incomplete or source package changed')
    return dict(status='pass', version=windows_package.VERSION, archive=output.name,
                bytes=output.stat().st_size, sha256=windows_package.sha(output),
                entries=len(expected), files={name: digest for name, (digest, _) in expected.items()},
                original_disc_files_included=False, installed_data_included=False,
                experimental=True, linux_gameplay_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-package', type=Path, required=True)
    parser.add_argument('--wrapper', type=Path, default=ROOT / 'launcher/linux')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    if args.audit.exists():
        parser.error('Preserve the previous audit; choose a new output')
    result = package(args.windows_package, args.wrapper, args.output)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'files'}, indent=2))


if __name__ == '__main__':
    main()
