"""Run with the packaged Windows Python; keep Proton alive while its game runs."""

from pathlib import Path
import sys
import time


def run(backend, arguments):
    code = backend.main(arguments)
    if code == 0 and "--play" in arguments:
        # The Windows launcher stays outside Wine; this adapter must keep the container alive.
        while backend.game_running():
            time.sleep(1)
    return code


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows/payload"))
    import setup_backend

    raise SystemExit(run(setup_backend, sys.argv[1:]))
