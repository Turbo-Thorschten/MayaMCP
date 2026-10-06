"""Starts the Maya MCP listener when Maya starts.

Maya runs every userSetup.py on the Python path; this module ships its own
scripts folder, so an existing userSetup.py of the user stays untouched.

Startup errors go to maya_mcp_startup.log in the temp directory
(Windows %TEMP%, macOS $TMPDIR), because output from userSetup.py would
otherwise only show up in the Script Editor.
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
        _log("listener started on port %s" % port)
    except Exception:
        _log("listener start failed:\n" + traceback.format_exc())


_log("userSetup.py loaded (pid %d)" % os.getpid())

if os.environ.get("MAYA_MCP_AUTOSTART", "1") != "0":
    _start_maya_mcp()
