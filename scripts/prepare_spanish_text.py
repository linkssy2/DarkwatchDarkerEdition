"""Prepare hashed Spanish text from locally supplied Xbox and PS2 resource archives."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
from ps2_text import catalogue, corrections, tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--ps2', type=Path, required=True)
    parser.add_argument('--corrections', type=Path,
                        default=ROOT / 'launcher/ps2-spanish-corrections.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original, ps2 = args.original.read_bytes(), args.ps2.read_bytes()
    edits = args.corrections.read_bytes()
    data, report = catalogue(tables(original), tables(ps2), corrections(edits))
    report.update(original_sha256=hashlib.sha256(original).hexdigest(),
                  ps2_sha256=hashlib.sha256(ps2).hexdigest(),
                  corrections_sha256=hashlib.sha256(edits).hexdigest(),
                  catalogue_sha256=hashlib.sha256(data).hexdigest(), catalogue_bytes=len(data),
                  game_archives_modified=False, live_verification=False)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'language_text.bin').write_bytes(data)
    (args.output / 'text-coverage.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
