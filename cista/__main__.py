import os
import sys
from pathlib import Path

from docopt import docopt

import cista
from cista import app, config, droppy, serve, server80
from cista.util import pwgen

del app, server80.app  # Only import needed, for Sanic multiprocessing


def create_banner():
    """Create a framed banner with the Cista version."""
    title = f"Cista {cista.__version__}"
    subtitle = "A file storage for the web"
    width = max(len(title), len(subtitle)) + 4

    return f"""\
╭{"─" * width}╮
│{title:^{width}}│
│{subtitle:^{width}}│
╰{"─" * width}╯
"""


banner = create_banner()

doc = """\
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

Listen address and path are preserved in config,
and only config dir and dev mode need to be specified on subsequent runs.

User management:
  --user NAME       Create or modify user
  --privileged      Give the user full admin rights
  --password        Reset password

Environment:
  PASKIA_BACKEND_URL   Paskia single sign-on (e.g. http://localhost:4401)
                       https://git.zi.fi/leovasanko/paskia
"""

first_time_help = """\
No config file found! Get started with:
  cista --user yourname --privileged     # If you want user accounts
  cista -l :8000 /path/to/files          # Run the server on localhost:8000

See cista --help for other options!
"""


def main():
    # Dev mode doesn't catch exceptions
    if "--dev" in sys.argv:
        return _main()
    # Normal mode keeps it quiet
    try:
        return _main()
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1


def _main():
    # The banner printing differs by mode, and needs to be done before docopt() printing its messages
    if any(arg in sys.argv for arg in ("--help", "-h")):
        sys.stdout.write(banner)
    elif "--version" in sys.argv:
        sys.stdout.write(f"cista {cista.__version__}\n")
        return 0
    else:
        sys.stderr.write(banner)
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
    import_droppy = args["--import-droppy"]
    necessary_opts = exists or import_droppy or path
    if not necessary_opts:
        # Maybe run without arguments
        sys.stderr.write(first_time_help)
        return 1
    settings = {}
    if import_droppy:
        if exists:
            raise ValueError(
                f"Importing Droppy: First remove the existing configuration:\n  rm {config.conffile}",
            )
        settings = droppy.readconf()
        # Droppy's public flag is kept as-is (same name in our config)
    if path:
        settings["path"] = path
    elif not exists:
        settings["path"] = Path.home() / "Downloads"
    if listen:
        settings["listen"] = listen
    elif not exists:
        settings["listen"] = ":8000"
    operation = config.update_config(settings)
    sys.stderr.write(f"Config {operation}: {config.conffile}\n")
    # Prepare to serve
    unix = None
    url, _ = serve.parse_listen(config.config.listen)
    if not config.config.path.is_dir():
        raise ValueError(f"No such directory: {config.config.path}")
    extra = f" ({unix})" if unix else ""
    dev = args["--dev"]
    if dev:
        extra += " (dev mode)"
    sys.stderr.write(f"Serving {config.config.path} at {url}{extra}\n")
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
        sys.stderr.write(f"Config {operation}: {config.conffile}\n\n")

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
    sys.stderr.write(f"{info}\n")
    if res == "read":
        sys.stderr.write("  No changes\n")

    if operation == "created":
        sys.stderr.write(
            "Now you can run the server:\n  cista    # defaults set: -l :8000 ~/Downloads\n"
        )


if __name__ == "__main__":
    sys.exit(main())
