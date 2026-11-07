# LAN Launcher native VLA service — unchanged signed driver

The selected implementation uses a private **LanLauncherVLA** service with the existing, unchanged, Microsoft-signed **zttap300** driver. No new kernel-driver signing process is required. The rebuilt user-mode service is currently an unsigned developer build. Nothing in these scripts installs or runs a service/driver or changes firewall/signing settings.

## Current identity and ownership contract

| Resource | Identity |
|---|---|
| Private service | `LanLauncherVLA` |
| Display name | `VLA - Virtual LAN Adaptor` |
| Executable | `%ProgramFiles%\LAN Launcher\VLA\vla-service.exe` |
| Private state | `%ProgramData%\LAN Launcher\VLA` |
| API / primary UDP default port | `47993` |
| Token / port protocol files | `authtoken.secret`, `zerotier-one.port` inside private state |
| Borrowed driver service / component | `zttap300` |
| Original driver provider | `ZeroTier` |
| Unchanged driver files | `driver/zttap300.inf`, `driver/zttap300.cat`, `driver/zttap300.sys` |
| Original hardware IDs / endpoint suffix | `root\zttap300`, `zttap300` / `.tap` |
| VLA adapter friendly name | `VLA [network-id]` |
| VLA registry ownership tag | `_VLATapIdentifier` = exactly 16 lowercase hexadecimal network-ID characters |
| VLA exact-device ledger | `vla-devices.d/<network-id>.instance` inside private state; exact Windows DeviceInstanceID, no added whitespace |
| Private DNS / firewall markers | `LANLauncherVLA:<network-id>`, `LAN Launcher VLA`, `lanlauncher-vla-icmp*` |

Original kernel product/provider metadata remains visible in driver details because the signed files are untouched. VLA's service, settings, adapter alias and policy ownership remain private.

Native adapter reuse, state changes and removal require the shared ComponentId **plus** VLA tag **plus** exact private ledger ID. Unmarked ZeroTier adapters are never adopted. New adapter binding uses a freshly created SetupAPI information element and a driver list restricted to the exact packaged INF; it calls `DIF_INSTALLDEVICE` for that device only. The upstream hardware-wide `UpdateDriverForPlugAndPlayDevices` code and ordinary legacy-device cleanup have been removed. Cleanup removes only owned device instances; it never explicitly deletes the shared driver package or kernel service.

Before creation and again immediately before binding, native code resolves the existing `zttap300` service ImagePath and compares that file byte-for-byte with packaged `zttap300.sys`. A different/unreadable existing binary causes refusal rather than an attempted replacement. This is a guard against interfering with another ZeroTier version; runtime coexistence under external concurrent upgrades still requires testing.

## Reproduce without installation or runtime tests

Prerequisites: Git, Visual Studio x64 C++ build tools, Windows SDK (including SignTool), and the exact ZeroTierOne MSI recorded in `shared-driver-lock.json`. The MSI and assembled runtime are excluded from the source repository. Put the MSI at `Source/vendor/ZeroTierOne.msi`, or pass its path with `extract-signed-driver.ps1 -MsiPath`. The required ProductVersion is 1.16.2 and SHA-256 is `42514072b0fe44b8f66e0395bcd23a0b1d1642c28ed00831f1527b2f41b14670`; another installer is refused.

From this directory:

```powershell
.\prepare-source.ps1 -Fetch
.\verify-source.ps1
.\extract-signed-driver.ps1
.\verify-shared-driver.ps1
.\prepare-driver-source.ps1
.\build-user.ps1
```

Then, from the repository root, assemble the runtime (using the Python environment containing `Source/requirements.txt`):

```powershell
python Source/scripts/assemble_vla_runtime.py --service Source/vla-native/out/user/vla-service.exe --driver Source/vla-native/out/shared-driver-source/driver --provenance Source/vla-native/out/user/service-provenance.json --notice Source/vla-native/THIRD-PARTY-NOTICES.md --notice Source/vla-native/licenses --notice Source/vla-native/out/shared-driver-source/notices
```

This creates `Source/vendor/vla` and refuses to overwrite an existing runtime. After successful assembly, the normal Windows release builder can use it. A complete fresh-machine native build has not yet been validated using these instructions.

Preparation downloads source only if absent. The user-mode build uses the installed Visual Studio x64 MSVC compiler and Windows SDK, with SSO disabled and the static C runtime. It launches development tools only, never the compiled service. No WDK or custom kernel build is needed. `verify-shared-driver.ps1` uses an installed Microsoft SignTool or an explicit `-SignToolPath`; its current local SDK fallback is optional and is not a runtime dependency.

Outputs:

- `out/user/vla-service.exe` and `service-provenance.json`: private service plus source/patch/binary identity attestation for the backend's schema-2 shared-driver package.
- `out/shared-driver-source/driver/`: unchanged x64 INF/CAT/SYS, extracted directly from an MSI database stream and cabinet; no `msiexec` or installer action is invoked.
- `out/shared-driver-source/signature-verification.json` and logs: static hash/catalog/kernel-policy results.
- `out/shared-driver-source/notices/`: original corresponding driver source ZIP, GPL text and provenance notice for distribution alongside the unchanged driver.

The parent packaging workflow assembles these into `vendor/vla`. The service provenance is a build record, not a publisher signature. Production publisher signing of the user-mode EXE can be added separately; it does not require rebuilding or signing the existing kernel package.

## Source, licensing and verification scope

Agent/controller source is pinned to [ZeroTierOne 1.14.2, commit 185a3a2](https://github.com/zerotier/ZeroTierOne/tree/185a3a2c76e6bf1b1c0415871f43076638eb007c). Its original LICENSE records Change Date **2026-01-01** and Change License **Apache-2.0**, while its Licensed Work label oddly says 1.4.4. These are recorded upstream terms, not a legal-clearance conclusion. Original notices are preserved. The source lock checks the commit, patch hash, every changed file and unexpected edits. A pristine pinned archive plus the patch reproduces all locked modified hashes.

The signed driver is extracted from the existing MSI ProductVersion **1.16.2**. Its three files are byte-identical to the x64 prebuilt driver in pinned 1.14.2; the driver source and x64 prebuilt files have no changes between tags 1.14.2 and 1.16.2. Driver source/INF headers state **GPL version 2**. Include the supplied original source archive, GPL text and notices with redistribution. Other components retain their own licenses; see `THIRD-PARTY-NOTICES.md` and `licenses/`. This route does not incorporate the newer nonfree controller into the private service.

Microsoft SignTool `/kp /v /c` verifies both the original SYS and INF against the original CAT successfully. The catalog chain includes Microsoft Windows Hardware Compatibility Publisher. This establishes static cryptographic/catalog verification, **not** acceptance under every current Windows blocklist, Secure Boot/HVCI policy or actual runtime coexistence. Those require an explicitly authorized disposable-VM/device test. No such installation/load/network test has been performed for this shared build.

The older pinned agent still needs security review and ongoing maintenance before public production use. Built-in ZeroTier root infrastructure/protocol interoperability remain; this is not an independently hosted root network.

Earlier custom `vlatap` development artifacts and records are preserved under `history/custom-driver/` and ignored `out/`; that route is superseded. `build-driver*.ps1` and `prepare-signing-input.ps1` now stop with an explicit retired-workflow message. Do not use those historical unsigned kernel artifacts in the current package.
