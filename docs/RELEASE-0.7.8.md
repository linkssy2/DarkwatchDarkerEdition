Darkwatch: Darker Edition 0.7.8

Changes since 0.7.7

- Third-person aiming: Improved weapon facing while jumping, strafing, moving diagonally, crouching, fanning, using melee and taking damage. Held weapons follow the corrected character pose.
- Third-person movement and reloads: Smoother directional transitions, a more natural free arm for one-handed weapons, and reduced excessive torso twisting. Reloads continue when standing up from crouch and follow the direction you face. Updated grips and support-hand paths include the starting revolver and long guns.
- Third-person death camera: Your selected character falls into a ragdoll, and the camera follows the body while staying outside it. Restarting keeps the normal game flow.
- Co-op screen layout: Choose Top and Bottom or Side by Side in Graphics. The shared layout applies when the next co-op mission loads. Each player's view, HUD, reticle and saved settings follow the active layout.
- Co-op character presentation: Updated aiming and action animations are visible when watching the other player, including when that player uses first-person view.
- Enemy blood: Regular enemies now leave the game's native ground blood splats.
- Horseback controls: Lean Left and Lean Right follow the camera's screen direction, including when looking backward.
- Torture Maze weapon switching: Fixed switching back to the campaign mace after equipping a firearm, including with Carry All Weapons disabled.
- Controller and mouse handoff: Deliberate controller input can take over single-player after connecting another pad. Controller navigation hides and suspends the mouse pointer until it moves again. Controls-menu highlighting and navigation recovery are corrected.
- Settings menus: Graphics and Controls have clearer sections, with help text placed beneath the related settings.
- Faster preparation and updates: Reduced repeated animation work, temporary archive writes and peak memory use. Progress reports identify the character, files and archive being prepared. Updates reuse verified unchanged files while fully checking new downloads and outputs.
- Direct launch: Play Darkwatch.exe keeps routine verification silent and avoids opening the launcher or checking GitHub. Actual pending preparation still shows progress.
- Steam Deck instructions: Updated the Linux README with the tested Steam launch commands and separate Proton/MangoHud and game-diagnostic instructions.

Updating

Close the game before updating. Use the launcher's Install Update button, or close the launcher and extract the complete new download over its existing folder, replacing matching package files. Keep GameData, your saves, settings, installed languages and texture packs. For a separate folder, choose Use Existing Install.

Existing installations reuse their game data. This update may prepare changed character animations; it does not require a full disc import for supported current installations. Direct-ISO setups still need their selected ISO in place. On Linux, keep the windows/ and linux/ folders together and preserve .proton/ where applicable.

HD textures

Keep using the existing 0.7 HD gameplay texture pack. No new HD download or reinstall is needed.

For a fresh HD installation, keep all five Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001 through .005 parts together with their original names. Choose Install HD Textures and select .001; the launcher reads the other parts automatically. Do not extract individual parts or mix versions. parts.json is not required. Enable HD Textures in Graphics and Apply afterward.

Both platform downloads contain the same runtime and game changes. The Linux/Proton package remains experimental; shared binaries and Windows checks do not establish new Linux gameplay or performance verification.

Thanks to [@brandonsoto](https://github.com/brandonsoto) for Steam Deck and live Linux testing and feedback.

The matching Source.zip contains the authored sources and SDK patches. Original disc assets and generated game code are not included.
