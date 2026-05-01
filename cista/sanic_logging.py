"""Custom access logging middleware for Sanic."""

import logging
import sys
import unicodedata
from ipaddress import IPv6Address

logger = logging.getLogger("cista.access")

_RESET = "\033[0m"
_STATUS_INFO = "\033[32m"  # 1xx (green)
_STATUS_OK = "\033[1;92m"  # 2xx (bright green)
_STATUS_REDIRECT = "\033[32m"  # 3xx (green)
_STATUS_CLIENT_ERR = "\033[0;31m"  # 4xx (red)
_STATUS_SERVER_ERR = "\033[1;91m"  # 5xx (bold bright red)
_METHOD_READ = "\033[0;34m"  # GET, HEAD, OPTIONS (blue)
_METHOD_WRITE = "\033[1;94m"  # POST, PUT, DELETE, PATCH (bold bright blue)
_HOST = "\033[38;5;242m"  # hostname (dark grey)
_PATH = "\033[38;5;250m"  # path (light grey)
_TIMING = "\033[38;5;242m"  # timing (dark grey)
_WS_OPEN = "\033[1;93m"  # WebSocket connect (bold bright yellow)
_WS_CLOSE = "\033[33m"  # WebSocket disconnect (yellow)
_WS_STATUS = "\033[38;5;250m"  # WebSocket close status (normal white)


def format_ipv6_network(ip: str) -> str:
    """Format IPv6 address to show only network part (first 64 bits)."""
    try:
        ip = ip.strip("[]")
        if "%" in ip:
            ip = ip.split("%")[0]
        addr = IPv6Address(ip)
        if addr.is_loopback:
            return "::1"
        if addr.is_unspecified:
            return "::"
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        if addr.is_link_local:
            return str(addr)
        network_int = int(addr) >> 64
        groups = []
        for _ in range(4):
            groups.insert(0, format(network_int & 0xFFFF, "x"))
            network_int >>= 16
        result = ":".join(groups) + "::"
        return str(IPv6Address(result + "0")).removesuffix("::")
    except Exception:
        return ip


def format_client_ip(ip: str) -> str:
    """Format client IP, compressing IPv6 to network part only."""
    if not ip or ip == "-":
        return "-"
    stripped = ip.strip("[]")
    if ":" in stripped:
        return format_ipv6_network(stripped)
    return stripped


def status_color(status: int) -> str:
    if status < 200:
        return _STATUS_INFO
    if status < 300:
        return _STATUS_OK
    if status < 400:
        return _STATUS_REDIRECT
    if status < 500:
        return _STATUS_CLIENT_ERR
    return _STATUS_SERVER_ERR


def method_color(method: str) -> str:
    if method in ("GET", "HEAD", "OPTIONS"):
        return _METHOD_READ
    return _METHOD_WRITE


def format_duration_ms(duration_ms: float) -> str:
    rounded_ms = round(duration_ms)
    if rounded_ms < 2000:
        return f"{rounded_ms}ms"
    total_s = round(duration_ms / 1000)
    if total_s < 60:
        return f"{total_s}s"
    if total_s <= 3600:
        minutes, seconds = divmod(total_s, 60)
        return f"{minutes}m{seconds}s"
    hours, remainder = divmod(total_s, 3600)
    minutes = round(remainder / 60)
    if minutes == 60:
        hours += 1
        minutes = 0
    return f"{hours}h{minutes}m"


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def _format_left(label: str) -> str:
    return label[:19].ljust(19)


def _format_method_label(label: str, *, color: str | None = None) -> str:
    color_value = _METHOD_WRITE if color is None else color
    padding = max(0, 7 - _display_width(label))
    return f"{color_value}{label}{' ' * padding}{_RESET}"


def format_access_log(
    client: str,
    status: int,
    method: str,
    host: str,
    path: str,
    duration_ms: float,
    extra: str | None = None,
) -> str:
    ip = _format_left(format_client_ip(client))
    status_str = f"{status_color(status)}{str(status).rjust(3)}{_RESET}"
    method_str = _format_method_label(method, color=method_color(method))
    host_str = f"{_HOST}{host}{_RESET}"
    path_str = f"{_PATH}{path}{_RESET}"
    timing_str = f"{_TIMING}{format_duration_ms(duration_ms)}{_RESET}"
    extra_str = f" {_TIMING}{extra}{_RESET}" if extra else ""
    return (
        f"{ip} {status_str} {method_str} {host_str}{path_str}{extra_str} {timing_str}"
    )


_ws_counter = 1


def _next_ws_id() -> int:
    global _ws_counter
    ws_id = _ws_counter
    _ws_counter += 1
    return ws_id


def _format_ws_id(ws_id: int, *, bright: bool = False) -> str:
    value = str(ws_id) if ws_id >= 100 else f"{ws_id:02d}"
    color = _WS_OPEN if bright else _WS_CLOSE
    return f"{color}{value.rjust(3)}{_RESET}"


def log_ws_open(request, extra: str | None = None) -> int:
    """Log WebSocket connection open. Returns connection ID for use in log_ws_close."""
    ws_id = _next_ws_id()

    client = request.client_ip or "-"
    host = request.host or "-"
    path = request.path
    origin = request.headers.get("origin")

    ip = _format_left(format_client_ip(client))
    id_str = _format_ws_id(ws_id, bright=True)

    origin_host = origin.split("://", 1)[-1] if origin else None
    show_origin = origin_host and origin_host != host

    method_str = _format_method_label("🔌", color=_WS_OPEN)
    host_str = f"{_HOST}{host}{_RESET}"
    path_str = f"{_PATH}{path}{_RESET}"
    origin_str = f" {_RESET}from {_HOST}{origin_host}{_RESET}" if show_origin else ""
    extra_str = f" {_TIMING}{extra}{_RESET}" if extra else ""

    logger.info(
        "%s %s %s %s%s%s",
        ip,
        id_str,
        method_str,
        host_str,
        path_str,
        origin_str + extra_str,
    )
    return ws_id


WS_CLOSE_CODES = {
    1000: "ok",
    1001: "going away",
    1002: "protocol error",
    1003: "unsupported",
    1005: "no status",
    1006: "abnormal",
    1007: "invalid data",
    1008: "policy violation",
    1009: "too large",
    1010: "extension required",
    1011: "server error",
    1012: "restarting",
    1013: "try again",
    1014: "bad gateway",
    1015: "tls error",
}


def log_ws_close(
    ws_id: int, close_code: int | None, duration: float, extra: str | None = None
) -> None:
    """Log WebSocket connection close with duration and status."""
    id_str = _format_ws_id(ws_id)
    timing = format_duration_ms(duration * 1000)

    if close_code is None:
        code = "----"
        status = "unknown"
    else:
        code = str(close_code)
        status = WS_CLOSE_CODES.get(close_code, f"code {close_code}")

    method_str = _format_method_label("closed", color=_TIMING)
    status_str = f"{_WS_STATUS}{code} {status}{_RESET}"
    timing_str = f"{_TIMING}{timing}{_RESET}"
    extra_str = f" {_TIMING}{extra}{_RESET}" if extra else ""

    logger.info(
        "%s %s %s %s %s%s",
        " " * 19,
        id_str,
        method_str,
        status_str,
        timing_str,
        extra_str,
    )


def configure_access_logging() -> None:
    """Configure the cista.access logger to output to stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_LEVEL_EMOJI = {
    logging.DEBUG: "🔍",
    logging.INFO: "i",
    logging.WARNING: "⚠️",
    logging.ERROR: "🛑",
    logging.CRITICAL: "🛑",
}


class _EmojiFormatter(logging.Formatter):
    """Compact formatter: emoji + message, no timestamp/level text/logger name."""

    def format(self, record: logging.LogRecord) -> str:
        emoji = _LEVEL_EMOJI.get(record.levelno, "▪️")
        sep = "  " if record.levelno in (logging.INFO, logging.WARNING) else " "
        msg = f"{emoji}{sep}{record.getMessage()}"
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                msg = msg + "\n" + record.exc_text
        if record.stack_info:
            msg = msg + "\n" + record.stack_info
        return msg


def configure_main_logging() -> None:
    """Replace Sanic's verbose 'Main yyyy-mm-dd INFO:' prefix with emoji-only format.

    Patches LOGGING_CONFIG_DEFAULTS so the formatter survives every dictConfig
    call Sanic makes during serve_single() / serve().
    """
    from sanic.log import LOGGING_CONFIG_DEFAULTS

    LOGGING_CONFIG_DEFAULTS["formatters"]["generic"] = {
        "class": "cista.sanic_logging._EmojiFormatter",
    }
    # Also reformat any handlers already attached (covers the initial Sanic() call)
    for name in ("sanic.root", "sanic.error", "sanic.server", "sanic.websockets"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(_EmojiFormatter())
