# Native VLA component notices

LAN Launcher VLA is a modified derivative of the pinned ZeroTierOne 1.14.2 source. It is not represented as an unmodified ZeroTier product or endorsed by its authors. Original source copyright and attribution notices are retained. Changed source/build files are marked or listed by the patch and source lock.

The license text filenames below are in `vla-native/licenses/` in the source tree. The Windows runtime includes copies beside this notice in `vendor/vla/notices/`.

| Component | Recorded source terms / notice location |
|---|---|
| ZeroTier agent and embedded controller at the pin | Original `LICENSE.txt`, `COPYING` and file headers; BSL Change Date 2026-01-01 and Apache-2.0 Change License. Original Licensed Work label says 1.4.4; see README caveat. Copies named `upstream-*`. |
| Windows TAP driver (`windows/TapDriver6`) | GPL version 2 notices in `tapdrvr.c`, other source files and the INF. Copyright OpenVPN Technologies, Inc., with ZeroTier modifications and retained attribution. GPL text in `GPL-2.0-only.txt`. The selected driver binaries are unchanged; include the supplied original corresponding-source/build ZIP and full GPL text with distribution. |
| Windows ServiceBase / ServiceInstaller helpers | Microsoft Public License per original file headers. Copyright Microsoft Corporation. Text in `MS-PL.txt`. |
| http-parser | MIT; `http-parser-MIT.txt`. |
| libnatpmp and MiniUPnPc | Their BSD-style licenses; `libnatpmp-BSD.txt`, `miniupnpc-BSD.txt`. |
| nlohmann JSON / inja | MIT; `nlohmann-MIT.txt`, `inja-MIT.txt`. |
| prometheus-cpp-lite | MIT; `prometheus-MIT.txt`. |

These notices describe the sources selected by this build. They do not replace embedded source notices or constitute a complete legal assessment. Other upstream code, bundled tools, or new dependencies must be assessed if enabled in a later configuration. SSO/Rust is disabled in this build. The selected shared zttap300 prebuilt driver is distributed unchanged with its original names, provider and signatures; it is borrowed by the private VLA service. The driver source and x64 prebuilt files have no changes between official 1.14.2 and 1.16.2; the MSI-extracted files are byte-identical to the pinned 1.14.2 prebuilt files. No claim of endorsement or new kernel-driver authorship is made.

The Apache-2.0, GPL-2.0-only and MS-PL license texts were copied from the [SPDX license-list-data](https://github.com/spdx/license-list-data/tree/main/text) project; original dependency notices were copied directly from the pinned source. Canonical references: [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0), [GPL version 2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html), [Microsoft Public License](https://learn.microsoft.com/en-us/previous-versions/msp-n-p/ff647676(v=pandp.10)).
