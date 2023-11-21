import os
import sys
from pathlib import Path

from docopt import docopt

import cista
from cista import app, config, droppy, serve, server80
from cista.util import pwgen

del app, server80.app  # Only import needed, for Sanic multiprocessing

doc = f"""Cista {cista.__version__} - A file storage for the web.

Usage:
  cista [-c <confdir>] [-l <host>] [--import-droppy] [--dev] [<path>]
  cista [-c <confdir>] --user <name> [--privileged] [--password]

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

User management:
  --user NAME       Create or modify user
  --privileged      Give the user full admin rights
  --password        Reset password
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
    if args["--user"]:
        return _user(args)
    listen = args["-l"]
    # Validate arguments first
    if args["<path>"]:
        path = Path(args["<path>"]).resolve()
        if not path.is_dir():
            raise ValueError(f"No such directory: {path}")
    else:
        path = None
    _confdir(args)
    exists = config.conffile.exists()
    print(config.conffile, exists)
    import_droppy = args["--import-droppy"]
    necessary_opts = exists or import_droppy or path
    if not necessary_opts:
        # Maybe run without arguments
        print(doc)
        print(
            "No config file found! Get started with one of:\n"
            "  cista --user yourname --privileged\n"
            "  cista --import-droppy\n"
            "  cista -l :8000 /path/to/files\n"
        )
        return 1
    settings = {}
    if import_droppy:
        if exists:
            raise ValueError(
                f"Importing Droppy: First remove the existing configuration:\n  rm {config.conffile}",
            )
        settings = droppy.readconf()
    if path:
        settings["path"] = path
    elif not exists:
        settings["path"] = Path.home() / "Downloads"
    if listen:
        settings["listen"] = listen
    elif not exists:
        settings["listen"] = ":8000"
    if not exists and not import_droppy:
        # We have no users, so make it public
        settings["public"] = True
    operation = config.update_config(settings)
    print(f"Config {operation}: {config.conffile}")
    # Prepare to serve
    unix = None
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
    return 0


def _confdir(args):
    if args["-c"]:
        # Custom config directory
        confdir = Path(args["-c"]).resolve()
        if confdir.exists() and not confdir.is_dir():
            if confdir.name != config.conffile.name:
                raise ValueError("Config path is not a directory")
            # Accidentally pointed to the db.toml, use parent
            confdir = confdir.parent
        os.environ["CISTA_HOME"] = confdir.as_posix()
    config.init_confdir()  # Uses environ if available


def _user(args):
    _confdir(args)
    if config.conffile.exists():
        config.load_config()
        operation = False
    else:
        # Defaults for new config when user is created
        operation = config.update_config(
            {
                "listen": ":8000",
                "path": Path.home() / "Downloads",
                "public": False,
            }
        )
        print(f"Config {operation}: {config.conffile}\n")

    name = args["--user"]
    if not name or not name.isidentifier():
        raise ValueError("Invalid username")
    u = config.config.users.get(name)
    info = f"User {name}" if u else f"New user {name}"
    changes = {}
    oldadmin = u and u.privileged
    if args["--privileged"]:
        changes["privileged"] = True
        info += " (already admin)" if oldadmin else " (made admin)"
    else:
        info += " (admin)" if oldadmin else ""
    if args["--password"] or not u:
        changes["password"] = pw = pwgen.generate()
        info += f"\n  Password: {pw}\n"
    res = config.update_user(name, changes)
    print(info)
    if res == "read":
        print("  No changes")

    if operation == "created":
        print(
            "Now you can run the server:\n  cista    # defaults set: -l :8000 ~/Downloads\n"
        )


if __name__ == "__main__":
    sys.exit(main())
