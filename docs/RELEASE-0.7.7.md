Darkwatch: Darker Edition 0.7.7

Changes since 0.7.6

- Third-person play: Graphics now offers Centered and Shoulder camera views, with a separately saved choice for each local co-op player. First Person remains the default. Swap shoulders smoothly using V, or assign your preferred keyboard/controller button in Controls.
- Third-person weapon handling: Updated character movement, aiming, grips and reload poses across the selectable roster. Shots follow the centered reticle; the starting revolver has smoother reload transitions, and the Redeemer's supporting hand follows its magazine. Dual-pistol and long-gun attachment corrections are included.
- Third-person zoom: Blood Vision zoom stays in third-person and returns to your chosen framing when released. Scoped weapons retain their first-person scope view.
- 16:10 displays: Automatic now uses the full 16:10 view, and an explicit Widescreen 16:10 choice is available. Menus, mouse targets, HUD positioning and cinematic framing follow the selected proportions.
- Menu presentation: HD Artwork Off now gives the newer Graphics, Controls, Audio and character-selection panels their original-resolution artwork and fonts. A separate Menu Aspect Ratio option lets you choose Widescreen or Original 4:3 for the frontend.
- Jericho's outfit: Corrected his mounted and in-game cinematic duster to use the black coat when Jericho is selected.
- Launcher redesign: Organized Game Files, Textures & Languages, and Updates & Support into clear sections, with consistent buttons, correctly fitted cover art and layouts that adapt to smaller desktop work areas. The Linux setup menu follows the same grouping.
- Windows presentation: The game window and taskbar now use the Darker Edition icon.

Updating

Close the game before updating. Use the launcher's Check for Updates and Install Update buttons when this version is available, or close the launcher and extract the complete Windows download over your existing launcher folder, replacing matching package files.

On Linux, use ./Darkwatch.sh --download-update from a native terminal or replace matching files with the complete Linux download. Keep the windows/ and linux/ folders together, and preserve .proton/ where applicable.

Keep GameData, saves, settings, installed languages and HD textures. Existing installations reuse their game files; a full disc import is not required. The launcher may prepare changed character data. Direct-ISO installations still need their ISO in place. For a separate installation folder, choose Use Existing Install.

HD textures

Keep using the existing 0.7 HD gameplay texture pack. No new HD download or reinstall is needed.

For a fresh HD installation, download Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001 through .005 from the 0.7 release. Keep all five parts together with their original names, choose Install HD Textures, and select .001. The launcher reads the other parts automatically; do not extract the individual parts or mix versions. parts.json is not required. Enable Graphics > HD Textures and Apply afterward.

Linux terminal installation: ./Darkwatch.sh --install-hd-textures "/path/to/Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001"

The experimental Linux/Proton package uses the same runtime and changes. Live Linux gameplay verification remains pending for this update.

Developers can use the matching Darkwatch-Darker-Edition-0.7.7-Source.zip for authored sources and SDK patches.
