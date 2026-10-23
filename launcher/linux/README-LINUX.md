# Darkwatch: Darker Edition 0.5 — Experimental Linux / Proton

This package runs the Windows port through your installed Proton. Linux graphics,
audio and controller behavior have not been verified. Co-op remains beta.

You need native Linux Steam, Proton Experimental and its matching Steam Linux
Runtime already installed, Python 3.9 or newer, and Vulkan graphics drivers
supported by Proton. Flatpak Steam is not supported by this wrapper. It does not
download dependencies. Supply your own original Xbox Darkwatch ISO or XISO.

Extract the entire archive into a writable Linux folder and open a terminal there:

```sh
./Darkwatch.sh
```

The terminal menu provides Import, Play, optional HD installation, Verify and
Status. Import your disc first and let shader preparation finish. Nothing plays
automatically after import. The optional HD pack is a separate download; keep all
its numbered parts together and select the `.zip.001` file. Both the Windows and
Linux packages use the same optional HD download.

Commands are also available:

```sh
./Darkwatch.sh --import-iso "/home/me/Games/Darkwatch.iso"
./Darkwatch.sh --install-hd-textures "/home/me/Downloads/Darkwatch-Darker-Edition-0.5-HD-Textures.zip.001"
./Darkwatch.sh --status
./Darkwatch.sh --verify
./Darkwatch.sh --play
```

If Steam or Proton is elsewhere, add `--steam-root "/path/to/Steam"` and/or
`--proton "/path/to/Proton - Experimental"` before the action. The launcher finds
the matching runtime from that Proton installation's manifest. If it is missing,
install the requested runtime through Steam. Use folder names without colons or
backslashes. Paths with spaces and Unicode characters are supported.

Keep `windows/` and `linux/` beside `Darkwatch.sh`. Saves, settings, installed game
files and game caches stay in `GameData/`; Proton's prefix and shader cache stay
in `.proton/`, all inside this folder. Keep both when moving the installation.
Leave the terminal open during play; the launcher waits for the game to close
naturally. One operation or play session can use a folder at a time. Proton may
also perform its normal one-time setup in its own installed Steam tool folder.
First-time Proton setup and shader preparation can take several minutes. Press
Ctrl+C once to request cancellation and allow the current operation to roll back.
Close the game before importing, repairing or changing the HD pack.

This terminal launcher bypasses the Windows graphical launcher. No .NET or
Windows launcher setup is required. Do not force a second Proton compatibility
layer around `Darkwatch.sh`. Normal play has no test timer or diagnostic logging.
