# Darkwatch: Darker Edition 0.7

Changes since 0.6.1:

- **Choose how to use your disc:** Put one supported Xbox ISO/XISO in the included assets folder and open the launcher for automatic first-time setup. Select Game also offers direct Xbox ISO playback, import-once installation, or reuse of an existing installation. Direct ISO mode keeps the disc image in use and copies only the resources that need preparation. Import once lets you remove the ISO after setup.
- **Faster first-time preparation:** Removed repeated resource-list rebuilding and streamlined archive writing while retaining the same verification checks and prepared game files. The content-conversion stage measured about nine times faster on the test PC. With the latest shader preparation, an empty direct-ISO installation completed in about 2 minutes 25 seconds, compared with 5 minutes 4 seconds in the preceding test. These are single-PC measurements with normal operating-system caches; setup time depends on your CPU and storage.
- **Faster shader preparation:** Added 34 more observed shader variants to first-time preparation and compile using up to four CPU workers. Completed shaders are verified and reused; failed or cancelled preparation cannot mark an installation ready. New unseen shaders and graphics-driver pipeline creation can still occur during play.
- **Simpler launcher and updates:** The ready home screen centers on Play, with files, language and textures under Manage. The launcher checks GitHub for newer compatible releases. Install Update downloads and verifies the matching package, replaces its managed files in place, and preserves your game data, saves, settings and installed add-ons. Downloads start only when you choose them.
- **Less update copying:** Updates to an extracted installation no longer temporarily copy unrelated original movies and dialogue files. Verification and preservation of installed data remain in place.
- **Linux launch choices:** Clarified how to select an installed Proton version and set environment options in Steam. Experimental is optional. The optional terminal launcher now preserves explicitly supplied Proton and driver logging settings.
- **Co-op texture quality:** With HD textures disabled or absent, co-op now uses the full original single-player world and character textures. Both modes continue to use the same optional HD replacements.
- **Split-screen proportions:** Corrected camera, HUD, text and reticle proportions in horizontal split-screen while retaining each player's FOV settings and HUD edge spacing.
- **Grenades:** Restored switching between TNT and Splitter Grenades, including the empty-grenade fallback. The two types keep their own ammo counts and refill behavior.
- **Mouse aiming and screen effects:** Mouse zoom sensitivity now reads the equipped weapon's actual zoom state. Power effects such as Silver Bullet cover the intended view instead of appearing as an inset rectangle at expanded FOV.
- **Weapons:** Fixed missing left-hand pistol attachments for Civilian Jericho and the blue/red Troopers. The starter revolver remains available after receiving the Redeemer, deals 65 base damage, and has zero random shot spread with the Redeemer's range settings. A clean headshot kills a standard opening Reaper on every difficulty in single-player and co-op; ordinary body shots still take more than one hit. Accepted Redeemer ammo refills also replenish an owned revolver; firing either weapon still uses its own ammo.
- **Campaign weapon restoration:** When the campaign returns your weapons after a story transition, it also returns the starter revolver in single-player and co-op. Authored unarmed scenes, horseback restrictions and weapon trials remain intact, and the restored revolver does not replace another carried gun.
- **Optional weapon capacity:** Added the shared, default-off Carry All Weapons cheat and separate Next/Previous Weapon bindings in Controls, including mouse-wheel cycling. These binding rows are unavailable while Carry All is off, without clearing your assignments. Turning it off keeps already collected weapons while restoring normal pickup capacity rules. Corrected weapon identification used by cycling and revolver ammo refills.
- **More playable Tala variants:** Vampire Tala and wingless Boss Tala join both single-player and co-op character selectors, with their own previews and first-person arms. The story NPC boss remains unchanged.
- **Regular Tala's gloves:** Dedicated HD black-leather artwork fits the original first-person hand rig, replacing the stretched converted hands while retaining the original weapon animations. This is included in the base update and does not require another HD-pack download.
- **Cinematics and menus:** Corrected in-engine widescreen cinematic proportions while preserving the authored horizontal framing and animated camera FOV. Chapter preview transparency removes the black rectangle behind the frame. Graphics and Controls have taller lists inside narrower panels; Audio also uses the compact scale and has its own pause-menu entry for both players.
- **Interface and stability:** Improved small HD HUD power emblems and multiplayer indicators, and corrected a campaign stream fallback involved in a reproduced Wrong Train loading crash.
- **Checkpoint caption:** Prevented expired checkpoint text from flashing during weapon changes while retaining genuine checkpoint messages and their fades.
- **HUD brightness:** Fixed the brief health-display brightness flash during weapon changes by restoring the intended interface transparency.
- **Enemy eye glow:** Corrected the rendering offset that made glowing eyes appear displaced from enemies at a distance.
- **Subtitle setting:** Subtitles can now be turned on or off from Pause → Graphics for either player, as well as from the main-menu Graphics screen. Applying the setting takes effect for subsequent dialogue or scenes; it does not recreate captions for a line already playing. This fixes the case where the menu showed On but captions stayed disabled.
- **Expanded HD pack:** A new separate pack adds reviewed campaign, character, prop, weapon and blood texture coverage, including Cassidy's story ragdoll and matching distance versions. Shared texture data reduces download duplication without losing detail, alpha or mipmaps. Existing published packs remain compatible; they cannot supply artwork that was not included in those packs.

Windows and experimental Linux/Proton use the same runtime and game preparation.
**Co-op remains beta. Linux/Proton remains experimental and needs live testing.**
Direct-ISO preparation from an empty Windows installation completed and passed
file verification, without changing the ISO. The separate compact HD pack also
installed and passed full file verification. A fresh Windows copy reached
the opening mission and pause menu in a bounded visual check; the final shader
preparation additions were then verified offline and at startup. Extended gameplay
acceptance is still pending. Targeted Windows checks and user reports do not establish full-campaign, every-character,
physical 5.1-speaker, or complete Spanish playback verification. Prerecorded
movie aspect handling is separate from the in-engine cinematic correction.

## Windows setup

Extract the complete **Darkwatch-Darker-Edition-0.7-Windows-x64.zip** into a
writable folder. Keep both EXEs and the payload folder together.

For automatic first-time setup, first put one supported Xbox ISO/XISO in the
included **assets/** folder. The launcher uses it directly and prepares the
required resources and shaders. Keep the ISO there for play and updates.
If multiple images are present, choose one in **Select Game**. Existing
installations take priority; dropping in an ISO does not replace them.

The manual **Select Game** choices remain available:

1. **Use ISO directly:** Select your supported original Xbox ISO/XISO. Keep it
   in place for play and updates. Setup still verifies the disc and prepares
   characters, the HD interface and shaders; it can take several minutes.
2. **Import once:** Copy the game locally and complete preparation. You can
   remove the ISO afterward; normal play and future updates reuse installed data.
3. **Use Existing Install:** Select a prior launcher folder or its **GameData/**
   folder. The game, saves and add-ons stay there and are reused without duplication.

Choose **Play** when setup finishes. **Play Darkwatch.exe** starts the same
prepared game without opening the launcher. Neither mode changes your source ISO.
If a directly used ISO moves, select its new location using **Use ISO directly**.

## Updating without losing your installation

Once this launcher is installed, **Manage → Check for Updates → Install Update**
downloads a newer matching release and updates this folder. Close the game first.
An interrupted replacement is recovered when the launcher next starts.

For a manual update, close the game and launcher and extract the **complete** new
package over the existing package folder, replacing matching package files.
Keep **GameData/**, any externally selected installation folder, and any ISO used
in direct mode. If using a separate new package folder instead, choose
**Use Existing Install** and point it at the original game data.

**Updating from published 0.6.1 can need one final Xbox ISO import** because its
older content lacks the small recovery records used by the new content updater.
Follow the launcher's setup prompt; saves, settings and compatible optional packs
are retained. After import-once setup with this version, future updates reuse
that recovery data without the ISO. Direct ISO mode continues using its ISO.

## Experimental Linux / Proton

Extract **Darkwatch-Darker-Edition-0.7-Linux-Proton-Experimental.tar.gz** into a
writable folder. Use native Linux Steam, an installed Proton version and working Vulkan
drivers. Keep `windows/` and `linux/` together and use real package/GameData files
rather than symlinks.

1. Add **windows/payload/python/python.exe** as a Non-Steam Game. Set **Start In**
   to the extracted package folder, in quotes. In **Properties → Compatibility**,
   enable the compatibility-tool override and select your preferred installed
   Proton version. **Experimental is optional; the launcher does not require it.**
2. Place one supported Xbox ISO/XISO in the included **assets/** folder. Set
   Launch Options to:

   ```text
   -B "linux/run_backend.py" --interactive --play
   ```

   Keep this ISO for future launches and updates.
3. Click Play and acknowledge first-time preparation. The game starts when setup
   finishes; keep the same shortcut and options for later sessions.

To choose an image explicitly, temporarily replace `--play` with
`--use-iso "assets/game.iso"`. To import once and remove the disc image after
setup, use `--import-iso "assets/game.iso"`. Restore `--play` afterward.

The Steam route does not need a terminal or `.sh` command. Change Proton in the
same shortcut whenever needed; keep `GameData/` and the shortcut to reuse your
installation. For environment options, place variables before `%command%` and
the Python arguments after it, for example:

```text
PROTON_LOG=1 %command% -B "linux/run_backend.py" --interactive --play
```

The Linux download includes the same Windows game files plus the Steam adapter;
the Windows graphical launcher has not been verified under Proton. The adapter
honors Steam's chosen tool and environment. The optional terminal wrapper now
also keeps explicit Proton/driver logging options instead of replacing them.

The optional native terminal launcher is `./Darkwatch.sh` and needs Python 3.9
or newer. Its **Manage installation → Select Game** menu offers the same choices;
`--use-iso`, `--import-iso` and `--use-installation` are also available as commands.
It defaults to Experimental; use `--proton "/path/to/Chosen Proton"` to select
another installed tool and its declared Steam Linux Runtime.

For an automatic download/update, close the game and Steam shortcut, then run
`./Darkwatch.sh --download-update` from a native Linux terminal in this folder.
For manual updates, replace matching package files in place and keep **GameData/**,
the existing Steam shortcut and **.proton/** if using the terminal route. The
Steam setup shortcut cannot safely replace its own running Python files.

## Optional Spanish from your PS2 disc

After Xbox setup, close Darkwatch, open **Manage → Install Spanish**, and select
your own **European PAL PS2 Darkwatch ISO, SLES-53564**. Choose **Español** in
the launcher's language selector. English remains available; direct play uses
the same selection. The PS2 disc supplements the required Xbox game source.

This imports Spanish text, subtitles, dialogue and 14 matched story/intro movie
soundtracks. Missing/silent entries, music and unmatched extras retain original
Xbox audio. Spanish movies use the PS2 stereo mix; English retains the Xbox mix.
Older community language ZIPs are not used.

For the Steam route, temporarily use
`-B "linux/run_backend.py" --interactive --install-spanish "Darkwatch-PS2.iso"`,
then `-B "linux/run_backend.py" --interactive --language` to choose Español.
Restore `--play` afterward. The native terminal menu also has Install Spanish and
Language / Idioma actions.

## Optional HD textures

**The existing 0.6 HD pack still works without reinstallation. The new separate
0.7 HD pack is recommended for added coverage.** Its five parts total about
**5.12 GB (4.77 GiB)** and contain 2,229 replacement files. Identical pixel data is
stored once, reducing duplication without changing texture detail, transparency
or distance mipmaps. Installation reconstructs about **18.31 GB** of texture data.
Use the **0.7 launcher** to install this new compact pack.

Earlier 0.4/0.5 packs remain compatible, with less coverage. Original textures
are retained where the installed pack has no faithful replacement. This is an
audit of available supplied artwork, not a claim that every texture has an HD
replacement; some unmatched character and world textures remain original.

For the new pack, download **Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001**
through **.005** and keep all five together with their original names. Do not mix
versions. In **Manage → Install HD Textures**, select
**Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001**.
The installer reads the other parts automatically. Do not extract individual
parts; **parts.json is not required**. Enable **Graphics → HD Textures → Apply**.
An already installed compatible pack is reused during an update. Installing the
new optional pack replaces it through the normal verified installer.

On the Steam route, temporarily use
`-B "linux/run_backend.py" --interactive --install-hd-textures "Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001"`,
then restore
`--play`. The native terminal menu also installs the pack. The older compatible
download remains on the [0.6 release page](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.6).

Powered by [XboxXBERecomp](https://github.com/TGP482/Xbox-XBERecomp). Supply your
own supported discs. Original disc files and generated game source are not
included. Normal play has no test timer; small failure reports remain available.
