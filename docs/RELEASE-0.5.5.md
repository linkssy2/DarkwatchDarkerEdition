# Darkwatch: Darker Edition — 0.5.5 Linux Compatibility Test

A Linux/Proton compatibility update based on 0.5. No new Windows download is included; Windows users should use [0.5](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.5).

- Fixes shader syntax rejected by Wine's compiler and ISO imports blocked by mapped Linux drives.
- Adds direct Steam setup with visible start, completion and error dialogs, plus a small failure report.
- Keeps terminal setup available with preparation progress and clearer errors.

**Steam setup:** install native Linux Steam, Proton Experimental and working Vulkan drivers. Let Steam finish its runtime downloads. Extract the full archive into a writable folder. Add `windows/payload/python/python.exe` as a non-Steam game, set **Start In** to the extracted folder in double quotes, and force **Proton Experimental**. Put your own supported Xbox ISO/XISO in that folder as `game.iso`, then use these **Launch Options**:

```text
-B "linux/run_backend.py" --interactive --import-iso "game.iso"
```

Click Play and acknowledge the setup dialog. Keep Steam running until the completion/error dialog appears; import and shader preparation may take several minutes. After successful import, change Launch Options on the **same shortcut** to:

```text
-B "linux/run_backend.py" --interactive --play
```

**Optional HD textures:** download all five [0.5 HD parts](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.5), `.zip.001` through `.005`, keeping their names unchanged. Put them together in the package folder. Close the game and temporarily use:

```text
-B "linux/run_backend.py" --interactive --install-hd-textures "Darkwatch-Darker-Edition-0.5-HD-Textures.zip.001"
```

The installer reads every part automatically. After completion, restore the play command and enable **Graphics → HD Textures**, then choose **Apply**.

**Updating:** copy your existing `GameData/` into a fresh extraction, keep the same Steam shortcut, update its Target and Start In, then import your original disc to repair with the new runtime. Saves, settings, the optional HD pack and compatible game caches are preserved. Steam manages this route's Proton prefix. Terminal users should also preserve `.proton/`. Keep the old installation until the new one is checked.

Use real files/folders in the package and `GameData/`, not symlinks. If setup fails, include the error dialog and `last-setup-error.txt` if present. If no dialog ever appears, report that too. Do not edit manifest hashes or disable verification. See `README-LINUX.md` for full instructions and the optional `./Darkwatch.sh` terminal route.

**Live Darkwatch Linux gameplay, rendering, audio, controllers and movies still need testing. Co-op remains BETA.** Offline compiler and setup checks do not establish live Proton compatibility. Flatpak Steam is unverified. Requires your own supported disc; no original disc files, generated game source or Microsoft XDK are included.
