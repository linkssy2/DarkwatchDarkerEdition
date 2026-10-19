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
| `graphics_cinematic.*` | Guarded in-level cinematic border suppression; movie playback is explicitly excluded. |
| `cri_lifetime.cpp`, `sound_pool.*` | Host synchronization and sound allocation fixes. |
| `shader_preparation.*`, `shader_preparation_catalogue.h` | Local preparation of known shaders from verified game data. The catalogue stores descriptors and hashes, not captured shader programs. |
| `hd_ui.*`, `hd_ui_*.h`, `xbexbe/src/tools/` | Runtime HD replacement and the local pack builder. Atlas headers contain layout/identity metadata, not extracted texture pixels. |
| `xbexbe/hd_ui/` | Approved restored enhancement images and their exact override map. Original archives and assembled texture packs are excluded. |
| `launcher/` | WPF launcher/direct start, verified import, portable saves, local shader preparation and package allowlist. |
| `launcher/bonus_content.py` | Three fixed-width XML selector edits in the user's verified original packfile, guarded by original and prepared hashes. No game asset payload is included. |
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

`setup_backend.py` first verifies every extracted file against the original
disc manifest, then applies `bonus_content.py` only to the uncommitted import
stage. Installed verification expects the prepared hash for that packfile and
original hashes for every other disc file. The content-revision marker requires
older portable installations to reimport while preserving saves, settings and
compatible cache. `test_bonus_content.py` and `test_launcher_setup.py` exercise
this path with synthetic archives and never start the game.

Weapon FOV borrows the registered player camera only for the first-person model pass, then restores the world projection. Both preferences retain the original at 100%. Cutscene Borders skips only the active cinematic manager's two border draws; animation, camera, fades and subtitles keep their original paths. The authored view, cinematic-guard and ImGui tests are included; original-function fixtures remain private.
