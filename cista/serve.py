import os
import re
from pathlib import Path

from sanic import Sanic

from cista import config, server80


def run(*, dev=False):
    """Run Sanic main process that spawns worker processes to serve HTTP requests."""
    from .app import app

    url, opts = parse_listen(config.config.listen)
    # Silence Sanic's warning about running in production rather than debug
    os.environ["SANIC_IGNORE_PRODUCTION_WARNING"] = "1"
    confdir = config.conffile.parent
    if opts.get("ssl"):
        # Run plain HTTP redirect/acme server on port 80
        server80.app.prepare(port=80, motd=False)
        domain = opts["host"]
        check_cert(confdir / domain, domain)
        opts["ssl"] = str(confdir / domain)  # type: ignore
    app.prepare(
        **opts,
        motd=False,
        dev=dev,
        auto_reload=dev,
        access_log=True,
    )  # type: ignore
    if dev:
        Sanic.serve()
    else:
        Sanic.serve_single()


def check_cert(certdir, domain):
    if (certdir / "privkey.pem").exist() and (certdir / "fullchain.pem").exists():
        return
    # TODO: Use certbot to fetch a cert
    raise ValueError(
        f"TLS certificate files privkey.pem and fullchain.pem needed in {certdir}",
    )


def parse_listen(listen):
    if listen.startswith("/"):
        unix = Path(listen).resolve()
        if not unix.parent.exists():
            raise ValueError(
                f"Directory for unix socket does not exist: {unix.parent}/",
            )
        return "http://localhost", {"unix": unix.as_posix()}
    if re.fullmatch(r"(\w+(-\w+)*\.)+\w{2,}", listen, re.UNICODE):
        return f"https://{listen}", {"host": listen, "port": 443, "ssl": True}
    try:
        addr, _port = listen.split(":", 1)
        port = int(_port)
    except Exception:
        raise ValueError(f"Invalid listen address: {listen}") from None
    return f"http://localhost:{port}", {"host": addr, "port": port}
