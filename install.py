"""Installs the MayaMCP module for Maya and shows the Claude Code registration.

    python install.py                 # install the module for Maya 2026 (Windows, macOS, Linux)
    python install.py --register      # also register with Claude Code
    python install.py --uninstall     # remove the module file
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
MODULE_ROOT = REPO / "maya_module"
MODULE_NAME = "MayaMCP"
SERVER = REPO / "src" / "maya_mcp_server.py"


def windows_documents() -> Path:
    """Asks Windows for the Documents folder, which OneDrive may have moved."""
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    folder_id = GUID.from_buffer_copy(uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le)
    path = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(path)):
        return Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
    try:
        return Path(path.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)


def maya_modules_dir(version: str) -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "Autodesk" / "maya" / version / "modules"
    if sys.platform.startswith("linux"):
        return Path.home() / "maya" / version / "modules"
    return windows_documents() / "maya" / version / "modules"


def module_file(version: str) -> Path:
    return maya_modules_dir(version) / f"{MODULE_NAME}.mod"


def install(version: str) -> Path:
    if not (MODULE_ROOT / "scripts" / "maya_mcp_listener.py").is_file():
        raise SystemExit(f"Listener not found under {MODULE_ROOT}")

    target = module_file(version)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"+ MAYAVERSION:{version} {MODULE_NAME} 1.0 {MODULE_ROOT.as_posix()}\n"
        "scripts: scripts\n"
    )
    target.write_text(content, encoding="utf-8")
    return target


def uninstall(version: str) -> Path | None:
    target = module_file(version)
    if target.is_file():
        target.unlink()
        return target
    return None


def python_executable() -> Path:
    venv = REPO / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    candidate = venv / ("python.exe" if os.name == "nt" else "python")
    return candidate if candidate.is_file() else Path(sys.executable)


def claude_command() -> list[str]:
    return [
        "claude", "mcp", "add", "--scope", "user", "--transport", "stdio", "maya",
        "--", str(python_executable()), str(SERVER),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maya-version", default="2026")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--register", action="store_true",
                        help="register the server via 'claude mcp add' in user scope")
    args = parser.parse_args()

    if args.uninstall:
        removed = uninstall(args.maya_version)
        print(f"Module removed: {removed}" if removed else "No module installed.")
        print("Claude Code: claude mcp remove maya --scope user")
        return 0

    target = install(args.maya_version)
    print(f"Module installed: {target}")
    print(f"Listener: {MODULE_ROOT / 'scripts' / 'maya_mcp_listener.py'}")
    print("Restart Maya - the listener then starts automatically.")
    print("In a running Maya, use the Script Editor (Python) instead:")
    print(f"  import sys; sys.path.append(r'{MODULE_ROOT / 'scripts'}')")
    print("  import maya_mcp_listener; maya_mcp_listener.start()")

    command = claude_command()
    if args.register:
        print("\n$ " + " ".join(command))
        return subprocess.call(command, shell=(os.name == "nt"))

    print("\nRegistration in Claude Code:")
    print("  " + " ".join(command))
    print("Remove:")
    print("  claude mcp remove maya --scope user")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
