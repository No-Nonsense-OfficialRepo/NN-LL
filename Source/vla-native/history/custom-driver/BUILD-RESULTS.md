# Native build evidence — 2026-10-26

## Completed

- Pinned upstream commit: `185a3a2c76e6bf1b1c0415871f43076638eb007c` (tag 1.14.2).
- Patch: `patches/0001-vla-windows.patch`, SHA-256 `55a48a72f5cd1ceda8554b15f562bfe500a3befbfa7de1a4fe29bbd34302a65b`.
- `verify-source.ps1` passed pin, patch integrity, changed-source hashes and unexpected-change checks.
- A pristine `git archive` of the pinned commit accepted the patch; all resulting changed file hashes matched `source-lock.json`.
- x64 user-mode build succeeded using VS Community 2026 MSVC 14.51.36231 and Windows SDK 10.0.26100.0. The compiler used the actual upstream Windows project source list, with SSO disabled and the static C runtime.
- Artifact: `out/user/vla-service.exe`, 2,351,616 bytes, SHA-256 `c42af241f4710820c41b8aa73422c12d7a7c39e911e26565423a7cda8e8a0bc3`. Unsigned.
- `-v` reported `1.14.2`; `-h` reported `VLA - Virtual LAN Adaptor`, upstream copyright attribution and the recorded license Change Date.
- The missing system-wide WDK was resolved without a system install: acquired official `Microsoft.Windows.WDK.x64`, `Microsoft.Windows.SDK.cpp.x64` and `Microsoft.Windows.SDK.cpp` NuGet packages, all version `10.0.28000.2526`, into local ignored `out/`. Download sizes/hashes are pinned in `wdk-lock.json`. Combined compressed size is 327,538,318 bytes; expanded size is about 1.22 GB.
- `build-driver-local.ps1` compiled all nine actual upstream driver C sources plus the Windows version resource with the existing MSVC compiler and matching local WDK/SDK. No driver-code change was needed beyond the earlier VLA identity changes. Compiler warnings are inherited unused locals/labels.
- Current Microsoft INF validation initially identified missing `PnpLockdown=1` and Driver Store isolation. The INF-only patch added lockdown, `DIRID 13`/`%13%` and model decorations requiring Windows 10 build 16299 or later. Updated pristine-archive patch reproduction and source-lock verification passed. The user-mode executable did not need rebuilding and its hash is unchanged.
- Microsoft **InfVerif `/h /v` and `/w /v` both pass**, with no remaining reported errors or warnings.
- Static PE inspection: x64 (`0x8664`), Native subsystem, empty embedded certificate directory, expected VLA resource metadata and retained legal copyrights. Imports are only `ntoskrnl.exe` and `NDIS.SYS`; no user-mode CRT dependency.
- Genuine Microsoft **Inf2Cat** completed signability checks with **no errors or warnings** and generated `vlatap.cat`. This is a real **unsigned** hash catalog, not a dummy or production-signed artifact.

## Final unsigned signing input

`out/signing-input/` contains:

| File | Bytes | SHA-256 |
|---|---:|---|
| `vla-service.exe` | 2,351,616 | `c42af241f4710820c41b8aa73422c12d7a7c39e911e26565423a7cda8e8a0bc3` |
| `driver/vlatap.sys` | 27,136 | `b128250c79e9500313d17caad1aa54221c7f613dfa84be4a837920fc5bb67f25` |
| `driver/vlatap.inf` | 5,446 | `fcc1849aeef5a901f07f30b6633dff2d3f27df02b9ae32a919260b13b62bdbd5` |
| `driver/vlatap.cat` | 1,348 | `3f35fd1cf76f34ac200f914ecd5271728331144b295938812e8502ab734211f9` |

The directory includes `UNSIGNED.txt`, `UNSIGNED-ARTIFACTS.json` and the actual Inf2Cat log. No production backend manifest is present. A read-only Microsoft SignTool `/kp /c` verification recognized the catalog membership but correctly failed with **No signature found** (exit 1). The CAT/SYS have no production trust. Build outputs can change hash on rebuild because the inherited driver source records compile timestamps; the recorded values identify this exact built set.

## Earlier isolated runtime check

The non-elevated command was `vla-service.exe -C -U -p47994 "out/smoke-<unique-id>"`. Its state was under this directory's ignored `out/`, separate from live services. A local authenticated `/status` request, private embedded-controller network creation, and `zerotier-one.port` output all passed. The process was stopped in the test's cleanup; no `vla-service` process remained when checked afterward. Machine service and driver installation were not performed.

Opening sockets caused a Windows Firewall popup. The user was informed. No firewall prompt was approved, no firewall rule was deliberately added, and the networking test was removed from the scripts. Build and source verification launch development tools only; they never launch the service or driver. No further native networking/runtime tests were performed during the local WDK work. Further socket/driver/SCM integration tests require explicit opt-in on a test machine. The prior result is evidence for local user-mode APIs only; it proves neither driver functionality, Secure Boot loading nor cross-machine LAN connectivity.

## Blocked / unverified

- No publisher signature or Microsoft production driver signature was created or claimed. Those require the publisher's applicable signing/account workflow. No test certificate, signing-policy relaxation or production `vendor/vla/manifest.json` was produced.
- Installation/uninstallation, Secure Boot/HVCI loading, side-by-side ordinary ZeroTier coexistence, reboot behavior and real multi-machine LAN traffic remain unverified. No driver was installed or loaded.
- Microsoft development-tool packages were acquired over official NuGet HTTPS endpoints and pinned by SHA-256. Their NuGet package-signature verification was not completed because the machine has a .NET host but no .NET SDK; no SDK was installed. This does not affect the completed compiler/INF/catalog checks or imply that the new driver is signed.
- The older pinned release needs security review and continued maintenance before public production use.

VS18 MSBuild encountered an access-denied FileTracker initialization error. Direct compiler invocation succeeded without installing system tools or altering permissions. Logs are `build-user.log`, `build-driver-local.log`, `out/driver-unsigned/infverif-h.log`, `infverif-w.log`, `pe-inspection.txt` and `out/signing-input/inf2cat.log`. Logs, fetched source/packages and compiled outputs are local and ignored. `build-driver.ps1` can delegate to the verified local path; its alternative system-WDK/MSBuild path remains unverified.
