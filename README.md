# Web File Storage

Run directly from repository with Hatch (or use pip install as usual):
```sh
hatch run sanic cista --reload --dev
```

Configuration file is created `.cista.toml` in current directory, which is also shared by default. Edit while the server is not running to set share path and other parameters.

No authentication yet, so implement access control externally or be careful with your files.
