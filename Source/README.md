# LAN Launcher

LAN Launcher is a portable Windows app for a shared game night. One PC runs **Host** and chooses which games to share. Other PCs run **Client** to find or join the room, see its game library, obtain verified game files from the Host and other Clients, and launch their own installed copies. **Quick Start** walks through the Host and Client flows. No game binaries are included in the launcher package.

The app is branded **No-Nonsense** in its interface. `LAN Launcher` is the release and package name; `lantool` and `silent_tunnel` are internal source package names. VLA (Virtual LAN Adaptor) is the launcher's private networking service. It uses an unchanged, signed ZeroTier network driver, but has its own service, identity, controller, data directory, and API. Installing the ordinary ZeroTier desktop client is not part of the current setup path.

## What ships

A normal release folder contains `Host.exe`, `Client.exe`, `Quick Start.exe`, `Launcher Bin/`, and an empty `Game Directory/`. Keep the folder together; the executables use the shared runtime in `Launcher Bin`. The release also has a `version.json` and `SHA256SUMS.txt` under `Launcher Bin/Release`. The current version and room protocol are defined in [`lantool/_version.py`](lantool/_version.py), not in this document.

The normal Windows build requires a verified VLA package in `vendor/vla/`. The release builder stops if it is absent. The packaged **Prepare this PC** flow can install the bundled VLA service and driver offline, with a Windows administrator prompt when required. A standalone system installer is not shipped. An optional `portable.flag` beside the executables stores launcher data in a local `LanTool-data/` folder instead of the usual per-user location.

The executables currently have no publisher signature. The bundled driver has its own original signature; that does not sign the launcher executables. Publisher signing and antivirus review remain release work. If the folder is downloaded as a ZIP, Windows may mark its files as downloaded; the package includes `Launcher Bin/Release/Unblock downloaded files.cmd` for that folder.

Project-owned code is licensed under [GPLv3](../LICENSE). The native VLA service and bundled dependencies have their own notices and license texts under `vla-native/` and `vendor/vla/notices/`. New release builds include the project license and the native notices.

## Use the launcher

1. Copy the whole release folder. On each PC, run **Quick Start** if you want the guided flow. It presents the terms of service for acknowledgement.
2. On the Host, put each game's files in its own folder under `Game Directory/`. In Host, choose each launch executable and portrait artwork, then enable the games for the room playlist. Open the room when ready.
3. On each Client, finish the player and game-directory setup. Use **Find host automatically** on the same LAN, enter a Host LAN IP, or use a room key where that route is available. A Host join bundle can also establish a trusted Host identity and is saved for later launches.
4. Select a game in the Client library. Install or repair it from the Host and verified peers, then choose **Play**. **Verify integrity** on game details forces a full file recheck against the Host's signed index. Ordinary sync reuses file hashes for up to 24 hours when size and modification time match; expired entries are rehashed on the next check.

The Host may require a room password. Repeated wrong attempts can require explicit Host approval; the Host can deny and block an attempt for that room. Host and Client releases must match exactly to join. If they differ, the Host can approve a launcher-only transfer protected by a three-digit key. Games and player data are excluded from that transfer.

The Client has Library, Room, Downloads, Settings, game details, and About views. Downloads can be queued, reordered, paused, resumed, and cancelled. The UI includes No-Nonsense, Pearl, Dark, Neon, and Custom themes. The Client supports a screen-filling window mode; Client and Host remember separate window sizes. About exposes the terms of service.

Current source recovery improvements include authenticated sharing of already installed games in protected rooms, activity restoration after reconnect, fragmented moon downloads, and settings saves that preserve changes from another launcher role. Presence is bounded to 1,024 connected players with matching limits for complete avatar rosters.

## Network behavior and limits

Local discovery uses signed LAN announcements. A Client can trust a discovered Host or import its signed join bundle; later announcements are checked against that identity. The Host creates a room moon, serves it with a signature, and advertises its hash. The Client verifies and installs it before joining the VLA room when needed. Room-key joining through VLA is implemented for a Host whose physical LAN address is not reachable, but internet-path behavior is not a blanket guarantee of remote play.

VLA setup, service operations, launcher firewall rules, moon installation, adapter preference, and network-profile changes can request administrator permission. Opening an unused launcher does not itself install VLA or join a room. **Prepare this PC**, **Repair LAN**, network diagnostics, and **Repair Network/Wipe VLA** are explicit controls. Wipe is an ownership-scoped removal action and does not remove game files or the shared signed driver.

An interrupted VLA installation can resume with the same verified package and installing user. Network profile recovery checks the saved adapter and network identity before restoring a category; old records containing only interface indexes require manual restoration. If an administrator operation times out, its helper may still be running: wait for it to exit before retrying. Its request and eventual result are retained at the location shown in the error.

Code paths and local tests establish much of this behavior; they do not prove every physical network arrangement. See [`FEATURES.md`](FEATURES.md) for implemented, packaged, and live-validation status. On 6 November 2026 the user reported completing offline VLA preparation, an internet-disconnected two-PC moon join, close/reopen recovery, a large transfer with peers, and a real multiplayer session without apparent frontend issues. Exact test configuration and logs remain unrecorded; see the acceptance report in FEATURES.md.

## Build and source layout

Start with [the step-by-step build guide](../BUILD-INSTRUCTIONS.md), including prerequisites, Essential ZIP versus Git-source differences, output locations and troubleshooting.

From the workspace root, double-click `Build Latest LAN Launcher.cmd`. It advances the patch version for a new build attempt, checks the Qt pages, runs `Source/scripts/build_windows.ps1`, then checks the assembled Client and Host. The versioned release folder appears inside `Releases/`; the build does not create a ZIP. Logs and reusable caches stay under `Source/build/`. Temporary packaging copies are removed after successful assembly. Source export ZIPs belong in `Exports/`. Building is a release action; ordinary source or documentation edits do not require an immediate build.

For development, use a supported Python environment with `requirements.txt`, then run `python -m lantool.qt.main --preview` from `Source/` for an isolated UI preview. `--capture-ui <path>` saves a screenshot without joining a room. The runnable role entry points are `run_host.py`, `run_client.py`, and `run_quickstart.py`. Network-capable behavior needs Windows and the bundled VLA runtime.

Release packaging requires **Windows x64 CPython 3.15.0**, installed with the exact dependencies in `build-requirements.lock` (`python -m pip install --require-hashes -r build-requirements.lock` from `Source/`). The Essential ZIP includes `vendor/vla`; Git source downloads omit it and require [native build and assembly](vla-native/README.md) first. To run the automated suite from the full repository, install `dev-requirements.txt` and run `python -m pytest -q` from `Source/`. The Essential ZIP omits tests. Tests use isolated state; they do not establish physical two-PC behavior.

- `lantool/qt/`: Qt frontend and bridge.
- `lantool/netcore/`, `lantool/trust/`, `lantool/presence/`, `lantool/filesync/`: room, identity, activity, and file transfer.
- `silent_tunnel/`, `vla-native/`, `vendor/vla/`: private network service integration, native source, and verified release payload.
- `scripts/build_windows.ps1`: Windows release assembly and packaged startup checks.
- `tests/`: automated behavior checks. Hardware and multi-PC outcomes must be recorded separately from these tests.

Keep current user-facing and feature status information in this README and [`FEATURES.md`](FEATURES.md). Older release notes and audit claims should not be reintroduced as current product facts.
