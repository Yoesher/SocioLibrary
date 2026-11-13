# SocioLibrary maintenance conventions

- The current milestone broadens the workbench to social science research, following the user's explicit competition-related request. Preserve stability and lightweight operation; do not add unrelated features.
- Research lenses adjust examples and evidence-review prompts only. Never use them to hide papers, change Zotero permissions, expand semantic scope, enable subscriptions, or make AI requests without the existing per-request review.
- Keep the application display name exactly `SocioLibrary`: native window titles, HTML title, installer product name, executable product metadata, macOS bundle display name, and shortcut descriptions. Keep explanatory text in page content, not in the product name.
- GitHub releases use the title `SocioLibrary` and a separate `vX.Y.Z` tag. Upload only software packages: the Windows installer, Windows portable ZIP, and the two macOS architecture ZIPs. Keep checksums in the release body and CI artifacts; do not upload checksum text files, documentation, reports, or other ancillary release assets. GitHub-generated source archives are platform-managed.
- Keep the Chinese and English README landing pages aligned. Preserve verified platform limitations and direct download links.
- Maintenance work must preserve libraries, PDFs, notes, annotations, models, settings and backups. Runtime pruning is limited to authenticated program artifacts; never blanket-delete installation or research directories.
- Before publishing, pass source checks, frozen offline inference/search, native GUI loading, repeated launch, overlay installation, updater handoff and data-retention checks. Windows upgrade validation must use the preceding public installer, not only a fresh install.
