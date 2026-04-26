"""OnlyOffice Document Server integration for office document preview.

Provides server-side conversion of office documents to PNG via the
OnlyOffice Document Server /ConvertService.ashx API. The resulting PNG
is passed through pyvips for AVIF compression.

Environment requirements:
    - OnlyOffice Document Server must be running and reachable.
    - If Document Server runs in Docker, the callback host IP must be
      reachable from the container (usually the docker bridge IP).
"""

import json
import os
import socket
import socketserver
import subprocess
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from time import perf_counter
from urllib.parse import quote

import jwt
from sanic.log import logger

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _get_onlyoffice_url() -> str:
    return os.environ.get("ONLYOFFICE_URL", "http://localhost:8080")


def _get_jwt_secret() -> str | None:
    return os.environ.get("ONLYOFFICE_JWT_SECRET") or None


def _get_callback_host() -> str:
    """Return the host IP that OnlyOffice (usually in Docker) can use to reach us."""
    if host := os.environ.get("ONLYOFFICE_CALLBACK_HOST"):
        return host
    # Try to auto-detect docker bridge IP
    try:
        result = subprocess.run(
            ["/sbin/ip", "-4", "addr", "show", "docker0"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        for line in result.stdout.splitlines():
            if "inet " in line:
                parts = line.strip().split()
                addr_part = parts[1]  # e.g. 172.17.0.1/16
                return addr_part.split("/")[0]
    except Exception:
        logger.debug("Failed to auto-detect docker bridge IP")
    return "127.0.0.1"


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """Return True if the configured OnlyOffice Document Server is reachable."""
    url = _get_onlyoffice_url()
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
            return resp.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Temporary HTTP server so OnlyOffice can download the file
# ---------------------------------------------------------------------------


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args) -> None:
        pass


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))  # noqa: S104
        return s.getsockname()[1]


def _serve_file_temporarily(file_path: Path):
    """Start a temporary HTTP server for *file_path* and return (url, server)."""
    directory = str(file_path.parent)
    filename = file_path.name
    port = _get_free_port()

    handler = partial(_QuietHandler, directory=directory)
    httpd = socketserver.TCPServer(("0.0.0.0", port), handler)  # noqa: S104
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    host = _get_callback_host()
    url = f"http://{host}:{port}/{quote(filename)}"
    return url, httpd


# ---------------------------------------------------------------------------
# OnlyOffice conversion client
# ---------------------------------------------------------------------------


def _build_jwt_token(payload: dict) -> str | None:
    secret = _get_jwt_secret()
    if not secret:
        return None
    return jwt.encode(payload, secret, algorithm="HS256")


def convert_to_png(file_path: Path, timeout: float = 30.0) -> bytes:
    """Convert *file_path* to PNG using OnlyOffice Document Server.

    Returns the PNG bytes. Raises RuntimeError on failure.
    """
    oo_url = _get_onlyoffice_url().rstrip("/")
    convert_url = f"{oo_url}/ConvertService.ashx"

    # Start temporary HTTP server so OnlyOffice can fetch the file
    doc_url, httpd = _serve_file_temporarily(file_path)
    try:
        suffix = file_path.suffix.lstrip(".").lower()
        payload = {
            "async": False,
            "filetype": suffix,
            "key": f"cista_{file_path.stat().st_mtime_ns}",
            "outputtype": "png",
            "title": file_path.name,
            "url": doc_url,
        }

        headers = {"Content-Type": "application/json"}
        token = _build_jwt_token(payload)
        if token:
            headers["Authorization"] = token

        req = urllib.request.Request(  # noqa: S310
            convert_url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )

        t_start = perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read()
        t_end = perf_counter()

        # Parse XML response
        text = body.decode("utf-8", errors="replace")
        if "<Error>" in text:
            code = "unknown"
            if "<Error>" in text and "</Error>" in text:
                code = text.split("<Error>")[1].split("</Error>")[0]
            raise RuntimeError(f"OnlyOffice conversion error: {code}")

        if "<FileUrl>" not in text:
            raise RuntimeError("OnlyOffice response did not contain FileUrl")

        file_url = text.split("<FileUrl>")[1].split("</FileUrl>")[0]
        file_url = file_url.replace("&amp;", "&")

        logger.debug("OnlyOffice converted in %.2fs: %s", t_end - t_start, file_url)

        # Download converted PNG
        with urllib.request.urlopen(file_url, timeout=timeout) as png_resp:  # noqa: S310
            return png_resp.read()
    finally:
        httpd.shutdown()
