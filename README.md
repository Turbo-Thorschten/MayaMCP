# Maya MCP

MCP server (Model Context Protocol) for Autodesk Maya 2026 on Windows and macOS.

The server runs as a separate process and talks to the MCP client (e.g.
Claude Code) over **stdio**. Inside Maya, a **listener** accepts
length-prefixed JSON requests on `127.0.0.1:20777` and executes the code in
Maya's main thread via `maya.utils.executeInMainThreadWithResult`.

```
Claude Code  --stdio-->  src/maya_mcp_server.py  --TCP/JSON-->  Maya (listener)
```

## Origin

This project is based on [PatrickPalmer/MayaMCP](https://github.com/PatrickPalmer/MayaMCP)
(MIT, Copyright (c) 2025 Patrick Palmer, see `LICENSE`). It keeps the basic
idea and the architecture of an MCP server plus a Maya-side counterpart.

Changes compared to the original:

* **MCP SDK 2.x**: The original uses the lowlevel `Server` and
  `mcp.server.fastmcp.*`. In `mcp` 2.x, FastMCP was renamed to `MCPServer`, and
  `mcp.server.fastmcp` no longer exists. The server now uses
  `from mcp.server import MCPServer` with `@mcp.tool()` and `mcp.run(transport="stdio")`.
* **Transport to Maya**: Instead of escaping Python code into MEL strings and
  opening two connections to Maya's MEL command port per call, a dedicated
  listener with a JSON protocol runs inside Maya. This removes escaping issues,
  and stdout, return value and traceback come back separately.
* **Fixed tool set** instead of dynamically loaded script files (the
  original's `src/mayatools/` scripts were removed).

## Installation

MCP dependencies go into a separate venv (Python 3.10+), not into Maya's Python:

```bash
uv venv .venv
uv pip install -r requirements.txt      # or: pip install -r requirements.txt
```

Install the Maya module:

```bash
python install.py                 # Maya version selectable via --maya-version
python install.py --register      # also register with Claude Code
python install.py --uninstall     # remove the module again
```

On macOS use `python3` if `python` is not available. The module file
`MayaMCP.mod` is written to:

| Platform | Location |
|----------|----------|
| Windows | `<Documents>\maya\2026\modules\` (the real Documents folder, also when OneDrive has moved it) |
| macOS | `~/Library/Preferences/Autodesk/maya/2026/modules/` |
| Linux | `~/maya/2026/modules/` |

The module ships its own `scripts` folder; its `userSetup.py` starts the
listener when Maya starts. An existing user `userSetup.py` is left untouched.
Startup messages and errors are written to `maya_mcp_startup.log` in the temp
directory (`%TEMP%` on Windows, `$TMPDIR` on macOS).

In an already running Maya, the listener can be loaded from the Script Editor
(Python):

```python
import sys; sys.path.append(r"<repo>/maya_module/scripts")
import maya_mcp_listener; maya_mcp_listener.start()
```

## Registering with Claude Code

`python install.py --register` does this for you. Manually:

```bash
# Windows
claude mcp add --scope user --transport stdio maya -- <repo>\.venv\Scripts\python.exe <repo>\src\maya_mcp_server.py
# macOS / Linux
claude mcp add --scope user --transport stdio maya -- <repo>/.venv/bin/python <repo>/src/maya_mcp_server.py

claude mcp list
claude mcp get maya
claude mcp remove maya --scope user      # remove
```

After starting a new session, the tools are available as `mcp__maya__*`.

## Tools

| Tool | Signature |
|------|-----------|
| `maya_exec_python` | `(code: str, timeout: float = 30)` – Python in Maya's main thread; returns stdout, the value of the last expression and the traceback |
| `maya_exec_mel` | `(code: str, timeout: float = 30)` |
| `maya_status` | `()` – connection, port, Maya version, process ID |
| `maya_scene_info` | `()` – file, frame range, units, up axis, node count per type |
| `maya_list_nodes` | `(node_type: str = "", pattern: str = "", limit: int = 200)` |
| `maya_get_attr` | `(node: str, attr: str)` |
| `maya_set_attr` | `(node: str, attr: str, value: Any)` |
| `maya_select` | `(nodes: list[str], replace: bool = True)` |
| `maya_new_scene` | `(force: bool = False)` |
| `maya_open_file` | `(path: str, force: bool = False)` |
| `maya_import_file` | `(path: str, file_type: str = "", namespace: str = "")` – USD via mayaUsdPlugin, FBX via fbxmaya |
| `maya_set_time` | `(frame: float)` |
| `maya_screenshot` | `(path: str, width: int = 960, height: int = 540, camera: str = "")` |

The namespace inside Maya persists across calls: variables set in one call are
still available in the next.

## Configuration

| Variable | Default | Effect |
|----------|---------|--------|
| `MAYA_MCP_PORT` | `20777` | Port of listener and server |
| `MAYA_MCP_HOST` | `127.0.0.1` | Address the server connects to |
| `MAYA_MCP_TIMEOUT` | `30` | Default timeout in seconds |
| `MAYA_MCP_AUTOSTART` | `1` | `0` prevents the listener from starting automatically |

## Notes

* If Maya is not running or the listener is not loaded, every tool reports
  this as an error mentioning the port; the server does not block.
* If Maya's main thread does not respond (modal dialog, long computation), the
  timeout kicks in and reports exactly that.
* The listener claims its port exclusively. A second Maya instance fails to
  start its listener with a clear error instead of silently sharing the port;
  give it a different `MAYA_MCP_PORT`.
* Windows reserves dynamic port ranges
  (`netsh interface ipv4 show excludedportrange protocol=tcp`). If the port
  falls inside one, `bind` fails with WinError 10013 – change `MAYA_MCP_PORT`
  in that case.
* `maya_screenshot` uses `ogsRender` (Viewport 2.0) instead of `playblast`.
  `playblast` reads the framebuffer of the Maya window and returns blank images
  as soon as the window is covered. The PNG format is forced for the render
  and the scene's render settings are restored afterwards.

## Test

```bash
.venv/bin/python tests/mcp_smoke.py          # full run against a running Maya
.venv/bin/python tests/mcp_smoke.py --list   # tools/list only
```

On Windows use `.venv\Scripts\python.exe` instead.

## License

MIT, see `LICENSE`.
