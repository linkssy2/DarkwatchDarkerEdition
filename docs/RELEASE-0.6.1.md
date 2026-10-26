# Darkwatch: Darker Edition 0.6.1

Changes since 0.6:

- **Co-op loading:** Increased string-storage capacity to address a reproduced loading crash when entering the next Torture Maze room.
- **Co-op views:** Each player's Pause → Graphics keeps separate world FOV, weapon FOV and reticle size. Controller settings remain separate; display-wide options stay shared.
- **Horseback boss:** Fixed Lazarus getting stuck during his first mounted attack phase at high frame rates, confirmed working at 240 FPS.
- **Directional audio:** Corrected positional panning and surround routing. Left/right and front/back movement was confirmed with Windows Sonic headphones.
- **Spanish from your PS2 disc:** Install Spanish text, subtitles, dialogue and 14 matched story/intro movie soundtracks from your supported PAL PS2 ISO. Select English or Español in the launcher. The old community-pack dependency is removed.
- **Trooper weapons:** Restored the authored weapon grip for standard, red and blue Troopers.
- **Installer progress:** Character preparation shows progress and handles cancellation more responsively. This step can still take several minutes.
- **Windows and Linux:** Both downloads contain the same updated runtime and importer. Keep using the existing HD pack.

**Testing:** Co-op remains beta and Linux/Proton remains experimental. Linux gameplay, physical 5.1 speakers, broader Spanish playback/synchronization and wider campaign transitions still need live testing. The loading fix addresses the reproduced failure; the boss confirmation covers the reported phase.

## Windows and updating

Extract **Darkwatch-Darker-Edition-0.6.1-Windows-x64.zip**, open **Darkwatch Darker Edition.exe**, and import your original Xbox ISO/XISO. Wait for verification and shader preparation. **Play Darkwatch.exe** starts the installed game directly.

**Updating requires Import / Repair with your Xbox ISO to rebuild the updated character data.** Close the game, extract to a new folder, copy your previous **GameData/** into it, then run Import / Repair. Saves, settings and compatible optional packs are preserved. Keep the old folder until your saves are checked. Repair retains the previous extracted installation and needs additional disk space; it only reads your ISO.

## Optional Spanish

After Xbox setup, select **Install Spanish** and choose your own **European PAL PS2 Darkwatch ISO, SLES-53564**, then choose **Español**. The PS2 disc supplements the required Xbox installation. Direct play uses the same language choice.

The import supplies 1,481 dialogue recordings; 63 missing/silent entries retain Xbox audio. Matched Spanish movies use the PS2 stereo mix; unmatched movies, music and extras stay original. English keeps the Xbox movie mix. Older Spanish ZIPs are no longer accepted. If an older language installation needs repair, import the supported PS2 ISO or select English; existing files remain intact until replacement succeeds.

## Experimental Linux / Proton

Extract **Darkwatch-Darker-Edition-0.6.1-Linux-Proton-Experimental.tar.gz** into a writable folder. Use native Linux Steam, **Proton Experimental** and working Vulkan drivers. Live Linux testing is still needed.

1. Add **windows/payload/python/python.exe** as a Non-Steam Game. Set **Start In** to the extracted package folder, in quotes. Force **Proton Experimental** under Compatibility.
2. Put your Xbox ISO/XISO in that folder. For `game.iso`, use Launch Options:

   ```text
   -B "linux/run_backend.py" --interactive --import-iso "game.iso"
   ```

3. Click Play and wait for completion. Change the **same shortcut's** Launch Options to:

   ```text
   -B "linux/run_backend.py" --interactive --play
   ```

For updates, copy old **GameData/** beside the new `windows/` folder, update the existing shortcut's paths, repeat the import command, then restore `--play`. Use real files/folders for the package and GameData, not symlinks.

For Spanish, place your supported PS2 ISO in the package folder and temporarily use:

```text
-B "linux/run_backend.py" --interactive --install-spanish "Darkwatch-PS2.iso"
```

Then use `-B "linux/run_backend.py" --interactive --language` to choose the language and restore `--play`. Close the game before setup or language changes.

## Optional HD textures

**Reuse the 0.6 HD pack—no new HD download is needed.** Earlier 0.4/0.5 packs also work, with less character coverage. The complete pack is on the [0.6 release page](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.6).

Keep all five **Darkwatch-Darker-Edition-0.6-HD-Textures.zip.001** through **.005** files together with their original names. Choose **Install HD Textures** and select **.zip.001**. The installer reads the remaining parts automatically. Do not extract individual parts; `parts.json` is unnecessary. Enable **Graphics → HD Textures → Apply** afterward.

On Linux, place all five parts in the package folder and temporarily use:

```text
-B "linux/run_backend.py" --interactive --install-hd-textures "Darkwatch-Darker-Edition-0.6-HD-Textures.zip.001"
```

Restore `--play` afterward. Incomplete downloads or browser-added suffixes such as `(1)` prevent the parts from matching.

For surround speakers, configure the actual speaker layout in Windows and select **Surround** in Audio. For spatial headphones, enable Windows spatial audio and restart the game before selecting Surround.

Powered by **[XboxXBERecomp by TGP482](https://github.com/TGP482/Xbox-XBERecomp)**. Supply your own discs. Original disc assets, generated game source and the Microsoft XDK are not included. Normal play has no test timer or diagnostic tracing; small failure reports remain available.
