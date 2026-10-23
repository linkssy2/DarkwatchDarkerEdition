# Darkwatch: Darker Edition 0.5.5 — Experimental Linux / Proton

This package runs the Windows port through Proton. Darkwatch's Linux graphics,
audio, movies and controls still need live testing. Co-op remains beta. Supply
your own supported original Xbox Darkwatch ISO or XISO.

## Recommended: setup and play through Steam

Use native Linux Steam with Proton Experimental and working Vulkan graphics
drivers. Let Steam finish downloading Proton and its required runtime. Flatpak
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
   Under **Compatibility**, force **Proton Experimental**.
4. Put your own disc image in the package folder as `game.iso` (or `game.xiso`).
   Set **Launch Options** to the following, matching your disc's filename:

   ```text
   -B "linux/run_backend.py" --interactive --import-iso "game.iso"
   ```

5. Click **Play** in Steam and acknowledge the setup dialog. Keep Steam running
   while import, verification and shader preparation finish; this can take
   several minutes. A completion or error dialog appears when setup ends.
   Steam does not show a progress bar for this route. Import does not start the
   game automatically.
6. After successful setup, change **Launch Options** on the **same shortcut** to:

   ```text
   -B "linux/run_backend.py" --interactive --play
   ```

Click **Play** to start Darkwatch. Keep the same Target, Start In and compatibility
setting for import, verification, HD installation and play. Do not create a new
shortcut for each action or force Proton around `Darkwatch.sh`.

The shortcut starts the bundled setup Python directly, bypassing the Windows
graphical launcher. A failure saves a small `last-setup-error.txt` beside this
README when that folder is writable. If even the first dialog never appears,
Python/Proton may not have started: launch Steam from a terminal and keep its
error output. Do not edit manifest hashes or disable verification.

## Optional HD textures

The existing 0.5 HD download works with this package. Download **all five** files
`Darkwatch-Darker-Edition-0.5-HD-Textures.zip.001` through `.005`. Keep the names
unchanged and put all five parts together in the package folder. Close Darkwatch,
then temporarily change the same Steam shortcut's Launch Options to:

```text
-B "linux/run_backend.py" --interactive --install-hd-textures "Darkwatch-Darker-Edition-0.5-HD-Textures.zip.001"
```

Click Play, wait for the completion dialog, then restore the `--play` command.
The installer reads the other parts automatically. Enable **Graphics → HD
Textures** in the game, then choose **Apply**. Do not extract or install each numbered part separately.

To verify installed files, use this command in Launch Options and then restore
the play command:

```text
-B "linux/run_backend.py" --interactive --verify
```

## Saves and updating

Game files, saves, settings and game caches stay in the package's `GameData/`.
For the recommended route, Steam manages the Proton prefix for the shortcut;
it is not stored in the package. Retain the same shortcut when updating.

Close the game and Steam shortcut, extract the new archive into a separate
folder, and copy your existing `GameData/` into it. Point the existing shortcut's
**Target** to the new `windows/payload/python/python.exe` and **Start In** to the
new package folder. Use the import command with your own disc to repair the
installation with the new runtime, then restore the play command. Saves,
settings, the optional HD pack and compatible completed game shader caches are
preserved. Keep the old folder until the new installation and saves are checked.

If moving from the terminal route below, copy `GameData/` and keep the old
`.proton/` as a backup. The Steam shortcut uses its own prefix and may rebuild
driver caches. Do not move or delete Steam's prefix while it is running.

## Optional terminal route

The terminal route also needs Python 3.9 or newer. It invokes the installed
Steam Linux Runtime itself, instead of Steam launching the executable. This
route has separate compatibility limits and is not the tester-accepted Urban
Chaos Steam shortcut route.

In native Steam's Library, enable **Tools**, install **Proton Experimental**,
and install its matching **Steam Linux Runtime**. In the extracted folder:

```sh
./Darkwatch.sh
```

Choose Import, let shader preparation finish, then choose Play. The menu also
offers HD installation, Verify and Status. Leave the terminal open during play.
Commands are also available:

```sh
./Darkwatch.sh --import-iso "/home/me/Games/Darkwatch.iso"
./Darkwatch.sh --install-hd-textures "/home/me/Downloads/Darkwatch-Darker-Edition-0.5-HD-Textures.zip.001"
./Darkwatch.sh --status
./Darkwatch.sh --verify
./Darkwatch.sh --play
```

A missing-runtime error gives the required Steam app ID. Install that runtime
through Steam's Tools list. If Steam or Proton is elsewhere, add
`--steam-root "/path/to/Steam"` and/or `--proton "/path/to/Proton - Experimental"`
before the action. The launcher follows the installed Proton manifest. Use
folder names without colons or backslashes. Spaces and Unicode are supported.
Flatpak Steam is not supported by this terminal wrapper.

This route keeps its prefix and driver caches in the package's hidden
`.proton/`. Preserve both `GameData/` and `.proton/` when moving or updating a
terminal installation. Press Ctrl+C once to request setup cancellation and
allow rollback. Close Darkwatch before import, repair or HD installation.

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
