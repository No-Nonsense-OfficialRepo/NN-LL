# Publish the first GitHub test release

Local materials are prepared; this document does not mean a release is published.

1. Complete a physical two-PC smoke test of the current rebuilt native runtime. Record launcher versions, Windows builds, topology, setup/join, transfer, close/reopen and multiplayer results. Record failures as known issues rather than implying they passed.
2. Create or choose the GitHub repository and review the staged source inventory. Generated builds, game data, fetched upstream trees, local state and assembled VLA binaries are ignored. The Essential ZIP separately includes the verified native runtime.
3. Push the reviewed source commit and tag that commit `v0.9.62` for this source-kit snapshot. Do not attach a runnable package built from older native inputs and describe it as the current candidate.
4. In repository Settings, enable Issues and private vulnerability reporting if available. Review the issue template and Security policy.
5. Create a GitHub Release marked **Pre-release**. Use `RELEASE_NOTES-V0.9.62.md` as its description and attach the latest Essential ZIP and matching `.zip.sha256` from `Exports/`.
6. Download the uploaded archive and compare its SHA-256 with the sidecar. Check that its build guide, native provenance and source version describe the tagged snapshot.

A later runnable Windows package requires its own complete bundled-dependency notice review and validation. The Essential source-kit release does not automatically clear every subsequently built executable distribution.
