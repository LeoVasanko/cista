# Cista Web Storage

<img src="https://git.zi.fi/Vasanko/cista-storage/raw/branch/main/docs/cista.webp" align=left width=250>

Cista takes its name from the ancient *cistae*, metal containers used by Greeks and Egyptians to safeguard valuable items. This modern application provides a browser interface for secure and accessible file storage, echoing the trust and reliability of its historical namesake.

This is a cutting-edge **file and document server** designed for speed, efficiency, and unparalleled ease of use. Experience **lightning-fast browsing**, thanks to the file list maintained directly in your browser and updated from server filesystem events, coupled with our highly optimized code. Fully **keyboard-navigable** and with a responsive layout, Cista flawlessly adapts to your devices, providing a seamless experience wherever you are. Our powerful **instant search** means you're always just a few keystrokes away from finding exactly what you need. Press **1/2/3** to switch ordering, navigate with all four arrow keys (+Shift to select). Or click your way around on **breadcrumbs that remember where you were**.

**Built-in document and media previews** let you quickly view files without downloading them. Cista shows PDF and other documents, video and image thumbnails, with **HDR10 support** video previews and image formats, including HEIC and AVIF. It also has a player for music and video files.

The Cista project started as an inevitable remake of [Droppy](https://github.com/droppyjs/droppy) which we used and loved despite its numerous bugs. Cista Storage stands out in handling even the most exotic filenames, ensuring a smooth experience where others falter.

All of this is wrapped in an intuitive interface with automatic light and dark themes, making Cista Storage the ideal choice for anyone seeking a reliable, versatile, and quick file storage solution. Quickly setup your own Cista where your files are just a click away, safe, and always accessible.

Experience Cista by visiting [Cista Demo](https://drop.zi.fi) for a test run and perhaps upload something...


## Getting Started
### Running the Server

We recommend using [UV](https://docs.astral.sh/uv/getting-started/installation/) to directly run Cista:

Create an account: (otherwise the server is public for all)
```fish
uvx cista --user yourname --privileged
```

Serve your files at http://localhost:8000:
```fish
uvx cista -l :8000 /path/to/files
```

Alternatively, you can install with `pip` or `uv pip`. This enables using the `cista` command directly without `uvx` or `uv run`.

```fish
pip install cista --break-system-packages
```

The server remembers its settings in the config folder (default `~/.local/share/cista/`), including the listen port and directory, for future runs without arguments.

### Internet Access

Most admins find the [Caddy](https://caddyserver.com/) web server convenient for its auto TLS certificates and all. A proxy also allows running multiple web services or Cista instances on the same IP address but different (sub)domains.

`/etc/caddy/Caddyfile`:

```Caddyfile
cista.example.com {
    reverse_proxy :8000
}
```

Nxing or other proxy may be similarly used, or alternatively you can place cert and key in cista config dir and run `cista -l cista.example.com`

## System Deployment

This setup allows easy addition of storages, each with its own domain, configuration, and files.

Assuming a restricted user account `storage` for serving files and that UV is installed system-wide or on this account. Only UV is required: this does not use git or bun/npm.

Create `/etc/systemd/system/cista@.service`:

```ini
[Unit]
Description=Cista storage %i

[Service]
User=storage
ExecStart=uvx cista -c /srv/cista/%i -l /srv/cista/%i/socket /media/storage/%i
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

## Development setup

For rapid development, we use the Vite development server for the Vue frontend, while running the backend on port 8000 that Vite proxies backend requests to. Each server live reloads whenever its code or configuration are modified.

Make sure you have git, uv and bun (or npm) installed.

Backend (Python) – setup and run:

```fish
git clone https://git.zi.fi/Vasanko/cista-storage.git
cd cista-storage
uv sync --dev
uv run cista --dev -l :8000 /path/to/files
```

Frontend (Vue/Vite) – run the dev server in another terminal:

```fish
cd frontend
bun install
bun run dev
```

Building the package for release (frontend + Python wheel/sdist):

```fish
uv build
```

Vue is used to build files in `cista/wwwroot`, included prebuilt in the Python package. `uv build` runs the project build hooks to bundle the frontend and produce a NodeJS-independent Python package.
