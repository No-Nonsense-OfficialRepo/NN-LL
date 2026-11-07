# Essential archive licensing verification — 6 November 2026

Result: the identified modification-notice omission has been corrected and the native service rebuilt. This is an evidence report, not legal clearance.

## Evidence checked

- The Essential archive contains project source, UI assets/fonts, GPLv3 text, native patches/build scripts and the prebuilt VLA service/driver. It contains no Python or Qt binaries/wheels.
- The service executable hash matches service-provenance.json. Its source commit and patch hash match source-lock.json. verify-source.ps1 passed all modified-source hashes and unexpected-edit checks. These checks establish consistency with the build records, not an independently reproducible binary build.
- The pinned upstream license and source headers record a 2026-01-01 change to Apache-2.0. The upstream license's Licensed Work label says 1.4.4 despite the 1.14.2 pin; that wording is retained rather than silently corrected.
- All 29 upstream driver source/project files occur in the supplied original-source ZIP. Comparison with Git objects found only Windows line-ending conversions in 28 files; one was byte-identical. No substantive source differences were found.
- Driver SYS and CAT bytes match the pinned upstream prebuilt files. The packaged INF differs from Git blob bytes; its Windows packaging/extraction hash is recorded, but this pass did not establish an independent exact Git-blob match for it. Do not describe all three as byte-identical to raw Git objects on this evidence.
- Driver GPLv2 text, original source/project ZIP, source reference and copyright-bearing source headers are supplied.
- Native notice texts include copyright/license/disclaimer material for http-parser, libnatpmp, MiniUPnPc, nlohmann JSON, inja and prometheus-cpp-lite. Ms-PL text is supplied; inspected Microsoft service source retains its original copyright/license header.
- Bundled fonts include their OFL license files. Root GPLv3 documentation expressly preserves third-party licensing.

## Modification-notice item closed

Apache-2.0 section 4(b) requires modified files to carry prominent modification notices. The missing notice in osdep/WindowsEthernetTap.hpp has been added. All 14 locked modified files now contain VLA modification markers. Original copyright/license headers remain present.

The patch and header lock were regenerated. Source verification and reverse-application checks passed. MSVC rebuilt the service and generated a new provenance record. A fresh runtime was assembled and passed package hash, identity and signature checks before replacing the source build input. All three driver files remained byte-for-byte identical to the previous verified package. No installed service was replaced and no live game/network session was run for this rebuild.

- New patch SHA-256: `205451603afa78ecab9448a8eb75cf3b4acd7166ed6b4014801d1b56c9c9d4c0`
- Rebuilt service SHA-256: `69d8d360a3c062ca16ff1549402e02e6559795bffb9d856d86d88339e400405d`

No further unmet notice condition was identified among the native components reviewed. This does not convert the evidence into a guarantee covering every possible legal claim.

## Interpretation boundary

Retained terms and notices support redistribution; this review does not certify absence of all legal claims or independently establish rights in every original project asset. If the pinned upstream Licensed Work wording or another applicable term remains disputed, obtain focused copyright-holder clarification or legal review. A separate finished Windows launcher distribution needs its own Python/Qt dependency review; this archive does not ship those libraries.

References:

- Apache-2.0 section 4: https://www.apache.org/licenses/LICENSE-2.0.txt
- Pinned upstream license: https://github.com/zerotier/ZeroTierOne/blob/185a3a2c76e6bf1b1c0415871f43076638eb007c/LICENSE.txt
- Driver copyright and GPLv2 notice: https://github.com/zerotier/ZeroTierOne/blob/185a3a2c76e6bf1b1c0415871f43076638eb007c/windows/TapDriver6/tapdrvr.c
