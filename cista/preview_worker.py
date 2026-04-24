"""Preview generation worker subprocess.

Two modes are supported:
1) Legacy one-shot mode: argv has path/quality/maxsize/maxzoom.
2) Long-lived mode: read JSONL commands from stdin and write framed responses.

Framed response format:
    (blake3(packet))(uint32 json size)(uint32 payload size)(json)(binary payload)
where packet = (uint32 json size)(uint32 payload size)(json)(binary payload).
"""
import logging
import struct
import sys
from pathlib import Path

import msgspec
from blake3 import blake3


class PreviewRequest(msgspec.Struct, omit_defaults=True):
    path: str
    quality: int
    maxsize: int
    maxzoom: float


class PreviewResponse(msgspec.Struct, omit_defaults=True):
    ok: bool
    mime: str | None = None
    backend: str | None = None
    load_ms: float | None = None
    process_ms: float | None = None
    save_ms: float | None = None
    total_ms: float | None = None
    error: str | None = None


_enc = msgspec.json.Encoder()
_dec_req = msgspec.json.Decoder(PreviewRequest)


def _write_response(resp: PreviewResponse, payload: bytes) -> None:
    meta_bytes = _enc.encode(resp)
    packet = struct.pack("<II", len(meta_bytes), len(payload)) + meta_bytes + payload
    checksum = blake3(packet).digest()
    sys.stdout.buffer.write(checksum)
    sys.stdout.buffer.write(packet)
    sys.stdout.buffer.flush()


def _run_once() -> None:
    if len(sys.argv) != 5:
        sys.stderr.write(
            f"Usage: {sys.argv[0]} <path> <quality> <maxsize> <maxzoom>\n"
        )
        sys.exit(1)

    from cista.preview import dispatch

    path = Path(sys.argv[1])
    quality = int(sys.argv[2])
    maxsize = int(sys.argv[3])
    maxzoom = float(sys.argv[4])
    result, _ = dispatch(path, quality, maxsize, maxzoom)
    if result:
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()


def _run_loop() -> None:
    from cista.preview import dispatch

    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return
        try:
            req = _dec_req.decode(line)
            result, resp = dispatch(Path(req.path), req.quality, req.maxsize, req.maxzoom)
            _write_response(resp, result or b"")
        except Exception as e:
            _write_response(PreviewResponse(ok=False, error=str(e)), b"")


def main() -> None:
    # Configure all log output to stderr before any imports that may emit logs.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    if len(sys.argv) > 1:
        _run_once()
        return
    _run_loop()


if __name__ == "__main__":
    main()
