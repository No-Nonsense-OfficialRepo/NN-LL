# V0.9.62 — public test source build kit

No-Nonsense LAN Launcher provides a Windows Host and Client for private LAN game nights, with a shared playlist, verified file transfers and game launching. No game binaries or game licenses are included.

## Download and build

Download `LAN Launcher V0.9.62 Essential Build Source.zip` and its `.zip.sha256` checksum. Extract the whole ZIP and follow `BUILD-INSTRUCTIONS.md`. It contains the source, UI assets, verified prebuilt VLA runtime, native source patches and licensing notices. It needs Windows x64, CPython 3.15.0 and internet access for pinned build dependencies.

GitHub's automatic source-code archive omits the assembled VLA runtime. The Essential ZIP is the shortest build path. This source kit does not include the Python/Qt dependency binaries or a ready-to-run launcher package.

## Included changes

- Local cover selection recognizes common artwork filenames and an unambiguous single image.
- Qt startup uses the bundled font directory.
- Builds put releases under `Releases/`, logs under `Source/build/logs`, and remove duplicate staging copies after success.
- Project licensing text is included; launcher handoff preserves it.
- Diagnostics redact Windows profile names containing spaces or apostrophes.
- The native VLA header modification notice was corrected; the service was rebuilt with matching patch, source lock and provenance.

## Test status and limits

An isolated public-source snapshot passed 797 automated tests during preparation. A complete launcher build using a separate Python environment and locked dependencies also passed packaged Host/Client startup checks before the latest native notice rebuild. The rebuilt native package passed source, hash, identity and signature validation. The maintainer has also completed a successful two-PC join/game test with the rebuilt native runtime. These results cover different checkpoints and are not a single end-to-end certification of this source snapshot.

The launcher and private VLA service are unsigned developer builds. The original third-party driver retains its own signature. Game prerequisites are not installed automatically. General remote play and broad Windows/network compatibility are not established. Host and Client releases must match exactly.

For problems, open a bug report with the version, Windows build, reproduction steps and a reviewed error excerpt. See the included build guide and Security policy. Preserve component licenses and notices when redistributing; the native verification report records its scope and limitations.

## Community and tutorials

- [YouTube — No-Nonsense](https://www.youtube.com/@NoNonsenseLAN): app tutorials and walkthroughs are coming soon.
- [Discord](https://discord.com/invite/a9NgtcnH5r): quick chats, setup questions and feedback.
- Use GitHub Issues for reproducible bug reports.
