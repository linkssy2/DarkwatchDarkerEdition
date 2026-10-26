"""Verified Spanish text and optional voices; original disc files stay intact."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib
import uuid
import zipfile
import zlib

from gameplay_hd import checked, remove_tree

DIRECTORY = "language/es"
SETTINGS = "darkwatch_xbe_settings.toml"
ALLOWED = {"language_text.bin", "assets/audioDlg.pck", "assets/audioMu2.pck",
           *("assets/Movies%d.pck" % n for n in range(1, 5))}
LIMIT = 2 * 1024 ** 3


def selected(current):
    path = checked(current, SETTINGS)
    if not path.exists():
        return "en"
    if path.stat().st_size > 1024 * 1024:
        return "en"
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8-sig")).get("language", {})
    except (tomllib.TOMLDecodeError, UnicodeError):
        # Match the runtime's default without rewriting a damaged settings file.
        return "en"
    return "es" if isinstance(table, dict) and table.get("text") == "es" else "en"


def select(current, value):
    if value not in ("en", "es"):
        raise ValueError("Unsupported language.")
    path = checked(current, SETTINGS)
    if path.exists() and path.stat().st_size > 1024 * 1024:
        raise ValueError("Settings file is too large.")
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    parsed = tomllib.loads(text)
    # The runtime writes this simple table. Refuse exotic TOML instead of losing settings.
    section = re.search(r"(?m)^\[language\][ \t]*(?:#[^\n]*)?$", text)
    if "language" in parsed and not section:
        raise ValueError("The language settings table needs repair.")
    line = 'text = "%s"\n' % value
    if section:
        start = section.end()
        following = re.search(r"(?m)^\[", text[start:])
        end = start + following.start() if following else len(text)
        body = text[start:end]
        if "text" in parsed["language"]:
            body, count = re.subn(r"(?m)^[ \t]*text[ \t]*=[^\n]*\n?", line, body)
            if count != 1:
                raise ValueError("The language settings entry needs repair.")
        else:
            body = "\n" + line + body
        text = text[:start] + body + text[end:]
    else:
        text += "\n[language]\n" + line
    result = tomllib.loads(text)
    expected = dict(parsed)
    expected["language"] = dict(parsed.get("language", {}), text=value)
    if result != expected:
        raise ValueError("Could not preserve the existing game settings.")
    temporary = checked(current, SETTINGS + ".language.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Catalog:
    def __init__(self, raw):
        if len(raw) > 16384:
            raise ValueError("Spanish pack catalog is too large.")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid Spanish pack catalog.")
        self.files = data.get("files", {})
        if data.get("schema_version") != 1 or data.get("language") != "es" or not isinstance(self.files, dict):
            raise ValueError("Invalid Spanish pack catalog.")
        if "language_text.bin" not in self.files or not set(self.files) <= ALLOWED:
            raise ValueError("Unexpected Spanish pack resources.")
        for row in self.files.values():
            if not isinstance(row, dict) or type(row.get("size")) is not int or not 0 < row["size"] <= LIMIT or not isinstance(row.get("sha256"), str) or not re.fullmatch("[0-9a-f]{64}", row["sha256"]):
                raise ValueError("Invalid Spanish resource identity.")
        if sum(row["size"] for row in self.files.values()) > LIMIT or self.files["language_text.bin"]["size"] > 8 * 1024 ** 2:
            raise ValueError("Spanish resources exceed the size limit.")

    def validate(self, current, cancel=lambda: None, full=True):
        folder = checked(current, DIRECTORY)
        if not folder.exists():
            return False
        media = {name.removeprefix("assets/") for name in self.files if name.startswith("assets/")}
        if media:
            assets = checked(folder, "assets")
            if not assets.is_dir() or {path.name for path in assets.iterdir()} != media:
                return False
        for name, row in self.files.items():
            cancel()
            path = checked(folder, name)
            if not path.is_file() or path.stat().st_size != row["size"]:
                return False
            if full:
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    while block := source.read(8 * 1024 ** 2):
                        cancel()
                        digest.update(block)
                if digest.hexdigest() != row["sha256"]:
                    return False
        return True

    def install(self, archive, current, cancel, notify, require_closed):
        parent = checked(current, "language")
        parent.mkdir(exist_ok=True)
        stage_name = ".spanish-stage-" + uuid.uuid4().hex
        stage = checked(parent, stage_name)
        stage.mkdir()
        target = checked(parent, "es")
        backup = checked(parent, stage_name + "-previous")
        moved = committed = False
        try:
            source = checked(Path(archive).absolute().parent, Path(archive).name)
            if source.stat().st_size > LIMIT:
                raise ValueError("Spanish download exceeds the size limit.")
            with zipfile.ZipFile(source) as bundle:
                entries = bundle.infolist()
                if len(entries) != len(self.files) or {e.filename for e in entries} != set(self.files):
                    raise ValueError("Choose the complete matching Spanish language ZIP.")
                for index, entry in enumerate(entries):
                    row = self.files[entry.filename]
                    mode = entry.external_attr >> 16
                    if entry.file_size != row["size"] or entry.flag_bits & 1 or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)):
                        raise ValueError("Invalid Spanish resource in download.")
                    destination = checked(stage, entry.filename)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    digest, total = hashlib.sha256(), 0
                    with bundle.open(entry) as src, destination.open("xb") as out:
                        while block := src.read(8 * 1024 ** 2):
                            cancel()
                            total += len(block)
                            if total > row["size"]:
                                raise ValueError("Spanish resource exceeds its declared size.")
                            digest.update(block)
                            out.write(block)
                    if total != row["size"] or digest.hexdigest() != row["sha256"]:
                        raise ValueError("Spanish download is damaged or incompatible.")
                    notify("progress", "Installing Spanish resources", percent=int(100 * (index + 1) / len(entries)))
            cancel()
            require_closed()
            if target.exists():
                # Retain the previous pack on disk, including any unrelated user files.
                os.replace(target, backup)
                moved = True
            try:
                os.replace(stage, target)
                committed = True
            except OSError:
                if moved:
                    os.replace(backup, target)
                raise
        except (zipfile.BadZipFile, zlib.error, EOFError) as error:
            raise ValueError("Spanish download is damaged or incompatible.") from error
        finally:
            if not committed:
                remove_tree(parent, stage_name)

    def preserve(self, previous, stage, cancel, copy):
        if not previous or not self.validate(previous, cancel):
            return False
        for name in self.files:
            target = checked(stage, DIRECTORY + "/" + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            copy(checked(previous, DIRECTORY + "/" + name), target)
        if not self.validate(stage, cancel):
            raise ValueError("Could not preserve the Spanish language pack.")
        return True
