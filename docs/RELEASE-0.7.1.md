# Darkwatch: Darker Edition 0.7.1

Changes since 0.7:

- **Steadier Blood Vision:** Corrected differences between normal character rendering and the highlight pass that caused dark patches and flickering on highlighted bodies. The correction works at higher frame rates without requiring a 60 FPS cap.
- **Forever Ragdolls:** Added a default-off Graphics option to keep ordinary enemy ragdolls in the current level. Players can push them, and already-active physical bodies placed in a level also react to contact. Original deliberate disintegration and gib effects remain intact.
- **More consistent corpse interaction:** Improved push strength and corrected a contact-distance calculation that made bodies harder to move at high frame rates. The reported 60/240 FPS difference was checked in Windows playtesting.
- **Encounter progression with retained bodies:** Dead bodies no longer occupy the enemy-spawn budget or report leftover health to the affected encounter checks. This prevents the reproduced wave/cutscene stalls and avoids the old body limit forcing later deaths to disappear immediately.
- **Co-op player bodies:** With Forever Ragdolls enabled, an individually respawning co-op player leaves a separate physical body using their selected character and final pose. The original player object is still removed normally; its controls and inventory are not kept on the corpse. Turning the option off removes these retained player bodies.
- **Co-op respawn inventory:** With Carry All Weapons enabled, a player who dies and respawns while their partner stays alive retains their own collected guns and ammunition. The surviving player's inventory is left alone.
- **Revolver ammo pickups:** Redeemer ammunition can now be collected when an owned starter revolver needs ammo, even if the Redeemer is full. Both guns keep their separate ammunition counts and capacity limits.
- **Mouse zoom sensitivity:** Zoom sensitivity now compensates for the actual camera magnification, including the zoom transition. At 100%, small aiming movements near the crosshair are comparable between zoomed and unzoomed views; the slider still lets you adjust from there. Previously saved values are kept, so players who lowered this setting to compensate may want to raise it again.
- **Reticle controls:** Reticle size now ranges from 0% to 200%: 100% is the normal size and 0% hides it. Each co-op player keeps their own setting. Reticle and zoom explanations appear beneath their settings, matching the other menu descriptions.
- **Mark of Evil effect:** Corrected the camera-facing tree explosion effect so its edges no longer appear as an inset square or diamond with wider views. The original world particles and explosion remain.
- **Character TNT voices:** Playable Cassidy and Tala variants use their character effort sounds for the TNT throw vocal cue, while retaining the separate throwing and fuse sounds.
- **Resource preparation:** The new player-body resources reuse existing resource indexing during preparation, avoiding repeated parsing and unnecessary work.

Windows and experimental Linux/Proton packages contain the same updated runtime
and preparation tools. **Co-op remains beta. Linux/Proton remains experimental
and still needs live testing.** Targeted Windows tests and user feedback cover
the reported fixes; they do not establish full-campaign or every-character
verification. Forever Ragdolls can increase memory and physics work as bodies
accumulate; retained bodies are not a new persistent save feature.

## Updating from 0.7

Close Darkwatch before updating. In the Windows launcher, use
**Manage → Check for Updates → Install Update**. For a manual update, close the
launcher too and extract the **complete 0.7.1 package** over the existing package
folder, replacing matching package files.

Keep **GameData/**, any externally selected installation folder, and any ISO used
in direct-ISO mode. Existing saves, settings, Spanish resources and compatible HD
textures are reused. If you extract into a different folder, choose
**Use Existing Install** and point it at the previous installation.

**This update prepares the new character-body resources once.** Modern
import-once installations reuse their installed recovery data without the ISO;
direct-ISO installations still need the ISO in its selected location. Older
extracted installations without recovery data may need one final ISO import.
Preparation does not mean you need another HD-pack download.

On Linux, close the game and Steam shortcut before updating. You can run
`./Darkwatch.sh --download-update` from a native terminal, or replace the complete
package's matching files manually. Keep **GameData/**, the existing Steam
shortcut, and **.proton/** if using the terminal route. Keep `windows/` and
`linux/` together. The Steam setup shortcut cannot replace its own running Python
files.

## HD textures: keep your existing pack

**The 0.7 HD texture pack is compatible with 0.7.1. If it is already installed,
keep it; no download or reinstallation is needed. No new HD pack is uploaded
with this release.** Earlier compatible packs also work, with their existing
coverage.

For a fresh installation, download the five HD parts from the
[0.7 release](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7):
**Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001** through **.005**. Keep all
five in one folder with their original names. In
**Manage → Install HD Textures**, select **.001**; the installer reads the other
parts automatically. Do not extract the individual parts, and do not mix pack
versions. **parts.json is not required.** Enable the installed pack in
**Graphics → HD Textures → Apply**.

For the Linux Steam route, temporarily use:

```text
-B "linux/run_backend.py" --interactive --install-hd-textures "Darkwatch-Darker-Edition-HD-Textures-0.7.zip.001"
```

Restore `-B "linux/run_backend.py" --interactive --play` afterward. The native
terminal launcher also offers HD installation.

## First-time setup

The existing disc and language choices remain available. Put one supported Xbox
ISO/XISO in **assets/** and launch for direct-ISO setup, or use **Select Game** to
import once or reuse an existing installation. Direct mode keeps using the ISO;
import-once mode lets you remove it after successful preparation. Original game
files are not included.

For Linux Steam, add **windows/payload/python/python.exe** as a Non-Steam Game,
set **Start In** to the extracted package folder, select an installed Proton
version in Compatibility, and use:

```text
-B "linux/run_backend.py" --interactive --play
```

An installed Proton version and working Vulkan drivers are required;
Proton Experimental is optional. This is a Proton package, not a native Linux
port. The Windows graphical launcher has not been verified under Proton.

Spanish installation remains under **Manage → Install Spanish**, using your own
European PAL PS2 disc (**SLES-53564**) alongside the required Xbox game source.
Existing installed language resources and the selected language are preserved.

Powered by [XboxXBERecomp](https://github.com/TGP482/Xbox-XBERecomp).
