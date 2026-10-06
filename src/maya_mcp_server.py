"""MCP server for Autodesk Maya.

Talks to the MCP client over stdio and to the listener inside Maya
(maya_module/scripts/maya_mcp_listener.py) over a local socket.
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
DEFAULT_PORT = int(os.environ.get("MAYA_MCP_PORT", "20777"))
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
    """Maya is unreachable; the message is passed on to the MCP client."""


class MayaError(ToolError):
    """The code ran in Maya but ended with an error there."""


def _recv_exactly(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            raise MayaUnavailable(
                "Connection to Maya was closed during the response "
                "(Maya exited, scene crashed or listener stopped)."
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
            f"No connection to the Maya MCP listener on {DEFAULT_HOST}:{DEFAULT_PORT} "
            f"({exc.__class__.__name__}: {exc}). Is Maya running with the MayaMCP "
            "module installed? Check in the Script Editor with: "
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
            f"Timed out after {timeout}s. Maya is not responding - the main "
            "thread is busy (modal dialog, running computation) or the code "
            "runs too long. Increase the timeout argument or check Maya."
        ) from exc
    finally:
        sock.close()


def _exec(code: str, timeout: float = DEFAULT_TIMEOUT, mel: bool = False) -> dict:
    response = _request(
        {"op": "exec_mel" if mel else "exec_python", "code": code}, timeout
    )
    if not response.get("ok"):
        raise MayaError(response.get("error", "Unknown listener error"))
    return response


def _value(code: str, timeout: float = DEFAULT_TIMEOUT) -> Any:
    response = _exec(code, timeout)
    if response.get("traceback"):
        raise MayaError(response["traceback"].strip())
    if not response.get("result_jsonable", True):
        raise MayaError(
            "Return value is not JSON serializable: "
            f"{response.get('result_repr')}"
        )
    return response.get("result")


@mcp.tool()
def maya_exec_python(code: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Runs Python code in the running Maya (maya.cmds, maya.api.OpenMaya,
    pymel if installed).

    The code runs in Maya's main thread in a persistent namespace that
    survives across calls. If the last statement is an expression, its value
    is returned.

    Args:
        code: Python source, multiple lines allowed.
        timeout: Seconds to wait for Maya's response.

    Returns:
        stdout, result (if JSON serializable), result_repr and traceback.
    """
    return _exec(code, timeout)


@mcp.tool()
def maya_exec_mel(code: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Runs MEL code in the running Maya.

    Args:
        code: MEL source.
        timeout: Seconds to wait for Maya's response.
    """
    return _exec(code, timeout, mel=True)


@mcp.tool()
def maya_status() -> dict:
    """Checks the connection to Maya and reports version, process ID and port."""
    response = _request({"op": "ping"}, DEFAULT_TIMEOUT)
    version = _value("import maya.cmds as cmds\ncmds.about(version=True)")
    return {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "maya_version": version,
        **response,
    }


@mcp.tool()
def maya_scene_info() -> dict:
    """Returns scene file, frame range, units, up axis and the node count
    per type of the current Maya scene."""
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
    """Lists scene nodes, optionally filtered.

    Args:
        node_type: Node type such as "transform", "mesh", "camera" (empty = all).
        pattern: Name pattern with wildcards, e.g. "mcp_*" (empty = all).
        limit: Maximum number of returned names.
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
    """Reads an attribute of a node.

    Args:
        node: Node name, e.g. "pCube1".
        attr: Attribute name, e.g. "translateX" or "translate".
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
    """Sets an attribute of a node.

    Args:
        node: Node name.
        attr: Attribute name.
        value: Number, string, boolean or list (e.g. [1, 2, 3] for translate).
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
    if _type in ("doubleArray", "Int32Array"):
        cmds.setAttr(_plug, list(_value), type=_type)
    elif _type == "stringArray":
        cmds.setAttr(_plug, len(_value), *_value, type=_type)
    elif _type in ("double2", "float2", "double3", "float3", "short2", "short3",
                   "long2", "long3", "matrix"):
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
    """Selects nodes. An empty list clears the selection.

    Args:
        nodes: Node names.
        replace: True replaces the selection, False adds to it.
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
    """Creates a new, empty scene.

    Args:
        force: True discards unsaved changes without asking.
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
    """Opens a Maya scene (.ma/.mb).

    Args:
        path: Absolute path to the scene file.
        force: True discards unsaved changes without asking.
    """
    return _value(
        f"""
import os
import maya.cmds as cmds
_path = {path!r}
if not os.path.isfile(_path):
    raise IOError("File not found: " + _path)
cmds.file(_path, open=True, force={bool(force)!r})
{{"file": cmds.file(query=True, sceneName=True), "node_total": len(cmds.ls())}}
""",
        timeout=max(DEFAULT_TIMEOUT, 120.0),
    )


@mcp.tool()
def maya_import_file(path: str, file_type: str = "", namespace: str = "") -> dict:
    """Imports a file into the current scene.

    USD (.usd/.usda/.usdc/.usdz) and FBX are detected and load the matching
    plugin (mayaUsdPlugin or fbxmaya) on their own.

    Args:
        path: Absolute path to the file.
        file_type: Force a Maya translator, e.g. "USD Import", "FBX", "OBJ".
        namespace: Optional namespace for the imported nodes.
    """
    return _value(
        f"""
import os
import maya.cmds as cmds
_path = {path!r}
_type = {file_type!r}
_namespace = {namespace!r}
if not os.path.isfile(_path):
    raise IOError("File not found: " + _path)
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
    """Sets the scene's current time to a frame.

    Args:
        frame: Target frame.
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
    """Renders the current frame through Viewport 2.0 as PNG.

    Uses ogsRender instead of playblast, because playblast reads the
    framebuffer of the Maya window and returns blank images as soon as the
    window is covered or minimized.

    Args:
        path: Absolute target path of the PNG file.
        width: Image width in pixels.
        height: Image height in pixels.
        camera: Camera to shoot from, e.g. "persp" (empty = current view).
    """
    return _value(
        f"""
import os
import shutil
import maya.cmds as cmds
_path = os.path.abspath({path!r})
_camera = {camera!r}
os.makedirs(os.path.dirname(_path) or ".", exist_ok=True)

if not _camera:
    _models = cmds.getPanel(type="modelPanel") or []
    _panel = cmds.getPanel(withFocus=True)
    if _panel not in _models:
        _visible = [p for p in (cmds.getPanel(visiblePanels=True) or []) if p in _models]
        _panel = _visible[0] if _visible else (_models[0] if _models else None)
    if _panel is not None:
        _camera = cmds.modelPanel(_panel, query=True, camera=True)
if not _camera:
    _camera = "persp"

_frame = cmds.currentTime(query=True)
_format = cmds.getAttr("defaultRenderGlobals.imageFormat")
cmds.setAttr("defaultRenderGlobals.imageFormat", 32)
try:
    _rendered = cmds.ogsRender(
        camera=_camera,
        width={int(width)!r},
        height={int(height)!r},
        currentFrame=True,
    )
finally:
    cmds.setAttr("defaultRenderGlobals.imageFormat", _format)
if isinstance(_rendered, (list, tuple)):
    _rendered = _rendered[0]
if not _rendered or not os.path.isfile(_rendered):
    raise RuntimeError("ogsRender produced no image: " + repr(_rendered))
shutil.copyfile(_rendered, _path)
{{
    "path": _path,
    "exists": os.path.isfile(_path),
    "bytes": os.path.getsize(_path),
    "camera": _camera,
    "frame": _frame,
    "rendered_from": _rendered,
}}
""",
        timeout=max(DEFAULT_TIMEOUT, 120.0),
    )


if __name__ == "__main__":
    logger.info("maya-mcp %s -> %s:%s", __version__, DEFAULT_HOST, DEFAULT_PORT)
    mcp.run(transport="stdio")
