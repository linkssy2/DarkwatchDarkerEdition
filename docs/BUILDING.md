# Building from this source snapshot

This is the maintained XboxXBERecomp integration, not a copy of the original
game source. You must supply the supported original Xbox disc. Generated title
C++, the Xbox executable, game archives, videos and the assembled HD pack are
created locally and must not be committed or redistributed with this source.
The Windows player package contains compiled recompiled gameplay; it is not
only a generic emulator or launcher.

## Windows build requirements

- Windows x64, PowerShell 7, Git, CMake 3.25 or newer, and Ninja on `PATH`.
- Visual Studio 2022 C++ Build Tools with Clang, x64 tools and a Windows SDK.
  The native build wrapper discovers Visual Studio using `vswhere`.
- Python 3.12. The public build/import tools use the standard library.
- The exact disc revision identified in `config/xbexbe-toolchain.json` and
  `launcher/supported-disc.json`. A different revision is rejected.
- For the launcher, .NET Framework 4.8 with its C# compiler and WPF assemblies.

Use a short writable checkout path. Commands below run from its root in
PowerShell 7. These instructions describe the checked-in build closure, but a
clean-machine build of this public snapshot has not yet been validated.

## Import your disc for development

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe tools/intake.py extract 'C:/path/to/Darkwatch.xiso' --output game_files --analysis analysis
```

The intake command defaults to a trimmed XISO game partition at offset zero.
For a full Xbox image whose game partition is at `0x18300000`, add
`--partition-offset 0x18300000`. The end-user launcher detects these two layouts
automatically. The `.iso` or `.xiso` filename extension does not identify the
layout. Extraction reads the input and records local file hashes; it does not
alter the disc image. Raw development extraction retains the original selectors.
The launcher's import prepares War Train, Splitter selectors and character/co-op
resources locally after verifying the original files. Use that import when
testing character selection; raw extraction retains the original resources.

## Build the runtime

```powershell
./scripts/build-xbexbe.ps1
./scripts/build-xbexbe.ps1 -Release
```

The first build fetches the pinned XboxXBERecomp checkout, applies
`patches/xbexbe.patch`, fetches its dependencies, generates title C++ from your
XBE, and builds the development runtime. The release build uses a separate
object/output directory and reuses those dependency source checkouts. Running
`-Release` before the first build currently fails because those checkouts do not
exist. `dependencies.lock.json` records the revisions retained from version 0.1
for version 0.5; dependency tags in the SDK should resolve to those commits.

`-Stage Recompile` regenerates title code without rebuilding the runtime.
`-Stage Symbols` records a signature-scan comparison without replacing the
maintained configuration. Do not edit generated C++ to change the port; maintain
hooks in `xbexbe/src/common/` and the configuration, or update the SDK patch.

Outputs include `build/xbexbe-release/darkwatch_xbe.exe`,
`darkwatch_hd_ui_builder.exe` and a local provenance manifest. The build also
assembles `hd-ui.pack` from your original `packfile.pck` and the approved
enhancement images. The assembled pack is private build output. The release
profile disables routine diagnostics but retains bounded fatal-error reporting.

## Build the portable launcher package

The packaging script still has build-machine provisioning assumptions. Before
running it, adjust the constants at the top of `launcher/package.py` to your
local generic dependencies:

- `PYTHON`: an unmodified embedded Python 3.12.10 x64 distribution with the
  files listed in `PYTHON_FILES`, including its license, OpenSSL and libffi.
- `VS` and `CRT`: your licensed Visual Studio installation and its x64
  `Microsoft.VC143.CRT` redistributable directory. Version 0.1 was packaged with
  MSVC redist `14.44.35112`.
- The two Visual C++ redistribution notice paths in `sources()`: provide the
  corresponding notices for your licensed redist. The retained local defaults
  reference a sibling development folder, **not another game's code or assets**.

Those generic dependency binaries are not included in the source repository.
Do not copy a neighboring game's source or payload to satisfy these paths.
The public source is therefore not yet a one-command clean-machine packager.
After provisioning and a successful release runtime build:

```powershell
./scripts/build-launcher.ps1 -Output 'C:/build-output/Darkwatch-0.5'
```

The output directory must not already exist. The script builds both launcher
EXEs and validates an explicit package allowlist. It includes approved
enhancement PNGs, authored Cassidy hand repaints and edited branding, while
original disc files, character archives and assembled packs are excluded. Import and shader preparation happen locally
when the player supplies their disc. Keep all package files together.

## Experimental Proton wrapper

`launcher/linux/` provides the experimental Linux launcher for an already built
Windows package. It runs the packaged import backend and game through the
player's Proton installation; it does not compile the D3D12 runtime for Linux.
See its [README](../launcher/linux/README-LINUX.md) for the host requirements and commands.
The native runtime and package build instructions above still require Windows.

After producing a verified Windows release directory, make the experimental
archive without adding installed game data:

```powershell
.venv/Scripts/python.exe tools/package_linux.py --windows-package 'C:/build-output/Darkwatch-0.5' --output 'C:/build-output/Darkwatch-0.5-Linux-Proton-Experimental.tar.gz' --audit 'C:/build-output/linux-package-audit.json'
```

The packager copies the verified Windows allowlist under `windows/`, adds only
the approved Proton wrapper files and Linux README, then reads back and
hashes every archive member. It refuses to overwrite an existing archive.

The wrapper uses the existing disc verification, portable data and shader
preparation paths. Synthetic wrapper tests do not verify actual Linux graphics,
audio, controller behavior or performance. No tested Proton version is claimed.

## Tests

The selected public tests use synthetic discs, host protocols and controlled
input state. They do not start Darkwatch or require a private gameplay capture.
From a developer shell with the native compiler on `PATH`:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

The native tests need the first build's patched SDK and dependency checkouts.
Some fixtures also use the standard VS2022 Build Tools installation path;
adjust their compiler constant for a nonstandard installation. Missing tools
may cause skips: a skipped test is not verification. Launcher fixtures compile
harmless test workers and exercise WPF offscreen; they do not launch the game.

Private tests that contain original instruction windows, generated guest
function bodies or captured shader data are deliberately omitted. The public
suite does not establish full campaign fidelity, physical controller behavior,
or complete shader coverage.

## Character and optional texture content

`launcher/character_*.py` reconstructs the three character archives from the
verified own-disc import. `character-catalog.json` pins source resources and
prepared output identities; it contains no model, animation or voice payloads.
Living Cassidy hand repaints are separate authored enhancement images. Spectral
body and hand resources are derived locally from the supplied disc. Do not substitute
prebuilt development archives into the Windows package.

`gameplay-hd-catalog.json` identifies the optional texture download. Its pixels
are not in this source snapshot. `tools/package_gameplay_hd.py` validates and
packages separately provisioned replacements, stripping original native bytes
from the distribution format. It cannot recreate an external texture pack from
metadata alone. `xbexbe/config/gameplay_hd_assets.json` and the compiled header
contain matching/fingerprint metadata, not textures.

The maintained native address-key headers are included as metadata. Original
native body/byte regression fixtures and private acceptance recordings remain
excluded. Synthetic source tests do not establish live gameplay acceptance.

Version 0.5 retains the pinned SDK revision with an updated maintained patch.
Source checks cover the exported synthetic suite and native host fixtures; they
do not replace a clean-machine full rebuild or full-campaign testing. Local co-op
remains beta, and Cassidy hurt-voice work remains paused.
