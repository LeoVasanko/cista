import os
import sys
from pathlib import Path

from docopt import docopt

import cista
from cista import app, config, droppy, onlyoffice, serve, server80
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


def create_startup_box(
    *, folder, url, unix=None, dev=False, paskia_url=None, public=False
):
    """Create a framed startup box with server information."""
    title = f"Cista {cista.__version__}"
    listen = unix if unix else url
    location = f"{folder} @ {listen}"
    lines = [title, location]
    # Auth line: Paskia <url> or Password, with optional Public suffix
    auth_line = f"Auth: Paskia {paskia_url}" if paskia_url else "Auth: Password"
    if public:
        auth_line += ", Public"
    lines.append(auth_line)
    if dev:
        lines.append("dev mode")

    # Calculate width based on content
    inner_width = max(len(line) for line in lines) + 2

    # Build the box
    box = [f"╭{'─' * inner_width}╮"]
    box.extend(f"│ {line:<{inner_width - 1}}│" for line in lines)
    box.append(f"╰{'─' * inner_width}╯")
    return "\n".join(box) + "\n"


banner = create_banner()

_default_confdir = (
    (Path(os.environ["XDG_CONFIG_HOME"]) / "cista").as_posix()
    if os.environ.get("XDG_CONFIG_HOME")
    else (Path.home() / ".config/cista").as_posix()
)

doc = f"""\
Usage:
  cista [-c <confdir>] [-l <host>] [--import-droppy] [--dev] [<path>]
  cista [-c <confdir>] --user <name> [--privileged] [--password]
  cista [-c <confdir>] --oosetup
  cista --version

Options:
  -c CONFDIR          Config directory [{_default_confdir}]
  -l, --listen ADDR   Listen on address (port, :port, /socket or domain for https)
  --import-droppy     Import Droppy config from ~/.droppy/config
  --dev               Developer mode (reloads, friendlier crashes, more logs)
  --user NAME         Create or modify a user account (when server is not running)
    --privileged        Grant admin rights
    --password          Reset password
  --oosetup           Build and run OnlyOffice in Docker for document previews

Environment:
  PASKIA_BACKEND_URL  Paskia single sign-on (e.g. http://localhost:4401)
                        https://git.zi.fi/leovasanko/paskia
    ONLYOFFICE_CISTA_URL, ONLYOFFICE_JWT_SECRET, ONLYOFFICE_CALLBACK_HOST (if needed)
"""

first_time_help = """\
No config file found! Get started with:
  cista --user yourname --privileged   # If you want user accounts
  cista -l :8989 /path/to/files        # Run the server on localhost:8989

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
    # Don't print banner yet for normal startup - we'll print the startup box later
    args = docopt(doc)
    if args["--user"]:
        return _user(args)
    if args["--oosetup"]:
        return onlyoffice.setup_docker(_resolve_confdir(args))
    listen = args["--listen"]
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
        settings["listen"] = ":8989"
    config.update_config(settings)
    # Prepare to serve
    url, opts = serve.parse_listen(config.config.listen)
    if not config.config.path.is_dir():
        raise ValueError(f"No such directory: {config.config.path}")
    dev = args["--dev"]
    # Check for Paskia SSO
    from cista.sso import PASKIA_BACKEND_URL

    # Print startup box
    startup_box = create_startup_box(
        folder=config.config.path,
        url=url,
        unix=opts.get("unix"),
        dev=dev,
        paskia_url=PASKIA_BACKEND_URL or None,
        public=config.config.public,
    )
    sys.stderr.write(startup_box)
    # Run the server
    serve.run(dev=dev)
    return 0


def _resolve_confdir(args):
    confdir = None
    if args["-c"]:
        # Custom config directory
        confdir = Path(args["-c"]).resolve()
        if confdir.exists() and not confdir.is_dir():
            if confdir.name != "db.toml":
                raise ValueError("Config path is not a directory")
            # Accidentally pointed to the db.toml, use parent
            confdir = confdir.parent
    return confdir


def _confdir(args):
    confdir = _resolve_confdir(args)
    config.init_confdir(confdir)


def _user(args):
    _confdir(args)
    if config.conffile.exists():
        config.load_config()
        operation = False
    else:
        # Defaults for new config when user is created
        operation = config.update_config(
            {
                "listen": ":8989",
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
            "Now you can run the server:\n  cista    # defaults set: -l :8989 ~/Downloads\n"
        )


if __name__ == "__main__":
    sys.exit(main())
