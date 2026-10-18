# Launcher artwork

The file paths below describe retained project sources, not additional files
required beside the launcher.

The launcher uses a cleaned edit of the original North American Xbox front cover, retrieved
from the [LaunchBox Darkwatch image gallery](https://gamesdb.launchbox-app.com/games/images/5762-darkwatch).
Direct source: https://images.launchbox-app.com/45699ed6-9280-430d-84eb-fd9595bff9d1.jpg
SHA256: 7de33bb3b0b6825d897efdda2661b895f46793f07314847c5a36c1fa3ab1f477

Intermediate image: `cover-clean.png`, edited with the built-in image generator at the
user's request to remove Xbox branding, ratings, publisher logos and printed text.
The character, costume badge and moonlit setting are retained; previously covered
background is reconstructed. The untouched source remains as `cover.jpg`.
The generation prompt and source/output hashes are in `artwork-edit.json`.

Active image: `cover-darker-edition.png`. A second built-in image edit adds the
Darkwatch wordmark and DARKER EDITION subtitle to the cover itself, as requested.
Its exact prompt is retained in `artwork-title-edit.json`.

The insignia is the already approved restored Darkwatch badge from this project:
`xbexbe/hd_ui/StartScreenBadge-restored-v2.png`. It is reused unchanged in the UI,
and encoded at standard Windows icon sizes for the launcher EXE.

Darkwatch artwork and marks belong to their respective rights holders. Inclusion
in this release does not mean these artworks are freely licensed.
Original disc files, audio, movies and the generated HD texture pack are excluded
from the launcher payload. The HD pack is prepared locally from the user's ISO.

An additional clear-logo download was inspected but rejected for visible edge
artifacts; it is not used or included in the launcher package.
