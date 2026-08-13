"""Cista-specific OnlyOffice setup.

The conversion client itself lives in `mediapreview.office`; this module
only bridges cista's config-derived JWT secret into it and wires the
`--oosetup` Docker bootstrap to cista's config.
"""

import os
import sys
from pathlib import Path

import mediapreview.office

from cista import config


def configure() -> None:
    """Point mediapreview's OnlyOffice client at cista's derived JWT secret."""
    os.environ.setdefault(
        "ONLYOFFICE_JWT_SECRET", config.derived_secret("onlyoffice", size=16).hex()
    )


def setup_docker(confdir: Path | None = None) -> str:
    """Build and run the patched OnlyOffice Docker image (via mediapreview)."""
    if confdir is not None:
        os.environ["CISTA_HOME"] = confdir.as_posix()
    config.init_confdir()
    if config.conffile.exists():
        config.load_config()
    else:
        config.update_config(
            {
                "listen": ":8989",
                "path": Path.home() / "Downloads",
                "public": False,
            }
        )
    configure()
    try:
        return mediapreview.office.setup_docker()
    finally:
        # Print regardless of build outcome: the secret is deterministic
        # (derived from the config).
        sys.stdout.write(
            f"ONLYOFFICE_JWT_SECRET={os.environ['ONLYOFFICE_JWT_SECRET']}\n"
        )
