#!/usr/bin/env -S uv run
"""Run Vite development server for frontend and Cista backend with auto-reload.

Usage:
    uv run scripts/devserver.py [-l listen] [--backend backend] [cista_args...]

Options:
    -l, --listen  Vite frontend endpoint (default: localhost:8989)
    --backend     Cista backend endpoint (default: from config, or :8999)

Any additional arguments are passed to the cista command.

Environment:
    JS_RUNTIME  Path or name of JS runtime to use (deno, npm/node or bun).
"""

import argparse
import asyncio
import os
import sys
from contextlib import suppress
from pathlib import Path

# Import devutil from scripts/fastapi-vue (not a package, so we adjust sys.path)
sys.path.insert(0, str(Path(__file__).with_name("fastapi-vue")))
from devutil import (  # type: ignore[import-not-found]
    ProcessGroup,
    check_ports_free,
    logger,
    ready,
    setup_vite,
)

from cista import config
from cista.serve import parse_listen

DEFAULT_VITE_PORT = 8989
DEFAULT_BACKEND_PORT = 8999
HEALTH = "/api/health?from=devserver.py"


def setup_sanic_backend(
    listen: str | None, extra_args: list[str]
) -> tuple[str, list[str]]:
    """Parse backend listen address and build cista dev command.

    Returns (url, cmd).
    """
    config.load_config()
    listen = listen or config.config.listen or f":{DEFAULT_BACKEND_PORT}"
    _url, opts = parse_listen(listen)
    port = opts.get("port", DEFAULT_BACKEND_PORT)
    host = opts.get("host", "localhost") or "localhost"

    # Use the current interpreter/module path so devserver always runs
    # workspace source code instead of a potentially stale installed script.
    cmd = [sys.executable, "-m", "cista", "--dev", "-l", listen, *extra_args]
    return f"http://{host}:{port}", cmd


async def run_devserver(
    frontend: str | None, backend: str | None, extra_args: list[str]
) -> None:
    reporoot = Path(__file__).parent.parent
    front = reporoot / "frontend"
    if not (front / "package.json").exists():
        logger.warning("Frontend source not found at %s", front)
        raise SystemExit(1)

    frontend_url, npm_install, vite = setup_vite(frontend or "", DEFAULT_VITE_PORT)
    backend_url, sanic_cmd = setup_sanic_backend(backend, extra_args)

    # Tell vite where to proxy API requests
    os.environ["FASTAPI_VUE_BACKEND_URL"] = backend_url

    async with ProcessGroup() as pg:
        install_proc = await pg.spawn(*npm_install, cwd=str(front))
        await check_ports_free(frontend_url, backend_url)
        await pg.spawn(*sanic_cmd, cwd=str(reporoot))

        # Wait for dependencies to be installed and backend to accept requests
        await pg.wait(install_proc, ready(backend_url, path=HEALTH))

        # Start Vite dev server (ProcessGroup waits for any exit, then terminates others)
        await pg.spawn(*vite, cwd=str(front))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Vite and Cista (Sanic) development servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )
    parser.add_argument(
        "-l",
        "--listen",
        metavar="host:port",
        help="Vite frontend endpoint (default: localhost:8989)",
    )
    parser.add_argument(
        "--backend",
        metavar="host:port",
        help="Cista backend endpoint (default: from config, or :8999)",
    )
    args, unknown = parser.parse_known_args()
    with suppress(KeyboardInterrupt):
        asyncio.run(run_devserver(args.listen, args.backend, unknown))


HELP_EPILOG = """
  scripts/devserver.py                        # Default ports
  scripts/devserver.py -l 3000                # Vite on localhost:3000
  scripts/devserver.py -l :3000 --backend 8080  # Vite on *:3000, backend on :8080

  Additional arguments are passed to the cista backend command.

  JS_RUNTIME environment variable can be used to select the JS runtime
"""


if __name__ == "__main__":
    main()
