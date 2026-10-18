# Code map

| Location | Purpose |
| --- | --- |
| `config/xbexbe-toolchain.json` | SDK commit and supported XBE identity. |
| `xbexbe/config/game.toml` | Discovered function addresses, hooks and translator configuration. Address metadata is not generated gameplay source. |
| `patches/xbexbe.patch` | Maintained fixes to the pinned SDK: x86 translation, Xbox services, input, audio and D3D12 rendering. |
| `xbexbe/src/common/game_info.cpp` | Title registration and narrow original-game integration hooks. |
| `controls.*`, `menu_cursor.*`, `native_menu.*`, `desktop_quit.*` | Bindings, native mouse navigation and menu callbacks. |
| `prompts.*` | Keyboard/mouse and Xbox, PlayStation, Switch prompt selection and artwork. |
| `graphics.*`, `graphics_route.*`, `settings_skin.h` | Host settings pages, routing, persistence and original-style presentation. |
| `graphics_camera.*`, `graphics_view.*`, `graphics_reticle.*`, `graphics_hud.*` | FOV, camera, widescreen, reticle and HUD adjustments. |
| `cri_lifetime.cpp`, `sound_pool.*` | Host synchronization and sound allocation fixes. |
| `shader_preparation.*`, `shader_preparation_catalogue.h` | Local preparation of known shaders from verified game data. The catalogue stores descriptors and hashes, not captured shader programs. |
| `hd_ui.*`, `hd_ui_*.h`, `xbexbe/src/tools/` | Runtime HD replacement and the local pack builder. Atlas headers contain layout/identity metadata, not extracted texture pixels. |
| `xbexbe/hd_ui/` | Approved restored enhancement images and their exact override map. Original archives and assembled texture packs are excluded. |
| `launcher/` | WPF launcher/direct start, verified import, portable saves, local shader preparation and package allowlist. |
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
