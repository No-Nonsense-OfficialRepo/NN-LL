# Shared signed-driver build evidence — 2026-10-26

## Later live investigation (after the 19:41 Windows restart)

### Final verified result

Windows DISM RestoreHealth completed successfully; full SFC reported no integrity
violations. A subsequent room test still failed with the old installation
sequence, so component-store repair alone did not resolve the VLA failure.

The final native implementation uses `DiInstallDevice` with an explicit Unicode
`SP_DRVINFO_DATA_W` retrieved from the exact INF-restricted compatible-driver
list. It finishes installation on the newly created device only; the shared
driver files, service compatibility guard and ownership checks are unchanged.
The original direct `DIF_INSTALLDEVICE` call did not complete network-class
setup on this PC. The first full-API trial used an ANSI structure and returned
Windows error 87; that intermediate build was replaced by the Unicode fix.

Two successive final room tests connected and cleaned up without errors. The
last reported network status `OK`, `portError=0`, address `10.147.236.1/24`, and
a real Windows interface named `VLA [a01f1c1b3b2fe2cc]` carrying that address.
The earlier successful final test used `10.147.41.1`. No second-PC traffic or
game session was tested. The installed service, source vendor package and
release vendor package contain the final native build. Native compilation,
source/patch verification, signed driver package assembly and 28 related
Python tests passed. Current binary identity is in the package provenance;
the original hash table below is historical.

The hash table below records the earlier build. A subsequent build changes
`VlaSharedDevice.inl` to wait up to 30 seconds for asynchronous network-class
configuration before tagging the exact newly created device. The updated patch,
source hashes and binary provenance are recorded in `source-lock.json` and
`out/user/service-provenance.json`. Source verification, reverse patch validation,
native compilation and both packaged runtime validations passed. The signed
driver files remain unchanged. The updated native package was applied to the
installed private VLA service and the release's external `vendor/vla` directory.

Two temporary local room tests reproduced Code 56 (`CM_PROB_NEED_CLASS_CONFIG`).
Windows bound `zttap300` successfully, but `ComponentId` and `NetCfgInstanceId`
remained absent for the full 30 seconds. Both tests removed their own room and
device; neither established working LAN connectivity. The service API remains
online. The timing change alone does **not** fix this PC's adapter failure.

Windows DISM `/CheckHealth` separately reported a repairable component store.
Targeted SFC verification of `NetSetupSvc.dll` and `netcfgx.dll` passed. Windows
component repair and a subsequent full SFC check were started; their logs are
under `Source/build/windows-repair-*`. Do not assume the corruption caused the
adapter failure without a successful post-repair test.

The selected path uses the unchanged signed zttap300 kernel package with a rebuilt private VLA user-mode service. The prior custom-kernel signing blocker is superseded.

## Exact final artifacts

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `out/user/vla-service.exe` | 2,367,488 | `642095bdd45e307bfec1c056d48fe1659bc7dee285a70b62530849804652f81e` |
| `out/shared-driver-source/driver/zttap300.inf` | 5,312 | `4afb5e5a2897350926704cdcb427fd69bd2c9f0da271941d1484896b54d294ae` |
| `out/shared-driver-source/driver/zttap300.cat` | 10,769 | `38c0bbbca2e32509a32150990dbebf98be4ffe2c141a23e878cbeb6c7d483365` |
| `out/shared-driver-source/driver/zttap300.sys` | 31,744 | `4221486a0d36ef96ab1ed2a537747388655c4c2e470911646f4102d0b88fbdc6` |

Private service source commit: `185a3a2c76e6bf1b1c0415871f43076638eb007c` (1.14.2). Final patch SHA-256: `c59692f6b2ed35d0fb12f6874d20a4c972289fe9bf58c84b3589a86e88325ca2`. The sidecar `out/user/service-provenance.json` records these values and the private SCM/display/port plus shared-driver identity. It is not a code signature; the user-mode EXE remains unsigned.

The source MSI is ProductVersion 1.16.2, SHA-256 `42514072b0fe44b8f66e0395bcd23a0b1d1642c28ed00831f1527b2f41b14670`. It was opened read-only; its `disk1.cab` stream was read and only the three x64 members were expanded. No MSI install/admin install or installer custom action occurred. Extracted files match the pinned originals and are also byte-identical to upstream 1.14.2's prebuilt x64 files.

## Checks completed

- The private service compiled successfully using installed MSVC 14.51 and Windows SDK 10.0.26100.0. No compiled service invocation, including `-v`/`-h`, was performed for this build.
- Source commit, patch, every modified file hash and unexpected-change checks passed. Applying the final patch to a pristine pinned archive reproduced every locked modified file.
- The native binary contains `LanLauncherVLA`; its provenance sidecar's EXE and patch hashes match the final output/source lock.
- Native source has no hardware-wide driver update API. New binding uses only a freshly created exact device information element, then records/tags that instance. Reuse/state/removal require ComponentId `zttap300`, `_VLATapIdentifier` and the exact matching private ledger. Existing shared service SYS byte comparison is checked before creation and immediately before binding; a differing/unreadable version is refused.
- Microsoft SignTool `verify /kp /v /c zttap300.cat zttap300.sys` **passed**, exit 0, zero warnings/errors.
- The same check for `zttap300.inf` **passed**, exit 0, zero warnings/errors. The catalog chain includes Microsoft Windows Hardware Compatibility Publisher, with its original timestamped signature.
- Driver INF/CAT/SYS hashes are pinned in `shared-driver-lock.json`; extraction and signature verification are reproducible via their scripts.
- The driver source tree and x64 prebuilt files have no differences between official 1.14.2 and 1.16.2. `out/shared-driver-source/notices/` includes the original source/build files in a ZIP, full GPL-2.0 text and provenance notice for redistribution. No driver rebuild or new catalog/signature is performed.

## What remains unverified

Static signature/catalog checks do not establish actual loading under every current Windows vulnerable-driver blocklist, Secure Boot/HVCI policy, service installation, reboot behavior, uninstall behavior, ordinary ZeroTier coexistence or real multi-machine LAN traffic. No service or driver was installed, loaded or run during this shared-driver work. These runtime checks require an explicitly authorized test environment.

The EXE is a developer build without a publisher signature; no publisher signature is fabricated. The original driver's valid signature is retained. No test mode, Secure Boot or signature-enforcement setting was changed. The older pinned agent/controller needs security review and continued maintenance before public production use.

An earlier prototype's local API smoke test (before the shared-driver route) opened sockets and caused a firewall prompt, then its process was stopped; no prompt was approved and no service/driver installed. That historical test is not runtime evidence for this rebuilt shared-driver service. No further native networking was launched.

The earlier custom `vlatap` build/unsigned CAT records are archived under `history/custom-driver/`; they are superseded and excluded from the current shared package. Current retired kernel-build entry points refuse execution. Local SDK/WDK downloads remain ignored build tools only.
