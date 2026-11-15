"""Immutable installation choices; old receipts retain their enhanced content."""
import os
from pathlib import Path

import bonus_content
import character_content

ORIGINAL_REVISION = 'original-playable-characters-v1'
ORIGINAL = {
    'packfile.pck': (110109318, bonus_content.INSTALLED_SHA256),
    'LvlSingl.pck': (207710373, 'ee1af353ad47b929b019e0b75ec605d980e8ef96466fb304277199665b4feaf5'),
    'audio.pck': (137741272, 'ffa551a20dbe3abf0eb6359011fe62a693f7f8b67822920f2bb9d31fe77c2d43'),
}


def selected(metadata):
    value = metadata.get('content_profile', 'enhanced')
    if value not in ('original', 'enhanced'):
        raise ValueError('Unknown installation content choice; repair the installation record.')
    return value


def choose(previous, requested=None):
    if previous:
        current = selected(previous)
        if requested is not None and requested != current:
            raise ValueError('Content choices apply to fresh installations only. Existing content and saves were kept.')
        return current
    return selected({'content_profile': requested or 'original'})


def revision(metadata):
    return ORIGINAL_REVISION if selected(metadata) == 'original' else character_content.CONTENT_REVISION


def files(metadata):
    return ORIGINAL if selected(metadata) == 'original' else character_content.INSTALLED


def prepare(assets, payload, cancel, progress, *, profile, previous_assets=None):
    if selected({'content_profile': profile}) == 'enhanced':
        return character_content.prepare(assets, payload, cancel, progress, previous_assets=previous_assets)
    assets = Path(assets)
    metadata = character_content.catalog(Path(payload))
    for name in ORIGINAL:
        character_content.checked_file(assets / name, metadata['originals'][name], cancel)
    progress('Preparing original playable characters, models and animations...')
    target = assets / 'packfile.pck.original.tmp'
    try:
        target.write_bytes(bonus_content.patch_pack((assets / 'packfile.pck').read_bytes()))
        size, digest = ORIGINAL['packfile.pck']
        character_content.checked_file(target, {'size': size, 'sha256': digest}, cancel)
        cancel()
        os.replace(target, assets / 'packfile.pck')
    finally:
        target.unlink(missing_ok=True)
