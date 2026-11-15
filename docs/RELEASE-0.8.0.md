# Darkwatch: Darker Edition 0.8.0

Windows and experimental Linux/Proton release candidate. Not published yet.

## Installation and launcher

- Fresh installs default to original playable characters, models and animations.
  Choose expanded characters during setup for the added roster and enhanced
  models/animations. The original option saves about 2.79 GiB of prepared game
  archives. Existing installations keep their content choice; changing it needs
  a separate fresh installation.
- Successful installs and updates retire recognized superseded installation
  versions. Unique older user files are preserved under
  `GameData/preserved-user-data`. Unrelated installations and original disc
  images are not deleted. Failed or cancelled preparation keeps the working install.
- Windows and Linux setup offer the content choice, including automatically
  detected ISO setup. Skip Intro and direct play remain available.
- Routine runtime tracing, capture tools, GPU debugging and the development test
  room are disabled in release builds. Optional launcher support logging defaults
  off; bounded failure reporting remains available.

## Gameplay and presentation

- Improved first-person camera stopping after walking.
- Reworked third-person crossbow, sniper, rifle, shotgun and rocket launcher
  reloads using their first-person motions, across supported characters.
  Improved head stability, neck proportions and Jericho's rocket launcher hold.
- Corrected dual-pistol and Redeemer reload cartridges and their drop handoff.
- Forever Ragdolls also retains supported severed heads and limbs. Walking into
  them, bullets and explosions move them.
- Optional Darkwatch-styled weapon wheel with clearer weapon outlines. Requires
  Carry All Weapons, shows collected selectable weapons only, and slows time in
  solo play. Multiplayer remains real-time.
- Monster Screams controls enemy vocal sounds separately, including growls, pain
  and death sounds. Added secondary motion for the supported Banshee model.
- Simplified settings: camera switching is assigned in Controls; split-screen
  orientation is chosen with cooperative characters. Ground pound requires its
  story rune; the testing override is removed.

## Local multiplayer

- Updated cooperative and versus character selection with rotating portraits.
  Versus has four player-owned boxes, controller connection detection and direct
  character selection without a separate profile prompt.
- Expanded installations offer the campaign roster in versus; original-style
  installations retain native Troopers. Players can enter versus session names.
- Styled pause menus fit inside the pausing player's viewport, with working
  Graphics, Controls, Audio, Resume and Quit actions.
- Corrected supported character secondary motion and neck proportions in
  multiplayer, controller name-entry navigation, and the reconnect prompt after
  quitting deathmatch.
- Removed the pre-loading socket shutdown hitch. Matches load resources for
  selected characters instead of preparing the entire expanded roster.

## Updating and optional textures

Close the game and launcher. Install the complete Windows or Linux package over
the matching existing launcher folder, or use the launcher's update action once
0.8.0 is published. Keep GameData, saves, settings, languages, optional textures,
and any external installation. Direct-ISO installations still require their ISO.
Linux users must keep the windows/ and linux/ folders together and preserve their
Proton environment. No original game files are included; your supported Xbox
Darkwatch disc image is required.

The separate 0.7 HD texture pack remains compatible and optional. Its installed
gameplay textures occupy about 18.3 GB independently of the base install. Turning
HD textures off in Graphics does not uninstall that pack. HD menus and HUD do not
require the optional gameplay pack.

## Verification and known limits

Reported enhanced-content gameplay fixes have targeted Windows user acceptance.
Original-profile installation, preservation, cleanup and native admission have
offline verification. Windows original-profile campaign smoke and the corrected
multiplayer selector were checked live; original archives are now admitted at
startup before the game opens them. Native Linux launcher checks pass. Full
campaign, four-controller play and Linux/Proton gameplay have not been verified
for this candidate. Linux/Proton remains experimental. No new frame-rate gain is
claimed from release packaging.

Quiver currently omits the published 0.7.9 Windows asset from its catalog and
reports a pending scan. The platform archive naming is compatible; automatic
Quiver recognition of 0.8.0 must be checked after publication. Direct GitHub
downloads and the Darkwatch launcher's updater do not depend on that catalog.
