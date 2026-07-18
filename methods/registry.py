from __future__ import annotations
from typing import Any

from ai.providers.base import ToolSpec
from methods.base import Tool
from methods.web.search import WebSearchTool
from methods.google.search import GoogleSearchTool
from methods.steam.search import SteamSearchTool, SteamGameTool, SteamReviewsTool
from methods.anime.search import AnimeSearchTool
from methods.anime.info import AnimeInfoTool
from methods.anime.tracking import AnimeTrackingTool
from methods.lib.search import LibSearchTool
from methods.lib.info import LibInfoTool
from methods.lib.downloader import LibDownloadTool
from methods.memory.save import MemorySaveTool
from methods.image.vision import ImageVisionTool
from methods.api_keys.request import RequestApiKeyTool

_TOOLS: dict[str, Tool] = {}

def register(tool: Tool) -> None:
    _TOOLS[tool.name] = tool

for _t in (
    WebSearchTool(),
    GoogleSearchTool(),
    SteamSearchTool(), SteamGameTool(), SteamReviewsTool(),
    AnimeSearchTool(), AnimeInfoTool(), AnimeTrackingTool(),
    LibSearchTool(), LibInfoTool(), LibDownloadTool(),
    MemorySaveTool(),
    ImageVisionTool(),
    RequestApiKeyTool(),
):
    register(_t)

def tool_specs() -> list[ToolSpec]:
    return [t.spec() for t in _TOOLS.values()]

async def run_tool(name: str, args: dict[str, Any], *, session, user_id: int) -> Any:
    tool = _TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool {name}"}
    return await tool.run(args or {}, session=session, user_id=user_id)
