# Darkwatch: Darker Edition

**PC port | Version 0.4 | Windows x64**

[Release downloads](https://github.com/linkssy2/DarkwatchDarkerEdition/releases)
| [Release notes](docs/RELEASE-0.4.md)

An unofficial PC port of the original Xbox Darkwatch, powered by
[XboxXBERecomp by TGP482](https://github.com/TGP482/Xbox-XBERecomp), with native
Direct3D 12 rendering and statically recompiled gameplay. Bring your own supported
Xbox disc image. Original game files and the Microsoft XDK are not included.

## Install

1. Extract **Darkwatch-Darker-Edition-0.4-Windows-x64.zip** into a short writable
   folder such as `C:/Games/Darkwatch`. The source ZIP is for developers.
2. Open **Darkwatch Darker Edition.exe**, choose **Import ISO**, and select your
   supported original Xbox `.iso` or `.xiso`.
3. Wait for import and shader preparation to finish, then choose **Play**.

After setup, **Play Darkwatch.exe** starts directly. Both launch paths prepare
missing shaders before gameplay. Normal play has no time limit.

Keep both EXEs, `payload/`, and `GameData/` together. Imported files, saves,
bindings, settings and shader cache remain inside the portable folder. For an
update, extract into a new folder, copy your existing `GameData/` into it, then
use **Import / Repair** with your original disc. This prepares the character
content locally while preserving saves, settings and compatible cache. Keep your
old folder until you have checked your saves.

The optional HD gameplay texture pack is a separate download. Keep all numbered
parts together and select its `.zip.001` file using **Install HD Textures** in the
launcher, or select the complete texture ZIP. The Graphics toggle is unavailable
until installation completes. HD menus, fonts and HUD are included separately;
the gameplay pack does not replace them. Videos remain original.

Requires Windows 10 version 1903 or newer / Windows 11 x64, .NET Framework 4.8,
an x86-64-v2 CPU (including SSE4.2 and POPCNT), and a Direct3D 12 GPU supporting
feature level 11_0. Dependencies are local; no administrator access is required.

## Features

- Mouse-friendly menus, editable bindings, automatic mouse input and separate zoom sensitivity.
- Xbox, PS4, Switch Pro and paired Joy-Con controls with matching prompts.
- Graphics and Controls accessible from the main menu and Pause.
- Widescreen framing, resolution/internal scale, world/weapon FOV, reticle size,
  MSAA, anisotropic filtering, brightness and optional FPS display.
- Restored HD menus, fonts and HUD; optional HD gameplay textures.
- Jericho/Cassidy selection for single-player and **BETA local split-screen co-op**
  through **Multiplayer → CO-OP**. Co-op testing is incomplete; online co-op is not supported.
- Local shader preparation, portable saves and **Quit to Desktop** confirmation.

**Esc pauses; right-click goes back in menus.** Switch buttons use physical
positions: B selects and A goes back. PS4 uses Cross and Circle. Controllers
presented as Xbox by a remapper show Xbox prompts. A single Joy-Con does not
provide the complete dual-stick controls.

The retained War Train chapter and Splitter Grenade campaign placements use your
supported Xbox disc, with no PS2 disc assets. After a Splitter pickup, use D-pad Up
(Up Arrow by default) to change grenade type. Original campaign progression is
retained. High-FPS script and vampire-jump mouse fixes from earlier releases remain.

## Supported disc and limitations

Setup verifies all 23 files of the supported North American Xbox revision. Both
full Xbox ISO and trimmed XISO layouts work; other revisions are rejected.
The required `default.xbe` SHA-256 is
`72fc8033e01df4f22c703121cfd160969c642b18e841248224fc97a8f32050d7`.
Allow at least 5 GB per import plus saves/cache and optional HD textures.

Cassidy checkpoint loading and melee voice
replacement received user confirmation on earlier candidates; Cassidy hurt
sounds remain unresolved. Subtitle afterimages, distant eye-glow alignment,
the reported pipe-room performance issue and an unreproduced Controls crash
remain open. Full co-op gameplay, full-campaign completion, fresh Windows and
physical PS4/Switch acceptance remain unverified. This combined release has
not been live-tested. Unseen shaders, driver pipelines and loading may still
cause pauses. Extreme weapon FOV can expose original model boundaries.

Routine recording, capture hotkeys and development probes are disabled in the
player build. A failure may produce a small capped error report. The optional
FPS display remains available.

## Source

See [build notes](docs/BUILDING.md), [code map](docs/CODE_MAP.md),
[credits](CREDITS.md) and [release notes](docs/RELEASE-0.4.md).
This snapshot contains maintained integration, SDK patches, import code and
selected synthetic tests. Generated game code, original disc files, disassembly,
private research, captures, saves and build output are excluded. The compiled
player executable contains recompiled gameplay; it is not only a generic launcher.

Approved restored artwork and launcher branding are included as enhancements.
Character archives are reconstructed locally from the player's verified disc;
original models, animations and voices are not shipped. Artwork and original
marks remain with their owners; see [provenance](launcher/assets/SOURCES.md)
and [notices](COPYRIGHT). No original game source or XDK distribution is included.
