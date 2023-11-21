# noqa: INP001
import os
import shutil
import subprocess
from sys import stderr

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        super().initialize(version, build_data)
        # A hack to stop building twice on run
        if not build_data.get("force_include"):
            return
        stderr.write(">>> Building Cista frontend\n")
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError(
                "NodeJS `npm` is required for building Cista but it was not found"
            )
        # npm --prefix doesn't work on Windows, so we chdir instead
        os.chdir("frontend")
        try:
            stderr.write("### npm install\n")
            subprocess.run([npm, "install"], check=True)  # noqa: S603
            stderr.write("\n### npm run build\n")
            subprocess.run([npm, "run", "build"], check=True)  # noqa: S603
        finally:
            os.chdir("..")
