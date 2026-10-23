"""Run with the packaged Windows Python; keep Proton alive while its game runs."""

from contextlib import redirect_stderr, redirect_stdout
import importlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

ERROR_FILE = "last-setup-error.txt"
MAX_ERROR_BYTES = 16384


def notify(message, error=False):
    try:
        import ctypes
        box = ctypes.WinDLL("user32", use_last_error=True).MessageBoxW
        box.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        box.restype = ctypes.c_int
        return bool(box(None, str(message), "Darkwatch: Darker Edition",
                        0x10000 | (0x10 if error else 0x40)))
    except Exception as failure:
        try:
            print(str(message) + "\nCould not show setup dialog: " + str(failure), file=sys.stderr)
        except (OSError, ValueError):
            pass
        return False


def check_error_destination(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError("The setup error file must be a regular file without links.")


def report_error(root, error):
    message = "Setup failed: " + str(error)
    temporary = None
    try:
        root = Path(root).resolve(strict=True)
        destination = root / ERROR_FILE
        check_error_destination(destination)
        payload = (message + "\n").encode("utf-8", "replace")[:MAX_ERROR_BYTES]
        payload = payload.decode("utf-8", "ignore").encode("utf-8")
        descriptor, name = tempfile.mkstemp(prefix=".setup-error-", dir=root)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
        check_error_destination(destination)
        os.replace(temporary, destination)
        return message + "\n\nDetails saved to: " + str(destination)
    except Exception as failure:
        return message + "\n\nCould not save setup details: " + str(failure)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class ConsoleOutput:
    """Allow a missing console and optionally retain a bounded argument-error tail."""
    def __init__(self, stream, capture=False):
        self.stream = stream
        self.capture = capture
        self.text = ""

    def write(self, value):
        if self.capture:
            self.text = (self.text + value)[-MAX_ERROR_BYTES:]
        try:
            self.stream.write(value)
        except (AttributeError, OSError, ValueError):
            self.discard()
        return len(value)

    def flush(self):
        try:
            self.stream.flush()
        except (AttributeError, OSError, ValueError):
            self.discard()

    def discard(self):
        # A buffered broken pipe can otherwise change Python's final exit code to 120.
        try:
            self.stream.close()
        except (AttributeError, OSError, ValueError):
            pass
        self.stream = None


def run(backend, arguments):
    code = backend.main(arguments)
    if code == 0 and "--play" in arguments:
        # The Windows launcher stays outside Wine; this adapter must keep the container alive.
        while backend.game_running():
            time.sleep(1)
    return code


def run_interactive(root, arguments):
    output = ConsoleOutput(sys.stderr, capture=True)
    backend = original_emit = None
    result = failure = None

    def capture(event, message, **fields):
        nonlocal result, failure
        if event in ("result", "status"):
            result = str(message)
        elif event == "error":
            failure = str(message)
        try:
            original_emit(event, message, **fields)
        except (OSError, ValueError):
            # Steam may close stdout; setup still needs its completion/error dialog.
            pass

    with redirect_stderr(output), redirect_stdout(ConsoleOutput(sys.stdout)):
        try:
            backend = importlib.import_module("setup_backend")
            original_emit = backend.emit
            backend.emit = capture
            if any(arg.partition("=")[0] in ("--import-iso", "--install-hd-textures")
                   for arg in arguments):
                notify("Press OK to begin setup. Import and preparation may take several minutes. "
                       "Leave Steam running; another message will confirm completion or explain any error.")
            code = run(backend, arguments)
            if code or failure is not None:
                raise RuntimeError(failure or output.text.strip() or "Setup stopped (exit " + str(code) + ").")
            if "--play" not in arguments:
                notify(result or "Setup completed successfully.")
            return 0
        except SystemExit as error:
            if error.code in (None, 0):
                return 0
            code = error.code if isinstance(error.code, int) else 1
            detail = output.text.strip() or str(error)
        except Exception as error:
            code, detail = 1, str(error)
        finally:
            if original_emit is not None:
                backend.emit = original_emit
    notify(report_error(root, detail), error=True)
    return code


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    interactive = "--interactive" in arguments
    arguments = [arg for arg in arguments if arg != "--interactive"]
    root = Path(__file__).resolve().parents[1]
    for option, path in (("--package", root / "windows"), ("--install-root", root / "GameData")):
        if not any(arg == option or arg.startswith(option + "=") for arg in arguments):
            arguments[:0] = [option, str(path)]
    previous = sys.path[:]
    sys.path.insert(0, str(root / "windows/payload"))
    try:
        if interactive:
            return run_interactive(root, arguments)
        return run(importlib.import_module("setup_backend"), arguments)
    finally:
        sys.path[:] = previous


if __name__ == "__main__":
    raise SystemExit(main())
