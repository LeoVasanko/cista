#!/usr/bin/env -S uv run
"""Run Vite development server for frontend and Cista backend with auto-reload.

Usage:
    uv run scripts/devserver.py [frontend] [--backend backend]

Options:
    frontend    Vite frontend endpoint (default: localhost:5173)
    --backend   Cista backend endpoint (default: from config, or :8000)

Environment:
    JS_RUNTIME  Path or name of JS runtime to use (deno, npm/node or bun).
"""

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

# Import devutil from scripts/fastapi-vue (not a package, so we adjust sys.path)
sys.path.insert(0, str(Path(__file__).with_name("fastapi-vue")))
from devutil import ProcessGroup, logger, ready, setup_vite  # type: ignore

from cista import config
from cista.serve import parse_listen

DEFAULT_BACKEND_PORT = 8000


def setup_sanic_backend(listen: str | None) -> tuple[str, list[str]]:
    """Parse backend listen address and build cista dev command.

    Returns (url, cmd).
    """
    config.load_config()
    listen = listen or config.config.listen or f":{DEFAULT_BACKEND_PORT}"
    url, opts = parse_listen(listen)
    port = opts.get("port", DEFAULT_BACKEND_PORT)
    host = opts.get("host", "localhost") or "localhost"

    cmd = ["cista", "--dev", "-l", listen]
    return f"http://{host}:{port}", cmd


async def run_devserver(frontend: str | None, backend: str | None) -> None:
    reporoot = Path(__file__).parent.parent
    front = reporoot / "frontend"
    if not (front / "package.json").exists():
        logger.warning("Frontend source not found at %s", front)
        raise SystemExit(1)

    frontend_url, npm_install, vite = setup_vite(frontend or "")
    backend_url, sanic_cmd = setup_sanic_backend(backend)

    # Tell vite where to proxy API requests
    os.environ["FASTAPI_VUE_BACKEND_URL"] = backend_url

    async with ProcessGroup() as pg:
        install_proc = await pg.spawn(*npm_install, cwd=str(front))
        await asyncio.sleep(0.2)  # reduce message overlap
        await pg.spawn(*sanic_cmd, cwd=str(reporoot))

        # Wait for both install and backend to be ready
        async with asyncio.TaskGroup() as tg:
            tg.create_task(pg.wait(install_proc))
            tg.create_task(ready(backend_url, path="/api/health?from=devserver.py"))

        # Start Vite dev server (ProcessGroup waits for any exit, then terminates others)
        await pg.spawn(*vite, cwd=str(front))


def main():
    parser = argparse.ArgumentParser(
        description="Run Vite and Cista (Sanic) development servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )
    parser.add_argument(
        "frontend",
        nargs="?",
        metavar="host:port",
        help="Vite frontend endpoint (default: localhost:5173)",
    )
    parser.add_argument(
        "--backend",
        "-l",
        metavar="host:port",
        help="Cista backend endpoint (default: from config, or :8000)",
    )
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_devserver(args.frontend, args.backend))


HELP_EPILOG = """
  scripts/devserver.py                       # Default ports
  scripts/devserver.py 3000                  # Vite on localhost:3000
  scripts/devserver.py :3000 --backend 8080  # Vite on *:3000, backend on :8080

  JS_RUNTIME environment variable can be used to select the JS runtime
"""


if __name__ == "__main__":
    main()
