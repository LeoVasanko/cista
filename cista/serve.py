import os
import re
from pathlib import Path

from fastapi_vue.hostutil import parse_endpoint
from sanic import Sanic
from sanic.worker.loader import AppLoader

from cista import config, server80
from cista.app import app


def load_app() -> Sanic:
    """Return the app instance for spawned Sanic worker/reloader processes."""
    return app


def run(*, dev=False):
    """Run Sanic main process that spawns worker processes to serve HTTP requests."""
    _url, opts = parse_listen(config.config.listen)
    # Silence Sanic's warning about running in production rather than debug
    os.environ["SANIC_IGNORE_PRODUCTION_WARNING"] = "1"
    confdir = config.conffile.parent
    if opts.get("ssl"):
        # Run plain HTTP redirect/acme server on port 80
        server80.app.prepare(port=80, motd=False)
        domain = opts["host"]
        check_cert(confdir / domain, domain)
        opts["ssl"] = str(confdir / domain)  # type: ignore[assignment]
    app.prepare(
        **opts,
        motd=False,
        dev=dev,
        auto_reload=dev,
        access_log=False,
    )  # type: ignore[call-arg]
    if dev:
        Sanic.serve(app_loader=AppLoader(factory=load_app))
    else:
        Sanic.serve_single()


def check_cert(certdir, domain):
    _ = domain
    if (certdir / "privkey.pem").exist() and (certdir / "fullchain.pem").exists():
        return
    # Certificate provisioning is external; files must exist before startup.
    raise ValueError(
        f"TLS certificate files privkey.pem and fullchain.pem needed in {certdir}",
    )


def parse_listen(listen):
    # Domain name (e.g. example.com) -> HTTPS with LetsEncrypt
    if re.fullmatch(r"(\w+(-\w+)*\.)+\w{2,}", listen, re.UNICODE):
        return f"https://{listen}", {"host": listen, "port": 443, "ssl": True}

    # Use fastapi_vue's parse_endpoint for everything else
    endpoints = parse_endpoint(listen, default_port=8989)
    ep = endpoints[0]

    if "uds" in ep:
        unix = Path(ep["uds"]).resolve()
        if not unix.parent.exists():
            raise ValueError(
                f"Directory for unix socket does not exist: {unix.parent}/",
            )
        return "http://localhost", {"unix": unix.as_posix()}

    host, port = ep["host"], ep["port"]
    if len(endpoints) > 1:
        return f"http://localhost:{port}", {"host": host, "port": port}
    return f"http://{host}:{port}", {"host": host, "port": port}
