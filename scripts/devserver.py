#!/usr/bin/env -S uv run
"""Run Vite development server for frontend and Cista backend with auto-reload.

Usage:
    uv run scripts/devserver.py [-l <listen>]

Options:
    -l LISTEN   Listen address for backend (default: from config, or :8000)

Environment:
    JS_RUNTIME  Path or name of JS runtime to use (deno, npm/node or bun).
"""

import asyncio
import contextlib
import os
import sys
from pathlib import Path
from sys import stderr

import httpx

from cista import config
from cista.serve import parse_listen

exec((Path(__file__).parent / "fastapi-vue/util.py").read_text("UTF-8"))  # noqa: S102

DEFAULT_VITE_PORT = 5173
FRONTEND_PATH = Path(__file__).parent.parent / "frontend"

BUN_BUG = """\
┃ ⚠️  Bun cannot correctly proxy API requests to the backend.
┃ Bug report: https://github.com/oven-sh/bun/issues/9882
┃
┃ Consider using deno or npm instead for development.
"""


def resolve_frontend_tools(vite_port: int) -> tuple[list[str], list[str], str]:
    """Resolve frontend install and dev commands.

    Returns (install_cmd, dev_cmd, tool_name).
    Raises SystemExit if tools are not available.
    """
    if not (FRONTEND_PATH / "package.json").exists():
        stderr.write(f"┃ ⚠️  Frontend source not found at {FRONTEND_PATH}\n")
        raise SystemExit(1)

    install_cmd, build_cmd = find_build_tool()  # noqa # type: ignore
    dev_cmd, name = find_dev_tool()  # noqa # type: ignore
    if dev_cmd is None:
        if not os.environ.get("JS_RUNTIME"):
            stderr.write("┃ ⚠️  deno, npm or bun needed to run the frontend server.\n")
        raise SystemExit(1)

    dev_cmd = [*dev_cmd, "--clearScreen=false", f"--port={vite_port}"]

    if name == "bun":
        stderr.write(BUN_BUG)

    return install_cmd, dev_cmd, name


async def wait_for_backend(host: str, port: int):
    """Wait for the backend to be ready by polling the health endpoint."""
    max_attempts = 50
    url = f"http://{host}:{port}"

    async with httpx.AsyncClient() as client:
        for attempt in range(max_attempts):
            try:
                await client.get(url, timeout=1.0)
                stderr.write("✓ Backend ready!\n")
                return True
            except httpx.RequestError:
                if attempt == max_attempts - 1:
                    stderr.write("┃ ⚠️  Backend didn't start in time\n")
                    return False
                await asyncio.sleep(0.1)
    return False


async def _terminate_process(proc: asyncio.subprocess.Process, name: str) -> None:
    """Gracefully terminate a subprocess."""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            return
        await proc.wait()


async def run_devserver(backend_port: int, cista_args: list[str]) -> None:
    """Run the development server with install, backend, and frontend."""
    vite_port = DEFAULT_VITE_PORT
    install_cmd, dev_cmd, tool_name = resolve_frontend_tools(vite_port)

    # Tell the backend where the Vite dev server is (not used yet)
    os.environ["CISTA_DEV_FRONTEND_URL"] = f"http://localhost:{vite_port}"

    backend_cmd = ["cista", "--dev", *cista_args]

    cwd = str(Path(__file__).parent.parent)
    frontend_cwd = str(FRONTEND_PATH)

    backend_proc: asyncio.subprocess.Process | None = None
    install_proc: asyncio.subprocess.Process | None = None
    frontend_proc: asyncio.subprocess.Process | None = None

    try:
        # Start install (concurrent with backend)
        stderr.write(f">>> {tool_name} {' '.join(install_cmd[1:])}\n")
        install_proc = await asyncio.create_subprocess_exec(
            *install_cmd, cwd=frontend_cwd
        )

        await asyncio.sleep(0.1)

        # Start backend (concurrent with install)
        stderr.write(f">>> {' '.join(backend_cmd)}\n")
        backend_proc = await asyncio.create_subprocess_exec(*backend_cmd, cwd=cwd)

        # Wait for install to complete and backend to be ready
        install_task = asyncio.create_task(install_proc.wait(), name="install")
        backend_ready_task = asyncio.create_task(
            wait_for_backend("localhost", backend_port), name="backend_ready"
        )

        done, pending = await asyncio.wait(
            {install_task, backend_ready_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in done:
            if task.get_name() == "install":
                if task.result() != 0:
                    stderr.write("┃ ⚠️  Install failed\n")
                    raise SystemExit(1)
            elif task.get_name() == "backend_ready" and not task.result():
                raise SystemExit(1)

        if pending:
            done2, _ = await asyncio.wait(pending)
            for task in done2:
                if task.get_name() == "install":
                    if task.result() != 0:
                        stderr.write("┃ ⚠️  Install failed\n")
                        raise SystemExit(1)
                elif task.get_name() == "backend_ready" and not task.result():
                    raise SystemExit(1)

        install_proc = None

        # Start Vite dev server
        stderr.write(f">>> {tool_name} {' '.join(dev_cmd[1:])}\n")
        frontend_proc = await asyncio.create_subprocess_exec(*dev_cmd, cwd=frontend_cwd)

        # Wait for either process to exit
        done, pending = await asyncio.wait(
            {
                asyncio.create_task(backend_proc.wait(), name="backend"),
                asyncio.create_task(frontend_proc.wait(), name="frontend"),
            },
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in done:
            t.result()
        for t in pending:
            t.cancel()

    except asyncio.CancelledError:
        stderr.write("\n✓ Shutting down...\n")
    finally:
        if frontend_proc is not None:
            await _terminate_process(frontend_proc, "frontend")
        if install_proc is not None:
            await _terminate_process(install_proc, "install")
        if backend_proc is not None:
            await _terminate_process(backend_proc, "backend")


def main():
    # Pass all arguments to cista, parse -l to determine backend port
    cista_args = sys.argv[1:]
    listen_arg = None
    if "-l" in cista_args:
        idx = cista_args.index("-l")
        if idx + 1 < len(cista_args):
            listen_arg = cista_args[idx + 1]

    # Load config to get the backend port
    config.load_config()
    listen = listen_arg or config.config.listen or ":8000"
    _, opts = parse_listen(listen)
    backend_port = opts.get("port", 8000)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_devserver(backend_port, cista_args))


if __name__ == "__main__":
    main()
