"""Startet den Maya-MCP-Server ueber stdio und ruft die Tools real auf.

    python tests/mcp_smoke.py           # tools/list und alle Pruefaufrufe
    python tests/mcp_smoke.py --list    # nur tools/list
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "src" / "maya_mcp_server.py"


def show(title, result):
    print(f"\n=== {title} ===")
    print("is_error:", getattr(result, "is_error", None))
    for block in result.content:
        text = getattr(block, "text", None)
        print(text if text is not None else block)


async def main(list_only: bool) -> int:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("=== tools/list ===")
            for tool in tools.tools:
                props = tool.input_schema.get("properties", {})
                required = set(tool.input_schema.get("required", []))
                signature = ", ".join(
                    name if name in required else f"{name}?" for name in props
                )
                print(f"{tool.name}({signature})")
            if list_only:
                return 0

            show("maya_status", await session.call_tool("maya_status"))
            show(
                "maya_exec_python polyCube",
                await session.call_tool(
                    "maya_exec_python",
                    {"code": "import maya.cmds as cmds\ncmds.polyCube(name='mcp_test')"},
                ),
            )
            show(
                "maya_list_nodes mcp_*",
                await session.call_tool(
                    "maya_list_nodes", {"pattern": "mcp_*", "node_type": "transform"}
                ),
            )
            show("maya_scene_info", await session.call_tool("maya_scene_info"))
            show(
                "maya_set_attr",
                await session.call_tool(
                    "maya_set_attr",
                    {"node": "mcp_test", "attr": "translate", "value": [1.5, 2.0, -3.0]},
                ),
            )
            show(
                "maya_get_attr",
                await session.call_tool(
                    "maya_get_attr", {"node": "mcp_test", "attr": "translateY"}
                ),
            )
            show(
                "maya_select",
                await session.call_tool("maya_select", {"nodes": ["mcp_test"]}),
            )
            show("maya_set_time", await session.call_tool("maya_set_time", {"frame": 12}))
            show(
                "maya_exec_mel",
                await session.call_tool("maya_exec_mel", {"code": "about -version;"}),
            )
            shot = REPO / "build" / "mcp_smoke.png"
            show(
                "maya_screenshot",
                await session.call_tool(
                    "maya_screenshot",
                    {"path": str(shot), "width": 800, "height": 600, "camera": "persp"},
                ),
            )
            show(
                "maya_exec_python traceback",
                await session.call_tool(
                    "maya_exec_python", {"code": "1 / 0"}
                ),
            )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.list_only)))
