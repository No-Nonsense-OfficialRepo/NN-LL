# No-Nonsense LAN Launcher (NNLL)

A Windows Host and Client for private LAN game nights. The Host shares a playlist and verified game files; Clients can join, download or repair files, and launch their own games. Game binaries and game licenses are not included.

## Download a test build

[Download NNLL v0.9.63 Test Build](https://github.com/No-Nonsense-OfficialRepo/NN-LL-Test-Build/releases/tag/v0.9.63) from the separate test-build repository. Download its attached ZIP, extract it completely, and keep `Host.exe`, `Client.exe`, `Quick Start.exe`, and `Launcher Bin/` together. Host and Client PCs must run the same version.

This repository contains the source. GitHub's automatically generated source ZIP is not a runnable Windows package. The test executables are unsigned, and network setup or launching some games can require administrator permission.

## Build from source

Follow [BUILD-INSTRUCTIONS.md](BUILD-INSTRUCTIONS.md) for the tested Windows build requirements and steps. A Git clone does not contain the assembled VLA runtime. Follow the [native VLA build and assembly instructions](Source/vla-native/README.md) before building from a clone. The Essential Build Source ZIP described in the build guide includes that runtime when published.

## Documentation

- [Using the launcher and source layout](Source/README.md)
- [Features and validation status](Source/FEATURES.md)
- [Build instructions](BUILD-INSTRUCTIONS.md)
- [Contributing](.github/CONTRIBUTING.md), [reporting a bug](.github/ISSUE_TEMPLATE/bug_report.md), and [security reports](.github/SECURITY.md)

## Community and license

- [No-Nonsense on YouTube](https://www.youtube.com/@NoNonsenseLAN)
- [Join the Discord community](https://discord.com/invite/a9NgtcnH5r)
- [GPL-3.0 project license](LICENSE). Bundled third-party components retain their own licenses and notices.
