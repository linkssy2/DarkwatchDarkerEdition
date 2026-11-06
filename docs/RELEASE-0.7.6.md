# Darkwatch: Darker Edition 0.7.6 — Ultrawide

Changes since 0.7.5:

- **Ultrawide displays:** Adds 21:9 and 32:9 choices, plus Automatic aspect ratio that follows the display's actual proportions. Existing 4:3 and 16:9 choices remain available. Existing installations should select **Graphics → Aspect Ratio → Automatic** to use their display's full width.
- **Gameplay and co-op:** Expands the horizontal view while preserving vertical framing. Health and ammo remain anchored to their edges, reticles stay centered, and each horizontal co-op view gets its own correctly proportioned HUD.
- **Menus and subtitles:** Keeps artwork and text proportional, with matching mouse targets. Pause shading, loading transitions, warnings and screen effects cover the wider display.
- **Movies and in-game cinematics:** Preserves FMV proportions in Original and Fill modes, retaining the reviewed black-border crops. In-game cinematics gain the wider view while retaining their previous vertical framing and correctly sized cinematic borders.
- **Linux without Steam:** Adds an optional umu-launcher route to the existing setup, play, HD installation and update menus. The native launcher also checks for a missing desktop display before starting preparation. Thanks to [BitJager-dev](https://github.com/BitJager-dev/DarkwatchDarkerEdition/tree/linux-umu-no-steam/launcher/linux/umu) for testing and documenting the working setup that informed this integration. See the Linux README for commands and requirements.

## Updating

Close the game before updating. On Windows, use **Manage → Check for Updates → Install Update** once this release is published. For a manual update, close the launcher too and extract the **complete Windows package** over the existing launcher folder, replacing matching package files.

On Linux, close the game and Steam shortcut, then use `./Darkwatch.sh --download-update` from a native terminal or replace matching files with the **complete Linux package**. Keep its **windows/** and **linux/** folders together, along with **.proton/** where applicable.

Keep **GameData/**, external installations, saves, settings, installed languages and HD textures. A working installation reuses its game files; another full disc import is not required. Direct-ISO users must keep their ISO available. Missing or damaged original files may require the original disc again. Shader preparation validates or extends the existing cache. If using a separate package folder, choose **Use Existing Install** to select the previous installation.

## HD textures

**Keep using the existing 0.7 HD gameplay texture pack. No new pack or reinstall is needed.**

For a fresh HD installation, download **Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001** through **.005** from the [0.7 release](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7). Keep all five parts together with their original names. Choose **Manage → Install HD Textures** and select **.001**; the launcher reads the other parts automatically. Do not extract the parts individually or mix versions. **parts.json is not required.** Enable **Graphics → HD Textures → Apply** afterward.

Linux terminal users can run `./Darkwatch.sh --install-hd-textures "/path/to/Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001"`.

## Verification

Windows checks covered 21:9 and 32:9 windows, menus, single-player, horizontal co-op, FMV framing and the mounted opening cinematic. These checks were performed on a standard desktop display; a physical ultrawide monitor and every campaign cinematic have not been checked. Wider cinematic edges can expose staging outside the original view in untested scenes.

The experimental Linux/Proton package contains the same runtime and changes. A [community report](https://github.com/linkssy2/DarkwatchDarkerEdition/issues/53) confirms working 0.7.5 gameplay, setup, HD textures, controller input and audio through umu on CachyOS with a Radeon 780M. Linux gameplay and the new integrated umu route have not been live verified for this update.
