# Code map

| Location | Purpose |
| --- | --- |
| `config/xbexbe-toolchain.json` | SDK commit and supported XBE identity. |
| `xbexbe/config/game.toml` | Discovered function addresses, hooks and translator configuration. Address metadata is not generated gameplay source. |
| `patches/xbexbe.patch` | Maintained fixes to the pinned SDK: x86 translation, Xbox services, input, audio and D3D12 rendering. |
| `xbexbe/src/common/game_info.cpp` | Title registration and narrow original-game integration hooks. |
| `xbexbe/src/common/script_timing.cpp` | Keeps the actor-script update gate active above 100 FPS without changing global time or ordinary 60 FPS updates. |
| `controls.*`, `menu_cursor.*`, `native_menu.*`, `desktop_quit.*` | Bindings, native mouse navigation and menu callbacks. |
| `prompts.*` | Keyboard/mouse and Xbox, PlayStation, Switch prompt selection and artwork. |
| `graphics.*`, `graphics_route.*`, `settings_skin.h` | Host settings pages, routing, persistence and original-style presentation. |
| `graphics_camera.*`, `graphics_view.*`, `graphics_reticle.*`, `graphics_hud.*` | Separate world/weapon FOV, saved preferences, widescreen, reticle and HUD adjustments. |
| `graphics_cinematic.*`, `graphics_presentation.cpp` | In-level cinematic controls and original subtitle presentation isolated from scene feedback; movie playback is excluded. |
| `script_resume.cpp`, `fatal_assert.cpp` | Mission script resume bridge and bounded fatal assertion handling. |
| `coop.*`, `character_selection.*` | Beta local split-screen co-op routing, character selection and saved preferences. Co-op gameplay testing is incomplete; this is not online co-op. |
| `character_runtime.*`, `character_runtime_data.h` | Guarded original actor/animation integration; the data header contains identity keys only. |
| `character_content.cpp`, `character_audio.cpp`, `character_melee.*` | Verified own-disc character admission, bank setup and scoped melee cue selection. Hurt voice work remains unresolved. |
| `gameplay_textures.h`, `gameplay_texture_assets.h` | Optional replacement loader and fingerprint metadata; no original pixels. |
| `cri_lifetime.cpp`, `sound_pool.*` | Host synchronization and sound allocation fixes. |
| `shader_preparation.*`, `shader_preparation_catalogue.h`, `shader_preparation_observed.h` | Local preparation of known shaders from verified game data. The catalogue stores descriptors and hashes, not captured shader programs. |
| `hd_ui.*`, `hd_ui_*.h`, `xbexbe/src/tools/` | Runtime HD replacement and the local pack builder. Atlas headers contain layout/identity metadata, not extracted texture pixels. |
| `xbexbe/hd_ui/` | Approved restored enhancement images and their exact override map. Original archives and assembled texture packs are excluded. |
| `launcher/` | WPF launcher/direct start, verified import, portable saves, local shader preparation and package allowlist. |
| `launcher/linux/` | Experimental Linux launcher around the existing Windows backend and game through a player-supplied Proton installation; no native Linux runtime. |
| `launcher/bonus_content.py` | Three fixed-width XML selector edits in the user's verified original packfile, guarded by original and prepared hashes. No game asset payload is included. |
| `launcher/character_content.py`, `character-catalog.json` | Coordinates own-disc character preparation and verifies original, intermediate and installed archive identities. |
| `launcher/character_archive.py`, `character_assets.py` | Archive parsing/composition and model, locator and binary XML adaptation. |
| `launcher/character_*.py` | Adapts own-disc characters, animation, hands and presentation while retaining original player rules; no model or animation payload is included. |
| `launcher/gameplay_hd.py`, `gameplay-hd-catalog.json` | Optional HD texture installation, integrity checks and rollback. |
| `tools/package_gameplay_hd.py` | Separately provisioned texture packaging; strips native reference bytes. |
| `tools/package_linux.py` | Packages the exact verified Windows files and allowlisted Proton wrappers and guides; excludes installed data and records readback hashes. |
| `tools/intake.py` | Project-owned XDVDFS parser and extractor. |
| `scripts/` | Native/launcher build entry points and source fingerprinting. |
| `tests/` | Selected synthetic tests suitable for public distribution. |
| `licenses/`, `dependencies.lock.json` | Dependency attribution and recorded revisions. |

`*_diagnostic.*` files remain in the native build closure for development;
the release definition disables their recording paths. Debugging source in
this repository is not evidence that a player build enables diagnostics.

Original gameplay functions are generated locally under `xbexbe/generated/`.
That directory is not published. A few maintained host wrappers have
`X86_FUNC` names so the translator can call them; they add host behavior and
call `__imp__` original functions generated from the user's XBE. They do not
contain the generated original function bodies.

Keep changes small and explain the reason beside a non-obvious guard or
workaround. A successful build or synthetic test does not demonstrate live
menu, rendering, sound or gameplay correctness; record those separately.

For version 0.2, `game_info.cpp` accepts the original vampire-jump state only
at the existing jump-look callers. Ownership and mode guards still apply.
`tests/test_xbexbe_direct_mouse.py` covers this with synthetic state; private
fixtures containing original function bodies are excluded.

`setup_backend.py` verifies the extracted files against the original disc
manifest, then calls `character_content.prepare` inside the uncommitted import
stage. That function builds the character resources and calls
`bonus_content.patch_pack` before composing the character additions into
`packfile.pck`. All three prepared archives must match their output pins before
they replace the originals in that stage; the setup backend then commits the
installation. Installed verification expects prepared identities for those
archives and original hashes for untouched files.

The content-revision marker checks whether prepared data needs rebuilding.
Installed source-recovery records support future in-place upgrades without an
ISO for extracted installations; directly mounted installations keep their ISO.
Published 0.6.1 installations may need a final import to obtain those records.
The launcher tests use synthetic archives to cover preparation and transactional
installation without starting the game.

Weapon FOV borrows the registered player camera only for the first-person model pass, then restores the world projection. Both preferences retain the original at 100%. Cutscene Borders skips only the active cinematic manager's two border draws. Subtitle presentation retains original glyph layout and timing but draws separately from scene feedback. The authored view, cinematic-guard and ImGui tests are included; original-function fixtures remain private.

Main-menu additions are prepared during the original menu initializer before its
first layout, including return from gameplay. Input callbacks still require the
active page owner. Diagnostic modules remain in source for development, but the
release profile compiles out their recording paths; bounded fatal reports remain.

Player 2 pause navigation and Apply follow the pausing player's controller/profile.
The five original layouts remain presets; per-player controller rebinding adds editable physical-button mappings.
HUD spacing and Player 2 ownership were accepted in tested co-op scenes; selected co-op settings and separate solo/co-op storage were verified through a cold restart. Full-campaign progression remains unverified.

## Version 0.6 additions

| Location | Purpose |
| --- | --- |
| `audio_settings.*` | Host Audio page and saved channel-output preference. |
| `boss_intro.*` | Original mounted-boss intro event timing independent of display rate. |
| `campaign_replay.*`, `coop_saves.*` | Replay isolation and separate co-op progression storage. |
| `save_profile_io.*`, `save_storage.*` | Read-only profile lookup, atomic writes and backup recovery. |
| `coop_characters.*`, `character_preview.*`, `launcher/character_roster.py` | Two-player selection, local rotating previews and roster identities. |
| `graphics_presentation.*`, `language.*`, `prompt_owner.*` | Final UI presentation, language selection and input ownership. |
| `launcher/ps2_*.py`, `ps2-spanish-catalog.json`, `ps2-spanish-corrections.json` | Reads the player’s supported PAL PS2 ISO and prepares Spanish text, dialogue and compatible movie audio locally; metadata and project-authored corrections only. |

## Version 0.6.1

Mounted-boss intro preparation covers both native sequence-start paths.
The SDK audio mixer retains output-parent ownership, applies the native direction
payload to discrete-speaker balance, and keeps explicit speaker sends separate.
The public PCM tests cover these paths with synthetic data and negative controls.
Original instruction-based witnesses remain private.

Spanish conversion retains Xbox movie video and timestamps. Only matched audio
slots are replaced; complete campaign synchronization still needs live review.
No captured game media or generated original functions are exported.

## Version 0.7 additions

| Location | Purpose |
| --- | --- |
| `launcher/installed_source.py` | Captures small recovery records and reconstructs verified source archives during in-place content updates. |
| `launcher/release_check.py`, `release_download.py`, `release_update.py` | Reads compatible GitHub release metadata, downloads verified archives and replaces only managed package files with rollback. |
| `launcher/setup_backend.py`, `launcher/linux/` | Direct ISO, import-once and existing-install choices; retained ISO path repair and Linux read-only access. First-time startup can select one supported ISO from the packaged assets folder, including the Steam --play route. |
| `patches/xbexbe.patch` | Includes the read-only ISO mount, prepared-file precedence, optional language overlay and guest file-service integration. |
| `launcher/revolver_content.py`, `revolver_scripts.py` | Own-disc starter weapon tuning, resource dependencies and hash-guarded authored script deltas. No complete original scripts are exported. |
| `carry_all_weapons.*`, `weapon_input.*`, `revolver_ammo.cpp`, `grenade_switch.cpp` | Optional weapon capacity, cycle bindings, independent ammo refill and native grenade selection. |
| `launcher/character_tala.py` | Builds playable Vampire/Boss Tala from the player's disc; the playable boss adaptation excludes wings. |
| `hd_ui_small_hud.h` | Small HUD identity/layout metadata; no captured texture pixels. |
| `gameplay-hd-catalog.json`, `gameplay_hd.py`, `tools/package_gameplay_hd.py` | Expanded optional texture inventory and lossless shared-payload archive format. |

Direct ISO mode stores an explicit marker and prepared archive overrides. The
runtime reads other disc entries from the retained ISO; it never writes to the
image. Spanish overrides take precedence only for the language resources, and
save paths remain separate. The exported native fixtures use tiny synthetic
XDVDFS images to test these paths without original game data.

The updater owns only the instructional assets/README.txt file in that folder;
player ISO/XISO files are never package-owned. Either player's native pause
menu routes Audio separately from Graphics and Controls. Carry All bindings
retain their values while disabled; native weapon cycling and mirrored ammo
admission use the original weapon component's identity getter field.

Shader preparation constructs the original guest programs serially, then compiles
known host shaders with at most four workers. Observed recipes add only validated
metadata; shader words still come from the importing player's XBE. The 0.7
catalogue has 4,474 items and 3,822 distinct cache keys. Per-key synchronization
prevents duplicate cache writes, and failed preparation never publishes a ready
stamp. Unseen variants and driver pipeline creation may still occur in gameplay.

Character archive preparation uses bounded file output and memory-mapped inputs
for intermediate stages. Each intermediate and final archive remains hash-checked
before installation commits. Regular Tala uses an authored glove repaint on the
original first-person hand geometry and UVs; the other Tala variants retain
their existing hand conversions.
