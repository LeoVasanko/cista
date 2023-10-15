# Web File Storage

Development install:

```sh
python -m venv .venv        # Create virtual env
. .venv/bin/activate
pip install -e .            # Editable install
sanic cista --reload --dev  # Runs on localhost:8000
```

Environment variable `STORAGE=<path>` may be used to choose which folder it serves. The default is current directory.

No authentication is supported, so implement access control externally or be careful with your files.

