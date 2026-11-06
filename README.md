# Darkwatch: Darker Edition 0.7.7 source

This source snapshot is prepared for the Windows and experimental Linux/Proton
[0.7.7 release](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7.7).
See [changes and installation](docs/RELEASE-0.7.7.md), [building](docs/BUILDING.md),
[code map](docs/CODE_MAP.md) and [credits](CREDITS.md).

Supply your own supported original Xbox disc. This is the maintained host
integration and pinned SDK patch, not the original game source. Original game
files, generated game C++, saves, caches and private gameplay captures are absent.
The official runtime is built with `./scripts/build-xbexbe.ps1 -Release` after
the initial dependency build described in BUILDING.md. Keep the Release profile
for player packages; development-only code paths are not shipped features.

The existing 0.7 HD pack remains compatible and is not included in this source
archive. Text, dialogue and compatible movie voices for Spanish, French, German
and Italian are imported locally from the player's supported PAL PS2 disc.
The optional Brazilian Portuguese text adaptation and its attribution are included;
it provides no Portuguese dubbing. See the language setup in the release notes.

Windows and Linux packages use the same runtime. Linux/Proton remains experimental;
neither a clean-machine full rebuild nor complete multilingual campaign acceptance
is established by the source checks.
