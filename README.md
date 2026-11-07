# No-Nonsense LAN Launcher

A Windows Host and Client for private LAN game nights. The Host shares a playlist and verified game files; Clients can join the room, download or repair files, and launch their own games. Game binaries and licenses are not included.

This is a test release. The launcher executables are unsigned, so Windows and antivirus products may warn or block them. Network setup can require administrator permission. Host and Client must use the same release version.

- [Build the app — prerequisites, steps, outputs and troubleshooting](BUILD-INSTRUCTIONS.md)
- [How to use the launcher and source layout](Source/README.md)
- [Implemented features and validation status](Source/FEATURES.md)
- [Native VLA source and third-party notices](Source/vla-native/README.md)
- [Report a problem](.github/ISSUE_TEMPLATE/bug_report.md), [contribute](.github/CONTRIBUTING.md), or [report a security issue](.github/SECURITY.md)
- [Project license](LICENSE): GPLv3 for project-owned code. Bundled third-party components retain their own licenses and notices.

The Essential Build Source ZIP includes the verified prebuilt VLA runtime for the standard build. The Git source repository omits that assembled runtime; the native README explains how to reproduce and assemble it. See the build guide to choose the right download.

Download the complete Windows package from a GitHub Release when one is published. GitHub's automatically generated source ZIP is source code, not a runnable launcher package. Keep `Host.exe`, `Client.exe`, `Quick Start.exe`, and `Launcher Bin/` together.
