# Code map

| Location | Purpose |
| --- | --- |
| `config/xbexbe-toolchain.json`, `dependencies.lock.json` | Original XBE identity and pinned native dependencies. |
| `xbexbe/config/game.toml` | Translator entries and host hook configuration; original game bodies are generated locally. |
| `patches/xbexbe.patch` | Maintained SDK changes for CPU services, file access, input, audio and rendering. |
| `xbexbe/src/common/game_info.cpp` | Title registration and original-game integration. |
| `graphics.*`, `graphics_route.*`, `settings_skin.h` | Graphics/Controls/Audio panels, input routing and HD/original menu artwork. |
| `graphics_camera.*`, `third_person_aim.*`, `third_person_body.*`, `third_person_visibility.*` | Per-player camera views, smooth shoulder swaps, current aim target and body presentation with native action ownership. |
| `starter_grip.cpp`, `launcher/body_weapon_grips.inc` | Shared measured per-character/per-weapon grip corrections. |
| `graphics_view.*`, `graphics_reticle.*`, `graphics_hud.*` | Saved FOV/view choices, reticle appearance and per-player HUD layout. |
| `graphics_cinematic.*`, `graphics_presentation.*` | In-game cinematics, final UI/subtitles and separate frontend aspect ratio. |
| `controls.*`, `camera_input.*`, `weapon_input.*`, `native_menu.*`, `prompts.*` | Bindings, local player ownership, mouse/controller navigation and prompts. |
| `coop.*`, `coop_characters.*`, `character_selection.*`, `character_preview.*` | Local split-screen setup, character selection and preview. |
| `character_runtime.*`, `character_content.*`, `character_audio.*` | Guarded actor admission, generated identity metadata and voice-bank selection. |
| `carry_all_weapons.*`, `revolver_ammo.cpp`, `grenade_switch.cpp`, `coop_respawn_weapons.*` | Optional inventory rules, ammo handling, grenade selection and local respawn restoration. |
| `campaign_replay.*`, `coop_saves.*`, `save_storage.*`, `save_profile_io.*` | Replay isolation, separate progression, atomic save writes and recovery. |
| `script_timing.cpp`, `script_resume.cpp`, `boss_intro.*` | Original script/event sequencing and high-frame-rate integration. |
| `audio_settings.*`, `sound_pool.*`, `cri_lifetime.cpp` | Output preference, sound ownership and synchronization. |
| `shader_preparation.*`, `shader_preparation_catalogue.h`, `shader_preparation_observed.h` | Known shader recipes and identity metadata; programs are generated from the player's XBE. |
| `hd_ui.*`, `hd_ui_*.h`, `xbexbe/hd_ui/` | Original/HD interface pack assembly, approved artwork and replacement metadata. |
| `gameplay_textures.h`, `gameplay_texture_assets.h` | Optional gameplay HD loading and fingerprints. |
| `launcher/MainWindow.xaml`, `Launcher.cs`, `SetupProcess.cs`, `DirectPlay.cs` | Portable Windows launcher, grouped setup, background preparation and direct play. |
| `launcher/setup_backend.py`, `installed_source.py` | Verified import, direct ISO selection, recovery records and prepared overrides. |
| `launcher/character_*.py`, `third_person_animation.py` | Own-disc roster, coat, grip and animation preparation; no original model or animation payload is included. |
| `launcher/character_reload.py`, `character_starter_reload.py`, `character_weapon_pose.py`, `character_weapon_hold.py` | Body-action timing, smooth starter reload phases, visible aim and support-hand contact. |
| `launcher/ps2_*.py`, `language_pack.py`, language catalogs | Local import of text, dialogue and compatible movie audio from supported PS2 discs. |
| `launcher/release_check.py`, `release_download.py`, `release_update.py` | Release discovery, verified download and managed-file update with rollback. |
| `launcher/linux/`, `tools/package_linux.py` | Experimental Proton launcher and exact Windows-payload packaging. |
| `tools/intake.py`, `scripts/` | Disc parsing/extraction and native/launcher build entrypoints. |
| `tests/` | Selected synthetic regressions that do not ship original instructions or private captures. |
| `licenses/`, `CREDITS.md` | Required dependency and artwork attribution. |

Generated guest C++ and original disc resources are excluded. Authored host wrappers
may use `X86_FUNC` names to call locally generated original functions. The runtime
data headers contain identities/layout metadata, not original model or texture data.

Character preparation verifies original, intermediate and final archive identities
before committing changes. Direct ISO mode keeps prepared overrides separately and
reads the remaining data from the retained ISO. Updates preserve installation
records, saves, language content and compatible HD resources.

Use the Release profile for player builds. Optional diagnostic support and required
fatal-error handling remain available. A successful source test or compilation is
not proof of complete campaign, visual, audio or Linux gameplay acceptance.
