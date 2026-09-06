"""Startet den Maya-MCP-Listener beim Maya-Start.

Maya fuehrt jede userSetup.py aus, die auf dem Python-Pfad liegt; dieses
Modul bringt seinen eigenen scripts-Ordner mit, ein vorhandenes
userSetup.py des Benutzers bleibt unangetastet.

Startfehler landen in %TEMP%/maya_mcp_startup.log, weil Ausgaben aus
userSetup.py sonst nur im Script Editor sichtbar waeren.
"""

import os
import tempfile
import traceback

LOG = os.path.join(tempfile.gettempdir(), "maya_mcp_startup.log")


def _log(message):
    try:
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def _start_maya_mcp():
    try:
        import maya_mcp_listener

        port = maya_mcp_listener.start()
        _log("listener gestartet auf port %s" % port)
    except Exception:
        _log("listener-start fehlgeschlagen:\n" + traceback.format_exc())


_log("userSetup.py geladen (pid %d)" % os.getpid())

if os.environ.get("MAYA_MCP_AUTOSTART", "1") != "0":
    _start_maya_mcp()
