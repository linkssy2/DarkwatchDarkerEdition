# Darkwatch: Darker Edition

**PC port · Windows 0.6.1 · Experimental Linux/Proton 0.6.1**

[Release downloads](https://github.com/linkssy2/DarkwatchDarkerEdition/releases) · [0.6.1 changes and HD installation](docs/RELEASE-0.6.1.md)

An unofficial PC port of the original Xbox Darkwatch, powered by
[XboxXBERecomp by TGP482](https://github.com/TGP482/Xbox-XBERecomp), with Direct3D 12 rendering and statically recompiled gameplay. Bring your own supported original Xbox ISO or XISO. Original disc files and the Microsoft XDK are not included.

## Windows

1. Extract **Darkwatch-Darker-Edition-0.6.1-Windows-x64.zip** into a short writable folder such as `C:/Games/Darkwatch`. The source ZIP is for developers.
2. Open **Darkwatch Darker Edition.exe**, choose **Import ISO**, and select your disc image.
3. Wait for import and shader preparation to finish, then choose **Play**.

Preparing selectable characters can take several minutes. The launcher reports the current character and campaign step, with cancellation available during preparation. The 0.6.1 character content revision (`wartrain-splitter-characters-v4`) also corrects the standard, blue and red Troopers' weapon grips. Existing installations need **Import / Repair** with the Xbox disc to rebuild these resources; the optional 0.6 HD pack is unchanged.

After setup, **Play Darkwatch.exe** starts directly. Both paths prepare missing shaders before play. Normal play has no time limit.

Keep both EXEs, `payload/` and `GameData/` together. Saves, settings, imported files and game caches remain inside this portable folder. To update, extract into a new folder, copy the existing `GameData/`, then use **Import / Repair** with your original disc. This prepares the current character resources while preserving saves, settings and compatible cache. Earlier extracted installations are retained, so imports consume additional disk space. The ISO is only read. Keep your old folder until you verify your saves.

Requires Windows 10 version 1903 or newer / Windows 11 x64, .NET Framework 4.8, an x86-64-v2 CPU (including SSE4.2 and POPCNT), and a Direct3D 12 GPU supporting feature level 11_0. No administrator access is required.

## Linux / Proton

Use the **0.6.1 Linux-Proton-Experimental** archive and its [Linux instructions](launcher/linux/README-LINUX.md). The recommended route uses one Steam shortcut to the bundled Python for import, language selection, HD installation and play. Use native Steam, Proton Experimental and compatible Vulkan drivers. Steam/Proton are not bundled.

The game payload matches Windows. This is a Proton compatibility package; Linux graphics, audio, movies, controllers and gameplay still need live testing. Flatpak Steam is unverified. System Python is only needed for the optional terminal route.

## Textures and language

The optional HD pack is a separate five-part download. Keep `.zip.001` through `.005` together; in **Install HD Textures**, select `.zip.001` and let the launcher read all parts. Do not extract the parts separately. Enable **Graphics → HD Textures → Apply** after installation. The existing 0.6 HD pack is unchanged and works with 0.6.1; no new HD download is needed. Older 0.4/0.5 packs also remain compatible, with their previous coverage. HD menus, fonts and HUD are included independently.

Import the Xbox game first, then choose **Install Spanish** and provide your supported PAL PS2 Darkwatch ISO (SLES-53564). Select **Español** for the next launch. Import prepares Spanish text, subtitles, 1,481 dialogue clips and 14 compatible movie soundtracks locally. The 63 silent PS2 dialogue slots retain Xbox audio; unmatched movies stay original. Spanish movie soundtracks are stereo, while Xbox video and timestamps remain unchanged. English uses the original Xbox resources. The old community ZIP is no longer accepted. Linux uses the same importer through its Steam shortcut.

## Features

- Mouse and keyboard input, editable bindings and separate zoom sensitivity.
- Xbox, PS4, Switch Pro and paired Joy-Con controls with matching prompts and per-player button rebinding.
- Separate Graphics, Controls and Audio pages, accessible by mouse or controller.
- Widescreen, world/weapon FOV, reticle size, brightness, MSAA and in-game cutscene border controls.
- Eight selectable characters, rotating previews and a two-player co-op character selector.
- Beta local split-screen co-op, separate co-op saves and protected chapter replay.
- War Train and Splitter selector restoration, prepared from the player's supported disc.
- Local shader preparation, portable data, and a direct-start executable.

## Testing and limitations

Co-op remains beta. Full-campaign progression, every character/weapon/story transition, surround output and complete Spanish presentation have not been verified. The first mounted-boss phase was accepted in a Windows 240 FPS test; this does not verify every high-FPS encounter. Directional audio was accepted with Windows Sonic headphones; physical surround speakers and Linux audio still need live testing. Tree-damage checks remain separately scoped. Cassidy hurt audio remains unresolved. Earlier reports of snow-level crashes and missing saves are not claimed resolved by the storage safeguards. Unseen shaders, driver pipelines and loading can still cause pauses; extreme weapon FOV can expose model boundaries.

Routine logging, capture hotkeys and development probes are disabled in player builds. Failures may produce a small capped error report. The optional FPS display remains available.

## Source and credits

See [build instructions](docs/BUILDING.md), [code map](docs/CODE_MAP.md), [credits](CREDITS.md) and [release notes](docs/RELEASE-0.6.1.md). The maintained source includes host integration, SDK patches, import tools and selected synthetic tests. Generated gameplay code, original game archives, private instruction fixtures, installed saves and caches are excluded. The compiled player executable contains recompiled gameplay logic.
