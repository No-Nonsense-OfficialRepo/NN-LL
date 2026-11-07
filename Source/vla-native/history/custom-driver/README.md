# LAN Launcher native VLA fork

This directory contains the reproducible source customization and build path for the private LAN Launcher backend. Both the x64 user-mode service and renamed kernel driver were built successfully. Microsoft InfVerif checks passed and Microsoft Inf2Cat generated a real unsigned catalog. No production signatures, installation, driver loading or deployment tests have been performed. This is not a distributable production runtime package.

## Pinned source and recorded license terms

The source pin is [ZeroTierOne 1.14.2](https://github.com/zerotier/ZeroTierOne/tree/185a3a2c76e6bf1b1c0415871f43076638eb007c), commit `185a3a2c76e6bf1b1c0415871f43076638eb007c`. `source-lock.json` records the commit, patch SHA-256, modified-file hashes and deleted source path. The downloaded `upstream/` checkout and local outputs are ignored; the checked-in patch is the reviewable change set.

That exact release's [LICENSE.txt](https://github.com/zerotier/ZeroTierOne/blob/185a3a2c76e6bf1b1c0415871f43076638eb007c/LICENSE.txt) records Change Date **2026-01-01**, Change License **Apache License version 2.0**, and a grant effective on that date. Its “Licensed Work” label oddly names version **1.4.4** despite being the 1.14.2 repository. These are recorded source terms, not a legal-clearance conclusion. Original license/copyright notices are preserved. This pin intentionally avoids substituting the materially different current controller license from `nonfree/` into this build.

The TAP driver has its own **GPL version 2** notices; Microsoft service helper files carry **MS-PL** notices. Included dependencies retain their original licenses. See `THIRD-PARTY-NOTICES.md` and `licenses/`. A binary distribution must carry the appropriate notices/licenses and provide the corresponding modified GPL driver source, including its build files. The source pin and patch should accompany the native artifacts.

Version 1.14.2 is an older dependency. Public production release requires a security review and an ongoing process to assess and backport fixes; the license choice alone does not establish runtime security or current compatibility.

## Identity contract

| Resource | VLA identity |
|---|---|
| Windows service | `LanLauncherVLA` |
| Service display | `VLA - Virtual LAN Adaptor` |
| Executable | `%ProgramFiles%\LAN Launcher\VLA\vla-service.exe` |
| Private state | `%ProgramData%\LAN Launcher\VLA` |
| Default API and primary UDP port | `47993` |
| Driver service / component | `vlatap` |
| Root hardware ID | `root\vlatap` |
| Native SetupAPI hardware ID | `vlatap` (also declared in INF) |
| Driver provider | `LAN Launcher VLA` |
| Driver package | `driver/vlatap.inf`, `driver/vlatap.cat`, `driver/vlatap.sys` |
| Kernel/user device link suffix | `.vlatap` |
| INF minimum OS / package location | Windows 10 build 16299; Driver Store `DIRID 13` |
| Adapter alias | `VLA [network-id]` |
| Registry ownership value | `_VLATapIdentifier` |
| DNS policy ownership marker | `LANLauncherVLA:network-id` |
| Firewall program rule | `LAN Launcher VLA` |
| Firewall ICMP rule prefix | `lanlauncher-vla-icmp` |

The token and port protocol filenames remain `authtoken.secret` and `zerotier-one.port` inside VLA's private state directory. The Windows environment override is `VLA_HOME`; `ZEROTIER_HOME` cannot redirect the VLA Windows service into an ordinary ZeroTier installation. The service uses its compiled home/port defaults with an executable-only SCM command. Non-default foreground arguments do not change SCM defaults.

The patch removes ordinary ZeroTier legacy-device cleanup. `-D` matches the **exact** `vlatap` component ID. Driver lookup uses the executable directory plus `driver/vlatap.inf`, independently of private state. The stock self-updater and update distribution are disabled in code so an upstream binary cannot replace this fork. SSO is disabled for this private-controller build, removing the Rust/`zeroidc` dependency. ZeroTier protocol interoperability, built-in root servers and copyright attribution remain; this change does not establish an independently hosted root infrastructure.

## Reproduce the source and user-mode build

From this directory, in a normal PowerShell:

```powershell
.\prepare-source.ps1 -Fetch
.\verify-source.ps1
.\build-user.ps1
```

`-Fetch` downloads only when source is absent. Preparation refuses a different source commit and unrelated source edits. Verification checks the pin, patch hash, every modified file hash, deleted files and unexpected edits. The patch was separately applied to a pristine archive of the pinned commit; every resulting changed file matched the recorded hash.

The build uses installed Visual Studio x64 MSVC and Windows SDK tools. It compiles the actual `ClCompile` source list from the patched upstream project, excluding upstream `selftest.cpp`, with the x64 Release definitions and static C runtime. It writes only `out/` and `build-user.log`. It does not install a service, load a driver or launch the executable. No Rust or MFC installation is required. On this machine, VS18's MSBuild FileTracker failed with access denied; direct `cl.exe` compilation succeeded without changing system toolchains or permissions.

Output: `out/user/vla-service.exe`. It is an **unsigned user-mode build**, not a substitute for the renamed and signed driver package. Build output contains no version-resource block because the upstream user-mode resource file contains no application resources; service/display names are in the native service implementation.

## Local driver build and signing input

```powershell
node .\acquire-wdk.mjs
.\expand-wdk.ps1
.\build-driver-local.ps1
.\prepare-signing-input.ps1
```

`acquire-wdk.mjs` downloads the official Microsoft WDK and matched SDK packages, version **10.0.28000.2526**, from NuGet's HTTPS feed and verifies their pinned sizes/SHA-256 values in `wdk-lock.json`. The three packages total **327,538,318 bytes** compressed and about **1.22 GB** extracted. All downloads and extraction remain under ignored `out/`; there is no system-wide SDK/WDK installation or global package-cache change. This is the WDK release Microsoft's current documentation associates with Visual Studio 2026. The packages' own development-tool license terms apply; notably, the WDK package's included license text is headed “MICROSOFT PRE-RELEASE SOFTWARE LICENSE TERMS” even though this version is listed as a release on NuGet. Those tool packages are local development dependencies and are not added to runtime distribution artifacts.

`build-driver-local.ps1` reads the actual nine `ClCompile` inputs from the patched upstream `windows/TapDriver6/TapDriver6.vcxproj`. It uses the existing x64 MSVC compiler with `/kernel`, kernel-mode headers/libraries from the local WDK, and matching local SDK headers/resource compiler. It links an x64 Native driver with the `GsDriverEntry` security-cookie entry point, kernel libraries, `/NODEFAULTLIB`, `/INTEGRITYCHECK` and NX/ASLR flags. No user-mode CRT import is present. It does not execute the service or driver.

Output: `out/driver-unsigned/vlatap.sys` and `vlatap.inf`. The script checks PE architecture/subsystem, absence of an embedded certificate, resource identities and Microsoft **InfVerif `/h` and `/w`**. Both checks pass. The INF was updated with `PnpLockdown=1`, Driver Store `DIRID 13`, and model decorations restricting installation to Windows 10 build 16299 or later. The legacy source project's other architecture configurations are not evidence of x86/ARM64 builds; the output validated here is x64 only. Build warnings are limited to inherited unused locals/labels and are preserved in the log.

`prepare-signing-input.ps1` verifies the built hashes, stages the service and driver, then invokes Microsoft's actual **Inf2Cat** tool. Its signability checks pass with no errors or warnings. It produces a genuine **unsigned** `driver/vlatap.cat` bound to the finalized INF/SYS, and writes `UNSIGNED.txt` plus `UNSIGNED-ARTIFACTS.json` in `out/signing-input/`. This folder is suitable for the publisher's next signing/submission steps; it intentionally has no production backend manifest. The selected Inf2Cat OS identifiers cover its x64 RS3-through-GE catalog checks and do not substitute for actual OS/runtime testing.

`build-driver.ps1` delegates to the verified local path when these packages are available. Its optional `-SdkVersion` and `-MSBuildPath` parameters retain the alternative installed-WDK/MSBuild path; that alternative has not been validated on this machine.

The new INF/SYS identity invalidates the original vendor catalog/signature. The original `zttap300` binaries/catalog cannot be renamed and reused. The local build and matching unsigned catalog are complete; the publisher must now complete Microsoft's applicable driver submission/signing process and verify the returned signed catalog/SYS against kernel-mode signing policy. [Microsoft's policy](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/kernel-mode-code-signing-policy--windows-vista-and-later-) describes new kernel-driver signing through its developer portal. Nothing here disables Secure Boot, enables test signing, or relaxes signature enforcement. No publisher or Microsoft production signing credentials are available to this build.

After signing, stage the actual signed files as a package matching the Python backend's manifest contract: `schema=1`, `backend=lan-launcher-vla`, exact names above, `executable=vla-service.exe`, `driver_inf=driver/vlatap.inf`, and `files` mapping every packaged relative path to its SHA-256. Do not create a production manifest or copy an incomplete user-mode output into `vendor/vla`. That directory is the launcher's production-package boundary.

Production signing, installation/uninstallation, reboot/Secure Boot/HVCI behavior, side-by-side ordinary ZeroTier coexistence and real multi-machine LAN traffic remain unverified. Compilation, INF validation and catalog generation do not prove those runtime behaviors. Official development-tool references: [WDK NuGet instructions](https://learn.microsoft.com/en-us/windows-hardware/drivers/install-the-wdk-using-nuget), [Microsoft's current WDK/VS compatibility](https://learn.microsoft.com/en-us/windows-hardware/drivers/download-the-wdk), [pinned WDK package](https://www.nuget.org/packages/Microsoft.Windows.WDK.x64/10.0.28000.2526), and [INF validation modes](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/running-infverif-from-the-command-line).

## Native invocation reference

- SCM: executable only; no arguments.
- `-I`: register the currently located executable as `LanLauncherVLA` with the VLA display name. Requires administrator elevation. It does not copy binaries into Program Files.
- `-R`: uninstall `LanLauncherVLA`. Requires administrator elevation.
- `-D`: remove persistent adapters with exact component ID `vlatap` only.
- `-v` / `-h`: version/help without starting networking.
- `-C -U -pPORT "STATE"`: foreground developer mode. It opens sockets, contacts upstream roots, creates state and may cause a Windows Firewall prompt even without elevation. It is **not** run by the build or verification scripts. Elevated foreground mode also has native firewall-rule behavior. Use only as an explicit opt-in integration test on an appropriate test machine.

No native runtime is automatically launched. A prior isolated foreground API smoke test triggered Windows Firewall's prompt, then its process was stopped. No service or driver was installed and no firewall UI was approved. See `BUILD-RESULTS.md` for the exact scope and limitations of that evidence.
