# Building from this source snapshot

This is the maintained XboxXBERecomp integration, not a copy of the original
game source. You must supply the supported original Xbox disc. Generated title
C++, the Xbox executable, game archives, videos and the assembled HD pack are
created locally and must not be committed or redistributed with this source.
The Windows player package contains compiled recompiled gameplay; it is not
only a generic emulator or launcher.

## Requirements

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
The launcher's import prepares War Train and Splitter selectors locally
after verifying the original files; use that import for the bonus-content test.

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
for version 0.3; dependency tags in the SDK should resolve to those commits.

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
./scripts/build-launcher.ps1 -Output 'C:/build-output/Darkwatch-0.3'
```

The output directory must not already exist. The script builds both launcher
EXEs and validates an explicit package allowlist. It includes approved
enhancement PNGs and edited branding, while original disc files and the
assembled HD pack are excluded. Import and shader preparation happen locally
when the player supplies their disc. Keep all package files together.

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
