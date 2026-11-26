"""The package metadata, the .mcpb manifest and the server agree."""

import json
import sys
from pathlib import Path

import pytest
from mcp import Client

from geizhals import server as main

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    if sys.version_info >= (3, 11):
        import tomllib
        return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    import re  # 3.10 has no tomllib; the two fields read here are simple lines
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return {"project": {"version": re.search(r'^version = "(.+)"', text, re.M).group(1),
                        "name": re.search(r'^name = "(.+)"', text, re.M).group(1)}}


def test_versions_match():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    project = _pyproject()["project"]
    assert manifest["version"] == project["version"]
    assert manifest["name"] == project["name"]


async def test_manifest_lists_every_tool():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    async with Client(main.mcp) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert {tool["name"] for tool in manifest["tools"]} == names
