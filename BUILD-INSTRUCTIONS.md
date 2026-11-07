# Build No-Nonsense LAN Launcher on Windows

## Choose the right download

Use the **Essential Build Source ZIP** attached to a project Release for the shortest build path. It contains the launcher source, UI assets, build scripts, dependency lock and verified prebuilt VLA service/driver, with their notices and source patches.

GitHub's automatic **Source code (zip)** download and a Git clone omit the assembled `Source/vendor/vla` runtime. For those downloads, first follow [the native build and assembly instructions](Source/vla-native/README.md), or use the Essential Build Source ZIP instead.

To run the app without building, download the complete Windows launcher package when one is published. An Essential Build Source ZIP is not a ready-to-run launcher.

## Before starting

- Use Windows x64. The release build is pinned to **CPython 3.15.0, 64-bit**; a newer patch version, ARM64 Python or 32-bit Python is not interchangeable with this build lock.
- Install that exact interpreter from the [official Python 3.15.0 release page](https://www.python.org/downloads/release/python-3150/), including pip. The normal x64 installer/full runtime is appropriate; the embeddable Python package is not the tested build environment. If the installer offers it, enable Python's PATH/launcher integration so the builder can find it.
- Have internet access for the first dependency installation. Python and the dependency wheels are deliberately omitted from the Essential ZIP. The builder uses the pinned, hash-checked requirements; it does not need games or a running LAN room.
- Allow at least 5 GB of free working space, with more space if retaining multiple releases.
- Extract the entire ZIP to a short writable folder, for example `C:\LANBuild`. Do not run the builder from inside Explorer's ZIP view. Keep the top-level command, LICENSE and Source folder together. Avoid Program Files and temporary download-preview folders.
- Windows PowerShell 5.1 or newer and normal Windows utilities must be available. A C++ compiler, Visual Studio, Windows SDK and separate ZeroTier installation are not needed for the standard Essential build, which uses the included prebuilt VLA runtime. They are separate prerequisites for rebuilding that native runtime.

## Build

1. Open the extracted top folder containing `Build Latest LAN Launcher.cmd` and `Source`.
2. Double-click **Build Latest LAN Launcher.cmd**. Run it as your normal user; building does not require installing VLA or opening a room.
3. Leave the window open. The builder finds Python 3.15.0, installs or checks the locked dependencies, checks the Qt pages, and packages Client, Host, Quick Start and the administrator helper. Initial dependency installation and packaging can take several minutes.
4. Wait for **Release build complete**. The command window pauses so you can read the result.

The builder advances the patch version for a build attempt. Repeated attempts can therefore have different release numbers, including after a failure.

## Find the result

The complete runnable folder is created under `Releases/LAN Launcher V<version>/`:

```text
Releases/
  LAN Launcher V<version>/
    Host.exe
    Client.exe
    Quick Start.exe
    LICENSE
    Launcher Bin/
    Game Directory/
```

Keep that entire release folder together when copying it to another PC. `Launcher Bin` includes the runtime and elevation helper. No game binaries are included. Host and Clients must use exactly the same release version.

The builder does not automatically create a release ZIP. It checks the packaged Host and Client windows and writes `Launcher Bin/Release/version.json` plus `SHA256SUMS.txt`. These checks do not replace a real multi-PC test.

Logs and reusable build caches stay under `Source/build/`. The main log is `Source/build/logs/build-latest-lan-launcher.log`. Duplicate packaging copies are removed after a successful build; cache files are retained to speed up the next build. Source export archives belong in `Exports/`.

## If the build stops

| Message or symptom | What to check |
|---|---|
| Python 3.15.0 was not found | Confirm the exact standard 64-bit interpreter is installed. In a terminal, `py -3.15 -c "import sys; print(sys.version); print(sys.executable)"` shows what the launcher finds. If it reports another patch version, install the exact pinned version. Reopen the terminal after installation. |
| pip download, proxy or certificate failure | Check internet/proxy access to the package index and retry. Do not bypass TLS verification or change the dependency hashes. The first build needs online wheel access. |
| Dependency version/hash mismatch | Use the exact interpreter and `Source/build-requirements.lock`. From `Source`, `py -3.15 -m pip install --require-hashes -r build-requirements.lock` reinstalls the pinned requirements when needed. Confirm `py -3.15` resolves to 3.15.0 first. |
| `vendor/vla` missing or invalid | Extract the complete Essential ZIP again. Git source downloads omit this assembled runtime; follow the native assembly guide for those. Do not substitute an ordinary ZeroTier service or unrelated driver. |
| DLL load failure, including `python3t.dll` | Check that Python is the full, exact x64 runtime and that the locked wheel installation completed. Do not download individual DLLs from third-party sites. The full official Python 3.15.0 x64 runtime was used successfully in the isolated build test. |
| Qt page/package could not load | Read the last error in the build log. Keep all source assets and fonts together. A failed Qt check deliberately stops packaging. |
| Access denied or a file cannot be replaced | Close launchers opened from the destination release, check folder permissions and available disk space, and inspect any antivirus quarantine event. Use a writable extracted folder. |
| PyInstaller access violation | The builder retries the affected stage up to three times. If it still fails, retain the log and report the Windows/Python versions and failing stage. |
| Windows warns about an unsigned executable | The launcher executables and private VLA service are developer builds without a publisher signature. The original signed driver does not sign them. Do not disable antivirus as a build troubleshooting step. |

For a bug report, include the source/archive version, Windows version, exact Python version and the final error from the build log. Review logs for personal paths before posting them publicly. Do not include passwords, identity files or game data.

## Advanced development and native builds

See [Source/README.md](Source/README.md) for isolated UI preview commands and development tests. The Essential archive intentionally omits the test suite; use the full source repository for tests.

See [Source/vla-native/README.md](Source/vla-native/README.md) to reproduce the native service and assemble a new VLA runtime. Preserve its source lock, provenance, original driver files and licensing notices together.

Successful compilation does not establish compatibility with every Windows configuration or clearance for redistributing all dependencies in a finished executable package. The [native licensing verification report](Source/docs/essential-license-verification.md) records the review performed for the Essential archive.
