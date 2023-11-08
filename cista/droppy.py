from pathlib import Path

import msgspec


def readconf() -> dict:
    p = Path.home() / ".droppy/config"  # Hardcoded in Droppy
    cf = msgspec.json.decode((p / "config.json").read_bytes())
    db = msgspec.json.decode((p / "db.json").read_bytes())
    cf["path"] = p.parent / "files"
    cf["listen"] = _droppy_listeners(cf)
    return cf | db


def _droppy_listeners(cf):
    """Convert Droppy listeners to our format, for typical cases but not in full."""
    for listener in cf["listeners"]:
        try:
            if listener["protocol"] == "https":
                # TODO: Add support for TLS
                continue
            socket = listener.get("socket")
            if socket:
                if isinstance(socket, list):
                    socket = socket[0]
                return f"{socket}"
            port = listener["port"]
            if isinstance(port, list):
                port = port[0]
            host = listener["host"]
            if isinstance(host, list):
                host = host[0]
        except (KeyError, IndexError):
            continue
        else:
            if host in ("127.0.0.1", "::", "localhost"):
                return f":{port}"
            return f"{host}:{port}"

    # If none matched, fallback to Droppy default
    return "0.0.0.0:8989"
