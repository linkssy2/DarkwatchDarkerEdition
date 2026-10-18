# Darkwatch: Darker Edition

**PC port · Version 0.2 · Windows x64 · Community testing**

**[Download Darkwatch: Darker Edition 0.2 for Windows](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/download/v0.2/Darkwatch-Darker-Edition-0.2-Windows-x64.zip)**

[Latest release and download files](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/latest)
· [Version 0.2 release notes](docs/RELEASE-0.2.md)

An unofficial PC port of the original Xbox Darkwatch, powered by
[XboxXBERecomp by TGP482](https://github.com/TGP482/Xbox-XBERecomp), with native
Direct3D 12 rendering and statically recompiled original gameplay. Bring your
own supported Xbox disc image: original game files are not included.

## Install

1. Download **Darkwatch-Darker-Edition-0.2-Windows-x64.zip** using the link above.
   Choose the Windows package to play; the source archive is for development.
2. Extract the entire folder to a short writable location, such as `C:/Games/Darkwatch`.
3. Open **Darkwatch Darker Edition.exe**, choose **Import ISO**, and select your
   supported original Xbox `.iso` or `.xiso`.
4. Wait for import and shader preparation to finish, then choose **Play**.

After setup, **Play Darkwatch.exe** starts directly. Both launch paths prepare
missing shaders before gameplay. Normal play has no time limit.

Keep both EXEs, `payload/`, and `GameData/` together. Imported files, saves,
bindings, graphics settings and shader cache stay inside the portable folder.
The ISO is needed for import or repair, not normal play. For this update, extract
into a new folder, copy your existing `GameData/` into it, and use **Import / Repair**
with your original ISO or XISO. Reimport is required to enable the bonus content;
setup preserves saves, settings and compatible shader cache. Keep the old folder
until you have checked your saves.

Requires Windows 10 version 1903 or newer / Windows 11 x64, .NET Framework 4.8,
an x86-64-v2 CPU (including SSE4.2 and POPCNT), and a Direct3D 12 GPU supporting
feature level 11_0. Runtime dependencies are included locally; setup does not
install system components or require administrator access.

## Features

- Mouse-friendly menus, editable bindings and direct mouse aiming on foot and horseback.
- Xbox, PS4, Switch Pro and paired Joy-Con controls with matching button prompts.
- Graphics and Controls pages accessible from the main menu and Pause.
- Widescreen framing, resolution and internal scale, FOV, reticle size, MSAA,
  anisotropic filtering and optional FPS display.
- Optional restored HD menus, fonts and HUD, plus enhanced intro slides. Videos remain original.
- Local shader preparation, portable saves and **Quit to Desktop** in the main menu.

## Version 0.2

This full Windows package carries forward the changes introduced in 0.1.1 Test 1:

- Enables the retained **War Train** chapter and **Splitter Grenade** campaign
  placements from the supported Xbox disc. Paired Xbox dynamite replacements are
  disabled to avoid duplicate pickups; ordinary dynamite is unchanged. Original
  campaign progression is retained. No PS2 disc or downloaded game files are used.
- Corrects an actor-script timing gate that skipped updates above 100 FPS,
  linked to the first door staying closed at 144 FPS. Other high-FPS physics or
  event differences may remain.
- Enables direct mouse aiming during vampire jumps by accepting the original
  derived jump state in the existing look path.

After picking up Splitter Grenades, use the D-pad Up action (**Up Arrow** by
default) to change grenade type. These changes pass focused offline checks;
the first door at 144 FPS, vampire-jump aiming, War Train progression and grenade
behavior still need live acceptance testing.

**Esc pauses; right-click goes back in menus.** Switch buttons use physical
positions: **B selects, A goes back**. PS4 uses Cross to select, Circle to go back.
Controllers presented as Xbox by a remapper show Xbox prompts. A single Joy-Con
does not provide the complete dual-stick controls.

## Supported disc and limitations

Setup checks all 23 files of the supported North American Xbox revision. Both
full Xbox ISO and trimmed XISO layouts work. Other revisions are rejected.
The required `default.xbe` SHA-256 is
`72fc8033e01df4f22c703121cfd160969c642b18e841248224fc97a8f32050d7`.
Allow at least 4.5 GB per import plus saves/cache. The source disc image is read only.

Version 0.2 is available for community testing. Earlier user testing reached gameplay, the opening boss
and horse riding; the fresh-import shader preparation test had no noticeable
stutters on the opening route. Full-campaign completion, online play, fresh
Windows and physical PS4/Switch testing remain unverified. Unseen shaders,
driver pipelines and loading may still cause pauses.

Routine logging, capture hotkeys, debug output and development probes are disabled
in the player build. A failure can produce a small capped local error report.
The FPS display remains an optional graphics setting.

## Source

See [build notes](docs/BUILDING.md), [code map](docs/CODE_MAP.md),
[credits](CREDITS.md) and [version 0.2 release notes](docs/RELEASE-0.2.md).
The source snapshot contains maintained integration, SDK patches, launcher/import
code and selected tests. It excludes generated title code, disassembly, original
disc files, private research, captures, saves and build output. Standalone setup
still needs locally provisioned build dependencies; see the build notes.

Approved restored artwork and launcher branding are included as enhancements;
they are not an original disc asset pack. The HD texture pack is prepared locally
from the player's verified import. Original content and marks belong to their
owners; see [artwork provenance](launcher/assets/SOURCES.md) and [notices](COPYRIGHT).
