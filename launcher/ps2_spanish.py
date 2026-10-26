"""Prepare optional Spanish media from a verified, user-owned PS2 PAL disc."""
import hashlib
import os
from pathlib import Path
import zipfile

from gameplay_hd import checked
from ps2_disc import Iso, Pck, require
import ps2_dialogue
import ps2_movies
import ps2_text

PS2 = {
    "PACKFILE.PCK": (181235029, "8f96dc906a0af489b60ef281dd90d26ab0314939cb5d68f4ac3879543811a4ad"),
    "AUDIO.PCK": (1597867976, "6afd1a2a79471b0ce560a39dbb945d114d819c5c7f9d0a41e90493518dd5e1d3"),
    "MOVIES.PCK": (947103885, "986431e197f574522a8a6c64135190df09f0a98c793648fd14208d12a5ec700b"),
}
XBOX = {
    "audioDlg.pck": (67086949, "19f7e69d11a450b0d6727f9dfe1e5479eeb24a1c81c6ee92e5b5c58a46355c2e"),
    "Movies2.pck": (292771016, "9f4315e71e425494f66586bdde078492c2b3736e75e45336edd90883d9e215b1"),
    "Movies3.pck": (213652752, "2296df85db6a8495f415a5334359e3c94cf9fda8e5e70efe0781ed5b8fc97853"),
    "Movies4.pck": (207535376, "ab38c23e833931b4a59ce710a1db4bec3d9fcc9e4704fc56f24115528d9811a9"),
}


def pinned_file(path, pin, cancel):
    require(path.stat().st_size == pin[0], "Incompatible original Xbox file: " + path.name)
    digest, result = hashlib.sha256(), bytearray()
    with path.open("rb") as source:
        while block := source.read(8 * 1024 ** 2):
            cancel()
            result.extend(block)
            require(len(result) <= pin[0], "Xbox source changed during Spanish preparation.")
            digest.update(block)
    require(len(result) == pin[0] and digest.hexdigest() == pin[1],
            "Original Xbox file needs repair before Spanish import: " + path.name)
    return bytes(result)


def prepare(iso, original_assets, output_zip, cancel, notify):
    """Create a staging ZIP; the caller verifies its catalog and commits atomically."""
    iso, output_zip = Path(iso).absolute(), Path(output_zip).absolute()
    source = checked(iso.parent, iso.name)
    assets = Path(original_assets)
    require(not output_zip.exists(), "Spanish staging output already exists.")
    # Pin data archives rather than outer padding: valid dumps can have extra disc sectors.
    with Iso(source) as disc:
        initial = os.fstat(disc.stream.fileno())
        require(disc.system == "PLAYSTATION" and disc.label == "DRKWTCH"
                and disc.size("SYSTEM.CNF") <= 1024
                and b"SLES_535.64;1" in disc.read("SYSTEM.CNF"),
                "Use the supported European PS2 Darkwatch disc (SLES-53564).")
        for index, (name, pin) in enumerate(PS2.items()):
            cancel()
            notify("progress", "Verifying PS2 " + name, percent=index * 100 // len(PS2))
            require(disc.size(name) == pin[0] and disc.digest(name, cancel) == pin[1],
                    "PS2 Spanish disc data is damaged or unsupported: " + name)
        audio, movies = (Pck(disc, name) for name in ("AUDIO.PCK", "MOVIES.PCK"))
        cancel()
        notify("progress", "Preparing Spanish text and subtitles from your disc", percent=0)
        # Character imports change the archive; the converter checks the original text contexts.
        with checked(assets, "packfile.pck").open("rb") as original:
            text_source = original.read(256 * 1024 ** 2 + 1)
        require(len(text_source) <= 256 * 1024 ** 2, "Xbox text archive exceeds the supported size.")
        cancel()
        text = ps2_text.convert(Pck(disc, "PACKFILE.PCK"), text_source)
        del text_source
        created = False
        try:
            # Stored entries avoid an expensive second compression pass on movie data.
            with output_zip.open("xb") as target:
                created = True
                with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED, allowZip64=True) as bundle:
                    bundle.writestr("language_text.bin", text)
                    for name, pin in XBOX.items():
                        cancel()
                        notify("progress", "Verifying Xbox " + name, percent=0)
                        original = pinned_file(checked(assets, name), pin, cancel)
                        if name == "audioDlg.pck":
                            converted = ps2_dialogue.convert(audio, original, cancel, notify)
                        else:
                            converted = ps2_movies.convert(movies, original, cancel, notify)
                        cancel()
                        bundle.writestr("assets/" + name, converted)
                        del original, converted
            final = os.fstat(disc.stream.fileno())
            require((initial.st_size, initial.st_mtime_ns) == (final.st_size, final.st_mtime_ns),
                    "PS2 disc changed during Spanish preparation. Try again with a stable copy.")
            cancel()
        except BaseException:
            if created:
                output_zip.unlink(missing_ok=True)
            raise
