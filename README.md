# Maya MCP

MCP-Server (Model Context Protocol) für Autodesk Maya 2026 unter Windows.

Der Server läuft als eigener Prozess und spricht über **stdio** mit dem
MCP-Client (z. B. Claude Code). In Maya läuft ein **Listener**, der
längenpräfixierte JSON-Requests auf `127.0.0.1:20777` entgegennimmt und den
Code über `maya.utils.executeInMainThreadWithResult` im Maya-Hauptthread
ausführt.

```
Claude Code  --stdio-->  src/maya_mcp_server.py  --TCP/JSON-->  Maya (Listener)
```

## Ursprung

Dieses Projekt geht auf [PatrickPalmer/MayaMCP](https://github.com/PatrickPalmer/MayaMCP)
zurück (MIT, Copyright (c) 2025 Patrick Palmer, siehe `LICENSE`). Übernommen
sind die Grundidee und der Aufbau aus MCP-Server plus Maya-Gegenstelle.

Geändert gegenüber dem Original:

* **MCP-SDK 2.x**: Das Original nutzt den lowlevel-`Server` und
  `mcp.server.fastmcp.*`. In `mcp` 2.x wurde FastMCP zu `MCPServer` umbenannt,
  `mcp.server.fastmcp` existiert nicht mehr. Der Server verwendet jetzt
  `from mcp.server import MCPServer` mit `@mcp.tool()` und `mcp.run(transport="stdio")`.
* **Transport zu Maya**: Statt Python-Code in MEL-Strings zu escapen und pro
  Aufruf zwei Verbindungen auf Mayas MEL-Command-Port zu öffnen, läuft ein
  eigener Listener mit JSON-Protokoll. Damit entfallen Escaping-Probleme, und
  stdout, Rückgabewert und Traceback kommen getrennt zurück.
* **Fester Toolsatz** statt dynamisch geladener Skriptdateien.

`src/mayatools/` stammt unverändert aus dem Original und wird vom neuen Server
**nicht** geladen.

## Installation

MCP-Abhängigkeiten kommen in ein eigenes venv, nicht in Mayas Python:

```bash
uv venv .venv
uv pip install -r requirements.txt      # oder: pip install -r requirements.txt
```

Maya-Modul installieren (legt `%USERPROFILE%\Documents\maya\2026\modules\MayaMCP.mod` an):

```bash
python install.py                 # Maya-Version über --maya-version wählbar
python install.py --register      # zusätzlich in Claude Code eintragen
python install.py --uninstall     # Modul wieder entfernen
```

Das Modul bringt seinen eigenen `scripts`-Ordner mit; dessen `userSetup.py`
startet den Listener beim Maya-Start. Ein vorhandenes `userSetup.py` des
Benutzers wird nicht angefasst. Startmeldungen und -fehler landen in
`%TEMP%\maya_mcp_startup.log`.

In einem bereits laufenden Maya lässt sich der Listener im Script Editor
(Python) nachladen:

```python
import sys; sys.path.append(r"<repo>\maya_module\scripts")
import maya_mcp_listener; maya_mcp_listener.start()
```

## Registrierung in Claude Code

```bash
claude mcp add --scope user --transport stdio maya -- <repo>\.venv\Scripts\python.exe <repo>\src\maya_mcp_server.py
claude mcp list
claude mcp get maya
claude mcp remove maya --scope user      # entfernen
```

Nach dem Start einer neuen Session stehen die Tools als `mcp__maya__*` bereit.

## Tools

| Tool | Signatur |
|------|----------|
| `maya_exec_python` | `(code: str, timeout: float = 30)` – Python im Maya-Hauptthread; liefert stdout, Rückgabewert des letzten Ausdrucks und Traceback |
| `maya_exec_mel` | `(code: str, timeout: float = 30)` |
| `maya_status` | `()` – Verbindung, Port, Maya-Version, Prozess-ID |
| `maya_scene_info` | `()` – Datei, Frame-Range, Einheiten, Up-Achse, Node-Anzahl je Typ |
| `maya_list_nodes` | `(node_type: str = "", pattern: str = "", limit: int = 200)` |
| `maya_get_attr` | `(node: str, attr: str)` |
| `maya_set_attr` | `(node: str, attr: str, value: Any)` |
| `maya_select` | `(nodes: list[str], replace: bool = True)` |
| `maya_new_scene` | `(force: bool = False)` |
| `maya_open_file` | `(path: str, force: bool = False)` |
| `maya_import_file` | `(path: str, file_type: str = "", namespace: str = "")` – USD über mayaUsdPlugin, FBX über fbxmaya |
| `maya_set_time` | `(frame: float)` |
| `maya_screenshot` | `(path: str, width: int = 960, height: int = 540, camera: str = "")` |

Der Namensraum in Maya bleibt über Aufrufe hinweg erhalten: in einem Aufruf
gesetzte Variablen stehen im nächsten noch zur Verfügung.

## Konfiguration

| Variable | Vorgabe | Wirkung |
|----------|---------|---------|
| `MAYA_MCP_PORT` | `20777` | Port von Listener und Server |
| `MAYA_MCP_HOST` | `127.0.0.1` | Adresse, zu der der Server verbindet |
| `MAYA_MCP_TIMEOUT` | `30` | Vorgabe-Timeout in Sekunden |
| `MAYA_MCP_AUTOSTART` | `1` | `0` verhindert den Autostart des Listeners |

## Hinweise

* Läuft Maya nicht oder ist der Listener nicht geladen, meldet jedes Tool das
  als Fehler mit Hinweis auf den Port; der Server blockiert nicht.
* Antwortet Mayas Hauptthread nicht (modaler Dialog, lange Berechnung), greift
  das Timeout und meldet genau das.
* Windows reserviert dynamische Portbereiche
  (`netsh interface ipv4 show excludedportrange protocol=tcp`). Liegt der Port
  darin, scheitert `bind` mit WinError 10013 – dann `MAYA_MCP_PORT` ändern.
* `maya_screenshot` nutzt `ogsRender` (Viewport 2.0) statt `playblast`.
  `playblast` liest den Framebuffer des Maya-Fensters und liefert leere Bilder,
  sobald das Fenster verdeckt ist.

## Test

```bash
.venv\Scripts\python.exe tests\mcp_smoke.py          # voller Durchlauf gegen laufendes Maya
.venv\Scripts\python.exe tests\mcp_smoke.py --list   # nur tools/list
```

## Lizenz

MIT, siehe `LICENSE`.
