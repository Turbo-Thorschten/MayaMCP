"""Installiert das MayaMCP-Modul fuer Maya und zeigt die Claude-Code-Registrierung.

    python install.py                 # Modul fuer Maya 2026 installieren
    python install.py --register      # zusaetzlich in Claude Code eintragen
    python install.py --uninstall     # Modul-Datei entfernen
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


def maya_modules_dir(version: str) -> Path:
    documents = Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "Autodesk" / "maya" / version / "modules"
    if sys.platform.startswith("linux"):
        return Path.home() / "maya" / version / "modules"
    return documents / "maya" / version / "modules"


def module_file(version: str) -> Path:
    return maya_modules_dir(version) / f"{MODULE_NAME}.mod"


def install(version: str) -> Path:
    if not (MODULE_ROOT / "scripts" / "maya_mcp_listener.py").is_file():
        raise SystemExit(f"Listener nicht gefunden unter {MODULE_ROOT}")

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
                        help="Server per 'claude mcp add' im User-Scope eintragen")
    args = parser.parse_args()

    if args.uninstall:
        removed = uninstall(args.maya_version)
        print(f"Modul entfernt: {removed}" if removed else "Kein Modul installiert.")
        print("Claude Code: claude mcp remove maya --scope user")
        return 0

    target = install(args.maya_version)
    print(f"Modul installiert: {target}")
    print(f"Listener: {MODULE_ROOT / 'scripts' / 'maya_mcp_listener.py'}")
    print("Maya neu starten - der Listener startet dann automatisch.")
    print("Im laufenden Maya stattdessen im Script Editor (Python):")
    print(f"  import sys; sys.path.append(r'{MODULE_ROOT / 'scripts'}')")
    print("  import maya_mcp_listener; maya_mcp_listener.start()")

    command = claude_command()
    if args.register:
        print("\n$ " + " ".join(command))
        return subprocess.call(command, shell=(os.name == "nt"))

    print("\nRegistrierung in Claude Code:")
    print("  " + " ".join(command))
    print("Entfernen:")
    print("  claude mcp remove maya --scope user")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
