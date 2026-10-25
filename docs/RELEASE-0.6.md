# Darkwatch: Darker Edition 0.6

- Eight playable characters: adds Civilian Jericho, Tala and three Darkwatch Troopers, with rotating solo previews and a redesigned two-player co-op selector.
- Per-player controller rebinding, improved co-op navigation, an updated Audio menu with optional surround output, and “Press any key” at the keyboard/mouse title screen.
- Spanish text and subtitles selectable from the launcher; optional Spanish voices can be imported separately. Missing translated voice lines retain the original audio; movies remain unchanged.
- Separate co-op saves, chapter replay that preserves campaign progress, and safer profile storage.
- Fixes for startup-video and controller-menu crashes, old-menu flashes and HUD ghosting. Includes candidate fixes for Blood Frenzy at wider FOV, the mounted boss at high FPS and character-dependent tree damage.
- Matching Windows and experimental Linux/Proton downloads, plus an updated optional HD pack for the expanded roster.

**Co-op remains beta.** Linux gameplay still needs live testing. Blood Frenzy, mounted-boss and tree fixes pass regression checks but await live encounter verification. Full-campaign saving, surround output and Spanish dialogue/timing checks are incomplete; Cassidy hurt audio remains unresolved.

## Install or update

Windows: extract **Darkwatch-Darker-Edition-0.6-Windows-x64.zip**, open **Darkwatch Darker Edition.exe**, import your supported original Xbox ISO/XISO and wait for shader preparation. **Play Darkwatch.exe** starts directly after setup.

Linux: extract **Darkwatch-Darker-Edition-0.6-Linux-Proton-Experimental.tar.gz** and follow its **README-LINUX.md**. Use native Steam and Proton Experimental with the bundled Python shortcut for import and play. This is a Proton package, not a native Linux port.

For updates, close the game, extract into a new folder and copy your existing **GameData/** into it (Linux: the package root, beside `windows/`). Use **Import / Repair** with your original disc to prepare the new character content. Keep the old folder until you have checked your saves. Each successful import retains an earlier extracted installation, so it uses additional disk space; the ISO is only read.

## Optional HD textures

Download **all five** `Darkwatch-Darker-Edition-0.6-HD-Textures.zip.001` through `.005` files into one folder, keeping their names unchanged. Close the game, choose **Install HD Textures** in the Windows launcher and select **.zip.001**. The installer reads the other parts automatically; do not extract or install them separately. Enable **Graphics → HD Textures → Apply** afterward.

On Linux, put the five parts beside **README-LINUX.md** and temporarily use this on the same Steam shortcut:

```text
-B "linux/run_backend.py" --interactive --install-hd-textures "Darkwatch-Darker-Edition-0.6-HD-Textures.zip.001"
```

After completion, restore `-B "linux/run_backend.py" --interactive --play`. The existing 0.4 and 0.5 HD packs still work; the 0.6 pack adds character coverage. The pack is optional and does not replace the included HD interface.

Powered by **XboxXBERecomp by TGP482**. Spanish community translation by **ZARF**, integrated with compatibility corrections. Original disc files, original models/audio and the Microsoft XDK are not included; supply your own game.
