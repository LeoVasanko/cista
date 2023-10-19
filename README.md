# Web File Storage

Run directly from repository with Hatch (or use pip install as usual):
```sh
hatch run cista -l :3000 /path/to/files
```

Settings incl. these arguments are stored to config file on the first startup and later `hatch run cista` is sufficient. If the `cista` script is missing, consider `pip install -e .` (within `hatch shell`) or some other trickery (known issue with installs made prior to adding the startup script).

Create your user account:
```sh
hatch run cista --user admin --privileged
```
