r"""Assemble a private VLA service with an unchanged signed shared driver.

Example (run from the repository root after the private native service build):
    python Source/scripts/assemble_vla_runtime.py --service build/vla-service.exe \
        --driver original-signed-driver --provenance build/service-provenance.json \
        --notice Source/vla-native/THIRD-PARTY-NOTICES.md \
        --notice Source/vla-native/licenses

The default destination is Source/vendor/vla. Existing destinations are always
refused. Windows verifies the shared driver catalog without installing it.
Publisher signing of the private user-mode executable is optional; request it
with --require-service-signature. --signtool is an optional extra verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Sequence

SOURCE_ROOT = Path(__file__).absolute().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from silent_tunnel import backend, installer
from silent_tunnel.errors import InstallError

DEFAULT_OUTPUT = SOURCE_ROOT / "vendor" / "vla"
_DRIVER_FILES = (backend.DRIVER_INF, backend.DRIVER_CAT, backend.DRIVER_SYS)
_SAFE_NOTICE = re.compile(r"[A-Za-z0-9_.-]+")


class AssemblyError(ValueError):
    """The inputs cannot become a verified production runtime package."""


def _checked_path(value: Path) -> Path:
    path = Path(value).expanduser()
    if any(part == ".." for part in path.parts):
        raise AssemblyError("Paths containing '..' are refused; supply the intended path directly.")
    path = Path(os.path.abspath(path))
    if any(part.casefold() == ".git" for part in path.parts):
        raise AssemblyError("Paths inside .git are refused.")
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise AssemblyError(f"Linked paths and junctions are refused: {item}")
    return path


def _input_file(value: Path, label: str) -> Path:
    path = _checked_path(value)
    if not path.is_file():
        raise AssemblyError(f"Missing {label}: {path}")
    return path


def _notice_files(notices: Sequence[Path]) -> dict[str, Path]:
    result = {}
    names = set()
    for notice in notices:
        path = _checked_path(notice)
        if not path.exists():
            raise AssemblyError(f"Missing notice input: {path}")
        # Notice folders are deliberately flat; no repository or .git traversal.
        entries = sorted(path.iterdir()) if path.is_dir() else [path]
        for entry in entries:
            entry = _input_file(entry, "notice file (notice directories must be flat)")
            if not _SAFE_NOTICE.fullmatch(entry.name) or entry.name in (".", ".."):
                raise AssemblyError(f"Notice filenames must contain only letters, numbers, '.', '_' or '-': {entry.name}")
            if entry.name.casefold() in names:
                raise AssemblyError(f"Duplicate notice filename: {entry.name}")
            names.add(entry.name.casefold())
            result["notices/" + entry.name] = entry
    return result


def _find_signtool(explicit: Path | None) -> Path:
    if explicit is not None:
        tool = _input_file(explicit, "SignTool verification executable")
    else:
        found = shutil.which("signtool.exe")
        if not found:
            raise AssemblyError("Microsoft SignTool is needed to verify the signed driver catalog. "
                                "Supply --signtool with the path to an existing Windows SDK/WDK signtool.exe.")
        tool = _input_file(Path(found), "SignTool verification executable")
    if tool.name.casefold() != "signtool.exe" or not installer.verify_authenticode(tool):
        raise AssemblyError("The verification tool must be a Windows-trusted Microsoft SDK/WDK signtool.exe.")
    return tool


def _verify_catalog_membership(package: Path, signtool: Path) -> None:
    """Verify production kernel policy and catalog membership, without install.

    Microsoft documents verify /kp /c for checking a file against a catalog:
    https://learn.microsoft.com/windows/win32/seccrypto/signtool
    """
    catalog = package / "driver" / backend.DRIVER_CAT
    for name in (backend.DRIVER_INF, backend.DRIVER_SYS):
        try:
            result = subprocess.run([str(signtool), "verify", "/kp", "/c", str(catalog),
                                     str(package / "driver" / name)],
                                    capture_output=True, text=True, timeout=60,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AssemblyError(f"Could not verify the VLA driver catalog: {exc}") from None
        if result.returncode:
            detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()[-1600:]
            raise AssemblyError(f"Production driver verification failed for {name}. "
                                "Supply the final Microsoft-signed driver catalog and its matching, unchanged INF/SYS files. "
                                f"SignTool exit {result.returncode}: {detail}")


def assemble(service: Path, driver: Path, output: Path = DEFAULT_OUTPUT, *,
             notices: Sequence[Path] = (), signtool: Path | None = None,
             provenance: Path | None = None, require_service_signature: bool = False) -> Path:
    """Publish a validated runtime using one final same-filesystem rename."""
    if os.name != "nt":
        raise AssemblyError("Production VLA assembly requires Windows signature verification. Run this helper on Windows.")
    service = _input_file(service, "private native VLA service executable")
    if service.name.casefold() != backend.SERVICE_EXECUTABLE:
        raise AssemblyError(f"The service input must be named {backend.SERVICE_EXECUTABLE}.")
    driver = _checked_path(driver)
    if not driver.is_dir():
        raise AssemblyError(f"Missing finalized signed driver directory: {driver}")
    provenance = _input_file(provenance or service.parent / backend.SERVICE_PROVENANCE,
                             "private service build provenance (use --provenance)")
    inputs = {backend.SERVICE_EXECUTABLE: service, backend.SERVICE_PROVENANCE: provenance}
    inputs.update({"driver/" + name: _input_file(driver / name, "finalized signed driver file")
                   for name in _DRIVER_FILES})
    inputs.update(_notice_files(notices))
    output = _checked_path(output)
    if output.exists():
        raise AssemblyError(f"Output already exists and was left unchanged: {output}. Choose a new output directory.")
    for source in [service, driver, *inputs.values()]:
        if source == output or source.is_relative_to(output):
            raise AssemblyError("The output directory must not contain or replace any input path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    _checked_path(output.parent)
    with tempfile.TemporaryDirectory(prefix=".vla-assembly-", dir=output.parent) as temporary:
        staging = Path(temporary)
        for relative, source in inputs.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_checked_path(source), target)
        manifest = {**installer._MANIFEST_IDENTITY, "service_signature_required": require_service_signature, "files": {
            name: hashlib.sha256((staging / name).read_bytes()).hexdigest() for name in sorted(inputs)
        }}
        (staging / backend.MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        try:
            installer.validate_package(staging, check_signatures=True)
        except InstallError as exc:
            raise AssemblyError(f"VLA runtime was not published: {exc} "
                                "Supply the matching private service provenance and original unchanged signed driver files.") from None
        if signtool is not None:
            _verify_catalog_membership(staging, _find_signtool(signtool))
        # Check the same bytes again immediately before publication.
        installer.validate_package(staging, check_signatures=True)
        output = _checked_path(output)
        if output.exists():
            raise AssemblyError(f"Output appeared during validation and was left unchanged: {output}")
        # On Windows rename refuses any existing target, including empty folders.
        staging.rename(output)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--service", required=True, type=Path, help="Private rebuilt vla-service.exe (publisher signature optional)")
    parser.add_argument("--driver", required=True, type=Path, help="Original signed directory containing zttap300.inf/.cat/.sys")
    parser.add_argument("--provenance", type=Path, help="Native service-provenance.json (default: beside service)")
    parser.add_argument("--require-service-signature", action="store_true", help="Also require Windows-trusted publisher signature on the service EXE")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="New output directory (default: Source/vendor/vla)")
    parser.add_argument("--notice", action="append", type=Path, default=[], help="Notice file or flat license folder; repeat as needed")
    parser.add_argument("--signtool", type=Path, help="Optional extra read-only verification using an existing SDK/WDK signtool.exe")
    args = parser.parse_args(argv)
    try:
        result = assemble(args.service, args.driver, args.output, notices=args.notice, signtool=args.signtool,
                          provenance=args.provenance, require_service_signature=args.require_service_signature)
    except (AssemblyError, InstallError, OSError) as exc:
        print(f"VLA package assembly failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified VLA runtime package published: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
