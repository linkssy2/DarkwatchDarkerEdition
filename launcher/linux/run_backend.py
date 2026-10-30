"""Run with the packaged Windows Python; keep Proton alive while its game runs."""

from contextlib import redirect_stderr, redirect_stdout
import importlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import stat
import sys
import tempfile
import time

ERROR_FILE = "last-setup-error.txt"
MAX_ERROR_BYTES = 16384


def native_update_notice(root, interactive, interrupted=False):
    message = ("An interrupted launcher update must be recovered before starting Darkwatch. " if interrupted else
               "To download and install the Linux update in this same folder, ")
    message += ("Close Darkwatch and this Steam shortcut. Open a native Linux terminal in the extracted folder and run:\n\n"
                "./Darkwatch.sh --download-update\n\n"
                "Your game data and Steam shortcut location are kept. After it finishes, restore --play in Steam. "
                "Steam's bundled Python cannot safely replace itself during this shortcut.")
    with redirect_stdout(ConsoleOutput(sys.stdout)):
        print(json.dumps(dict(event="update_notice", message=message, native_update_required=True)), flush=True)
    if interactive:
        notify(message)
    return 1 if interrupted else 0


def update_interrupted(root):
    path = root / ".launcher-update/transaction.json"
    if not path.exists():
        return False
    try:
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            return True
        state = json.loads(path.read_text(encoding="utf-8-sig"))
        return not isinstance(state, dict) or state.get("phase") not in ("committed", "rolled_back")
    except (OSError, ValueError):
        return True


def release_tools(root):
    spec = importlib.util.spec_from_file_location("darkwatch_linux_launcher", root / "linux/launcher.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    return launcher


def check_updates(root, interactive):
    try:
        launcher = release_tools(root)
        result = launcher.check_releases(root)
        message = launcher.release_text(result)
    except Exception:
        message = "Could not check for new releases. You can keep playing and try again later."
        result = dict(status="unavailable", current_version="", platform="linux", message=message)
    with redirect_stdout(ConsoleOutput(sys.stdout)):
        print(json.dumps(dict(result, event="release_check")), flush=True)
    if interactive:
        notify(message)
    return 0


def notify(message, error=False, buttons=0):
    try:
        import ctypes
        box = ctypes.WinDLL("user32", use_last_error=True).MessageBoxW
        box.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        box.restype = ctypes.c_int
        return box(None, str(message), "Darkwatch: Darker Edition",
                   0x10000 | (0x10 if error else 0x40) | buttons)
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
    release = pending_release = None
    if "--play" in arguments:
        try:
            release = release_tools(root)
            pending_release = release.start_release_check(root)
        except Exception:
            pass

    def capture(event, message, **fields):
        nonlocal result, failure
        if event == "progress" and fields.get("automatic_setup"):
            notify(str(message) + "\n\nPreparation may take several minutes. Leave Steam running; "
                   "the game will start when setup finishes, or an error dialog will explain any problem.")
        if event in ("result", "status"):
            result = str(message)
            if fields.get("update_available"):
                result += "\n\nChoose Update Installation (--update) to prepare this build. Your Xbox ISO does not need to be imported again."
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
            if "--language" in arguments:
                choice = notify("Game language / Idioma del juego\n\n"
                                "Yes / Sí: Español\nNo: English\nCancel / Cancelar: Keep current language / No cambiar\n\n"
                                "Applies on the next launch. Close Darkwatch first.\n"
                                "Se aplica al iniciar el juego. Cierra Darkwatch primero.", buttons=0x203)
                if choice == 2:
                    return 0
                if choice not in (6, 7):
                    raise RuntimeError("Could not open the language selector. Use --set-language en or --set-language es.")
                index = arguments.index("--language")
                arguments = arguments[:index] + ["--set-language", "es" if choice == 6 else "en"] + arguments[index + 1:]
            if any(arg.partition("=")[0] in ("--import-iso", "--use-iso", "--install-hd-textures", "--install-spanish", "--update")
                   for arg in arguments):
                source_notice = ("Use ISO directly keeps your ISO required: leave it in place for every launch. "
                                 if any(arg.partition("=")[0] == "--use-iso" for arg in arguments) else
                                 "Import the Xbox disc once; use --update for later builds or --use-installation FOLDER to reuse an existing installation. ")
                notify("Press OK to begin setup. Import and preparation may take several minutes. "
                       + source_notice +
                       "Leave Steam running; another message will confirm completion or explain any error.")
            code = run(backend, arguments)
            if code or failure is not None:
                raise RuntimeError(failure or output.text.strip() or "Setup stopped (exit " + str(code) + ").")
            if "--play" not in arguments:
                notify(result or "Setup completed successfully.")
            elif pending_release is not None:
                try:
                    available = pending_release.get_nowait()
                    if available.get("status") == "available":
                        notify(release.release_text(available))
                except queue.Empty:
                    pass
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
    if update_interrupted(root):
        return native_update_notice(root, interactive, interrupted=True)
    if "--download-update" in arguments:
        return native_update_notice(root, interactive)
    if "--check-updates" in arguments:
        return check_updates(root, interactive)
    for option, path in (("--package", root / "windows"), ("--install-root", root / "GameData")):
        if not any(arg == option or arg.startswith(option + "=") for arg in arguments):
            arguments[:0] = [option, str(path)]
    if "--play" in arguments and not any(arg == "--auto-iso-folder" or arg.startswith("--auto-iso-folder=") for arg in arguments):
        arguments[:0] = ["--auto-iso-folder", str(root / "assets")]
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
