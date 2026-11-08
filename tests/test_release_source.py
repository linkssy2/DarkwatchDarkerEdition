"""Publishing requires the reviewed source contents on main, not just a source ZIP."""
import copy
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import release_source as source

PREFIX = '/repos/example/game'
COMMIT = '1' * 40


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, data in {'README.md': b'Release 1.2.3\n', 'scripts/start.sh': b'#!/bin/sh\n',
                           'launcher/config.json': b'{"version":"1.2.3"}\n'}.items():
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.audit = {'status': 'pass', 'version': '1.2.3', 'file_count': 3,
                      'files': {p.relative_to(self.root).as_posix():
                                hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in self.root.rglob('*') if p.is_file()}}
        self.expected = source.expected_tree(self.root, self.audit, '1.2.3')
        self.head = {'object': {'type': 'commit', 'sha': COMMIT}}
        self.tree = {'sha': '2'*40, 'truncated': False, 'tree': [
            {'path': 'scripts', 'type': 'tree', 'mode': '040000', 'sha': '3'*40},
            {'path': 'launcher', 'type': 'tree', 'mode': '040000', 'sha': '4'*40},
            *[dict(path=name, **row) for name, row in self.expected.items()]]}

    def api(self):
        responses = {PREFIX+'/git/ref/heads/main': self.head,
                     PREFIX+'/git/trees/'+COMMIT+'?recursive=1': self.tree,
                     PREFIX+'/git/ref/tags/v1.2.3': self.head}
        return Mock(side_effect=lambda path: copy.deepcopy(responses[path]))

    def test_git_blob_identity_and_shell_modes(self):
        data = (self.root/'README.md').read_bytes()
        self.assertEqual(self.expected['README.md']['sha'],
                         hashlib.sha1(b'blob 14\0'+data).hexdigest())
        self.assertEqual(self.expected['README.md']['mode'], '100644')
        self.assertEqual(self.expected['scripts/start.sh']['mode'], '100755')

    def test_matching_main_and_tag_use_only_get_requests(self):
        request = self.api()
        receipt = source.verify_remote(request, PREFIX, self.expected, tag='v1.2.3')
        self.assertEqual(receipt['source_commit'], COMMIT)
        self.assertEqual(receipt['source_files'], 3)
        self.assertEqual(receipt['tag_verified'], 'v1.2.3')
        self.assertTrue(all(len(c.args) == 1 and not c.kwargs for c in request.call_args_list))

    def test_hidden_issue_forms_are_required_by_the_audited_inventory(self):
        names = ('.github/ISSUE_TEMPLATE/bug_report.yml',
                 '.github/ISSUE_TEMPLATE/feature_request.yml')
        for name in names:
            data = (ROOT/name).read_bytes()
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.audit['files'][name] = hashlib.sha256(data).hexdigest()
        self.audit['file_count'] = len(self.audit['files'])
        expected = source.expected_tree(self.root, self.audit, '1.2.3')
        self.tree['tree'].extend([
            {'path': name, 'type': 'tree', 'mode': '040000', 'sha': '5'*40}
            for name in ('.github', '.github/ISSUE_TEMPLATE')])
        self.tree['tree'].extend(dict(path=name, **expected[name]) for name in names)
        result = source.verify_remote(self.api(), PREFIX, expected)
        self.assertEqual(result['source_files'], 5)
        self.assertTrue(all(expected[name]['mode'] == '100644' for name in names))
        self.tree['tree'].pop()
        with self.assertRaisesRegex(source.SourceMismatch, 'Remote source paths'):
            source.verify_remote(self.api(), PREFIX, expected)
        (self.root/names[0]).unlink()
        with self.assertRaisesRegex(source.SourceMismatch, 'inventory differs'):
            source.expected_tree(self.root, self.audit, '1.2.3')

    def test_stale_or_extra_local_files_are_rejected(self):
        (self.root/'README.md').write_text('Old release')
        with self.assertRaisesRegex(source.SourceMismatch, 'Local source changed'):
            source.expected_tree(self.root, self.audit, '1.2.3')
        (self.root/'extra.txt').write_text('not audited')
        with self.assertRaisesRegex(source.SourceMismatch, 'inventory differs'):
            source.expected_tree(self.root, self.audit, '1.2.3')

    def test_audit_identity_and_paths_are_not_loosely_matched(self):
        bad = [dict(self.audit, version='1.2.2'), dict(self.audit, status='pending'),
               dict(self.audit, file_count=4),
               dict(self.audit, files={'../README.md': 'a'*64}, file_count=1),
               dict(self.audit, files={'a/../README.md': 'a'*64}, file_count=1),
               dict(self.audit, files={'README.md': 'a'*64, 'readme.md': 'b'*64}, file_count=2)]
        for audit in bad:
            with self.subTest(audit=audit), self.assertRaises(source.SourceMismatch):
                source.expected_tree(self.root, audit, '1.2.3')

    def test_remote_missing_extra_stale_mode_and_submodule_rejected(self):
        original = copy.deepcopy(self.tree)
        variants = []
        for key, value in [('sha', 'f'*40), ('mode', '100755'), ('mode', '120000'),
                           ('type', 'commit')]:
            changed = copy.deepcopy(original)
            changed['tree'][2][key] = value
            variants.append(changed)
        missing = copy.deepcopy(original)
        missing['tree'].pop()
        variants.append(missing)
        extra = copy.deepcopy(original)
        extra['tree'].append(dict(path='unreviewed.txt', **self.expected['README.md']))
        variants.append(extra)
        for tree in variants:
            self.tree = tree
            with self.subTest(tree=tree), self.assertRaises(source.SourceMismatch):
                source.verify_remote(self.api(), PREFIX, self.expected)

    def test_remote_incomplete_or_duplicate_tree_rejected(self):
        self.tree['truncated'] = True
        with self.assertRaisesRegex(source.SourceMismatch, 'incomplete'):
            source.verify_remote(self.api(), PREFIX, self.expected)
        self.tree['truncated'] = False
        self.tree['tree'].append(copy.deepcopy(self.tree['tree'][2]))
        with self.assertRaisesRegex(source.SourceMismatch, 'Duplicate'):
            source.verify_remote(self.api(), PREFIX, self.expected)

    def test_wrong_commit_or_release_tag_rejected(self):
        with self.assertRaisesRegex(source.SourceMismatch, 'Main changed'):
            source.verify_remote(self.api(), PREFIX, self.expected, commit='9'*40)
        request = self.api()
        original = request.side_effect
        request.side_effect = lambda path: ({'object': {'type': 'commit', 'sha': '9'*40}}
                                            if '/tags/' in path else original(path))
        with self.assertRaisesRegex(source.SourceMismatch, 'Release tag'):
            source.verify_remote(request, PREFIX, self.expected, tag='v1.2.3')

    def test_main_movement_during_verification_is_rejected(self):
        request = Mock(side_effect=[self.head, self.tree,
                       {'object': {'type': 'commit', 'sha': '9'*40}}])
        with self.assertRaisesRegex(source.SourceMismatch, 'during source verification'):
            source.verify_remote(request, PREFIX, self.expected)




if __name__ == '__main__':
    unittest.main()
