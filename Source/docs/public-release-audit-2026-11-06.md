# Public test release audit — 6 November 2026

Scope: local source intended for a public GitHub repository, its Windows builder, and the existing V0.9.60 package. No repository was published and no new Windows package was built during this pass.

## Findings fixed in source

1. **Launcher sharing omitted the project license.** The release builder now copies the root `LICENSE`, but the launcher handoff's root-file allow-list excluded it. Added `LICENSE` to the manifest-verified export and to the existing export regression test.
2. **Diagnostics leaked part of profile names containing spaces.** The profile-path redactor stopped at the first space. It now redacts the entire profile directory, including names containing apostrophes and paths using forward slashes. Added regression coverage.
3. **Release Python selection disagreed with the release gate.** The wrapper accepted Python 3.10+ while packaging requires 3.15.0. It now selects 3.15.0 and checks locked dependency versions before deciding whether dependencies need installation.
4. **Native source-build instructions were incomplete.** They assumed a local MSI excluded from Git and stopped before assembling `vendor/vla`. Documented the exact installer version/hash, required tools and final assembly command. Added an explicit compression assembly import needed by the driver-source ZIP script in Windows PowerShell.
5. **Publication exclusions missed common local files.** Added environment files, virtual environments, Host identities and saved join bundles to the ignore rules. Public source candidates were checked using a separate empty Git index under ignored build output; the workspace itself remains outside Git.

## Verification

- Before the final documentation and ignore additions, the ignore rules selected 582 files totaling approximately 10.7 MiB. No executable/build outputs were included. A scan of those files found no matches for the selected private-key and credential-token patterns; this is not a guarantee that all possible secrets are absent.
- Copied those candidates into an isolated source snapshot without the ignored VLA runtime, upstream checkout, native outputs or packaged builds. Its complete suite passed: **797 tests in 165.00 seconds**.
- The final redaction refinement and license handoff passed **20 focused tests**.
- Edited PowerShell files parsed without errors. The wrapper and native build were not executed end to end during this pass.
- Tests used the already installed dependencies. This was not a fresh dependency installation or a clean Windows VM test.

## Remaining work before publishing a binary

1. **Resolve the Qt wheel notice discrepancy.** Installed PySide6, Essentials, Addons and shiboken6 6.12.0 metadata lists LGPL/GPL alternatives, while their recorded license files contain only `LicenseRef-Qt-Commercial.txt`. This does not establish which distribution was installed or its redistribution permissions. Verify the exact locked wheel provenance, applicable terms, required license notices and corresponding-source access. V0.9.60 does not contain a complete Qt/Python dependency notice bundle; copying the commercial notice alone is not a resolution.
2. **Verify the native build from a fresh checkout.** The public source excludes the MSI and generated VLA runtime. The documented process still requires the exact pinned MSI, compiler, SDK and upstream fetch. Its full execution on a clean machine has not been established. The old pinned native networking service also remains a security-maintenance concern recorded in its README.
3. **Build a fresh public candidate.** V0.9.60 predates the root license and these source fixes. Include the project license, corrected native notices, complete dependency notices and hashes, and tie the download to a source tag/commit. Keep the full runnable package as a Release asset; omit game files and personal state.
4. **Retain physical acceptance evidence for that candidate.** Record Windows builds, release version, topology and results for setup, protected admission, transfers, recovery and a multiplayer session. Existing reported tests lack that complete configuration record.

Publisher signing remains outstanding. A public test release must accurately state that the executables are unsigned and that broader physical compatibility has not been established. The signed third-party driver does not sign the launcher or private service.
