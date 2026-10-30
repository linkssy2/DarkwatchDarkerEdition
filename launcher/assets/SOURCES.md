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
Original disc files, audio and movies are excluded from the launcher payload.
Setup prepares the included HD interface using the user's verified disc. The
optional gameplay HD texture pack is a separate download installed through the launcher.

An additional clear-logo download was inspected but rejected for visible edge
artifacts; it is not used or included in the launcher package.

## Selectable Cassidy first-person repaint

`cassidy-hands-1024.dds` and `cassidy-hands-256.dds` contain only the approved
reconstructed hand/arm repaint pixels, including their mip chains. They are
encoded from the user-approved `cassidy-pov-atlas-repaint-v2.png` (SHA256
`65a49b71b2aeb107d82cac377740fd320b639bb6df5e2394bb5cb0c3e97d0c0c`).
The 1024-square image is resized with Lanczos and its lower levels with box
filtering; the 256-square companion is resized from that image with Lanczos.
The output uses DXT1 compression. The packaged DDS hashes are
`73ca5d8c1ab1451c8863ee91139678f28af63b992934090acf233433ebabb3a3`
and `fee9d7abf2f7b0100937f576c0bd1564c71f06b0d07b9ece14300d51c8f5113f`.

The launcher combines these pixels with the importing player's original model;
the original geometry, animation, audio, and modified game archives are not
shipped. Character animation and archive conversion are performed locally from
the verified disc, using the hash-only `character-catalog.json` manifest.

## Regular Tala first-person repaint

`tala-hands-1024.dds` and `tala-hands-256.dds` are a dedicated black-leather
repaint fitted to the original first-person UV layout. The built-in image
generator edited the project's authored Cassidy atlas using regular Tala's
outfit as a style reference. The full prompt and image provenance are retained in the project records.
The authored source PNG SHA256 is
`3652d0615bea8f46f592f231324d3b9a663413c03a73f186d09a65c50a49b879`.
Lanczos resizing and box-filtered DXT1 mip chains use the same encoding method
as the Cassidy repaint. DDS SHA256 values are
`0a129bc58ffe9639b0b9ff62c670380c36951d203f697aa7505a383fcb9b02b2`
and `2036c65069474ce6cab9bcba9db9396e59a3146416f90b1df5d629c0e75d479d`.
The user's disc supplies the unchanged first-person geometry, UVs, rig and
animations during setup; no original model or converted archive is bundled.
