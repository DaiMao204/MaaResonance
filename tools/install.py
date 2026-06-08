from pathlib import Path

import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

sys.path.insert(0, str(Path(__file__).parent.resolve()))

try:
    import jsonc
except ModuleNotFoundError as e:
    raise ImportError(
        "Missing dependency 'json-with-comments' (imported as 'jsonc').\n"
        f"Install it with:\n  {sys.executable} -m pip install json-with-comments\n"
        "Or add it to your project's requirements."
    ) from e

from configure import configure_ocr_model


working_dir = Path(__file__).parent.parent.resolve()
install_path = working_dir / Path("install")
version = len(sys.argv) > 1 and sys.argv[1] or "v0.0.1"
options = set(sys.argv[4:])

# the first parameter is self name
if sys.argv.__len__() < 4:
    print("Usage: python install.py <version> <os> <arch>")
    print("Example: python install.py v1.0.0 win x86_64")
    print("Optional: add --with-mxu to deploy the MXU frontend into install.")
    print("可选：添加 --with-mxu 将 MXU 前端部署到 install。")
    sys.exit(1)

os_name = sys.argv[2]
arch = sys.argv[3]

MXU_REPO = "MistEO/MXU"
MXU_API_ROOT = f"https://api.github.com/repos/{MXU_REPO}"
MXU_VERSION_ENV = "MAA_RESONANCE_MXU_VERSION"
MXU_ARCHIVE_ENV = "MAA_RESONANCE_MXU_ARCHIVE"
DEFAULT_CONFIG_DIR = working_dir / "assets" / "config"


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _reset_generated_path(path: Path) -> None:
    path = path.resolve()
    if not (path == install_path or path.is_relative_to(install_path)):
        raise RuntimeError(f"Refusing to remove path outside install: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def get_dotnet_platform_tag():
    """自动检测当前平台并返回对应的dotnet平台标签"""
    if os_name == "win" and arch == "x86_64":
        platform_tag = "win-x64"
    elif os_name == "win" and arch == "aarch64":
        platform_tag = "win-arm64"
    elif os_name == "macos" and arch == "x86_64":
        platform_tag = "osx-x64"
    elif os_name == "macos" and arch == "aarch64":
        platform_tag = "osx-arm64"
    elif os_name == "linux" and arch == "x86_64":
        platform_tag = "linux-x64"
    elif os_name == "linux" and arch == "aarch64":
        platform_tag = "linux-arm64"
    else:
        print("Unsupported OS or architecture.")
        print("available parameters:")
        print("version: e.g., v1.0.0")
        print("os: [win, macos, linux, android]")
        print("arch: [aarch64, x86_64]")
        sys.exit(1)

    return platform_tag


def install_deps():
    if not (working_dir / "deps" / "bin").exists():
        print('Please download the MaaFramework to "deps" first.')
        print('请先下载 MaaFramework 到 "deps"。')
        sys.exit(1)

    if "--with-mxu" in options and os_name != "android":
        _reset_generated_path(install_path / "maafw")
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path / "maafw",
            ignore=shutil.ignore_patterns(
                "*MaaDbgControlUnit*",
                "*MaaThriftControlUnit*",
                "*MaaRpc*",
                "*MaaHttp*",
                "*.node",
                "*MaaPiCli*",
            ),
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "maafw" / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
        return

    if os_name == "android":
        _reset_generated_path(install_path / "MaaAgentBinary")
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path,
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
    else:
        _reset_generated_path(install_path / "runtimes")
        _reset_generated_path(install_path / "libs")
        _reset_generated_path(install_path / "plugins")
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path / "runtimes" / get_dotnet_platform_tag() / "native",
            ignore=shutil.ignore_patterns(
                "*MaaDbgControlUnit*",
                "*MaaThriftControlUnit*",
                "*MaaRpc*",
                "*MaaHttp*",
                "plugins",
                "*.node",
                "*MaaPiCli*",
            ),
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "libs" / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "bin" / "plugins",
            install_path / "plugins" / get_dotnet_platform_tag(),
            dirs_exist_ok=True,
        )


def get_mxu_platform_tag():
    if os_name == "win" and arch == "x86_64":
        return "win-x86_64", ".zip"
    if os_name == "win" and arch == "aarch64":
        return "win-aarch64", ".zip"
    if os_name == "linux" and arch == "x86_64":
        return "linux-x86_64", ".tar.gz"
    if os_name == "macos" and arch == "x86_64":
        return "macos-x86_64", ".tar.gz"
    if os_name == "macos" and arch == "aarch64":
        return "macos-aarch64", ".tar.gz"

    print("MXU does not publish an artifact for this OS/architecture.")
    print("MXU 当前没有提供该平台/架构的预编译包。")
    sys.exit(1)


def _github_json(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "MaaResonanceInstaller",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _mxu_release_info():
    requested = os.environ.get(MXU_VERSION_ENV, "latest").strip() or "latest"
    if requested == "latest":
        return _github_json(f"{MXU_API_ROOT}/releases/latest")

    tag = requested if requested.startswith("v") else f"v{requested}"
    return _github_json(f"{MXU_API_ROOT}/releases/tags/{tag}")


def _find_mxu_asset(release: dict, platform_tag: str, suffix: str) -> dict:
    tag = release.get("tag_name") or os.environ.get(MXU_VERSION_ENV, "")
    expected_name = f"MXU-{platform_tag}-{tag}{suffix}"
    for asset in release.get("assets") or []:
        if asset.get("name") == expected_name:
            return asset

    for asset in release.get("assets") or []:
        name = asset.get("name", "")
        if name.startswith(f"MXU-{platform_tag}-") and name.endswith(suffix):
            return asset

    print(f"Cannot find MXU artifact for {platform_tag} in release {tag}.")
    print(f"在 MXU 发布 {tag} 中找不到 {platform_tag} 对应的预编译包。")
    sys.exit(1)


def _download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MaaResonanceInstaller"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        with target.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def _extract_archive(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
        return
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(target)
        return
    print(f"Unsupported MXU archive: {archive}")
    print(f"不支持的 MXU 压缩包格式：{archive}")
    sys.exit(1)


def install_mxu():
    if os_name == "android":
        print("MXU desktop frontend is not available for android target.")
        print("MXU 桌面前端不支持 android 打包目标。")
        sys.exit(1)

    if not (working_dir / "deps" / "bin").exists():
        print('Please download the MaaFramework to "deps" first.')
        print('请先下载 MaaFramework 到 "deps"。')
        sys.exit(1)

    platform_tag, suffix = get_mxu_platform_tag()
    archive_env = os.environ.get(MXU_ARCHIVE_ENV, "").strip()

    if archive_env:
        archive = Path(archive_env).expanduser().resolve()
        if not archive.exists():
            print(f"MXU archive does not exist: {archive}")
            print(f"指定的 MXU 压缩包不存在：{archive}")
            sys.exit(1)
        release_tag = archive.stem
    else:
        release = _mxu_release_info()
        asset = _find_mxu_asset(release, platform_tag, suffix)
        release_tag = release.get("tag_name", "unknown")
        archive = working_dir / "deps" / "mxu" / asset["name"]
        if not archive.exists():
            print(f"Downloading MXU {release_tag}: {asset['name']}")
            print(f"正在下载 MXU {release_tag}：{asset['name']}")
            _download_file(asset["browser_download_url"], archive)

    with tempfile.TemporaryDirectory(prefix="mxu-", dir=working_dir / "deps") as tmp:
        extracted = Path(tmp)
        _extract_archive(archive, extracted)

        executable_name = "mxu.exe" if os_name == "win" else "mxu"
        packaged_executable_name = "MaaResonance.exe" if os_name == "win" else "MaaResonance"
        executable = next(extracted.rglob(executable_name), None)
        if executable is None:
            print(f"Cannot find {executable_name} in MXU archive: {archive}")
            print(f"MXU 压缩包中找不到 {executable_name}：{archive}")
            sys.exit(1)

        install_path.mkdir(parents=True, exist_ok=True)
        _reset_generated_path(install_path / executable_name)
        _reset_generated_path(install_path / packaged_executable_name)
        _reset_generated_path(install_path / "Start_MXU.bat")
        shutil.copy2(executable, install_path / packaged_executable_name)

        pdb = next(extracted.rglob("mxu.pdb"), None)
        if pdb is not None and _truthy_env("MAA_RESONANCE_INCLUDE_MXU_PDB"):
            _reset_generated_path(install_path / "mxu.pdb")
            _reset_generated_path(install_path / "MaaResonance.pdb")
            shutil.copy2(pdb, install_path / "MaaResonance.pdb")
        else:
            _reset_generated_path(install_path / "mxu.pdb")
            _reset_generated_path(install_path / "MaaResonance.pdb")
    if os_name != "win":
        (install_path / packaged_executable_name).chmod(0o755)

    (install_path / "mxu-version.txt").write_text(
        f"{release_tag}\n{archive.name}\n",
        encoding="utf-8",
    )

    print(f"MXU frontend installed to {install_path}.")
    print(f"MXU 前端已部署到 {install_path}。")


def packaged_agent_python() -> str:
    agent_python = os.environ.get("MAA_RESONANCE_AGENT_PYTHON", "").strip()
    if agent_python:
        return agent_python
    if os_name == "win" and (install_path / "python" / "python.exe").exists():
        return "./python/python.exe"
    if os_name in {"macos", "linux"} and (install_path / "python" / "bin" / "python3").exists():
        return "./python/bin/python3"
    if os_name in {"macos", "linux"}:
        return "python3"
    return "python"



def install_resource():

    configure_ocr_model()

    _reset_generated_path(install_path / "resource")
    shutil.copytree(
        working_dir / "assets" / "resource",
        install_path / "resource",
        dirs_exist_ok=True,
    )
    shutil.copy2(
        working_dir / "assets" / "interface.json",
        install_path,
    )

    with open(install_path / "interface.json", "r", encoding="utf-8") as f:
        interface = jsonc.load(f)

    interface["version"] = version
    if "agent" in interface:
        interface["agent"]["child_exec"] = packaged_agent_python()
        interface["agent"]["child_args"] = [
            "-u",
            "./agent/main.py",
        ]

    with open(install_path / "interface.json", "w", encoding="utf-8") as f:
        jsonc.dump(interface, f, ensure_ascii=False, indent=4)


def install_chores():
    shutil.copy2(
        working_dir / "README.md",
        install_path,
    )
    shutil.copy2(
        working_dir / "LICENSE",
        install_path,
    )


def install_default_config():
    if DEFAULT_CONFIG_DIR.exists():
        _reset_generated_path(install_path / "config")
        shutil.copytree(
            DEFAULT_CONFIG_DIR,
            install_path / "config",
            dirs_exist_ok=True,
        )


def install_clean_runtime_state():
    _reset_generated_path(install_path / "cache")
    _reset_generated_path(install_path / "debug")
    _reset_generated_path(install_path / "maafw.log")


def install_agent():
    _reset_generated_path(install_path / "agent")
    shutil.copytree(
        working_dir / "agent",
        install_path / "agent",
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )


def install_runtime_logic():
    _reset_generated_path(install_path / "maa_resonance")
    shutil.copytree(
        working_dir / "maa_resonance",
        install_path / "maa_resonance",
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )
    _reset_generated_path(install_path / "resources")
    shutil.copytree(
        working_dir / "resources",
        install_path / "resources",
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )


if __name__ == "__main__":
    install_deps()
    install_clean_runtime_state()
    install_resource()
    install_chores()
    install_agent()
    install_runtime_logic()
    install_default_config()
    if "--with-mxu" in options:
        install_mxu()

    print(f"Install to {install_path} successfully.")
