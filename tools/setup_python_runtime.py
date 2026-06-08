#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


WORKING_DIR = Path(__file__).resolve().parent.parent
INSTALL_DIR = WORKING_DIR / "install"
PYTHON_DIR = INSTALL_DIR / "python"
DEFAULT_PYTHON_VERSION = "3.12.10"


def _arch_suffix(arch: str) -> str:
    normalized = (arch or "").lower()
    if normalized in {"x86_64", "amd64", "x64"}:
        return "amd64"
    if normalized in {"aarch64", "arm64"}:
        return "arm64"
    raise SystemExit(f"Unsupported Windows Python architecture: {arch}")


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=180) as response:
        with target.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def _patch_pth(python_dir: Path) -> None:
    pth_files = sorted(python_dir.glob("python*._pth"))
    if not pth_files:
        raise SystemExit(f"Cannot find python*._pth in {python_dir}")
    pth = pth_files[0]
    lines = pth.read_text(encoding="utf-8").splitlines()
    patched: list[str] = []
    seen = set()
    for line in lines:
        text = line.strip()
        if text in {"#import site", "# import site"}:
            text = "import site"
        patched.append(text)
        seen.add(text)
    for item in (".", "Lib", "Lib\\site-packages", "DLLs", "import site"):
        if item not in seen:
            patched.append(item)
    pth.write_text("\n".join(patched) + "\n", encoding="utf-8")


def _ensure_pip(python_exe: Path) -> None:
    code = "import pip; print(pip.__version__)"
    result = subprocess.run([str(python_exe), "-c", code], cwd=WORKING_DIR)
    if result.returncode == 0:
        return
    get_pip = PYTHON_DIR / "get-pip.py"
    _download("https://bootstrap.pypa.io/get-pip.py", get_pip)
    try:
        subprocess.run([str(python_exe), str(get_pip)], cwd=WORKING_DIR, check=True)
    finally:
        get_pip.unlink(missing_ok=True)


def _install_requirements(python_exe: Path) -> None:
    requirements = WORKING_DIR / "requirements.txt"
    subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--no-warn-script-location",
            "-r",
            str(requirements),
        ],
        cwd=WORKING_DIR,
        check=True,
    )


def setup_windows_python(arch: str, python_version: str) -> Path:
    python_exe = PYTHON_DIR / "python.exe"
    if not python_exe.exists():
        if PYTHON_DIR.exists():
            shutil.rmtree(PYTHON_DIR)
        PYTHON_DIR.mkdir(parents=True, exist_ok=True)
        suffix = _arch_suffix(arch)
        archive_name = f"python-{python_version}-embed-{suffix}.zip"
        archive = PYTHON_DIR / archive_name
        url = f"https://www.python.org/ftp/python/{python_version}/{archive_name}"
        _download(url, archive)
        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(PYTHON_DIR)
        finally:
            archive.unlink(missing_ok=True)
        _patch_pth(PYTHON_DIR)
    _ensure_pip(python_exe)
    _install_requirements(python_exe)
    return python_exe


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare packaged Python runtime for MXU bundles.")
    parser.add_argument("os", choices=["win", "macos", "linux"], help="Package target OS.")
    parser.add_argument("arch", choices=["x86_64", "aarch64"], help="Package target architecture.")
    parser.add_argument("--python-version", default=DEFAULT_PYTHON_VERSION)
    args = parser.parse_args()

    if args.os != "win":
        print("Bundled Python is currently prepared only for Windows MXU packages; non-Windows packages use python3.")
        return

    python_exe = setup_windows_python(args.arch, args.python_version)
    print(f"Packaged Python ready: {python_exe}")


if __name__ == "__main__":
    main()
