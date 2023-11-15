# Cista Web Storage

<img src="https://git.zi.fi/Vasanko/cista-storage/raw/branch/main/docs/cista.webp" align=left width=250>

Cista takes its name from the ancient *cistae*, metal containers used by Greeks and Egyptians to safeguard valuable items. This modern application provides a browser interface for secure and accessible file storage, echoing the trust and reliability of its historical namesake.

This is a cutting-edge **file and document server** designed for speed, efficiency, and unparalleled ease of use. Experience **lightning-fast browsing**, thanks to the file list maintained directly in your browser and updated from server filesystem events, coupled with our highly optimized code. Fully **keyboard-navigable** and with a responsive layout, Cista flawlessly adapts to your devices, providing a seamless experience wherever you are. Our powerful **instant search** means you're always just a few keystrokes away from finding exactly what you need. Press **1/2/3** to switch ordering, navigate with all four arrow keys (+Shift to select). Or click your way around on **breadcrumbs that remember where you were**.

The Cista project started as an inevitable remake of [Droppy](https://github.com/droppyjs/droppy) which we used and loved despite its numerous bugs. Cista Storage stands out in handling even the most exotic filenames, ensuring a smooth experience where others falter.

All of this is wrapped in an intuitive interface with automatic light and dark themes, making Cista Storage the ideal choice for anyone seeking a reliable, versatile, and quick file storage solution. Quickly setup your own Cista where your files are just a click away, safe, and always accessible.

Experience Cista by visiting [Cista Demo](https://drop.zi.fi) for a test run and perhaps upload something...


## Getting Started
### Installation

To install the cista application, use:

```fish
pip install cista
```

Note: Some Linux distributions might need `--break-system-packages` to install Python packages, which are safely installed in the user's home folder. As an alternative to avoid installation, run it with command `pipx run cista`

### Running the Server

Create an account: (or run a public server without authentication)
```fish
cista --user yourname --privileged
```

Serve your files at http://localhost:8000:
```fish
cista -l :8000 /path/to/files
```

The server remembers its settings in the config folder (default `~/.local/share/cista/`), including the listen port and directory, for future runs without arguments.

### Internet Access

To use your own TLS certificates, place them in the config folder and run:

```fish
cista -l cista.example.com
```

Most admins instead find the [Caddy](https://caddyserver.com/) web server convenient for its auto TLS certificates and all. A proxy also allows running multiple web services or Cista instances on the same IP address but different (sub)domains.

`/etc/caddy/Caddyfile`:

```Caddyfile
cista.example.com {
    reverse_proxy :8000
}
```

## Development setup

For rapid development, we use the Vite development server for the Vue frontend, while running the backend on port 8000 that Vite proxies backend requests to. Each server live reloads whenever its code or configuration are modified.

```fish
cd frontend
npm install
npm run dev
```

Concurrently, start the backend on another terminal:

```fish
hatch shell
pip install -e '.[dev]'
cista --dev -l :8000 /path/to/files
```

We use `hatch shell` for installing on a virtual environment, to avoid disturbing the rest of the system with our hacking.

Vue is used to build files in `cista/wwwroot`, included prebuilt in the Python package. Running `hatch build` builds the frontend and creates a NodeJS-independent Python package.

## System Deployment

This setup allows easy addition of storages, each with its own domain, configuration, and files.

Assuming a restricted user account `storage` for serving files and that cista is installed system-wide or on this account (check with `sudo -u storage -s`). Alternatively, use `pipx run cista` or `hatch run cista` as the ExecStart command.

Create `/etc/systemd/system/cista@.service`:

```ini
[Unit]
Description=Cista storage %i

[Service]
User=storage
ExecStart=cista -c /srv/cista/%i -l /srv/cista/%i/socket /media/storage/%i
Restart=always

[Install]
WantedBy=multi-user.target
```

This setup supports multiple storages, each under `/media/storage/<domain>` for files and `/srv/cista/<domain>/` for configuration. UNIX sockets are used instead of numeric ports for convenience.

```fish
systemctl daemon-reload
systemctl enable --now cista@foo.example.com
systemctl enable --now cista@bar.example.com
```

Public exposure is easiest using the Caddy web server.

`/etc/caddy/Caddyfile`:

```Caddyfile
foo.example.com, bar.example.com {
    reverse_proxy unix//srv/cista/{host}/socket
}
```
