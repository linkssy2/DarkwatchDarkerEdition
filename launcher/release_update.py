"""Verified in-place package updates; installed game data is never an operation."""
import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

STAGE = '.launcher-update'
MANIFEST = 'package-manifest.json'
WRAPPERS = ('Darkwatch.sh', 'linux/launcher.py', 'linux/run_backend.py', 'README-LINUX.md', 'assets/README.txt')


def safe(root, name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Invalid update path')
    for part in name.split('/'):
        if (not part or part in ('.', '..') or part.endswith(('.', ' ')) or
                re.search(r'[\x00-\x1f:<>"|?*]', part) or
                re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part)):
            raise ValueError('Invalid update path')
    path = Path(root)
    for part in (None, *name.split('/')):
        if part is not None:
            path /= part
        try:
            attributes = getattr(path.lstat(), 'st_file_attributes', 0)
        except FileNotFoundError:
            attributes = 0
        if path.is_symlink() or attributes & 0x400:
            raise ValueError('Linked update paths are not supported')
    return path


def owned(name, platform):
    prefix = 'windows/' if platform == 'linux' else ''
    if platform == 'linux' and name in WRAPPERS:
        return True
    if not name.startswith(prefix):
        return False
    local = name[len(prefix):]
    return (local in (MANIFEST, 'Darkwatch Darker Edition.exe', 'Play Darkwatch.exe', 'README.txt', 'assets/README.txt') or
            local.startswith(('payload/', 'licenses/')))


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def read(path):
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Update metadata is too large')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Invalid update metadata')
    return value


def write(path, value):
    descriptor, name = tempfile.mkstemp(prefix='.dw-update-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as target:
            json.dump(value, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def copy_atomic(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.dw-update-', dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as target, source.open('rb') as original:
            shutil.copyfileobj(original, target, 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        shutil.copystat(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path = safe(path.parent, path.name)
    with path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            if not path.stat().st_size:
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError('Another launcher or update is using this installation. Close it first.') from error
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('Another launcher or update is using this installation. Close it first.') from error
        yield


def transaction(root):
    file = safe(root, STAGE + '/transaction.json')
    if not file.exists():
        return None
    value = read(file)
    if (value.get('phase') not in ('prepared', 'applying', 'committed', 'rolled_back') or
            value.get('platform') not in ('windows', 'linux') or not isinstance(value.get('files'), dict)):
        raise ValueError('Invalid pending update; keep the update backup and repair the launcher package')
    for name, row in value['files'].items():
        safe(root, name)
        if not owned(name, value['platform']) or not isinstance(row, dict) or not {'old', 'new'} <= row.keys():
            raise ValueError('Update metadata includes an unmanaged path')
        for key in ('old', 'new'):
            if row.get(key) is not None and not re.fullmatch('[0-9a-f]{64}', str(row[key])):
                raise ValueError('Invalid update checksum')
        if row.get('old') is None and row.get('new') is None:
            raise ValueError('Empty update operation')
    return value


def pending(root):
    value = transaction(root)
    return value is not None and value['phase'] in ('prepared', 'applying')


def cleanup(root):
    """Discard a finished transaction after the replacement launcher works."""
    root = Path(root).absolute()
    scratch = safe(root, STAGE)
    if not scratch.exists():
        return
    try:
        with exclusive(safe(root, '.release-update.lock')):
            value = transaction(root)
            if value and value['phase'] in ('committed', 'rolled_back'):
                shutil.rmtree(scratch)
    except (OSError, ValueError):
        # Windows may still be releasing the helper DLLs; a later launch retries.
        pass


def package_files(root, platform):
    prefix = 'windows/' if platform == 'linux' else ''
    path = safe(root, prefix + MANIFEST)
    manifest = read(path)
    files = manifest.get('files')
    if not isinstance(files, dict) or not files or manifest.get('complete') is not True:
        raise ValueError('Incomplete launcher package')
    result = {prefix + name: value for name, value in files.items()}
    result[prefix + MANIFEST] = digest(path)
    if platform == 'linux':
        for name in WRAPPERS:
            result[name] = digest(safe(root, name))
    for name, checksum in result.items():
        safe(root, name)
        if not owned(name, platform) or not re.fullmatch('[0-9a-f]{64}', str(checksum)):
            raise ValueError('Invalid managed package file')
    return result


def prepare(root, current_version, platform, notify=lambda *a, **k: None, check_cancel=lambda: None):
    import release_download
    root = Path(root).absolute()
    scratch = safe(root, STAGE)
    if scratch.exists():
        previous = transaction(root)
        if previous and previous['phase'] in ('prepared', 'applying'):
            raise ValueError('A previous update needs recovery. Restart the launcher first.')
        # Only our fixed scratch directory is removed, never installation data.
        shutil.rmtree(scratch)
    scratch.mkdir()
    try:
        release = release_download.prepare(current_version, platform, scratch, notify, check_cancel)
        for name in ('download.zip', 'download.tar.gz'):
            safe(scratch, name).unlink(missing_ok=True)
        incoming = safe(scratch, 'new')
        old = package_files(root, platform)
        new = package_files(incoming, platform)
        prefix = 'windows/' if platform == 'linux' else ''
        if any(prefix + 'payload/' + name not in new for name in
               ('release_update.py', 'release_download.py', 'release_check.py')):
            raise ValueError('This release lacks safe automatic-update support. Download its complete package manually.')
        runner = safe(scratch, 'runner')
        runner.mkdir()
        payload = root / ('windows/payload' if platform == 'linux' else 'payload')
        for name in ('release_update.py', 'release_download.py', 'release_check.py'):
            shutil.copy2(safe(payload, name), runner / name)
        if platform == 'windows':
            for name in old:
                if name.startswith('payload/python/'):
                    path = safe(root, name)
                    if digest(path) != old[name]:
                        raise ValueError('The updater Python runtime is damaged. Extract a complete launcher package.')
                    shutil.copy2(path, runner / path.name)
            (runner / 'python312._pth').write_text('python312.zip\n.\n', encoding='ascii')
        operations = {}
        for name in sorted(set(old) | set(new)):
            check_cancel()
            target = safe(root, name)
            if name in new and digest(safe(incoming, name)) != new[name]:
                raise ValueError('Staged update changed after verification')
            if target.exists() and not target.is_file():
                raise ValueError('An update destination is not a regular file')
            actual = digest(target) if target.exists() else None
            if actual == new.get(name):
                continue
            if name not in old and target.exists():
                raise ValueError('The update would replace an unrecognized user file: ' + name)
            # shortcut: Steam starts embedded Python directly; use a fresh package for
            # interpreter upgrades until Steam has an independent recovery bootstrap.
            if platform == 'linux' and name.startswith('windows/payload/python/') and name in old:
                raise ValueError('This release changes the Steam Python runtime. Download and extract its complete Linux package to update safely.')
            if actual is not None:
                backup = safe(scratch, 'backup/' + name)
                copy_atomic(target, backup)
                if digest(backup) != actual:
                    raise ValueError('Update backup failed verification')
            operations[name] = dict(old=actual, new=new.get(name))
        check_cancel()
        value = dict(phase='prepared', platform=platform, version=release['version'], files=operations)
        write(scratch / 'transaction.json', value)
        notify('progress', 'Download verified. Restarting the launcher to apply the update.', percent=100)
        return value
    except BaseException:
        if not (scratch / 'transaction.json').exists():
            shutil.rmtree(scratch)
        raise


def recover(root):
    root = Path(root).absolute()
    value = transaction(root)
    if not value or value['phase'] not in ('prepared', 'applying'):
        return False
    scratch = safe(root, STAGE)
    # Validate every backup before restoring any destination. Keep copies for retries.
    for name, row in value['files'].items():
        if row['old'] is not None and digest(safe(scratch, 'backup/' + name)) != row['old']:
            raise ValueError('Update backup is damaged. Keep it and repair the launcher package.')
    if value['phase'] == 'applying':
        for name, row in value['files'].items():
            target = safe(root, name)
            if row['old'] is not None:
                if not target.is_file() or digest(target) != row['old']:
                    copy_atomic(safe(scratch, 'backup/' + name), target)
            elif target.exists():
                if not target.is_file() or digest(target) != row['new']:
                    raise ValueError('A newly installed file changed; refusing to delete it during recovery')
                target.unlink()
    value['phase'] = 'rolled_back'
    write(scratch / 'transaction.json', value)
    return True


def apply(root):
    root = Path(root).absolute()
    value = transaction(root)
    if not value or value['phase'] != 'prepared':
        raise ValueError('No verified update is ready to apply')
    scratch = safe(root, STAGE)
    growth, largest = 0, 0
    for name, row in value['files'].items():
        target = safe(root, name)
        if (digest(target) if target.exists() else None) != row['old']:
            raise ValueError('Launcher files changed while the update was being prepared')
        if row['new'] is not None and digest(safe(scratch, 'new/' + name)) != row['new']:
            raise ValueError('Staged update failed verification')
        if row['old'] is not None and digest(safe(scratch, 'backup/' + name)) != row['old']:
            raise ValueError('Update backup failed verification')
        old_size = safe(scratch, 'backup/' + name).stat().st_size if row['old'] is not None else 0
        new_size = safe(scratch, 'new/' + name).stat().st_size if row['new'] is not None else 0
        growth += max(0, new_size - old_size)
        largest = max(largest, old_size, new_size)
    if shutil.disk_usage(root).free < growth + largest + 16 * 1024 * 1024:
        raise ValueError('Not enough free disk space to apply and safely recover this update. Free space and retry; existing files were not changed.')
    value['phase'] = 'applying'
    write(scratch / 'transaction.json', value)
    try:
        for name, row in sorted(value['files'].items(), key=lambda item: (item[0].endswith(MANIFEST), item[0])):
            target = safe(root, name)
            if row['new'] is None:
                target.unlink()
            else:
                copy_atomic(safe(scratch, 'new/' + name), target)
        for name, row in value['files'].items():
            target = safe(root, name)
            if (digest(target) if target.exists() else None) != row['new']:
                raise ValueError('Installed update failed verification')
        value['phase'] = 'committed'
        write(scratch / 'transaction.json', value)
    except Exception:
        recover(root)
        raise
    return value['version']


def game_running():
    if os.name != 'nt':
        for process in Path('/proc').glob('[0-9]*/cmdline'):
            try:
                if any(part.replace(b'\\', b'/').rsplit(b'/', 1)[-1].lower() == b'darkwatch_xbe.exe'
                       for part in process.read_bytes().split(b'\0')):
                    return True
            except (OSError, PermissionError):
                continue
        return False
    # The same process-name contract as setup_backend, without importing replaced files.
    from ctypes import wintypes
    class Entry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
                    ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                    ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
                    ('name', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError('Could not check whether Darkwatch is running')
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            if entry.name.casefold() == 'darkwatch_xbe.exe':
                return True
            more = kernel.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() not in (0, 18):
            raise OSError('Could not finish checking running applications')
        return False
    finally:
        kernel.CloseHandle(handle)


def launch_worker(root, install_root, launcher_pid):
    root = Path(root).absolute()
    runner = safe(root, STAGE + '/runner')
    ready = safe(root, STAGE + '/worker-ready.json')
    ready.unlink(missing_ok=True)
    command = [str(runner / 'python.exe'), '-B', str(runner / 'release_update.py'), '--apply', str(root),
               '--install-root', str(install_root), '--wait-pid', str(os.getpid()),
               '--wait-pid', str(launcher_pid), '--restart']
    process = subprocess.Popen(command, cwd=runner, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 10
    while not ready.exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise ValueError('The update helper could not start. Restart the launcher to recover safely.')
        time.sleep(0.05)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--apply', type=Path)
    action.add_argument('--recover', type=Path)
    parser.add_argument('--wait-pid', type=int, action='append', default=[])
    parser.add_argument('--install-root', type=Path)
    parser.add_argument('--restart', action='store_true')
    args = parser.parse_args(argv)
    root = (args.apply or args.recover).absolute()
    kernel = handles = None
    try:
        if args.wait_pid:
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            handles = []
            for pid in args.wait_pid:
                if pid <= 0:
                    raise ValueError('Invalid launcher process')
                handle = kernel.OpenProcess(0x100000, False, pid)
                if not handle:
                    if ctypes.get_last_error() == 87:
                        continue
                    raise OSError('Could not wait for the launcher to close')
                handles.append(handle)
            write(safe(root, STAGE + '/worker-ready.json'), dict(pid=os.getpid()))
            for handle in handles:
                if kernel.WaitForSingleObject(handle, 60000) != 0:
                    raise ValueError('The launcher did not close; the update was not applied')
        with exclusive(safe(root, STAGE + '/worker.lock')):
            install_root = args.install_root or root / 'GameData'
            location = safe(install_root, 'installation-location.json')
            if location.exists():
                selected = read(location).get('root')
                if not isinstance(selected, str) or not Path(selected).is_absolute():
                    raise ValueError('Invalid saved installation location')
                install_root = Path(selected)
            with exclusive(safe(install_root, '.launcher.lock')):
                if game_running():
                    raise ValueError('Close Darkwatch before applying an update')
                if args.recover:
                    recover(root)
                else:
                    apply(root)
        if args.restart:
            command = [str(root / 'Darkwatch Darker Edition.exe')]
            if args.apply:
                command.append('--complete-update')
            subprocess.Popen(command, cwd=root, close_fds=True)
        return 0
    except Exception as error:
        # The backup survives both ordinary errors and interruption during rollback.
        write(safe(root, STAGE + '/last-error.json'), dict(error=str(error)))
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, str(error) + '\n\nRestart the launcher to recover. Your saves are kept.',
                                            'Darkwatch update', 0x10)
        else:
            print(str(error), file=sys.stderr)
        return 1
    finally:
        for handle in handles or []:
            kernel.CloseHandle(handle)


if __name__ == '__main__':
    raise SystemExit(main())
