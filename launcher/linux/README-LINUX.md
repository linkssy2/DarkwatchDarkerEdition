# Darkwatch: Darker Edition 0.7 — Experimental Linux / Proton

This package runs the Windows port through Proton. Darkwatch's Linux graphics,
audio, movies and controls still need live testing. Co-op remains beta. Supply
your own supported original Xbox Darkwatch ISO or XISO.

Both the Steam shortcut below and the native `Darkwatch.sh` launcher support
automatic first-time setup from one supported Xbox ISO/XISO in `assets/`.
They prepare direct ISO playback through Proton; leave the ISO in that folder.
Existing installations are reused. Multiple images require choosing one, and
unsupported discs are rejected.

## Recommended: setup and play through Steam

Use native Linux Steam and working Vulkan graphics drivers. Choose the installed
Proton version you want in Steam; **Experimental is optional, not required by
the launcher**. Let Steam finish downloading that Proton version and its required runtime. Flatpak
Steam has not been verified. No system Python or Windows graphical launcher
setup is required for this route.

1. Extract the entire archive into a writable Linux folder. Keep `windows/`
   and `linux/` together. Use real files and folders for the package and
   `GameData/`, not symlinks.
2. In Steam, choose **Games → Add a Non-Steam Game → Browse**. Change the file
   filter to show all files, then select **windows/payload/python/python.exe**
   inside the extracted folder.
3. Open that shortcut's **Properties**. Set **Start In** to the extracted
   package folder, in double quotes. For example: `"/home/me/Games/Darkwatch"`.
   Under **Compatibility**, enable **Force the use of a specific Steam Play
   compatibility tool**, then select your preferred installed Proton version.
4. Put one supported Xbox ISO/XISO in the included `assets/` folder; its filename
   does not matter. Set **Launch Options** to:

   ```text
   -B "linux/run_backend.py" --interactive --play
   ```

   This uses **direct ISO playback**: keep the ISO in `assets/` for play and
   updates. Only the resources requiring preparation are copied locally.

5. Click **Play** in Steam and acknowledge the setup dialog. Keep Steam running
   while verification and shader preparation finish; this can take several
   minutes. The game starts afterward, or an error dialog explains the problem.
   Steam does not show a progress bar for this route.
6. Keep the same **Launch Options** for later sessions. The prepared installation
   is reused and is not imported again.

To select a particular ISO when several are present, temporarily replace
`--play` with `--use-iso "assets/game.iso"`, using its actual filename. To copy
the complete game once and remove the ISO afterward, use
`--import-iso "assets/game.iso"` instead. These explicit setup actions stop
after completion; restore `--play` to start the game.

Click **Play** to start Darkwatch. Keep the same Target, Start In and compatibility
setting for import, verification, HD installation and play. Do not create a new
shortcut for each action or force Proton around `Darkwatch.sh`.

The shortcut starts the bundled setup Python directly, bypassing the Windows
graphical launcher. A failure saves a small `last-setup-error.txt` beside this
README when that folder is writable. If neither the first setup dialog nor the game appears,
Python/Proton may not have started: launch Steam from a terminal and keep its
error output. Do not edit manifest hashes or disable verification.

### Choosing Proton and environment options

You can change Proton later in the same shortcut's **Properties → Compatibility**.
Keep that shortcut and `GameData/`; changing the tool does not require importing
the game again. The Linux download contains the same Windows game/runtime files
plus this small Steam adapter. The adapter keeps Proton running until the game
closes. The Windows graphical launcher and its direct-play shortcut have not
been verified under Proton, so use the Linux package's bundled Python target
above instead of adding either graphical `.exe`.

Steam also accepts environment options before `%command%`. For example, to
enable Proton's own diagnostic log, use:

```text
PROTON_LOG=1 %command% -B "linux/run_backend.py" --interactive --play
```

Put any other Proton/driver variables before `%command%` and keep the Python
arguments after it. The Steam adapter leaves these options and Steam's chosen
compatibility tool unchanged. Remove the diagnostic option when finished if
you no longer need its log. This setup route needs no terminal or `.sh` command;
manual updates below can also be completed with a file manager.

## Checking for new releases

The launcher checks GitHub for a newer release that includes a Linux download.
Checks show the release page link and do not install anything automatically.
Being offline does not prevent playing. In the native terminal menu, choose
**Check / Install Updates → Download and Update** to download, verify and install the newer launcher in
the same folder. This also keeps the existing Steam shortcut path.

With the Steam route, a background check starts when you launch the game. If a
new release is found, the notice appears after you close Darkwatch. It never
waits for the network before starting or closing the game. To check immediately,
temporarily use these Launch Options on the same shortcut, then restore `--play`:

```text
-B "linux/run_backend.py" --interactive --check-updates
```

The Steam shortcut can show update notices but cannot safely replace its own
running Python files. To install an update, close Darkwatch and the Steam
shortcut, open a native Linux terminal in the extracted package folder, and run:

```sh
./Darkwatch.sh --download-update
```

This command needs native Python 3.9 or newer. It downloads and verifies the
Linux release, replaces managed launcher files in place, restarts the launcher,
and updates existing game files if installed. `GameData/`, optional packs,
saves, settings and `.proton/` stay in place. Keep the terminal open until it
finishes. Press Ctrl+C to cancel preparation; the brief file replacement finishes
or rolls back before stopping. An interrupted replacement is recovered on the
next native launcher start. If Steam reports an interrupted update, use this
same native command before playing again.

If a future release changes the bundled Python runtime, this updater asks for
a manual package update instead of replacing that runtime under Steam. Use the
manual procedure below. **Update Installation** (`--update`) only applies files
from the package already on disk; it does not download a release from GitHub.

## English / Español

Spanish requires the optional PS2 disc import described below. After installing
Spanish, close Darkwatch and temporarily set the same Steam shortcut's Launch
Options to:

```text
-B "linux/run_backend.py" --interactive --language
```

Click Play to open **Game language / Idioma del juego**. Choose **Yes / Sí** for
Español, **No** for English, or **Cancel** to keep your current language. After
the saved-language confirmation, restore the `--play` command. The language is
remembered for future launches; this selector does not appear on every play.
You can also use `--set-language es` or `--set-language en` instead of `--language`.

To install Spanish text, subtitles and voices, first import the Xbox game and
close it. Use your own European PS2 Darkwatch ISO (SLES-53564). Place the PS2 ISO
beside this README, then temporarily use this Steam Launch Options command:

```text
-B "linux/run_backend.py" --interactive --install-spanish "Darkwatch-PS2.iso"
```

Replace the filename with your disc's name. After installation, choose Español
and restore the play command. The PS2 import does not replace the required Xbox
game setup. Original game text and Spanish audio are not included in the launcher.
The source disc, saves and settings are kept. Older Spanish ZIPs are no longer
supported. Existing Spanish files remain intact until a successful PS2 import
replaces them atomically and retains a backup. If an old installation asks for
repair, import the PS2 ISO or choose English; English remains available.
The disc supplies 1,481 dialogue entries and 14 story/intro movie soundtracks.
Its 63 missing/silent entries retain Xbox audio; music and untranslated extras
stay original. Spanish movies use the PS2 stereo mix, while English retains the
Xbox movie surround mix. Live Windows and Proton playback still need verification
for this new import path.

## Optional HD textures

**The existing 0.6 HD pack still works. The new separate 0.7 pack is recommended
for expanded coverage and a smaller lossless download.** It preserves texture
detail, alpha and distance mipmaps; installed textures need the same disk space.
The expanded optional pack adds
HD textures for Cassidy's story ragdoll, corrected blood and additional campaign,
character, prop and weapon textures, including their distance versions. Older packs retain the
original textures for these additions.
Earlier 0.4 and 0.5 packs remain compatible but have less character coverage.
Download **every numbered part** of your chosen pack, keep the names unchanged,
and put them together in the package folder. Close Darkwatch,
then temporarily change the same Steam shortcut's Launch Options to:

```text
-B "linux/run_backend.py" --interactive --install-hd-textures "Darkwatch-Darker-Edition-0.6-HD-Textures.zip.001"
```

Click Play, wait for the completion dialog, then restore the `--play` command.
The installer reads the other parts automatically. Enable **Graphics → HD
Textures** in the game, then choose **Apply**. Do not extract or install each numbered part separately.
The command above uses the earlier 0.6 pack as an example. For the new 0.7 pack,
replace the filename with its first `.zip.001` part. The updated launcher also
accepts the complete texture ZIP. Do not mix parts from different pack versions.
The compact 0.7 download requires the updated launcher; `parts.json` is unnecessary.

To verify installed files, use this command in Launch Options and then restore
the play command:

```text
-B "linux/run_backend.py" --interactive --verify
```

## Saves and updating

Game files, saves, settings and game caches stay in the package's `GameData/`.
For the recommended route, Steam manages the Proton prefix for the shortcut;
it is not stored in the package. Retain the same shortcut when updating.

Close the game and Steam shortcut. For a manual update, extract the complete new
archive over the existing package folder and replace matching package files.
Keep `GameData/`, `.proton/` if present, and any retained ISO. The native
`--download-update` command above also keeps the folder and shortcut unchanged.
If you prefer a separate new package folder, point the existing shortcut's
**Target** to the new `windows/payload/python/python.exe` and **Start In** to the
new package folder. Temporarily set **Launch Options** to attach the existing
installation, replacing this example with its Wine `Z:` path:

```text
-B "linux/run_backend.py" --interactive --use-installation "Z:\home\me\Games\OldDarkwatch\GameData"
```

After that completes, use `-B "linux/run_backend.py" --interactive --update` to
apply the update, then restore `--play`. Play also applies a pending update.
The old game data stays in place and is remembered by the new launcher. Keep
that `GameData` folder; the game and saves are not duplicated. If you move it,
select its new location again. You can instead move `GameData/` into the new
package folder. Saves, settings, optional HD, Spanish resources and completed
game shader caches are preserved. Back up saves before removing old folders.
Steam must have filesystem access to that location. For the terminal launcher
below, pass the normal Linux path; it handles the Wine path and writable mount.

After **Import once** with this version, normal play and updates need no ISO.
**Use ISO directly** keeps the selected ISO required for play and updates. If it
moves, select it again with `--use-iso` at its new location. This keeps the same
installation and saves instead of creating another game copy.
Setup retains about 1 MB of private recovery data to rebuild original archive
inputs for future content updates. Older installations may need one final ISO
import to add it when content changes; runtime-only updates reuse them now.
Import/repair still keeps the previous full installation; normal updates do not
create another full copy. They stage changed files temporarily and remove the
stage on completion or cancellation. A damaged installation may still need its
source ISO for repair. The launcher never deletes your ISO.

If moving from the terminal route below, copy `GameData/` and keep the old
`.proton/` as a backup. The Steam shortcut uses its own prefix and may rebuild
driver caches. Do not move or delete Steam's prefix while it is running.

## Optional terminal route

The terminal route also needs Python 3.9 or newer. It invokes the installed
Steam Linux Runtime itself, instead of Steam launching the executable. This
route has separate compatibility limits and is not the tester-accepted Urban
Chaos Steam shortcut route.

In native Steam's Library, enable **Tools** and install Proton and its matching
**Steam Linux Runtime**. The terminal wrapper defaults to **Proton Experimental**;
select another installed version with `--proton`. In the extracted folder:

```sh
./Darkwatch.sh
```

The home menu has **Play**, **Manage installation**, **Check / Install Updates**
and **Exit**. For first-time setup, choose **Manage installation → Select Game**,
then **Use ISO directly**, **Import once**, or **Use Existing Install**. Direct
ISO mode requires keeping the ISO; import-once mode lets you remove it after
setup. Let shader preparation finish, then go Back and choose Play. If you already have
game data in another folder, choose **Manage installation → Use Existing Install**.
Manage installation also contains HD and PS2 Spanish installation, **Language /
Idioma**, Verify, Status and local installation updates. Leave the terminal open during play.
It checks for new Linux releases once in the background when the menu opens;
any notice appears when the menu refreshes. **Check / Install Updates → Check for Updates** checks again
on request. The standalone `--check-updates` command needs no Steam installation
or imported game data and never starts Proton.
Commands are also available:

```sh
./Darkwatch.sh --import-iso "/home/me/Games/Darkwatch.iso"
./Darkwatch.sh --use-iso "/home/me/Games/Darkwatch.iso"
./Darkwatch.sh --use-installation "/home/me/Games/OldDarkwatch/GameData"
./Darkwatch.sh --update
./Darkwatch.sh --check-updates
./Darkwatch.sh --download-update
./Darkwatch.sh --install-hd-textures "/home/me/Downloads/Darkwatch-Darker-Edition-0.6-HD-Textures.zip.001"
./Darkwatch.sh --set-language es
./Darkwatch.sh --set-language en
./Darkwatch.sh --install-spanish "/home/me/Games/Darkwatch-PS2.iso"
./Darkwatch.sh --status
./Darkwatch.sh --verify
./Darkwatch.sh --play
```

A missing-runtime error gives the required Steam app ID. Install that runtime
through Steam's Tools list. If Steam or Proton is elsewhere, add
`--steam-root "/path/to/Steam"` and/or `--proton "/path/to/Chosen Proton"`
before the action. The launcher follows the installed Proton manifest. Use
folder names without colons or backslashes. Spaces and Unicode are supported.
Flatpak Steam is not supported by this terminal wrapper.

For example, keep the same portable installation while choosing another tool
and passing a diagnostic option:

```sh
PROTON_LOG=1 ./Darkwatch.sh --proton "/path/to/Chosen Proton" --play
```

The wrapper preserves explicit Proton/driver options. It continues to manage
its own `.proton/` prefix, cache and container mounts so the installation stays
in the same place.

This route keeps its prefix and driver caches in the package's hidden
`.proton/`. Preserve both `GameData/` and `.proton/` when moving or updating a
terminal installation. Press Ctrl+C once to request setup cancellation and
allow rollback. Close Darkwatch before import, repair, installing optional packs
or changing language.

Linked external parents, ISO paths and shortcuts to `Darkwatch.sh` are supported.
The terminal wrapper checks that `windows/` and `GameData/` contain no native
Linux symlinks. Windows Python under Proton cannot reliably see those links,
so the direct Steam route does not provide that native check. Use real files
and directories for both routes. Proton's own prefix links are expected.

## Reporting a failure

Keep the error dialog/report or terminal output, and include your Linux
distribution, GPU/driver, Proton version and whether failure occurred during
import, shader preparation or play. Keep saves and caches while troubleshooting.
Normal play has no test timer or diagnostic logging; the optional setup report
is written only after a setup/launch failure.
