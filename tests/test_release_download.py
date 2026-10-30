"""Synthetic authenticated release staging; no network, active install, or game."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
import urllib.request
import warnings
import zipfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'launcher'), str(ROOT / 'tools')]
import release_download as staging
from test_release_check import release


def sha(data):
    return hashlib.sha256(data).hexdigest()


def contents(platform='windows', **manifest_fields):
    files = {name: ('fixture ' + name).encode() for name in staging.REQUIRED}
    files['licenses/notice.txt'] = b'fixture license'
    manifest = dict(version='0.7', complete=True, release_profile=dict(staging.PROFILE),
                    runtime_sha256=sha(files['payload/runtime/darkwatch_xbe.exe']),
                    files={name: sha(data) for name, data in files.items()}) | manifest_fields
    files['package-manifest.json'] = json.dumps(manifest).encode()
    if platform == 'linux':
        files = {'windows/' + name: data for name, data in files.items()}
        files.update({name: b'#!/bin/sh\nfixture\n' for name in staging.WRAPPERS})
    return files


def archive_bytes(platform='windows', files=None, prefix=False, extras=()):
    files = contents(platform) if files is None else files
    suffix = 'Windows-x64' if platform == 'windows' else 'Linux-Proton-Experimental'
    top = f'Darkwatch-Darker-Edition-0.7-{suffix}/' if prefix else ''
    output = io.BytesIO()
    if platform == 'windows':
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(top + name, data)
            for name, data, kind in extras:
                entry = zipfile.ZipInfo(top + name)
                entry.create_system = 3
                entry.external_attr = (kind | 0o644) << 16
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr(entry, data)
    else:
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, data in files.items():
                entry = tarfile.TarInfo(top + name)
                entry.size, entry.mode = len(data), 0o7777
                archive.addfile(entry, io.BytesIO(data))
            for name, data, kind in extras:
                entry = tarfile.TarInfo(top + name)
                entry.type, entry.size = kind, len(data)
                entry.linkname = '../../outside'
                archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()


class Response(io.BytesIO):
    def __init__(self, body, url, headers=None, status=200):
        super().__init__(body)
        self.url, self.status = url, status
        self.headers = {'Content-Length': str(len(body))} if headers is None else headers

    def geturl(self):
        return self.url


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        self.outside = self.root / 'outside'
        self.outside.write_bytes(b'preserved user data')
        self.events = []

    def tearDown(self):
        self.assertEqual(self.outside.read_bytes(), b'preserved user data')
        self.assertEqual({path.name for path in self.root.iterdir()}, {'scratch', 'outside'})

    def stage(self, body, platform='windows', fields=None, response_fields=None, cancel=lambda: None):
        candidate = release('v0.7', (platform,))
        candidate['assets'][0].update(size=len(body), digest='sha256:' + sha(body))
        info = staging.release_check.select_release([candidate], '0.6', platform)
        info.update(fields or {})
        response = Response(body, info['asset_url'], **(response_fields or {}))
        opener = Mock()
        opener.open.return_value = response
        with patch.object(staging.release_check, 'check', return_value=info) as check, \
                patch.object(staging.urllib.request, 'build_opener', return_value=opener):
            result = staging.prepare('0.6', platform, self.scratch,
                                     lambda event, message, **fields: self.events.append((event, message, fields)), cancel)
        check.assert_called_once_with('0.6', platform)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, info['asset_url'])
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 30)
        self.assertNotIn('authorization', {name.lower() for name, value in request.header_items()})
        return result

    def test_windows_direct_and_exact_version_prefix_are_verified(self):
        for prefixed in (False, True):
            with self.subTest(prefixed=prefixed), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                original = self.scratch
                self.scratch = Path(subdir)
                try:
                    body = archive_bytes(prefix=prefixed)
                    result = self.stage(body)
                    self.assertEqual(result, dict(version='0.7', directory=str(self.scratch / 'new'), asset_sha256=sha(body)))
                    self.assertTrue((Path(result['directory']) / 'Darkwatch Darker Edition.exe').is_file())
                    self.assertEqual(self.events[-1][2]['percent'], 100)
                finally:
                    self.scratch = original

    def test_linux_matches_existing_wrapper_layout_and_sanitizes_modes(self):
        result = self.stage(archive_bytes('linux', prefix=True), 'linux')
        root = Path(result['directory'])
        self.assertTrue((root / 'windows/package-manifest.json').is_file())
        self.assertTrue(all((root / name).is_file() for name in staging.WRAPPERS))
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE((root / 'Darkwatch.sh').stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((root / 'windows/Play Darkwatch.exe').stat().st_mode), 0o644)

    def test_bad_or_missing_github_digest_never_extracts(self):
        body = archive_bytes()
        for digest in (None, '', 'md5:' + '0' * 32, 'sha256:' + '0' * 64):
            with self.subTest(digest=digest), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                original, self.scratch = self.scratch, Path(subdir)
                try:
                    with self.assertRaises(ValueError):
                        self.stage(body, fields={'asset_digest': digest})
                    self.assertFalse((self.scratch / 'new').exists())
                finally:
                    self.scratch = original

    def test_partial_oversized_or_incorrect_length_download_is_rejected(self):
        body = archive_bytes()
        for fields, headers in (({'asset_size': len(body) + 1}, {}),
                                ({'asset_size': len(body) - 1}, {}),
                                ({'asset_size': staging.MAX_DOWNLOAD + 1}, {}),
                                ({}, {'Content-Length': str(len(body) + 1)})):
            with self.subTest(fields=fields, headers=headers), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                original, self.scratch = self.scratch, Path(subdir)
                try:
                    with self.assertRaises(ValueError):
                        self.stage(body, fields=fields, response_fields={'headers': headers})
                    self.assertFalse((self.scratch / 'new').exists())
                finally:
                    self.scratch = original

    def test_partial_http_response_and_offsite_download_are_rejected(self):
        body = archive_bytes()
        with self.assertRaises(ValueError):
            self.stage(body, response_fields={'status': 206})
        with self.assertRaises(ValueError):
            self.stage(body, fields={'asset_url': 'https://evil.test/release.zip'})
        self.assertFalse((self.scratch / 'new').exists())

    def test_redirects_allow_only_two_https_hosts(self):
        handler = staging.ReleaseRedirect()
        request = urllib.request.Request('https://github.com/fixture')
        for url in ('http://github.com/file', 'https://github.com.evil.test/file',
                    'https://github.com@evil.test/file', 'https://evil.test/file',
                    'file:///tmp/file', 'https://release-assets.githubusercontent.com:444/file'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, 'Found', {}, url)
        for url in ('https://github.com/fixture', 'https://release-assets.githubusercontent.com/file?signed=token'):
            redirected = handler.redirect_request(request, None, 302, 'Found', {}, url)
            self.assertEqual(redirected.full_url, url)

    def test_paths_cannot_escape_or_contain_user_data(self):
        paths = ('../outside', '/outside', 'C:/outside', 'payload\\outside', 'payload/x:stream',
                 'payload/CON', 'payload/a.', 'payload//a', 'GameData/save.dat',
                 'windows/.proton/save', 'payload/.launcher-update-new/file')
        for platform in ('windows', 'linux'):
            for name in paths:
                with self.subTest(platform=platform, name=name), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                    original, self.scratch = self.scratch, Path(subdir)
                    kind = stat.S_IFREG if platform == 'windows' else tarfile.REGTYPE
                    try:
                        with self.assertRaises(ValueError):
                            self.stage(archive_bytes(platform, extras=[(name, b'bad', kind)]), platform)
                    finally:
                        self.scratch = original

    def test_link_device_and_case_colliding_members_are_rejected(self):
        cases = [('windows', 'link', stat.S_IFLNK), ('windows', 'device', stat.S_IFCHR),
                 ('linux', 'link', tarfile.SYMTYPE), ('linux', 'hardlink', tarfile.LNKTYPE),
                 ('linux', 'device', tarfile.CHRTYPE), ('windows', 'PAYLOAD/setup_backend.py', stat.S_IFREG),
                 ('linux', 'WINDOWS/payload/setup_backend.py', tarfile.REGTYPE),
                 ('windows', 'package-manifest.json', stat.S_IFREG)]
        for platform, name, kind in cases:
            with self.subTest(platform=platform, name=name, kind=kind), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                original, self.scratch = self.scratch, Path(subdir)
                try:
                    with self.assertRaises(ValueError):
                        self.stage(archive_bytes(platform, extras=[(name, b'bad', kind)]), platform)
                finally:
                    self.scratch = original

    def test_file_count_and_unpacked_size_limits_are_enforced(self):
        for limit, value in (('MAX_FILES', 2), ('MAX_UNPACKED', 4)):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                original, self.scratch = self.scratch, Path(subdir)
                try:
                    with patch.object(staging, limit, value), self.assertRaises(ValueError):
                        self.stage(archive_bytes())
                finally:
                    self.scratch = original

    def test_wrong_version_profile_runtime_and_file_hash_are_rejected(self):
        variants = [contents(version='0.8'), contents(complete=False), contents(release_profile={}),
                    contents(runtime_sha256='0' * 64), contents()]
        variants[-1]['payload/setup_backend.py'] = b'changed after manifest was written'
        for index, files in enumerate(variants):
            with self.subTest(variant=index), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                original, self.scratch = self.scratch, Path(subdir)
                try:
                    with self.assertRaises(ValueError):
                        self.stage(archive_bytes(files=files))
                finally:
                    self.scratch = original

    def test_wrong_platform_layout_and_unlisted_files_are_rejected(self):
        for platform, files in (('windows', contents('linux')), ('linux', contents('windows')),
                                ('windows', contents() | {'unlisted.exe': b'bad'})):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                original, self.scratch = self.scratch, Path(subdir)
                try:
                    with self.assertRaises(ValueError):
                        self.stage(archive_bytes(platform, files=files), platform)
                finally:
                    self.scratch = original

    def test_missing_members_duplicate_manifest_keys_and_wrong_prefix_are_rejected(self):
        missing = contents()
        del missing['payload/setup_backend.py']
        duplicate = contents()
        duplicate['package-manifest.json'] = b'{"version":"0.6",' + duplicate['package-manifest.json'][1:]
        wrong_prefix = {'Darkwatch-Darker-Edition-0.8-Windows-x64/' + name: data for name, data in contents().items()}
        missing_wrapper = contents('linux')
        del missing_wrapper['README-LINUX.md']
        for platform, files in (('windows', missing), ('windows', duplicate),
                                ('windows', wrong_prefix), ('linux', missing_wrapper)):
            with self.subTest(platform=platform, names=list(files)), tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
                original, self.scratch = self.scratch, Path(subdir)
                try:
                    with self.assertRaises(ValueError):
                        self.stage(archive_bytes(platform, files=files), platform)
                finally:
                    self.scratch = original

    def test_bounded_zip_and_tar_metadata_and_truncated_archive(self):
        with patch.object(staging, 'MAX_METADATA', 4), self.assertRaisesRegex(ValueError, 'metadata'):
            self.stage(archive_bytes())
        with tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
            original, self.scratch = self.scratch, Path(subdir)
            try:
                body = archive_bytes('linux', extras=[('metadata', b'x' * 65537, tarfile.XHDTYPE)])
                with self.assertRaisesRegex(ValueError, 'metadata'):
                    self.stage(body, 'linux')
            finally:
                self.scratch = original
        with tempfile.TemporaryDirectory(dir=self.scratch) as subdir:
            original, self.scratch = self.scratch, Path(subdir)
            try:
                with self.assertRaisesRegex(ValueError, 'invalid or truncated'):
                    self.stage(archive_bytes()[:-5])
            finally:
                self.scratch = original

    def test_post_extraction_mutation_is_detected_before_return(self):
        archive = self.scratch / 'fixture.zip'
        archive.write_bytes(archive_bytes())
        root = self.scratch / 'new'
        root.mkdir()
        state = staging.extract(archive, root, '0.7', 'windows', Mock(), lambda: None)
        (root / 'payload/setup_backend.py').write_bytes(b'changed staged bytes')
        with self.assertRaisesRegex(ValueError, 'changed'):
            staging.verify(state, '0.7', 'windows')

    def test_cancel_propagates_without_returning_a_stage(self):
        class Cancelled(Exception):
            pass
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise Cancelled('user cancelled')
        with self.assertRaises(Cancelled):
            self.stage(archive_bytes(), cancel=cancel)
        self.assertFalse((self.scratch / 'new').exists())

    def test_existing_staging_file_is_preserved_and_no_fetch_occurs(self):
        archive = self.scratch / 'download.zip'
        archive.write_bytes(b'previous download')
        with patch.object(staging.release_check, 'check') as check, self.assertRaises(ValueError):
            staging.prepare('0.6', 'windows', self.scratch, Mock(), Mock())
        check.assert_not_called()
        self.assertEqual(archive.read_bytes(), b'previous download')

    def test_no_update_or_network_failure_does_not_create_files(self):
        for status in ('current', 'unavailable'):
            with self.subTest(status=status), patch.object(staging.release_check, 'check',
                    return_value={'status': status, 'message': 'No update available'}), self.assertRaises(ValueError):
                staging.prepare('0.6', 'windows', self.scratch, Mock(), Mock())
        self.assertEqual(list(self.scratch.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
