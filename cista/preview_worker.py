"""Preview generation worker subprocess.

Two modes are supported:
1) Legacy one-shot mode: argv has path/quality/maxsize/maxzoom.
2) Long-lived mode: read framed requests from stdin and write framed responses.

Framed request format (stdin):
    (uint32 json size)(uint32 data size)(json)(binary data)

Framed response format (stdout):
    (blake3(packet))(uint32 json size)(uint32 payload size)(json)(binary payload)
where packet = (uint32 json size)(uint32 payload size)(json)(binary payload).
"""

import contextlib
import io
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
    timings: list[float] | None = None
    error: str | None = None
    stderr: str | None = None


_enc = msgspec.json.Encoder()
_dec_req = msgspec.json.Decoder(PreviewRequest)


def _read_exactly(f, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def _read_request() -> tuple[PreviewRequest, bytes] | None:
    try:
        header = _read_exactly(sys.stdin.buffer, 8)
    except EOFError:
        return None
    json_size, data_size = struct.unpack("<II", header)
    meta_raw = _read_exactly(sys.stdin.buffer, json_size)
    data = b""
    if data_size:
        data = _read_exactly(sys.stdin.buffer, data_size)
    req = _dec_req.decode(meta_raw)
    return req, data


def _write_response(resp: PreviewResponse, payload: bytes) -> None:
    meta_bytes = _enc.encode(resp)
    packet = struct.pack("<II", len(meta_bytes), len(payload)) + meta_bytes + payload
    checksum = blake3(packet).digest()
    sys.stdout.buffer.write(checksum)
    sys.stdout.buffer.write(packet)
    sys.stdout.buffer.flush()


def _run_once() -> None:
    if len(sys.argv) != 5:
        sys.stderr.write(f"Usage: {sys.argv[0]} <path> <quality> <maxsize> <maxzoom>\n")
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
        result = _read_request()
        if result is None:
            return
        req, data = result
        stderr_capture = io.StringIO()
        handler = logging.StreamHandler(stderr_capture)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            with contextlib.redirect_stderr(stderr_capture):
                result, resp = dispatch(
                    Path(req.path), req.quality, req.maxsize, req.maxzoom, data
                )
            if not resp.ok:
                captured = stderr_capture.getvalue().strip()
                if captured:
                    resp = PreviewResponse(
                        ok=False,
                        backend=resp.backend,
                        error=resp.error,
                        stderr=captured,
                    )
            _write_response(resp, result or b"")
        except Exception as e:
            logging.exception("Preview worker error for %s", req.path)
            captured = stderr_capture.getvalue().strip()
            _write_response(
                PreviewResponse(ok=False, error=str(e), stderr=captured or None), b""
            )
        finally:
            root_logger.removeHandler(handler)
            handler.close()


def main() -> None:
    # Configure all log output to stderr before any imports that may emit logs.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        from cista import config

        config.load_config()
        logging.warning(
            "preview-worker config=%s master_secret=%s",
            config.conffile,
            config.config.secret,
        )
    except Exception:
        logging.exception("preview-worker failed to load config at startup")
    if len(sys.argv) > 1:
        _run_once()
        return
    # Eagerly import heavy modules before signalling readiness so the parent
    # does not hand us a request while we are still initialising.
    from cista.preview import dispatch  # noqa: F401

    sys.stdout.buffer.write(b"\x01")
    sys.stdout.buffer.flush()
    _run_loop()


if __name__ == "__main__":
    main()
