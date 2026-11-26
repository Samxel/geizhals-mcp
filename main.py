# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3.0,<3", "httpx[http2]>=0.28.1"]
# ///
"""Starts the server from a checkout: ``python main.py`` serves over HTTP,
``python main.py --stdio`` over stdin/stdout. ``uv run main.py`` installs the
dependencies above on the fly. Installed as a package, the ``geizhals-mcp``
command does the same."""

from geizhals.server import main

if __name__ == "__main__":
    main()
