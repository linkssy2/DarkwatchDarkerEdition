# Darkwatch: Darker Edition 0.8.1

- Faster first-time character and game-resource preparation. Fresh enhanced Import Once installations, including shader preparation, measured 4m25s to 4m34s on the development PC. Original-only preparation measured about 39 seconds. Times vary by CPU and storage.
- Corrected an intermittent character preparation verification failure while retaining parallel preparation and all content integrity checks.
- Faster cold shader preparation on larger CPUs, with identical generated cache output.
- Original-only installations use the original playable characters and animations, stay in first person, and do not offer unavailable added-character selections in campaign, co-op or versus.
- Original-only setup skips expanded-character preview generation and removes obsolete generated previews during verification.
- Expanded characters, enhanced models and animations remain an optional fresh-install choice. Existing installations preserve their chosen content and saves.
- The prepared character archives are byte-identical to the validated enhanced content; animation, model and physics changes are preserved.

Online co-op development remains separate from this release. Local split-screen co-op and versus remain available. The experimental Linux/Proton package shares the Windows runtime and preparation payload.

Close the game and launcher before updating. Extract the complete package over the matching launcher folder, preserving GameData, saves, settings and optional textures, or select Use Existing Install to reuse a previous installation. Existing installations retain their content choice; changing that choice requires a separate fresh installation. Direct-ISO installations still require the ISO. Linux users must keep the windows/ and linux/ folders together and preserve their Proton environment. No original game files are included; a supported Xbox Darkwatch disc image is required.

Fresh original-only and enhanced installations passed both Import Once and ISO-direct preparation checks. Both options also passed fresh Windows launcher UI installs and campaign startup: camera switching, firing and pause input checks, with third-person Cassidy available in the enhanced install and first-person restrictions retained in the original-only install. Installed assets and shader caches passed post-boot integrity checks, with no error logs or crash dumps found.

These are focused installation and startup checks, not full-campaign acceptance. Local multiplayer, audio and sustained performance were not retested in these final fresh-install runs. Live Linux/Proton gameplay and a clean-machine full source rebuild remain unverified; Linux/Proton remains experimental. Quiver-compatible asset naming is retained, but catalog recognition must be checked after publication.
