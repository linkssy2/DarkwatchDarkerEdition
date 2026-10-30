"""Release discovery is platform-specific, bounded, read-only and fails honestly."""
import copy
import http.client
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import release_check

REPO = 'https://github.com/linkssy2/DarkwatchDarkerEdition'
API = 'https://api.github.com/repos/linkssy2/DarkwatchDarkerEdition/releases?per_page=30'
SUFFIX = {'windows': 'Windows-x64.zip', 'linux': 'Linux-Proton-Experimental.tar.gz'}


def release(tag, platforms=('windows', 'linux'), **fields):
    assets = []
    for platform in platforms:
        name = 'Darkwatch-Darker-Edition-' + tag.lstrip('vV') + '-' + SUFFIX[platform]
        assets.append(dict(name=name, state='uploaded', size=123,
                           browser_download_url=f'{REPO}/releases/download/{tag}/{name}'))
    return dict(tag_name=tag, draft=False, prerelease=False,
                published_at='2026-10-28T00:00:00Z', html_url=f'{REPO}/releases/tag/{tag}',
                assets=assets) | fields


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class ReleaseAssertions(unittest.TestCase):
    def unavailable(self, result):
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('release_url', result)
        self.assertTrue(result['message'])


class ReleaseSelectionTests(ReleaseAssertions):
    def test_versions_are_numeric_and_have_two_or_three_ascii_components(self):
        for text, expected in (('0.6', (0, 6, 0)), ('v0.6.1', (0, 6, 1)),
                               ('V1.20.3', (1, 20, 3)), ('0.10', (0, 10, 0))):
            with self.subTest(text=text):
                self.assertEqual(release_check.version(text), expected)
        for text in (None, 6, '', 'v', '6', '0.6.1.2', '0.6-beta', '0.6.1+build',
                     ' 0.6', '0.6\n', 'v0.-6', '０.６', '0.6/../../other'):
            with self.subTest(text=text):
                self.assertIsNone(release_check.version(text))

    def test_selects_numeric_newest_regardless_of_api_order(self):
        releases = [release('v0.9'), release('v0.10'), release('v0.6.1')]
        result = release_check.select_release(releases, '0.9', 'windows')
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['current_version'], '0.9')
        self.assertEqual(result['latest_version'], '0.10')
        self.assertEqual(result['release_url'], REPO + '/releases/tag/v0.10')

    def test_available_asset_metadata_is_copied_without_requiring_digest_for_notice(self):
        candidate = release('v0.7', ('windows',))
        candidate['assets'][0]['digest'] = 'sha256:' + 'a' * 64
        result = release_check.select_release([candidate, copy.deepcopy(candidate)], '0.6', 'windows')
        asset = candidate['assets'][0]
        self.assertEqual(result['asset_name'], asset['name'])
        self.assertEqual(result['asset_url'], asset['browser_download_url'])
        self.assertEqual(result['asset_size'], asset['size'])
        self.assertEqual(result['asset_digest'], asset['digest'])
        del candidate['assets'][0]['digest']
        result = release_check.select_release([candidate], '0.6', 'windows')
        self.assertEqual(result['status'], 'available')
        self.assertIsNone(result['asset_digest'])

    def test_equivalent_versions_and_ahead_builds_do_not_offer_downgrades(self):
        for current, tag in (('0.6', 'v0.6.0'), ('0.6.0', 'v0.6'), ('0.10', 'v0.9')):
            with self.subTest(current=current, tag=tag):
                result = release_check.select_release([release(tag)], current, 'windows')
                self.assertEqual(result['status'], 'current')
                self.assertNotIn('release_url', result)
                self.assertEqual(release_check.version(result['latest_version']), release_check.version(tag))

    def test_linux_only_release_is_not_offered_to_windows(self):
        releases = [release('v0.5.5', ('linux',)), release('v0.5')]
        windows = release_check.select_release(releases, '0.5', 'windows')
        linux = release_check.select_release(releases, '0.5', 'linux')
        self.assertEqual(windows['status'], 'current')
        self.assertEqual(windows['latest_version'], '0.5')
        self.assertEqual(linux['status'], 'available')
        self.assertEqual(linux['latest_version'], '0.5.5')

    def test_drafts_prereleases_and_unpublished_entries_are_not_releases(self):
        for fields in ({'draft': True}, {'prerelease': True}, {'draft': 0},
                       {'prerelease': None}, {'published_at': None}, {'published_at': ''}):
            with self.subTest(fields=fields):
                result = release_check.select_release([release('v0.9', **fields), release('v0.6')], '0.5', 'windows')
                self.assertEqual(result['latest_version'], '0.6')

    def test_invalid_tags_and_unusable_response_shapes_are_unavailable(self):
        for payload in (None, {}, {'message': 'rate limit'}, '', [], [None, 1, []],
                        [release('v0.7-rc1')], [release('0.7/../../other')],
                        [release('0.7')], [release('V0.7')]):
            with self.subTest(payload=payload):
                self.unavailable(release_check.select_release(payload, '0.6', 'windows'))
        result = release_check.select_release([None, {}, release('v0.7')], '0.6', 'windows')
        self.assertEqual(result['status'], 'available')

    def test_asset_must_match_the_tag_and_platform_not_source_or_hd_only(self):
        for assets in ([], None, {}, release('v0.6')['assets'], release('v0.7', ('linux',))['assets'],
                       [dict(name='Source-code.zip', state='uploaded', size=123)],
                       [dict(name='Darkwatch-HD-Textures.zip.001', state='uploaded', size=123)]):
            with self.subTest(assets=assets):
                self.unavailable(release_check.select_release([release('v0.7', assets=assets)], '0.6', 'windows'))

    def test_asset_must_be_uploaded_with_a_positive_integer_size(self):
        for field, value in (('state', 'starter'), ('state', None), ('size', 0),
                             ('size', -1), ('size', True), ('size', '123'), ('size', None)):
            with self.subTest(field=field, value=value):
                candidate = release('v0.7', ('windows',))
                candidate['assets'][0][field] = value
                self.unavailable(release_check.select_release([candidate], '0.6', 'windows'))

    def test_release_and_download_urls_must_be_exact_trusted_locations(self):
        for location in ('html_url', 'browser_download_url'):
            original = release('v0.7', ('windows',))
            url = original[location] if location == 'html_url' else original['assets'][0][location]
            bad_urls = (url.replace('https:', 'http:'), url.replace('github.com', 'github.com.evil.test'),
                        url.replace('github.com', 'github.com@evil.test'),
                        url.replace('/linkssy2/', '/another-owner/'), url + '?redirect=evil',
                        url + '#other', url + '/', url.replace('/v0.7', '/v0.6'))
            for bad in bad_urls:
                with self.subTest(location=location, url=bad):
                    candidate = copy.deepcopy(original)
                    target = candidate if location == 'html_url' else candidate['assets'][0]
                    target[location] = bad
                    self.unavailable(release_check.select_release([candidate], '0.6', 'windows'))

    def test_invalid_current_version_or_platform_is_unavailable(self):
        for current, platform in (('unknown', 'windows'), (None, 'windows'),
                                  ('0.6', 'macos'), ('0.6', None)):
            with self.subTest(current=current, platform=platform):
                self.unavailable(release_check.select_release([release('v0.7')], current, platform))
                with patch.object(release_check.urllib.request, 'build_opener') as opener:
                    self.unavailable(release_check.check(current, platform))
                    opener.assert_not_called()

    def test_selection_preserves_input_metadata(self):
        releases = [release('v0.6'), release('v0.7', ('linux',))]
        before = copy.deepcopy(releases)
        release_check.select_release(releases, '0.5', 'windows')
        release_check.select_release(releases, '0.5', 'linux')
        self.assertEqual(releases, before)

    def test_messages_are_available_in_english_and_spanish(self):
        for payload, current in (([release('v0.7')], '0.6'), ([release('v0.6')], '0.6'), ([], '0.6')):
            result = release_check.select_release(payload, current, 'windows')
            english = release_check.format_message(result)
            spanish = release_check.format_message(result, 'es')
            self.assertEqual(result['message'], english)
            self.assertTrue(spanish)
            self.assertNotEqual(english, spanish)
            if result['status'] == 'available':
                self.assertIn('0.7', english)
                self.assertIn('0.7', spanish)


class ReleaseNetworkTests(ReleaseAssertions):
    def fetch(self, body):
        response = Response(body)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(release_check.urllib.request, 'build_opener', return_value=opener) as build:
            result = release_check.check('0.6', 'windows')
        return result, opener, response, build

    def test_request_is_fixed_https_anonymous_timeout_bounded_and_no_redirects(self):
        result, opener, response, build = self.fetch(json.dumps([release('v0.7')]).encode())
        self.assertEqual(result['status'], 'available')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, API)
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 5)
        self.assertNotIn('authorization', {name.lower() for name, value in request.header_items()})
        self.assertIsNone(request.data)
        self.assertEqual(response.read_sizes, [2 * 1024 * 1024 + 1])
        handler = build.call_args.args[0]
        self.assertIsNone(handler.redirect_request(request, None, 302, 'Found', {}, 'https://other.test/'))
        opener.open.assert_called_once()

    def test_network_rate_limit_and_http_failures_are_unavailable_not_current(self):
        failures = [TimeoutError('timed out'), urllib.error.URLError('offline'),
                    http.client.IncompleteRead(b'['), http.client.BadStatusLine('invalid HTTP')]
        failures.extend(urllib.error.HTTPError(API, code, 'unavailable', {}, None) for code in (302, 403, 429, 500))
        for error in failures:
            with self.subTest(error=repr(error)):
                opener = Mock()
                opener.open.side_effect = error
                with patch.object(release_check.urllib.request, 'build_opener', return_value=opener):
                    self.unavailable(release_check.check('0.6', 'windows'))

    def test_malformed_or_oversized_body_fails_without_an_unbounded_read(self):
        for body in (b'not json', b'\xff', b'{"message":"API rate limit exceeded"}',
                     b'[]', b' ' * (2 * 1024 * 1024 + 2)):
            with self.subTest(length=len(body), prefix=body[:30]):
                result, opener, response, build = self.fetch(body)
                self.unavailable(result)
                self.assertEqual(response.read_sizes, [2 * 1024 * 1024 + 1])

    def test_check_and_format_need_no_local_files_or_installation(self):
        response = Response(json.dumps([release('v0.7')]).encode())
        opener = Mock()
        opener.open.return_value = response
        with patch.object(release_check.urllib.request, 'build_opener', return_value=opener), \
                patch('builtins.open', side_effect=AssertionError('Release check accessed a local file')), \
                patch('io.open', side_effect=AssertionError('Release check accessed a local file')):
            result = release_check.check('0.6', 'linux')
            self.assertEqual(result['status'], 'available')
            self.assertIn('0.7', release_check.format_message(result, 'es'))
        opener.open.assert_called_once()


if __name__ == '__main__':
    unittest.main()
