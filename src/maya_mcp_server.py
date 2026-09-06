"""MCP-Server fuer Autodesk Maya.

Spricht ueber stdio mit dem MCP-Client und ueber einen lokalen Socket mit dem
Listener in Maya (maya_module/scripts/maya_mcp_listener.py).
"""

import json
import logging
import os
import socket
import struct
import sys
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

__version__ = "1.0.0"

DEFAULT_HOST = os.environ.get("MAYA_MCP_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("MAYA_MCP_PORT", "50777"))
DEFAULT_TIMEOUT = float(os.environ.get("MAYA_MCP_TIMEOUT", "30"))

_HEADER = struct.Struct(">I")

logging.basicConfig(
    level=os.environ.get("MAYA_MCP_LOGLEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("maya-mcp")

mcp = MCPServer("maya")


class MayaUnavailable(ToolError):
    """Maya ist nicht erreichbar; die Nachricht geht an den MCP-Client."""


class MayaError(ToolError):
    """Der Code lief in Maya, endete dort aber mit einem Fehler."""


def _recv_exactly(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            raise MayaUnavailable(
                "Verbindung zu Maya wurde waehrend der Antwort geschlossen "
                "(Maya beendet, Szene abgestuerzt oder Listener gestoppt)."
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _request(payload: dict, timeout: float) -> dict:
    address = (DEFAULT_HOST, DEFAULT_PORT)
    try:
        sock = socket.create_connection(address, timeout=timeout)
    except (ConnectionRefusedError, OSError) as exc:
        raise MayaUnavailable(
            f"Keine Verbindung zum Maya-MCP-Listener auf {DEFAULT_HOST}:{DEFAULT_PORT} "
            f"({exc.__class__.__name__}: {exc}). Laeuft Maya 2026 mit installiertem "
            "MayaMCP-Modul? Im Script Editor pruefen mit: "
            "import maya_mcp_listener; maya_mcp_listener.start()"
        ) from exc

    try:
        sock.settimeout(timeout)
        body = json.dumps(payload).encode("utf-8")
        sock.sendall(_HEADER.pack(len(body)) + body)
        header = _recv_exactly(sock, _HEADER.size)
        (size,) = _HEADER.unpack(header)
        return json.loads(_recv_exactly(sock, size).decode("utf-8"))
    except socket.timeout as exc:
        raise MayaUnavailable(
            f"Zeitueberschreitung nach {timeout}s. Maya antwortet nicht - der "
            "Hauptthread ist belegt (modaler Dialog, laufende Berechnung) oder der "
            "Code laeuft zu lange. Timeout-Argument erhoehen oder Maya pruefen."
        ) from exc
    finally:
        sock.close()


def _exec(code: str, timeout: float = DEFAULT_TIMEOUT, mel: bool = False) -> dict:
    response = _request(
        {"op": "exec_mel" if mel else "exec_python", "code": code}, timeout
    )
    if not response.get("ok"):
        raise MayaError(response.get("error", "Unbekannter Listener-Fehler"))
    return response


def _value(code: str, timeout: float = DEFAULT_TIMEOUT) -> Any:
    response = _exec(code, timeout)
    if response.get("traceback"):
        raise MayaError(response["traceback"].strip())
    if not response.get("result_jsonable", True):
        raise MayaError(
            "Rueckgabewert ist nicht JSON-serialisierbar: "
            f"{response.get('result_repr')}"
        )
    return response.get("result")


@mcp.tool()
def maya_exec_python(code: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Fuehrt Python-Code im laufenden Maya aus (maya.cmds, maya.api.OpenMaya,
    pymel falls installiert).

    Der Code laeuft im Maya-Hauptthread in einem persistenten Namensraum, der
    ueber Aufrufe hinweg erhalten bleibt. Ist das letzte Statement ein Ausdruck,
    wird sein Wert zurueckgegeben.

    Args:
        code: Python-Quelltext, mehrzeilig erlaubt.
        timeout: Sekunden, die auf Mayas Antwort gewartet wird.

    Returns:
        stdout, result (falls JSON-faehig), result_repr und traceback.
    """
    return _exec(code, timeout)


@mcp.tool()
def maya_exec_mel(code: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Fuehrt MEL-Code im laufenden Maya aus.

    Args:
        code: MEL-Quelltext.
        timeout: Sekunden, die auf Mayas Antwort gewartet wird.
    """
    return _exec(code, timeout, mel=True)


@mcp.tool()
def maya_status() -> dict:
    """Prueft die Verbindung zu Maya und meldet Version, Prozess-ID und Port."""
    response = _request({"op": "ping"}, DEFAULT_TIMEOUT)
    return {"host": DEFAULT_HOST, "port": DEFAULT_PORT, **response}


@mcp.tool()
def maya_scene_info() -> dict:
    """Liefert Szenendatei, Frame-Range, Einheiten, Up-Achse und die
    Node-Anzahl je Typ der aktuellen Maya-Szene."""
    return _value(
        """
import maya.cmds as cmds
from collections import Counter
_nodes = cmds.ls()
_counts = Counter(cmds.nodeType(n) for n in _nodes)
{
    "file": cmds.file(query=True, sceneName=True) or "",
    "modified": cmds.file(query=True, modified=True),
    "maya_version": cmds.about(version=True),
    "start_frame": cmds.playbackOptions(query=True, minTime=True),
    "end_frame": cmds.playbackOptions(query=True, maxTime=True),
    "current_frame": cmds.currentTime(query=True),
    "fps": cmds.currentUnit(query=True, time=True),
    "linear_unit": cmds.currentUnit(query=True, linear=True),
    "angular_unit": cmds.currentUnit(query=True, angle=True),
    "up_axis": cmds.upAxis(query=True, axis=True),
    "node_total": len(_nodes),
    "node_counts": dict(_counts.most_common(50)),
}
"""
    )


@mcp.tool()
def maya_list_nodes(node_type: str = "", pattern: str = "", limit: int = 200) -> dict:
    """Listet Nodes der Szene, optional gefiltert.

    Args:
        node_type: Node-Typ wie "transform", "mesh", "camera" (leer = alle).
        pattern: Namensmuster mit Wildcards, z.B. "mcp_*" (leer = alle).
        limit: Maximale Anzahl zurueckgegebener Namen.
    """
    return _value(
        f"""
import maya.cmds as cmds
_type = {node_type!r}
_pattern = {pattern!r}
_limit = {int(limit)!r}
_kwargs = {{"long": True}}
if _type:
    _kwargs["type"] = _type
_args = [_pattern] if _pattern else []
_found = cmds.ls(*_args, **_kwargs) or []
{{"count": len(_found), "truncated": len(_found) > _limit, "nodes": _found[:_limit]}}
"""
    )


@mcp.tool()
def maya_get_attr(node: str, attr: str) -> dict:
    """Liest ein Attribut eines Nodes.

    Args:
        node: Node-Name, z.B. "pCube1".
        attr: Attributname, z.B. "translateX" oder "translate".
    """
    return _value(
        f"""
import maya.cmds as cmds
_plug = "{{}}.{{}}".format({node!r}, {attr!r})
{{
    "plug": _plug,
    "type": cmds.getAttr(_plug, type=True),
    "value": cmds.getAttr(_plug),
    "locked": cmds.getAttr(_plug, lock=True),
}}
"""
    )


@mcp.tool()
def maya_set_attr(node: str, attr: str, value: Any) -> dict:
    """Setzt ein Attribut eines Nodes.

    Args:
        node: Node-Name.
        attr: Attributname.
        value: Zahl, Text, Wahrheitswert oder Liste (z.B. [1, 2, 3] fuer translate).
    """
    return _value(
        f"""
import maya.cmds as cmds
_plug = "{{}}.{{}}".format({node!r}, {attr!r})
_value = {value!r}
_type = cmds.getAttr(_plug, type=True)
if _type == "string":
    cmds.setAttr(_plug, _value, type="string")
elif isinstance(_value, (list, tuple)):
    if _type in ("double2", "float2", "double3", "float3", "short2", "short3",
                 "long2", "long3", "matrix", "doubleArray"):
        cmds.setAttr(_plug, *_value, type=_type)
    else:
        cmds.setAttr(_plug, *_value)
else:
    cmds.setAttr(_plug, _value)
{{"plug": _plug, "type": _type, "value": cmds.getAttr(_plug)}}
"""
    )


@mcp.tool()
def maya_select(nodes: list[str], replace: bool = True) -> dict:
    """Waehlt Nodes aus. Eine leere Liste hebt die Auswahl auf.

    Args:
        nodes: Node-Namen.
        replace: True ersetzt die Auswahl, False erweitert sie.
    """
    return _value(
        f"""
import maya.cmds as cmds
_nodes = {list(nodes)!r}
if _nodes:
    cmds.select(_nodes, replace={bool(replace)!r}, add=not {bool(replace)!r})
else:
    cmds.select(clear=True)
{{"selected": cmds.ls(selection=True, long=True) or []}}
"""
    )


@mcp.tool()
def maya_new_scene(force: bool = False) -> dict:
    """Erstellt eine neue, leere Szene.

    Args:
        force: True verwirft ungespeicherte Aenderungen ohne Nachfrage.
    """
    return _value(
        f"""
import maya.cmds as cmds
cmds.file(new=True, force={bool(force)!r})
{{"file": cmds.file(query=True, sceneName=True) or "", "node_total": len(cmds.ls())}}
"""
    )


@mcp.tool()
def maya_open_file(path: str, force: bool = False) -> dict:
    """Oeffnet eine Maya-Szene (.ma/.mb).

    Args:
        path: Absoluter Pfad zur Szenendatei.
        force: True verwirft ungespeicherte Aenderungen ohne Nachfrage.
    """
    return _value(
        f"""
import os
import maya.cmds as cmds
_path = {path!r}
if not os.path.isfile(_path):
    raise IOError("Datei nicht gefunden: " + _path)
cmds.file(_path, open=True, force={bool(force)!r})
{{"file": cmds.file(query=True, sceneName=True), "node_total": len(cmds.ls())}}
""",
        timeout=max(DEFAULT_TIMEOUT, 120.0),
    )


@mcp.tool()
def maya_import_file(path: str, file_type: str = "", namespace: str = "") -> dict:
    """Importiert eine Datei in die aktuelle Szene.

    USD (.usd/.usda/.usdc/.usdz) und FBX werden erkannt und laden das
    passende Plugin (mayaUsdPlugin bzw. fbxmaya) selbst.

    Args:
        path: Absoluter Pfad zur Datei.
        file_type: Maya-Translator erzwingen, z.B. "USD Import", "FBX", "OBJ".
        namespace: Optionaler Namespace fuer die importierten Nodes.
    """
    return _value(
        f"""
import os
import maya.cmds as cmds
_path = {path!r}
_type = {file_type!r}
_namespace = {namespace!r}
if not os.path.isfile(_path):
    raise IOError("Datei nicht gefunden: " + _path)
_ext = os.path.splitext(_path)[1].lower()
if not _type:
    if _ext in (".usd", ".usda", ".usdc", ".usdz"):
        _type = "USD Import"
    elif _ext == ".fbx":
        _type = "FBX"
    elif _ext == ".obj":
        _type = "OBJ"
if _type == "USD Import" and not cmds.pluginInfo("mayaUsdPlugin", query=True, loaded=True):
    cmds.loadPlugin("mayaUsdPlugin")
if _type == "FBX" and not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
    cmds.loadPlugin("fbxmaya")
_kwargs = {{"i": True, "returnNewNodes": True}}
if _type:
    _kwargs["type"] = _type
if _namespace:
    _kwargs["namespace"] = _namespace
_new = cmds.file(_path, **_kwargs) or []
{{"file": _path, "type": _type, "new_node_count": len(_new), "new_nodes": _new[:100]}}
""",
        timeout=max(DEFAULT_TIMEOUT, 180.0),
    )


@mcp.tool()
def maya_set_time(frame: float) -> dict:
    """Setzt die aktuelle Zeit der Szene auf einen Frame.

    Args:
        frame: Ziel-Frame.
    """
    return _value(
        f"""
import maya.cmds as cmds
cmds.currentTime({float(frame)!r}, edit=True)
{{"current_frame": cmds.currentTime(query=True)}}
"""
    )


@mcp.tool()
def maya_screenshot(
    path: str,
    width: int = 960,
    height: int = 540,
    camera: str = "",
) -> dict:
    """Nimmt ein Viewport-Einzelbild des aktuellen Frames als PNG auf.

    Args:
        path: Absoluter Zielpfad der PNG-Datei.
        width: Bildbreite in Pixeln.
        height: Bildhoehe in Pixeln.
        camera: Kamera fuer die Aufnahme, z.B. "persp" (leer = aktuelle Ansicht).
    """
    return _value(
        f"""
import os
import maya.cmds as cmds
_path = os.path.abspath({path!r})
_camera = {camera!r}
os.makedirs(os.path.dirname(_path) or ".", exist_ok=True)

_panel = cmds.getPanel(withFocus=True)
if _panel not in (cmds.getPanel(type="modelPanel") or []):
    _panels = cmds.getPanel(visiblePanels=True) or []
    _models = [p for p in _panels if p in (cmds.getPanel(type="modelPanel") or [])]
    _panel = _models[0] if _models else None
if _panel is None:
    raise RuntimeError("Kein sichtbarer modelPanel-Viewport - laeuft Maya im Batch-Modus?")

if _camera:
    cmds.lookThru(_panel, _camera)
cmds.refresh()

_frame = cmds.currentTime(query=True)
_result = cmds.playblast(
    completeFilename=_path,
    format="image",
    compression="png",
    forceOverwrite=True,
    widthHeight=[{int(width)!r}, {int(height)!r}],
    percent=100,
    quality=100,
    startTime=_frame,
    endTime=_frame,
    framePadding=4,
    viewer=False,
    showOrnaments=False,
)
{{
    "path": _path,
    "exists": os.path.isfile(_path),
    "bytes": os.path.getsize(_path) if os.path.isfile(_path) else 0,
    "panel": _panel,
    "camera": cmds.modelPanel(_panel, query=True, camera=True),
    "frame": _frame,
    "playblast_result": _result,
}}
""",
        timeout=max(DEFAULT_TIMEOUT, 120.0),
    )


if __name__ == "__main__":
    logger.info("maya-mcp %s -> %s:%s", __version__, DEFAULT_HOST, DEFAULT_PORT)
    mcp.run(transport="stdio")
