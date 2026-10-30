"""Download and verify an official release into a caller-owned, inactive stage."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import urllib.parse
import urllib.request
import zipfile
import zlib

import intake
import release_check

CHUNK = 1024 * 1024
MAX_DOWNLOAD = 2 * 1024 ** 3
MAX_UNPACKED = 4 * 1024 ** 3
MAX_FILES = 10000
MAX_MANIFEST = 8 * 1024 * 1024
MAX_METADATA = 16 * 1024 * 1024
PROFILE = {'name': 'release-candidate', 'diagnostics': False, 'strict_assets': True}
WRAPPERS = {'Darkwatch.sh', 'linux/launcher.py', 'linux/run_backend.py', 'README-LINUX.md', 'assets/README.txt'}
REQUIRED = {'Darkwatch Darker Edition.exe', 'Play Darkwatch.exe', 'payload/setup_backend.py',
            'payload/python/python.exe', 'payload/runtime/darkwatch_xbe.exe'}


def trusted_url(url):
    if not isinstance(url, str):
        raise ValueError('Invalid release download URL.')
    parsed = urllib.parse.urlsplit(url)
    if (url != url.strip() or any(ord(c) < 32 for c in url) or
            parsed.scheme != 'https' or parsed.netloc not in ('github.com', 'release-assets.githubusercontent.com') or
            parsed.fragment):
        raise ValueError('Release download redirected outside the trusted HTTPS hosts.')
    return url


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        trusted_url(new_url)
        return super().redirect_request(request, fp, code, message, headers, new_url)


class BoundedZipReader:
    def __init__(self, source):
        self.source = source
        self.size = os.fstat(source.fileno()).st_size

    def read(self, size=-1):
        if size < 0:
            size = self.size - self.source.tell()
        if size > MAX_METADATA:
            raise ValueError('Release ZIP metadata is too large.')
        return self.source.read(size)

    def __getattr__(self, name):
        return getattr(self.source, name)


def relative_path(name):
    if not isinstance(name, str) or len(name) > 1024:
        raise ValueError('Invalid release archive path.')
    for part in name.split('/'):
        intake.safe_component(part.encode('ascii'))
        if part.lower() in ('gamedata', '.proton') or part.lower().startswith('.launcher-update'):
            raise ValueError('Release archive contains installed user data.')
    return name


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate release manifest key.')
        value[key] = item
    return value


def download(info, path, notify, cancel):
    expected_size = info.get('asset_size')
    digest = info.get('asset_digest')
    if (type(expected_size) is not int or not 0 < expected_size <= MAX_DOWNLOAD or
            not isinstance(digest, str) or not re.fullmatch('sha256:[0-9a-f]{64}', digest)):
        raise ValueError('GitHub has not supplied a supported size and SHA256 digest for this release.')
    url = trusted_url(info['asset_url'])
    request = urllib.request.Request(url, headers={'User-Agent': 'Darkwatch-Darker-Edition-Updater',
                                                  'Accept-Encoding': 'identity'})
    hasher, count, last_percent = hashlib.sha256(), 0, -1
    cancel()
    with urllib.request.build_opener(ReleaseRedirect()).open(request, timeout=30) as response:
        trusted_url(response.geturl())
        if response.status != 200:
            raise ValueError('The release download did not return a complete file.')
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) != expected_size):
            raise ValueError('The release download size differs from GitHub metadata.')
        with path.open('xb') as sink:
            while True:
                cancel()
                block = response.read(CHUNK)
                if not block:
                    break
                count += len(block)
                if count > expected_size:
                    raise ValueError('Release download exceeds its declared size.')
                sink.write(block)
                hasher.update(block)
                percent = int(65 * count / expected_size)
                if percent != last_percent:
                    notify('progress', 'Downloading the new release...', percent=percent)
                    last_percent = percent
    if count != expected_size or hasher.hexdigest() != digest[7:]:
        raise ValueError('Release download is incomplete or failed its SHA256 check.')
    return hasher.hexdigest()


class Extraction:
    def __init__(self, root, version, platform, notify, cancel):
        self.root, self.notify, self.cancel = root, notify, cancel
        suffix = release_check.SUFFIX[platform].removesuffix('.zip').removesuffix('.tar.gz')
        self.prefix = f'Darkwatch-Darker-Edition-{version}-{suffix}'
        self.prefixed = None
        self.members, self.nodes, self.hashes, self.directories = set(), {}, {}, set()
        self.total = 0

    def entry(self, raw_name, size, directory):
        self.cancel()
        name = relative_path(raw_name[:-1] if directory and raw_name.endswith('/') else raw_name)
        parts = name.split('/')
        prefixed = parts[0] == self.prefix
        if self.prefixed is None:
            self.prefixed = prefixed
        if self.prefixed != prefixed:
            raise ValueError('Mixed release archive roots.')
        if prefixed:
            parts = parts[1:]
            if not parts:
                if not directory:
                    raise ValueError('Invalid release archive root.')
                name = ''
            else:
                name = '/'.join(parts)
        folded = name.lower()
        if folded in self.members or len(self.members) >= MAX_FILES:
            raise ValueError('Duplicate or excessive release archive entries.')
        self.members.add(folded)
        if not name:
            return None
        for index in range(1, len(parts) + 1):
            node = '/'.join(parts[:index])
            kind = 'directory' if index < len(parts) or directory else 'file'
            previous = self.nodes.setdefault(node.lower(), (node, kind))
            if previous != (node, kind):
                raise ValueError('Release archive has conflicting or case-colliding paths.')
        if directory:
            self.directories.add(name)
            return None
        if type(size) is not int or size < 0 or size > MAX_UNPACKED - self.total:
            raise ValueError('Release archive exceeds the unpacked size limit.')
        self.total += size
        target = intake.safe_destination(self.root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        return name, target

    def copy(self, entry, source, size):
        name, target = entry
        remaining, hasher = size, hashlib.sha256()
        with target.open('xb') as sink:
            while remaining:
                self.cancel()
                block = source.read(min(CHUNK, remaining))
                if not block:
                    raise ValueError('Truncated release archive member.')
                sink.write(block)
                hasher.update(block)
                remaining -= len(block)
            if source.read(1):
                raise ValueError('Release archive member exceeds its declared size.')
        self.hashes[name] = hasher.hexdigest()
        os.chmod(target, 0o755 if name == 'Darkwatch.sh' else 0o644)


def extract(archive, root, version, platform, notify, cancel):
    state = Extraction(root, version, platform, notify, cancel)
    notify('progress', 'Extracting the verified release...', percent=65)
    if platform == 'windows':
        with archive.open('rb') as stream, zipfile.ZipFile(BoundedZipReader(stream)) as bundle:
            if len(bundle.infolist()) > MAX_FILES:
                raise ValueError('Too many release archive entries.')
            for member in bundle.infolist():
                kind = stat.S_IFMT(member.external_attr >> 16)
                if (member.orig_filename != member.filename or member.flag_bits & 1 or
                        kind not in (0, stat.S_IFREG, stat.S_IFDIR) or
                        member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError('Unsupported or linked ZIP release member.')
                directory = member.is_dir()
                if kind == stat.S_IFDIR and not directory:
                    raise ValueError('Invalid ZIP release directory.')
                entry = state.entry(member.filename, member.file_size, directory)
                if entry:
                    with bundle.open(member) as source:
                        state.copy(entry, source, member.file_size)
    else:
        metadata_bytes = 0
        class ReleaseTarInfo(tarfile.TarInfo):
            # Bound extension headers before tarfile allocates their contents.
            def _proc_member(self, archive):
                nonlocal metadata_bytes
                if self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
                    metadata_bytes += self.size
                    if self.size > 64 * 1024 or metadata_bytes > MAX_METADATA:
                        raise ValueError('Release TAR metadata is too large.')
                elif self.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE):
                    raise ValueError('Unsupported or linked TAR release member.')
                return super()._proc_member(archive)
        with tarfile.open(archive, 'r|gz', tarinfo=ReleaseTarInfo) as bundle:
            for member in bundle:
                if not (member.isfile() or member.isdir()) or member.sparse is not None:
                    raise ValueError('Unsupported or linked TAR release member.')
                entry = state.entry(member.name, member.size, member.isdir())
                if entry:
                    with bundle.extractfile(member) as source:
                        state.copy(entry, source, member.size)
    return state


def verify(state, version, platform):
    state.cancel()
    state.notify('progress', 'Verifying every new release file...', percent=90)
    prefix = 'windows/' if platform == 'linux' else ''
    manifest_name = prefix + 'package-manifest.json'
    manifest = intake.safe_destination(state.root, manifest_name)
    if manifest_name not in state.hashes or manifest.stat().st_size > MAX_MANIFEST:
        raise ValueError('Release package manifest is missing or too large.')
    info = json.loads(manifest.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object)
    if (not isinstance(info, dict) or info.get('complete') is not True or
            info.get('version') != version or info.get('release_profile') != PROFILE):
        raise ValueError('Release package version or profile is invalid.')
    files = info.get('files')
    if not isinstance(files, dict) or not REQUIRED <= files.keys():
        raise ValueError('Release package manifest is incomplete.')
    expected = {manifest_name} | (WRAPPERS if platform == 'linux' else set())
    for name, digest in files.items():
        state.cancel()
        relative_path(name)
        if (name == 'package-manifest.json' or not isinstance(digest, str) or
                not re.fullmatch('[0-9a-f]{64}', digest) or state.hashes.get(prefix + name) != digest):
            raise ValueError('Release package file failed verification: ' + name)
        expected.add(prefix + name)
    if set(state.hashes) != expected:
        raise ValueError('Unexpected or missing files in the release package.')
    ancestors = {str(parent).replace('\\', '/') for name in expected for parent in Path(name).parents if str(parent) != '.'}
    if not state.directories <= ancestors:
        raise ValueError('Unexpected directories in the release package.')
    if info.get('runtime_sha256') != files['payload/runtime/darkwatch_xbe.exe']:
        raise ValueError('Release runtime does not match its manifest.')
    actual = set()
    for path in state.root.rglob('*'):
        state.cancel()
        name = path.relative_to(state.root).as_posix()
        intake.safe_destination(state.root, name)
        if path.is_dir():
            if name not in ancestors:
                raise ValueError('Unexpected release directory: ' + name)
            continue
        if not path.is_file() or path.stat().st_nlink != 1 or name not in expected:
            raise ValueError('Unexpected or linked release file: ' + name)
        hasher = hashlib.sha256()
        with path.open('rb') as source:
            while block := source.read(CHUNK):
                state.cancel()
                hasher.update(block)
        if hasher.hexdigest() != state.hashes[name]:
            raise ValueError('Staged release file changed: ' + name)
        actual.add(name)
    if actual != expected:
        raise ValueError('Staged release files are missing.')


def prepare(current_version, platform, scratch, notify, check_cancel):
    """Return an authenticated inactive tree; the caller owns cleanup and activation."""
    scratch = Path(scratch).absolute()
    if not scratch.is_dir():
        raise ValueError('Release staging directory does not exist.')
    root = intake.safe_destination(scratch, 'new')
    archive = intake.safe_destination(scratch, 'download.zip' if platform == 'windows' else 'download.tar.gz')
    if root.exists() or archive.exists():
        raise ValueError('Release staging paths already exist.')
    check_cancel()
    notify('progress', 'Checking the latest official release...', percent=0)
    info = release_check.check(current_version, platform)
    check_cancel()
    if info['status'] != 'available':
        raise ValueError(info['message'])
    digest = download(info, archive, notify, check_cancel)
    check_cancel()
    root.mkdir()
    try:
        state = extract(archive, root, info['latest_version'], platform, notify, check_cancel)
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, zlib.error) as error:
        raise ValueError('The verified release archive is invalid or truncated.') from error
    verify(state, info['latest_version'], platform)
    check_cancel()
    notify('progress', 'The new release is verified and ready to apply.', percent=100)
    return {'version': info['latest_version'], 'directory': str(root), 'asset_sha256': digest}
