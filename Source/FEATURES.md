# LAN Launcher features and validation

This is the current feature map for the Windows Host and Client. **Implemented** means there is an owning code path. **Packaged** means it is included in the normal release build. **Live validation pending** means automated tests or UI previews do not yet prove the behavior on the stated physical setup. A failed or missing live test does not turn implemented code into a planned feature. The release number and room protocol come from [`lantool/_version.py`](lantool/_version.py).

## Rooms and onboarding

| Capability | Current status | Boundary or next check |
|---|---|---|
| Portable Client, Host, Quick Start, and bundled VLA setup | Implemented and packaged | Check fresh-machine installation, UAC, service readiness, and coexistence. There is no separate system installer. A fresh package does not need an ordinary ZeroTier download. |
| Host discovery and trusted join bundles | Implemented | Host emits signed LAN beacons. Client verifies them and can persist an imported or packaged bundle. Repeat discovery and reconnect on two Windows PCs and on a LAN without internet. |
| Room moon | Implemented | Host generates and signs it; Client checks signature and expected hash, installs it, and remembers its ID. Confirm VLA discovers it and completes a two-PC internet-free join. A moon remains installed after room close; its Host endpoint is unavailable while that Host is offline. |
| VLA join, address, adapter preference, and recovery | Implemented | Confirm route choice, address assignment, Host loss, close/reopen, and adapter restoration on physical PCs. Game launches are blocked during a network transition. |
| Room key and direct IP join | Implemented | Room key can use VLA when the Host's physical LAN address is unreachable; direct IP contacts a Host on the reachable network. Test actual internet-path limits before advertising general remote play. LAN broadcast itself does not cross routers. |
| Password and Host admission | Implemented | Host can require a password. Repeated wrong attempts require Host approval; Host can deny and use a room-scoped blacklist. Validate the protected-room flow on a current matched release and retain the exact test result. |
| Host/Client release compatibility | Implemented | Exact release and protocol checks block mismatches. Host-approved launcher-only version sharing uses a three-digit key. Test new release pairs on two PCs; do not treat a transfer as an automatic update. |

## Games and transfers

| Capability | Current status | Boundary or next check |
|---|---|---|
| Host playlist and Client library | Implemented | Host selects launch executables and artwork from game folders; Client sees only shared games with status and player activity. Measure responsiveness with a populated library on HDD and SSD. |
| Game launch and configuration | Implemented | Executable and path checks, arguments, and the process watcher are present. Game-specific compatibility still needs real play sessions. `games/bfbc2.json` is a sample manifest, not the entire game catalog. |
| Signed index and file sync | Implemented | Host indexes files; Client verifies signed indexes and downloaded pieces, resumes partial downloads, and can force a full **Verify integrity** pass. Test large games, antivirus interaction, and repair on a physical LAN. |
| Peer sharing | Implemented | Verified complete or partial pieces can be served to other Clients; the Host remains a fallback. Request budgets adapt from four up to twelve, with at most eight uploads per process. There is no bandwidth cap. Measure throughput and fairness on multiple real PCs. |
| Download queue and controls | Implemented | Queue reordering, pause, resume, cancel, and transfer activity are in the Client UI. Verify interrupted sessions and restart recovery with real game data. |
| Presence and activity | Implemented | Player heartbeat, game activity, and Host/Client identity separation are wired. Check player count and launch/exit reporting in a current multi-PC run. |

## Windows app and operations

| Capability | Current status | Boundary or next check |
|---|---|---|
| Qt desktop interface | Implemented and packaged | Client and Host layouts, Quick Start, themes, custom colors, profile picture crop, About, and terms acknowledgement are present. Packaged startup checks run during release assembly; interaction still merits visual review. |
| Scoped elevation and firewall preparation | Implemented | The helper accepts allow-listed administrative actions. Launcher firewall rules and VLA preparation are available; UAC-free setup is not promised. Verify prompts and rule scope on a clean Windows PC. |
| Diagnostics and recovery | Implemented in part | Connection checks, Prepare this PC, Repair LAN, adapter profile switching, and Wipe VLA exist. VC++/DirectX installation, GPU-driver validation, and a full prerequisite manager are not shipped. |
| Portable data and exit behavior | Implemented | `portable.flag` selects local launcher data. Room cleanup and ownership-scoped VLA removal are wired. Confirm crash recovery and clean exit with both launcher roles and pre-existing networking software. |
| Publisher signing and antivirus review | Outstanding release work | The launcher executables are unsigned. Do not claim a Defender detection is resolved without a vendor determination for the exact submitted binary. |

## Still planned or deliberately limited

- A general remote-play promise is **not validated**. Room-key joining exists, but end-to-end internet reachability, routers, firewalls, and performance need acceptance evidence.
- A full offline browsing cache for library, manifests, and presence without a Host is **not shipped**. Saved game files and resumable partial transfers are separate capabilities.
- Automatic dedicated game-server launch from manifests is **not shipped**. The Host shares a playlist and files; a game may launch its own server through its normal executable.
- A standalone Windows system installer, publisher signature, and universal game prerequisite installer are **not shipped**.

