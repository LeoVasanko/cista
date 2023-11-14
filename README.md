# Web File Storage

The Python package installs a `cista` executable. Use `hatch shell` to initiate and install in a virtual environment, or `pip install` it on your system. Alternatively `hatch run cista` may be used to skip the shell step but stay virtual. `pip install hatch` first if needed.

Create your user account:

```sh
cista --user admin --privileged
```

## Running the server

Serve your files on localhost:8000:

```sh
cista -l :8000 /path/to/files
```

The Git repository does not contain a frontend build, so you should first do that...

## Build frontend

Frontend needs to be built before using and after any frontend changes:

```sh
cd frontend
npm install
npm run build
```

This will place the front in `cista/wwwroot` from where the backend server delivers it, and that also gets included in the Python package built via `hatch build`.

## Development setup

For rapid turnaround during development, you should run `npm run dev` Vite development server on the Vue frontend. While that is running, start the backend on another terminal `hatch run cista --dev -l :8000` and connect to the frontend.

The backend and the frontend will each reload automatically at any code or config changes.

## System deployment

Clone the repository to `/srv/cista/cista-storage` or other suitable location accessible to the storage user account you plan to use. `sudo -u storage -s` and build the frontend if you hadn't already.

Create **/etc/systemd/system/cista@.service**:

```ini
[Unit]
Description=Cista storage %i

[Service]
User=storage
WorkingDirectory=/srv/cista/cista-storage
ExecStart=hatch run cista -c /srv/cista/%i -l /srv/cista/%i/socket /media/storage/@%i/
TimeoutStopSec=2
Restart=always

[Install]
WantedBy=multi-user.target
```

This assumes you may want to run multiple separate storages, each having their files under `/media/storage/<domain>` and configuration under `/srv/cista/<domain>/`. Instead of numeric ports, we use UNIX sockets for convenience.

```sh
systemctl daemon-reload
systemctl enable --now cista@foo.example.com
systemctl enable --now cista@bar.example.com
```

Exposing this publicly online is the most convenient using the [Caddy](https://caddyserver.com/) web server but you can of course use Nginx or others as well. Or even run the server with `-l domain.example.com` given TLS certificates in the config folder.

**/etc/caddy/Caddyfile**:

```Caddyfile
foo.example.com, bar.example.com {
    reverse_proxy unix//srv/cista/{host}/socket
}
```

Using the `{host}` placeholder we can just put all the domains on the same block. That's the full server configuration you need. `systemctl enable --now caddy` or `systemctl restart caddy` for the config to take effect.
