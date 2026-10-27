"""Shared fixtures: an in-process MCP client and a fake Geizhals API standing in
for ``geizhals.api.post``, so the tools are exercised end to end without the network."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geizhals.api  # noqa: E402
import main  # noqa: E402
from mcp import Client  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeAPI:
    """Answers each endpoint from a canned response (a dict, a callable taking
    the payload, or an exception to raise) and records every payload sent."""

    def __init__(self):
        self.responses = {}
        self.calls = []

    def on(self, endpoint, response):
        self.responses[endpoint] = response
        return self

    async def __call__(self, endpoint, payload):
        self.calls.append((endpoint, payload))
        if endpoint not in self.responses:
            raise AssertionError(f"unexpected call to {endpoint}")
        response = self.responses[endpoint]
        if isinstance(response, Exception):
            raise response
        return response(payload) if callable(response) else response

    def sent(self, endpoint):
        return [payload for name, payload in self.calls if name == endpoint]


@pytest.fixture
def api(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(geizhals.api, "post", fake)
    # a feed cached by an earlier test would hide this test's canned one
    geizhals.api._deals_cache.clear()
    return fake


class ToolFailed(Exception):
    """The call came back with ``is_error`` set; the message is its text."""


async def call_tool(tool, **args):
    """Call a tool through a real MCP client and decode its JSON text."""
    async with Client(main.mcp) as client:
        result = await client.call_tool(tool, args)
    text = "".join(block.text for block in result.content if block.type == "text")
    if result.is_error:
        raise ToolFailed(text)
    return json.loads(text)


@pytest.fixture
def call():
    return call_tool
