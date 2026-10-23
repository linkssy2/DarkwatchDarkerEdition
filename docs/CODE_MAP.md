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
| `graphics_cinematic.*`, `graphics_subtitles.cpp` | In-level cinematic controls and original subtitle presentation isolated from scene feedback; movie playback is excluded. |
| `script_resume.cpp`, `fatal_assert.cpp` | Mission script resume bridge and bounded fatal assertion handling. |
| `coop.*`, `character_selection.*` | Beta local split-screen co-op routing, character selection and saved preferences. Co-op gameplay testing is incomplete; this is not online co-op. |
| `character_runtime.*`, `character_runtime_data.h` | Guarded original actor/animation integration; the data header contains identity keys only. |
| `character_content.cpp`, `character_audio.cpp`, `character_melee.*` | Verified own-disc character admission, bank setup and scoped melee cue selection. Hurt voice work remains unresolved. |
| `gameplay_textures.h`, `gameplay_texture_assets.h` | Optional replacement loader and fingerprint metadata; no original pixels. |
| `cri_lifetime.cpp`, `sound_pool.*` | Host synchronization and sound allocation fixes. |
| `shader_preparation.*`, `shader_preparation_catalogue.h` | Local preparation of known shaders from verified game data. The catalogue stores descriptors and hashes, not captured shader programs. |
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
| `tools/package_linux.py` | Packages the exact verified Windows files and three allowlisted Proton wrapper files; excludes installed data and records readback hashes. |
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

The content-revision marker requires older portable installations to reimport
while preserving saves, settings and compatible cache. The launcher tests use
synthetic archives to cover preparation and transactional installation without
starting the game.

Weapon FOV borrows the registered player camera only for the first-person model pass, then restores the world projection. Both preferences retain the original at 100%. Cutscene Borders skips only the active cinematic manager's two border draws. Subtitle presentation retains original glyph layout and timing but draws separately from scene feedback. The authored view, cinematic-guard and ImGui tests are included; original-function fixtures remain private.

Main-menu additions are prepared during the original menu initializer before its
first layout, including return from gameplay. Input callbacks still require the
active page owner. Diagnostic modules remain in source for development, but the
release profile compiles out their recording paths; bounded fatal reports remain.

Player 2 pause navigation and Apply follow the pausing player's controller/profile.
The original five controller layouts are presets, not arbitrary button remapping.
HUD spacing and Player 2 ownership were accepted in tested co-op scenes; profile
persistence after a complete process restart still needs an independent check.
