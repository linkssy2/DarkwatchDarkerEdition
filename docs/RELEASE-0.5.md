# Darkwatch: Darker Edition — 0.5

Download the [Windows build](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/download/v0.5/Darkwatch-Darker-Edition-0.5-Windows-x64.zip) or [experimental Linux/Proton package](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/download/v0.5/Darkwatch-Darker-Edition-0.5-Linux-Proton-Experimental.tar.gz). Requires your own supported Xbox ISO/XISO.

- **Spectral Cassidy:** selectable from the start in solo or co-op, with a wingless model, adapted first-person arms/hands and a story-based spectral transition for Player 2's Cassidy.
- **Character presentation:** improved hand seams, blue spectral eyes, a subtler playable aura and corrected weapon grip; removed misplaced co-op Jericho eye glow.
- **Character loading:** fixes for Cassidy and Spectral Cassidy in fresh missions, saved checkpoints and co-op selection.
- **Expanded HD pack:** added Jericho textures and missing world, NPC, enemy and prop connections across campaign/co-op, including distance variants.
- **Blood textures:** incorrect striped HD replacements now fall back to the original blood textures while other HD textures remain enabled.
- **Co-op interface:** HUDs sit nearer each player's edges; Player 2 gets the updated pause menus and their own controller settings. Removed the obsolete sign-in message.
- **Subtitles:** fixed text being affected by scene effects, duplicate afterimages and the black-background flicker when lines end.
- **Input fixes:** corrected false controller 3/4 reconnect prompts in two-player co-op and added Coyote vehicle mouse-look support.
- **Experimental Linux:** a Proton launcher for disc import, shader preparation, HD installation and play, with portable saves and caches.

**Updating:** extract into a new folder, copy your existing `GameData` folder, then use **Import / Repair** with your disc. Keep the old installation until you have checked your saves.

**Installing the optional HD pack:**

1. Download all five `Darkwatch-Darker-Edition-0.5-HD-Textures.zip.001` through `.005` parts into the same folder. Keep the filenames unchanged; do not extract or join them manually.
2. Close the game. In the Windows launcher, choose **Install HD Textures** and select `.zip.001`. On Linux, run `./Darkwatch.sh`, choose **3 — Install HD texture pack**, and select the same file. The launcher reads the remaining parts automatically.
3. After installation, launch the game and enable **Graphics → HD Textures**.

The 0.4 HD pack remains compatible; install the new pack for the added coverage. HD menus, fonts and HUD remain included with the base build.

**Known limits:** co-op remains **BETA**. Linux gameplay/audio/controllers, full-campaign completion, story transitions and the reported controller/Coyote fixes still need broader live testing. Cassidy hurt audio remains unresolved. Corrected HD blood artwork is not included; this build uses the fallback described above.

No original disc files, Microsoft XDK or generated game source are included. Built with [XboxXBERecomp by TGP482](https://github.com/TGP482/Xbox-XBERecomp); see included credits and notices.
