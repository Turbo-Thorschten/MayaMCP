"""Maya-seitiger Listener fuer den Maya-MCP-Server.

Laeuft in Maya und nimmt auf einem lokalen Socket laengenpraefixierte
JSON-Requests entgegen. Der eigentliche Code wird immer im Maya-Hauptthread
ausgefuehrt, weil maya.cmds aus einem anderen Thread nicht sicher ist.
"""

import ast
import contextlib
import io
import json
import os
import socket
import struct
import threading
import traceback

import maya.utils

DEFAULT_PORT = 20777
PROTOCOL_VERSION = 1

_HEADER = struct.Struct(">I")
_MAX_MESSAGE = 32 * 1024 * 1024

_state = {"server": None, "thread": None, "port": None}
_scope = {"__name__": "maya_mcp_scope"}


def _recv_exactly(sock, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_message(sock):
    header = _recv_exactly(sock, _HEADER.size)
    if header is None:
        return None
    (size,) = _HEADER.unpack(header)
    if size > _MAX_MESSAGE:
        raise ValueError("message too large: %d" % size)
    body = _recv_exactly(sock, size)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


def _send_message(sock, payload):
    body = json.dumps(payload).encode("utf-8")
    sock.sendall(_HEADER.pack(len(body)) + body)


def _jsonable(value):
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return None, False
    return value, True


def _exec_python(code):
    stdout = io.StringIO()
    value = None
    error = None
    try:
        tree = ast.parse(code, filename="<maya-mcp>", mode="exec")
    except SyntaxError:
        return {"stdout": "", "result": None, "result_repr": None,
                "traceback": traceback.format_exc()}

    body = tree.body
    tail = body[-1] if body else None
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
        try:
            if isinstance(tail, ast.Expr):
                head = ast.Module(body=body[:-1], type_ignores=[])
                exec(compile(head, "<maya-mcp>", "exec"), _scope)
                value = eval(
                    compile(ast.Expression(tail.value), "<maya-mcp>", "eval"), _scope
                )
            else:
                exec(compile(tree, "<maya-mcp>", "exec"), _scope)
        except BaseException:
            error = traceback.format_exc()

    result, ok = _jsonable(value)
    return {
        "stdout": stdout.getvalue(),
        "result": result,
        "result_repr": None if value is None else repr(value),
        "result_jsonable": ok,
        "traceback": error,
    }


def _exec_mel(code):
    import maya.mel

    stdout = io.StringIO()
    value = None
    error = None
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
        try:
            value = maya.mel.eval(code)
        except BaseException:
            error = traceback.format_exc()

    result, ok = _jsonable(value)
    return {
        "stdout": stdout.getvalue(),
        "result": result,
        "result_repr": None if value is None else repr(value),
        "result_jsonable": ok,
        "traceback": error,
    }


def _handle_request(request):
    op = request.get("op")
    if op == "ping":
        import maya.cmds as cmds

        return {
            "ok": True,
            "protocol": PROTOCOL_VERSION,
            "maya_version": cmds.about(version=True),
            "pid": os.getpid(),
        }
    if op == "exec_python":
        payload = maya.utils.executeInMainThreadWithResult(
            _exec_python, request.get("code", "")
        )
        return {"ok": True, **payload}
    if op == "exec_mel":
        payload = maya.utils.executeInMainThreadWithResult(
            _exec_mel, request.get("code", "")
        )
        return {"ok": True, **payload}
    return {"ok": False, "error": "unknown op: %r" % (op,)}


def _serve_client(conn):
    try:
        while True:
            request = _recv_message(conn)
            if request is None:
                return
            try:
                response = _handle_request(request)
            except BaseException:
                response = {"ok": False, "error": traceback.format_exc()}
            _send_message(conn, response)
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _serve(server):
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        conn.settimeout(None)
        threading.Thread(
            target=_serve_client, args=(conn,), daemon=True,
            name="maya-mcp-client",
        ).start()


def start(port=None):
    if _state["server"] is not None:
        return _state["port"]

    if port is None:
        port = int(os.environ.get("MAYA_MCP_PORT", DEFAULT_PORT))

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("127.0.0.1", port))
    except OSError as exc:
        server.close()
        raise OSError(
            "Port %d nicht verwendbar (%s). Unter Windows sind Portbereiche "
            "reserviert; 'netsh interface ipv4 show excludedportrange protocol=tcp' "
            "zeigt sie. Anderen Port ueber MAYA_MCP_PORT setzen." % (port, exc)
        ) from exc
    server.listen(8)

    thread = threading.Thread(
        target=_serve, args=(server,), daemon=True, name="maya-mcp-listener"
    )
    thread.start()

    _state.update({"server": server, "thread": thread, "port": port})
    print("Maya MCP listener on 127.0.0.1:%d" % port)
    return port


def stop():
    server = _state["server"]
    if server is None:
        return
    try:
        server.close()
    except OSError:
        pass
    _state.update({"server": None, "thread": None, "port": None})
    print("Maya MCP listener stopped")
