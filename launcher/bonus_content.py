"""Enable the retained War Train and Splitter selectors on one verified disc revision."""
import hashlib

CONTENT_REVISION = "wartrain-splitter-v1"
ORIGINAL_SHA256 = "1d50aceeded11b9e9a61448d194ab02f04491dc5243f4b107b565c95602f64d1"
INSTALLED_SHA256 = "4eb33149939efc9509620887383de8d551f6bca74935dadd52b6e26ac064a21a"
PATCHES = (
    (49996321, b"\x13\x00", b"\x29\x00"),       # Wartrain.xbox = true
    (109291330, b"\xf1\x00", b"\xf3\x00"),     # XboxDynamitePickup = pc,ps2
    (109292054, b"\xf3\x00", b"\xf1\x00"),     # SplitterPickup = xbox
)


def patch_pack(source):
    """Return a checked copy; reject altered, partial, or already-patched input."""
    if hashlib.sha256(source).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Bonus content requires the unchanged supported Xbox packfile.")
    candidate = bytearray(source)
    for offset, before, after in PATCHES:
        if len(before) != 2 or len(after) != 2 or source[offset:offset + 2] != before:
            raise ValueError("The supported packfile's bonus-content selectors do not match.")
        candidate[offset:offset + 2] = after
    if hashlib.sha256(candidate).hexdigest() != INSTALLED_SHA256:
        raise ValueError("Bonus-content preparation did not produce the expected packfile.")
    return candidate
