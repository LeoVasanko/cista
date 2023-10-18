import re
import sys
from pathlib import Path

from docopt import docopt

from . import app, config, droppy, serve
from ._version import version

app   # Needed for Sanic multiprocessing

doc = f"""Cista {version} - A file storage for the web.

Usage:
  cista [-c <confdir>] [-l <host>] [--import-droppy] [--dev] [<path>]

Options:
  -c CONFDIR        Custom config directory
  -l LISTEN-ADDR    Listen on
                       :8000 (localhost port, plain http)
                       <addr>:3000 (bind another address, port)
                       /path/to/unix.sock (unix socket)
                       example.com (run on 80 and 443 with LetsEncrypt)
  --import-droppy   Import Droppy config from ~/.droppy/config
  --dev             Developer mode (reloads, friendlier crashes, more logs)

Listen address, path and imported options are preserved in config, and only
custom config dir and dev mode need to be specified on subsequent runs.
"""

def main():
    # Dev mode doesn't catch exceptions
    if "--dev" in sys.argv:
        return _main()
    # Normal mode keeps it quiet
    try:
        return _main()
    except Exception as e:
        print("Error:", e)
        return 1

def _main():
    args = docopt(doc)
    listen = args["-l"]
    # Validate arguments first
    if args["<path>"]:
        path = Path(args["<path>"])
        if not path.is_dir():
            raise ValueError(f"No such directory: {path}")
    else:
        path = None
    if args["-c"]:
        # Custom config directory
        confdir = Path(args["-c"]).resolve()
        if confdir.exists() and not confdir.is_dir():
            if confdir.name != config.conffile.name:
                raise ValueError("Config path is not a directory")
            # Accidentally pointed to the cista.toml, use parent
            confdir = confdir.parent
        config.conffile = config.conffile.with_parent(confdir)
    exists = config.conffile.exists()
    import_droppy = args["--import-droppy"]
    necessary_opts = exists or import_droppy or path and listen
    if not necessary_opts:
        # Maybe run without arguments
        print(doc)
        print("No config file found! Get started with:\n  cista -l :8000 /path/to/files, or\n  cista -l example.com --import-droppy  # Uses Droppy files\n")
        return 1
    settings = {}
    if import_droppy:
        if exists:
            raise ValueError(f"Importing Droppy: First remove the existing configuration:\n  rm {config.conffile}")
        settings = droppy.readconf()
    if path: settings["path"] = path
    if listen: settings["listen"] = listen
    operation = config.update_config(settings)
    print(f"Config {operation}: {config.conffile}")
    # Prepare to serve
    domain = unix = port = None
    url, _ = serve.parse_listen(config.config.listen)
    if not config.config.path.is_dir():
        raise ValueError(f"No such directory: {config.config.path}")
    extra = f" ({unix})" if unix else ""
    dev = args["--dev"]
    if dev:
        extra += " (dev mode)"
    print(f"Serving {config.config.path} at {url}{extra}")
    # Run the server
    serve.run(dev=dev)

if __name__ == "__main__":
    sys.exit(main())
