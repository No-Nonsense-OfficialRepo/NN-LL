# Contributing

Start with [the build guide](../BUILD-INSTRUCTIONS.md). The Essential ZIP includes the prebuilt VLA input and omits tests; the Git repository includes tests and omits generated native binaries.

For a change to launcher code, use a branch and describe the concrete problem, resulting behavior and verification in the pull request. Keep unrelated changes separate. Preserve third-party attribution and source/provenance locks. Do not submit game files, generated releases, identity files or local configuration.

From `Source/`, use the intended Python interpreter to install `dev-requirements.txt`, then run `python -m pytest -q`. Start with relevant tests while developing; run the full suite before submitting a broad behavioral change. A full release build is useful for packaging changes but is not necessary for a documentation edit. Use `python -m lantool.qt.main --preview` for an isolated UI preview.

Report which tests and builds you actually ran. Describe physical two-PC tests separately from automated tests. A passing test suite does not establish a real LAN session or every Windows configuration.

The normal builder advances the release number. Do not manually bump it for every contribution; agree on release changes with the maintainer. Native changes require updating the patch/source lock, rebuilding the service, generating its actual provenance and validating the assembled runtime.

Review logs/screenshots for personal information before including them. See [the Security policy](SECURITY.md) for vulnerability reports.
