"""Read-only checks binding a public source commit to an audited release snapshot."""
from __future__ import annotations

import hashlib
from itertools import chain
from pathlib import Path, PurePosixPath
import re
import stat


class SourceMismatch(ValueError):
    """The local or remote source no longer matches its reviewed release audit."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceMismatch(message)


def _path(name: str) -> None:
    _require(isinstance(name, str) and bool(name) and '\\' not in name and
             ':' not in name and not PurePosixPath(name).is_absolute() and
             all(part not in {'', '.', '..'} for part in name.split('/')),
             'Invalid audited source path')


def expected_tree(source: Path, audit: dict, version: str) -> dict[str, dict[str, str]]:
    """Validate the entire snapshot; shell entrypoints alone receive executable mode."""
    _require(audit.get('status') == 'pass' and audit.get('version') == version,
             'Source audit is not a passing audit for this version')
    files = audit.get('files')
    _require(isinstance(files, dict) and bool(files) and
             audit.get('file_count') == len(files), 'Invalid source inventory')
    for name, digest in files.items():
        _path(name)
        _require(isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest),
                 'Invalid source digest: ' + name)
    _require(len({name.casefold() for name in files}) == len(files),
             'Case-colliding source paths')
    actual = set()
    for path in chain((source,), source.rglob('*')):
        metadata = path.lstat()
        _require(not path.is_symlink() and not
                 (getattr(metadata, 'st_file_attributes', 0) &
                  getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)),
                 'Linked source entries are not allowed')
        if path.is_file():
            actual.add(path.relative_to(source).as_posix())
    _require(actual == set(files), 'Local source file inventory differs from audit')
    expected = {}
    for name, digest in sorted(files.items()):
        data = (source / name).read_bytes()
        _require(hashlib.sha256(data).hexdigest() == digest,
                 'Local source changed: ' + name)
        blob = b'blob ' + str(len(data)).encode('ascii') + b'\0' + data
        expected[name] = {'sha': hashlib.sha1(blob).hexdigest(),
                          'mode': '100755' if name.endswith('.sh') else '100644',
                          'type': 'blob'}
    return expected


def verify_remote(request, prefix: str, expected: dict, *,
                  commit: str | None = None, tag: str | None = None) -> dict:
    """Require main (and an optional release tag) to name the exact audited tree.

    request is the existing GitHub client's read-only request method. No credentials,
    uploads, commits or ref updates are performed here.
    """
    head_path = prefix + '/git/ref/heads/main'
    head = request(head_path)['object']
    _require(head.get('type') == 'commit' and
             re.fullmatch(r'[0-9a-f]{40}', head.get('sha', '')),
             'Main does not identify a commit')
    commit = commit or head['sha']
    _require(head['sha'] == commit, 'Main changed from the verified source commit')
    tree = request(prefix + '/git/trees/' + commit + '?recursive=1')
    _require(tree.get('truncated') is False, 'Remote source tree is incomplete')
    directories = {str(parent) for name in expected
                   for parent in PurePosixPath(name).parents if str(parent) != '.'}
    seen, actual = set(), {}
    for row in tree['tree']:
        name = row['path']
        _path(name)
        _require(name not in seen, 'Duplicate remote source path: ' + name)
        seen.add(name)
        if row['type'] == 'tree':
            _require(name in directories and row['mode'] == '040000',
                     'Unexpected remote directory: ' + name)
            continue
        actual[name] = {key: row[key] for key in ('sha', 'mode', 'type')}
    _require(directories.issubset(seen) and actual == expected,
             'Remote source paths, blob hashes or modes differ from audit')
    if tag is not None:
        target = request(prefix + '/git/ref/tags/' + tag)['object']
        _require(target.get('type') == 'commit' and target.get('sha') == commit,
                 'Release tag does not target the verified source commit')
    _require(request(head_path)['object'] == head, 'Main changed during source verification')
    return {'source_commit': commit, 'source_files': len(expected), 'tag_verified': tag}
