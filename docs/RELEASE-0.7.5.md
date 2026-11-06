# Darkwatch: Darker Edition 0.7.5 — Languages & Fixes

Changes since 0.7.4:

- **French, German and Italian:** Import native game text, mapped dialogue and movie voices from your supported PAL PS2 ISO (SLES-53564) through **Manage Game → Install PS2 Language**. Spanish remains available through the same action. Select an installed language for the next launch; existing language installations are preserved.
- **Brazilian Portuguese text:** Adds the optional HNNEWGAMES v1.1 text adaptation, translated project menus and corrected accented headings. This is text-only: English audio is the default, with optional Spanish voices from a verified Spanish installation. No Portuguese dubbing is included.
- **Language display fixes:** Accented native headings now render correctly, and French and Italian Controls reset labels fit within their buttons.
- **Expanded shader preparation:** Prepares 25 additional gameplay shader variants and eight renderer helpers before play, reusing the existing cache. The tested Boneyard replay no longer compiled shaders during play; other scene-loading stalls can still occur.
- **Movie framing corrections:** Refines Fill Screen framing for two movies where brief flashes caused oversized borders. Picture proportions and normal scene composition are retained; Original Aspect Ratio is unchanged.
- **Jericho while mounted:** Fixes regular Jericho changing to the Civilian body in the **Ride Like the Devil** opening and mounted gameplay. Explicit Civilian Jericho still uses his Civilian outfit. Both selections were checked visually and against the active loaded models on Windows.
- **Update recovery:** Fixes a launcher recovery handoff that could close the launcher before its recovery worker was ready. Failed recovery startup is now detected and reported while retaining recovery data and backups.

## Updating

Close the game before updating. On Windows, use **Manage → Check for Updates → Install Update**. For a manual update, also close the launcher and extract the **complete Windows package** over the existing launcher folder, replacing matching package files.

On Linux, close the game and Steam shortcut, then use `./Darkwatch.sh --download-update` from a native terminal or replace matching files with the **complete Linux package**. Keep the package's **windows/** and **linux/** folders together, along with **.proton/** where applicable.

Keep **GameData/**, external installation folders, saves, settings, installed languages and HD textures. A current installation refreshes the revised character resources from its retained recovery data or linked Xbox ISO; **another full Xbox disc import is not required**. Direct-ISO users must keep their ISO available. Missing recovery data or damaged original files may require the original ISO again. Shader preparation validates or extends the existing cache. If moving to another package folder, use **Use Existing Install** to select the previous installation.

## HD textures

**The existing 0.7 HD gameplay texture pack remains compatible. No new download or reinstall is needed for an installed pack.**

For a fresh HD installation, download **Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001** through **.005** from the [0.7 release](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7). Keep all five parts together with their original names. Choose **Manage → Install HD Textures** and select **.001**; the installer reads the other parts automatically. Do not extract the parts individually or mix versions. **parts.json is not required.** Enable **Graphics → HD Textures → Apply** afterward.

Linux terminal users can run `./Darkwatch.sh --install-hd-textures "/path/to/Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001"`. For the Steam setup route, temporarily use `-B "linux/run_backend.py" --interactive --install-hd-textures "/path/to/Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001"` as Launch Options, then restore `-B "linux/run_backend.py" --interactive --play` when installation finishes.

## Language setup

After setting up the Xbox game, choose **Manage Game → Install PS2 Language**, select Spanish, French, German or Italian, and select your own supported **PAL PS2 ISO (SLES-53564)**. Let the import finish, then select the installed language before the next launch. PS2 language media is converted locally; it is not included in the release.

For Portuguese, choose **Install Portuguese Translation**, then **Português (Brasil)**. This optional text adaptation is not contained on the PS2 disc. It uses a verified Spanish audio installation when present; otherwise voices remain English. Install Spanish from your PS2 ISO first if you want those voices with Portuguese text. Imported movie voices use the PS2 stereo mix. Dialogue slots that are silent on the PS2 disc retain English, and other character/grunt banks are outside the import's scope.

Windows checks covered sampled language menus, headings and layouts, plus the mounted Jericho scene. They do not establish complete campaign translation, every dialogue/subtitle line or full audio/animation fidelity. The Linux/Proton package includes the same changes and remains experimental; Linux gameplay has not been live verified.
