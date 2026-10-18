# Darkwatch: Darker Edition — 0.1.1 Test 1

An experimental update for community testing.

- Enables **War Train** and retained **Splitter Grenade** campaign placements
  from your own supported Xbox disc. Paired Xbox dynamite replacements are
  disabled to avoid duplicate pickups; ordinary dynamite is unchanged.
- Corrects an actor-script timing gate that skipped updates above 100 FPS,
  linked to the first door staying closed at 144 FPS.
- Enables direct mouse aiming during vampire jumps by accepting the original
  derived jump state in the existing look path.

Extract into a new folder. To retain progress, copy your existing `GameData`
folder into it, then use **Import / Repair** with your original ISO or XISO.
Reimport is required to enable the bonus content. Setup preserves saves,
settings and compatible shader cache; keep your previous installation as a backup.
Both the launcher and `Play Darkwatch.exe` remain available.

Original campaign progression is retained. After picking up Splitter Grenades,
use the D-pad Up action (Up Arrow by default) to change grenade type. No PS2 disc
or downloaded game files are required.

Please test the first door at 144 FPS, mouse turning during vampire jumps, and
War Train progression and grenade behavior. Import, integrity, HD preparation
and focused offline checks pass; these gameplay changes have not received live
acceptance. Other high-FPS physics or event differences may remain.

No original disc assets, generated game source, saves, shader caches or diagnostic
logs are bundled. The Windows player contains compiled recompiled gameplay;
approved HD enhancement artwork and edited launcher branding remain included.
Routine diagnostics are disabled; failures retain a short local error report.

Built with [XboxXBERecomp by TGP482](https://github.com/TGP482/Xbox-XBERecomp).
Dependency notices and artwork credits are included. Darkwatch and its original
content belong to their respective owners.
