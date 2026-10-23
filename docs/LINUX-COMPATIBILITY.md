# Linux compatibility — 0.5.5

This Linux-only release retains 0.5 gameplay and adds Proton setup compatibility.
It remains an experimental compatibility build, published as a normal release.

The SDK shader helpers now construct infinity with IEEE bits instead of
Microsoft-only HLSL literals. Offline Wine compilation passed 16 corrected cases;
the original cases failed. Microsoft's compiler produced identical bytecode
for each old/new pair. This does not establish live Linux rendering.

The importer checks its managed root and descendants without rejecting Wine's
mapped host-drive ancestors. File hashes and disc admission remain enforced.
The terminal wrapper checks managed trees for native Linux symlinks; direct
Windows Python under Proton cannot reliably see those links. Both setup routes
require real package/data files and directories.

The recommended Steam shortcut invokes the existing packaged Python backend
through the adapter, with opt-in setup dialogs and a bounded failure-only report.
It tolerates a closed console and reports dependency/argument errors. Steam
manages its prefix; installed game files, saves and settings remain in GameData.
The optional terminal route retains its local .proton prefix and progress output.
See [setup and update instructions](../launcher/linux/README-LINUX.md).

Synthetic launcher/import tests, actual packaged-Python Wine error-path probes,
archive validation and SDK patch reconstruction passed. These do not replace
a successful full disc import or live Steam/Proton test. Linux graphics, audio,
movies and controllers still need testing. Co-op remains beta. Existing 0.5 HD
downloads remain compatible. No original game files, generated game source or
Microsoft XDK are distributed; users import their own supported disc.
