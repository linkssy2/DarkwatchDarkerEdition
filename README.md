# Darkwatch: Darker Edition

**Windows 0.7 · Experimental Linux/Proton 0.7**

[Release downloads](https://github.com/linkssy2/DarkwatchDarkerEdition/releases) ·
[0.7 changes and installation](docs/RELEASE-0.7.md)

An unofficial PC port of original Xbox Darkwatch, powered by
[XboxXBERecomp](https://github.com/TGP482/Xbox-XBERecomp), with Direct3D 12
rendering and statically recompiled gameplay. Supply your own supported original
Xbox ISO/XISO. Original disc files and the Microsoft XDK are not included.

## Install and update

Extract the complete Windows package to a writable folder. For automatic
first-time setup, put one supported Xbox ISO/XISO in the included **assets/**
folder and open **Darkwatch Darker Edition.exe**. Keep this ISO in place for
play and updates. An existing installation takes priority; multiple images
require explicit selection. **Select Game** also offers:

- **Use ISO directly:** verify your disc, prepare the resources that need local
  changes, and read other game files from the ISO. Keep the ISO in place.
- **Import once:** install the game locally. The ISO can be removed after setup.
- **Use Existing Install:** reuse a previous launcher folder or its GameData
  folder without duplicating its game files or saves.

Preparation can take several minutes. Choose Play when it finishes, or use
**Play Darkwatch.exe** to start directly. Normal play has no test timer.

**Manage → Check for Updates → Install Update** downloads and verifies a newer
compatible package, replaces its managed files in place, and preserves game
data, saves, settings and add-ons. For manual updates, close the game and launcher
and extract the complete new package over the old one, replacing matching files.
Keep GameData and any selected external installation or direct-mode ISO.

An upgrade from published 0.6.1 may need one final Xbox import because that
version did not retain the recovery records used for future content updates.
The launcher preserves saves, settings and compatible add-ons. See the
[release instructions](docs/RELEASE-0.7.md) for the exact options and limits.

Windows requires Windows 10 version 1903 or newer / Windows 11 x64, .NET
Framework 4.8, an x86-64-v2 CPU and a Direct3D 12 GPU supporting feature level
11_0. No administrator access is required.

Linux uses the separate experimental Proton package. Read its
[Linux instructions](launcher/linux/README-LINUX.md). The Windows runtime
payload is shared, but Linux graphics, sound, controllers and gameplay require
separate live testing. Native Linux Steam, a compatible Proton version and working Vulkan drivers are
required. Steam uses the compatibility tool you select; Proton Experimental is
one option. Steam/Proton are not bundled.

## Optional textures and Spanish

The new separate 0.7 HD pack contains five parts. Keep `.zip.001` through `.005`
together and select the first in **Manage → Install HD Textures**. Do not extract
individual parts; no parts.json is required. Enable **Graphics → HD Textures →
Apply**. The compact format preserves exact texture pixels, transparency and
mipmaps. Previous published packs remain compatible, with their prior coverage.
HD menus, fonts and HUD do not require this optional gameplay pack.

After Xbox setup, choose **Manage → Install Spanish** and provide your supported
European PAL PS2 Darkwatch ISO, SLES-53564. Select Español for the next launch.
The importer prepares text, subtitles, dialogue and matched movie soundtracks
locally. Missing or unmatched audio retains the original Xbox resources.
English remains available. Community language ZIPs are not used.

## Features and verification

- Editable keyboard, mouse and per-player controller bindings; separate zoom sensitivity.
- Separate Graphics, Controls and Audio menus with mouse and controller support,
  including a dedicated Audio entry in either player's pause menu.
- World/weapon FOV, reticle, widescreen, MSAA and cinematic presentation controls.
- Selectable characters and rotating previews for solo play and local co-op.
- Beta split-screen co-op with separate saves, protected chapter replay and
  full original single-player textures when the optional HD pack is absent.
- Starter revolver retention and optional Carry All Weapons with next/previous
  bindings and mouse-wheel cycling. Those binding rows are unavailable while
  the option is off, without erasing saved assignments.

Co-op remains beta and Linux/Proton remains experimental. Targeted tests do not
establish every campaign transition, character/weapon pairing, physical 5.1
output or complete Spanish synchronization. Empty-folder direct-ISO preparation
and file verification passed on Windows. Selected Windows menus and gameplay
received live checks; Linux gameplay still needs live testing. Small capped
failure reports remain enabled; routine development captures are disabled in player builds.

## Source

See [building](docs/BUILDING.md), [code map](docs/CODE_MAP.md),
[credits](CREDITS.md) and [release notes](docs/RELEASE-0.7.md). This snapshot
contains maintained host integration, the exact SDK patch, own-disc import
tools and synthetic tests. Generated gameplay C++, original assets, saves,
caches and private original-instruction fixtures are excluded. The player
executable contains compiled recompiled gameplay logic.
