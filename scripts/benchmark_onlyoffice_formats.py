#!/usr/bin/env python3
"""Benchmark OnlyOffice output formats for office document preview.

Compares:
1. BMP  → AVIF (via pyvips)
2. PNG  → AVIF (via pyvips)
3. PNG  only (no AVIF compression)

Usage:
    uv run python scripts/benchmark_onlyoffice_formats.py
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from time import perf_counter
from urllib.parse import quote

import pyvips

os.environ.setdefault("DOTNET_SYSTEM_GLOBALIZATION_INVARIANT", "1")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ONLYOFFICE_URL = os.environ.get("ONLYOFFICE_URL", "http://localhost:8080")
CALLBACK_HOST = os.environ.get("ONLYOFFICE_CALLBACK_HOST", "")

AVIF_QUALITY = 60
AVIF_MAXSIZE = 1024

# Directories to scan
SCAN_DIRS = [
    Path("/mnt/c/Users/User/Downloads/DocsMisc"),
    Path(
        "/mnt/c/Users/User/Downloads/Lattialämmityksen säätöarvot As Oy Helsingin Pulteri D ja E.etc"
    ),
    Path("/mnt/c/Users/User/Downloads/As. Oy Aidasmäentie 16-18 teholaskenta.etc"),
]

OFFICE_EXTS = {
    ".doc",
    ".dot",
    ".docx",
    ".docm",
    ".dotx",
    ".dotm",
    ".rtf",
    ".odt",
    ".ott",
    ".txt",
    ".md",
    ".mhtml",
    ".mht",
    ".html",
    ".htm",
    ".xml",
    ".wps",
    ".wri",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlsb",
    ".xltx",
    ".xltm",
    ".ods",
    ".ots",
    ".csv",
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".pot",
    ".potx",
    ".odp",
    ".otp",
}

# ---------------------------------------------------------------------------
# OnlyOffice client (inline to avoid import overhead)
# ---------------------------------------------------------------------------


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args) -> None:
        pass


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))  # noqa: S104
        return s.getsockname()[1]


def _get_callback_host() -> str:
    if CALLBACK_HOST:
        return CALLBACK_HOST
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
                return parts[1].split("/")[0]
    except Exception:
        return "127.0.0.1"


def _serve_file_temporarily(file_path: Path):
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


def onlyoffice_convert(
    file_path: Path, output_type: str, timeout: float = 60.0
) -> bytes:
    oo_url = ONLYOFFICE_URL.rstrip("/")
    convert_url = f"{oo_url}/ConvertService.ashx"
    doc_url, httpd = _serve_file_temporarily(file_path)
    try:
        suffix = file_path.suffix.lstrip(".").lower()
        payload = {
            "async": False,
            "filetype": suffix,
            "key": f"bench_{file_path.stat().st_mtime_ns}_{output_type}",
            "outputtype": output_type,
            "title": file_path.name,
            "url": doc_url,
        }
        req = urllib.request.Request(  # noqa: S310
            convert_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read()
        text = body.decode("utf-8", errors="replace")
        if "<Error>" in text:
            code = text.split("<Error>")[1].split("</Error>")[0]
            raise RuntimeError(f"OnlyOffice error {code}")
        file_url = text.split("<FileUrl>")[1].split("</FileUrl>")[0]
        file_url = file_url.replace("&amp;", "&")
        with urllib.request.urlopen(file_url, timeout=timeout) as img_resp:  # noqa: S310
            return img_resp.read()
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------


@dataclass
class Result:
    name: str
    ext: str
    oo_time: float
    avif_time: float = 0.0
    raw_size: int = 0
    final_size: int = 0
    error: str = ""


def avif_from_buffer(
    img_bytes: bytes, quality: int = AVIF_QUALITY, maxsize: int = AVIF_MAXSIZE
) -> tuple[float, bytes]:
    t0 = perf_counter()
    img = pyvips.Image.new_from_buffer(img_bytes, "")
    scale = min(maxsize / img.width, maxsize / img.height, 1.0)
    if scale < 1.0:
        img = img.resize(scale)
    buf = img.write_to_buffer(".avif", Q=quality, effort=0, strip=True)
    t1 = perf_counter()
    return t1 - t0, buf


def benchmark_file(path: Path) -> list[Result]:
    results: list[Result] = []

    # 1. BMP → AVIF
    try:
        t0 = perf_counter()
        bmp = onlyoffice_convert(path, "bmp")
        t1 = perf_counter()
        avif_t, avif_buf = avif_from_buffer(bmp)
        results.append(
            Result(
                name=path.name,
                ext=path.suffix.lower(),
                oo_time=t1 - t0,
                avif_time=avif_t,
                raw_size=len(bmp),
                final_size=len(avif_buf),
            )
        )
    except Exception as e:
        results.append(
            Result(
                name=path.name, ext=path.suffix.lower(), oo_time=0, error=f"bmp: {e}"
            )
        )

    # 2. PNG → AVIF
    try:
        t0 = perf_counter()
        png = onlyoffice_convert(path, "png")
        t1 = perf_counter()
        avif_t, avif_buf = avif_from_buffer(png)
        results.append(
            Result(
                name=path.name,
                ext=path.suffix.lower(),
                oo_time=t1 - t0,
                avif_time=avif_t,
                raw_size=len(png),
                final_size=len(avif_buf),
            )
        )
    except Exception as e:
        results.append(
            Result(
                name=path.name, ext=path.suffix.lower(), oo_time=0, error=f"png: {e}"
            )
        )

    # 3. PNG only
    try:
        t0 = perf_counter()
        png = onlyoffice_convert(path, "png")
        t1 = perf_counter()
        results.append(
            Result(
                name=path.name,
                ext=path.suffix.lower(),
                oo_time=t1 - t0,
                avif_time=0.0,
                raw_size=len(png),
                final_size=len(png),
            )
        )
    except Exception as e:
        results.append(
            Result(
                name=path.name,
                ext=path.suffix.lower(),
                oo_time=0,
                error=f"png-only: {e}",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    docs: list[Path] = []
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        docs.extend(p for p in d.iterdir() if p.suffix.lower() in OFFICE_EXTS)
    docs.sort()

    total = len(docs)
    print(f"Benchmarking {total} documents against OnlyOffice ({ONLYOFFICE_URL})...\n")

    all_results: dict[str, list[Result]] = {
        "bmp→avif": [],
        "png→avif": [],
        "png-only": [],
    }

    for i, doc in enumerate(docs, 1):
        print(f"[{i}/{total}] {doc.name} ...", end=" ", flush=True)
        res = benchmark_file(doc)
        for r, key in zip(res, all_results.keys(), strict=False):
            all_results[key].append(r)
            if r.error:
                print(f"{key} ERR", end=" ")
            else:
                print(f"{key} OK", end=" ")
        print()

    # Summary
    print("\n" + "=" * 100)
    print(
        f"{'Format':<12} {'Count':>6} {'OO ms':>10} {'AVIF ms':>10} {'Total ms':>10} {'Raw KB':>10} {'Final KB':>10} {'Ratio':>8}"
    )
    print("-" * 100)

    for key, results in all_results.items():
        ok = [r for r in results if not r.error]
        errs = [r for r in results if r.error]
        if not ok:
            continue
        avg_oo = sum(r.oo_time for r in ok) / len(ok) * 1000
        avg_avif = sum(r.avif_time for r in ok) / len(ok) * 1000
        avg_total = avg_oo + avg_avif
        avg_raw = sum(r.raw_size for r in ok) / len(ok) / 1024
        avg_final = sum(r.final_size for r in ok) / len(ok) / 1024
        ratio = avg_raw / avg_final if avg_final else 0
        print(
            f"{key:<12} {len(ok):>6} {avg_oo:>10.1f} {avg_avif:>10.1f} {avg_total:>10.1f} {avg_raw:>10.1f} {avg_final:>10.1f} {ratio:>8.1f}x"
        )
        for r in errs[:3]:
            print(f"  ERROR: {r.name}: {r.error}")

    # Per-extension breakdown
    print("\n" + "=" * 100)
    print("Per-extension summary (png→avif)")
    print(
        f"{'Ext':<8} {'Count':>6} {'OO ms':>10} {'AVIF ms':>10} {'Total ms':>10} {'Raw KB':>10} {'Final KB':>10}"
    )
    print("-" * 100)

    by_ext: dict[str, list[Result]] = defaultdict(list)
    for r in all_results["png→avif"]:
        by_ext[r.ext].append(r)

    for ext in sorted(by_ext.keys()):
        results = [r for r in by_ext[ext] if not r.error]
        if not results:
            continue
        avg_oo = sum(r.oo_time for r in results) / len(results) * 1000
        avg_avif = sum(r.avif_time for r in results) / len(results) * 1000
        avg_raw = sum(r.raw_size for r in results) / len(results) / 1024
        avg_final = sum(r.final_size for r in results) / len(results) / 1024
        print(
            f"{ext:<8} {len(results):>6} {avg_oo:>10.1f} {avg_avif:>10.1f} {avg_oo + avg_avif:>10.1f} {avg_raw:>10.1f} {avg_final:>10.1f}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
