import os
import re
from pathlib import Path

from sanic import Sanic

from . import config


def run(dev=False):
    """Run Sanic main process that spawns worker processes to serve HTTP requests."""
    from .app import app
    url, opts = parse_listen(config.config.listen)
    # Silence Sanic's warning about running in production rather than debug
    os.environ["SANIC_IGNORE_PRODUCTION_WARNING"] = "1"
    if opts.get("ssl"):
        # Run plain HTTP redirect/acme server on port 80
        from . import httpredir
        httpredir.app.prepare(port=80, motd=False)
        domain = opts["host"]
        opts["ssl"] = str(config.conffile.parent / domain)
    app.prepare(**opts, motd=False, dev=dev, auto_reload=dev, access_log=True)
    Sanic.serve()

def parse_listen(listen):
    if listen.startswith("/"):
        unix = Path(listen).resolve()
        if not unix.parent.exists():
            raise ValueError(f"Directory for unix socket does not exist: {unix.parent}/")
        return "http://localhost", {"unix": unix}
    elif re.fullmatch(r"(\w+(-\w+)*\.)+\w{2,}", listen, re.UNICODE):
        return f"https://{listen}", {"host": listen, "port": 443, "ssl": True}
    else:
        try:
            addr, _port = listen.split(":", 1)
            port = int(_port)
        except Exception:
            raise ValueError(f"Invalid listen address: {listen}")
        return f"http://localhost:{port}", {"host": addr, "port": port}
