"""Build an own-ISO release from an explicit file allowlist."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import shutil
import tomllib

REPO = Path(__file__).resolve().parents[1]
HERE = REPO / 'launcher'
REFERENCE = REPO.parent / 'Urban Chaos Riot Response Recompiled'
PYTHON = REFERENCE / '.tools/python'
VS = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools')
CRT = VS / 'VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.CRT'
VERSION = '0.1.1-test.1'
RELEASE_PROFILE = {'name': 'release-candidate', 'diagnostics': False, 'strict_assets': True}
LAUNCHER = 'Darkwatch Darker Edition.exe'
DIRECT_PLAY = 'Play Darkwatch.exe'
CRT_FILES = ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
PYTHON_FILES = ('python.exe', 'python312.dll', 'python3.dll', 'python312.zip',
                'vcruntime140.dll', 'vcruntime140_1.dll', '_hashlib.pyd',
                'libcrypto-3.dll', '_ctypes.pyd', 'libffi-8.dll', 'LICENSE.txt')
FORBIDDEN = {'.iso', '.xiso', '.xbe', '.pck', '.xmv', '.wmv', '.wav', '.pdb', '.log', '.dmp', '.pyc'}
GENERATED = {
    'payload/python/python312._pth': 'python312.zip\n.\n..\n',
    'README.txt': '''Darkwatch: Darker Edition - 0.1.1-test.1

Experimental tester build
Enables War Train and the retained campaign Splitter Grenade placements from
your own supported Xbox disc. The paired Xbox dynamite substitutes are disabled;
ordinary dynamite and multiplayer placements remain unchanged. No PS2 disc or
downloaded game assets are used. Original chapter progression is retained.
Use the D-pad Up action (Up Arrow by default) to change grenade type after pickup.
Also corrects actor scripts being skipped above 100 FPS, which affected the
opening door at 144 FPS, and enables direct mouse look during vampire jumps.
These changes pass offline checks; testers still need to verify gameplay,
campaign progression, grenade behavior and high-FPS events. This is not a claim
that all physics and events are frame-rate independent.

Extract the entire ZIP into a new folder, then open Darkwatch Darker Edition.exe.
Keep both EXEs and the payload folder together; do not run them inside the ZIP.
Use a short writable path such as C:/Games/Darkwatch, not Program Files.
Native Windows path handling still has the 260-character limit.
Select your supported original Xbox ISO with Import ISO. Setup imports your own
disc locally, then prepares shaders and the HD menus, font and HUD from that verified data.
After import, choose Play. No ISO, Xbox executable, movies or original game
payloads are included. The prebuilt HD pack is not included either.
Play from this launcher has no ten-minute test timer.

After importing once, open Play Darkwatch.exe to start the game directly without
the launcher window. It uses the same installed game, saves and verification.
Shader preparation must finish before play. Both launch paths check the cache;
if preparation is needed, a themed screen reports the completed shaders. Warm
direct launches remain windowless until the game opens. Canceling preparation
before play keeps completed cache entries for the next attempt.
Keep it beside the rest of this extracted package, or create a desktop shortcut
to it. If no game is installed, it asks you to use the launcher to import first.
The entire extracted folder is portable; move it together with GameData.

Requires Windows 10 version 1903 or newer / Windows 11 x64, .NET Framework 4.8,
an x86-64-v2 CPU (including
SSE4.2 and POPCNT), and a Direct3D 12-capable GPU with feature level 11_0.
Python and the Microsoft Visual C++ runtime are included locally;
setup does not install system software or request administrator access.

The supported disc is the original Xbox revision with executable SHA-256:
72fc8033e01df4f22c703121cfd160969c642b18e841248224fc97a8f32050d7
Setup accepts a full Xbox disc image or XISO and checks all 23 original files.
The file picker accepts both .iso and .xiso filenames; no renaming is needed.
Other revisions are rejected. Keep at least 4.5 GB free per import, plus space
for saves and shader cache. Your source ISO is never modified.

The launcher stores everything it installs in GameData/ beside both EXEs.
That includes imported game files, saves, controls, graphics settings and cache.
The original source ISO is only needed for import or repair, not normal play.
Use Open Game Folder to find the imported game, settings and saves. The existing
development build and its saves are not changed or automatically migrated.
Import cancellation or a failed verification keeps the previous complete install.
To update a portable copy, extract the new release into a new folder and copy your
existing GameData folder into it, then use Import / Repair with your original ISO.
This tester requires reimport to enable its bonus content in the installed copy.
For an earlier per-user installation, import your ISO once here; setup copies its
matching saved data and settings into the new portable install, leaving the old
installation untouched. Later repairs preserve the portable saves and cache.
Previous versions remain on disk. Do not delete them until you have checked the
new version and backed up your saves. Verify Files checks without running the game.

Graphics and Controls are available from the main menu and Pause. Esc pauses;
right-click goes back in menus. Configure bindings in Controls. Choose Quit to
Desktop in the main menu to close the game.
PS4 and Switch Pro controllers use matching prompts and controller-layout pages.
Button actions follow physical positions: Switch B confirms and A goes back.
Native USB and Bluetooth paths are enabled but have not been tested on physical
PS4/Switch hardware. If a wrapper exposes an Xbox controller, Xbox prompts apply.
This build disables routine logging, capture hotkeys and development probes.
Fatal errors may still report a short local error to help identify a failure.

This tester has not been verified through the full campaign. On the preceding
release, fresh ISO import and shader preparation passed on the test PC, and the player
reported no noticeable stutters on the opening route and boss fight. Preparation
covers the known shader catalogue, not every possible campaign shader. Unseen
shaders, driver work and ordinary loading can still cause pauses. Testing on a
fresh Windows installation remains outstanding.
Original game content and branding belong to their owners.
See licenses/ for dependency notices and artwork sources.
''',
    'licenses/DEPENDENCIES.txt': '''XboxXBERecomp by TGP482 (MIT): https://github.com/TGP482/Xbox-XBERecomp
SDK dependencies, including Dear ImGui, SDL3 and toml++: XboxXBERecomp-third-party.txt.
SDL's bundled HIDAPI is distributed under its BSD license: HIDAPI-license.txt
and HIDAPI-BSD.txt.
ISO import uses this project's own standard-library XDVDFS reader.
Embedded Python 3.12.10 x64, OpenSSL and libffi: payload/python/LICENSE.txt.
Microsoft Visual C++ 2015-2022 runtime: unmodified app-local DLLs from VS2022 Redist;
Microsoft notices and English terms included. Windows supplies UCRT, Direct3D,
WPF and other system components; those DLLs are not copied into this package.
Launcher cover and insignia provenance: ARTWORK-SOURCES.md.
HD restoration PNGs are the project's approved authored enhancements. Original
texture bytes and the resulting HD pack are prepared only from the user's import.
''',
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_relative(name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Invalid package path')
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(
        part in ('', '.', '..') or part.endswith((' ', '.')) or
        any(char in part for char in ':<>"|?*') or any(ord(char) < 32 for char in part)
        for part in name.split('/')
    ):
        raise ValueError('Invalid package path: ' + name)
    return path


def hd_sources():
    folder = REPO / 'xbexbe/hd_ui'
    overrides = folder / 'overrides.toml'
    data = tomllib.loads(overrides.read_text(encoding='utf-8'))
    names = set()
    for texture in data['texture']:
        for row in [texture, *texture.get('region', [])]:
            if 'file' in row:
                name = row['file']
                if safe_relative(name).suffix.lower() != '.png':
                    raise ValueError('HD override must reference a PNG')
                names.add(name)
    return {'payload/hd_ui/overrides.toml': overrides, **{
        'payload/hd_ui/' + name: folder / name for name in sorted(names)}}


def sources():
    runtime = REPO / 'build/xbexbe-release'
    plan = {
        'payload/setup_backend.py': HERE / 'setup_backend.py',
        'payload/bonus_content.py': HERE / 'bonus_content.py',
        'payload/intake.py': REPO / 'tools/intake.py',
        'payload/supported-disc.json': HERE / 'supported-disc.json',
        'payload/runtime/darkwatch_xbe.exe': runtime / 'darkwatch_xbe.exe',
        'payload/runtime/darkwatch_hd_ui_builder.exe': runtime / 'darkwatch_hd_ui_builder.exe',
        'licenses/XboxXBERecomp.txt': REPO / 'third_party/XboxXBERecomp/LICENSE',
        'licenses/XboxXBERecomp-third-party.txt': REPO / 'third_party/XboxXBERecomp/THIRD_PARTY.txt',
        'licenses/HIDAPI-license.txt': REPO / 'build/xbexbe/_deps/sdl3-src/src/hidapi/LICENSE.txt',
        'licenses/HIDAPI-BSD.txt': REPO / 'build/xbexbe/_deps/sdl3-src/src/hidapi/LICENSE-bsd.txt',
        'licenses/Microsoft-Visual-Studio-Redist.txt': VS / 'Licenses/1033/Redist.txt',
        'licenses/ARTWORK-SOURCES.md': HERE / 'assets/SOURCES.md',
    }
    for name in ('Microsoft-Visual-Cpp-Runtime-license.rtf', 'Microsoft-Visual-Cpp-Redistribution.txt'):
        plan['licenses/' + name] = REFERENCE / 'launcher/burner-xbe' / name
    plan.update({'payload/runtime/' + name: CRT / name for name in CRT_FILES})
    plan.update({'payload/python/' + name: PYTHON / name for name in PYTHON_FILES})
    plan.update(hd_sources())
    return plan


def check_sources(plan):
    build = json.loads((REPO / 'build/xbexbe-release/build-manifest.json').read_text(encoding='utf-8'))
    if build.get('release_profile') != RELEASE_PROFILE:
        raise ValueError('Package requires the quiet release-candidate runtime with strict installed assets.')
    if sha(plan['payload/runtime/darkwatch_xbe.exe']) != build['executable']['sha256']:
        raise ValueError('Runtime differs from the recorded build; rebuild it first.')
    for name, source in plan.items():
        safe_relative(name)
        if not source.is_file() or source.is_symlink() or source.is_junction():
            raise ValueError('Missing or linked package input: ' + str(source))
    return build['executable']['sha256']


def disc_hashes(package):
    data = json.loads((package / 'payload/supported-disc.json').read_text(encoding='utf-8'))
    rows = data['files'].values() if isinstance(data['files'], dict) else data['files']
    return {row['sha256'] for row in rows}


def audit(package, expected, forbidden_hashes):
    """Check the exact payload and renamed original files before declaring it ready."""
    seen = set()
    files = {}
    for path in package.rglob('*'):
        if path.is_symlink() or path.is_junction():
            raise ValueError('Linked package entry: ' + str(path))
        if not path.is_file():
            continue
        name = path.relative_to(package).as_posix()
        safe_relative(name)
        if name.lower() in seen:
            raise ValueError('Duplicate package path')
        seen.add(name.lower())
        if name == 'package-manifest.json':
            continue
        if path.suffix.lower() in FORBIDDEN or path.name.lower() == 'hd-ui.pack':
            raise ValueError('Forbidden original or diagnostic payload: ' + name)
        digest = sha(path)
        if digest in forbidden_hashes:
            raise ValueError('Original disc file in package: ' + name)
        files[name] = digest
    if set(files) != set(expected):
        raise ValueError('Unexpected/missing package files: ' + repr(sorted(set(files) ^ set(expected))))
    for name, digest in expected.items():
        if files[name] != digest:
            raise ValueError('Changed package file: ' + name)
    return files


def assemble(output):
    if output.exists():
        raise ValueError('Use a new package directory; previous packages are never overwritten.')
    plan = sources()
    runtime_sha = check_sources(plan)
    output.mkdir(parents=True)
    for name, source in plan.items():
        dest = output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    for name, text in GENERATED.items():
        dest = output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')
    files = {name: sha(output / name) for name in set(plan) | set(GENERATED)}
    audit(output, files, disc_hashes(output))
    info = {'version': VERSION, 'complete': False, 'release_profile': RELEASE_PROFILE,
            'runtime_sha256': runtime_sha, 'files': files}
    (output / 'package-manifest.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    return info


def finalize(output):
    manifest = output / 'package-manifest.json'
    info = json.loads(manifest.read_text(encoding='utf-8'))
    expected = info['files']
    allowed = set(sources()) | set(GENERATED)
    if set(expected) != allowed or info.get('complete') or info.get('release_profile') != RELEASE_PROFILE:
        raise ValueError('Package is not a fresh assembled launcher candidate.')
    for name in (LAUNCHER, DIRECT_PLAY):
        if not (output / name).is_file():
            raise ValueError('Compile both launch executables before finalizing: ' + name)
    for name in (LAUNCHER, DIRECT_PLAY):
        expected[name] = sha(output / name)
    info['files'] = audit(output, expected, disc_hashes(output))
    info['complete'] = True
    manifest.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    return info


def verify(output):
    info = json.loads((output / 'package-manifest.json').read_text(encoding='utf-8'))
    if not info.get('complete') or info['version'] != VERSION or info.get('release_profile') != RELEASE_PROFILE:
        raise ValueError('Incomplete launcher package')
    if set(info['files']) != set(sources()) | set(GENERATED) | {LAUNCHER, DIRECT_PLAY}:
        raise ValueError('Package allowlist changed')
    return audit(output, info['files'], disc_hashes(output))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('assemble', 'finalize', 'verify'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = {'assemble': assemble, 'finalize': finalize, 'verify': verify}[args.action](args.output.resolve())
    print(json.dumps({'action': args.action, 'package': str(args.output.resolve()),
                      'files': len(result.get('files', result))}))


if __name__ == '__main__':
    main()
