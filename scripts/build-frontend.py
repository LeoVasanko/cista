# noqa: INP001
import subprocess

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        super().initialize(version, build_data)
        print("Building Cista frontend...")
        subprocess.run("npm install --prefix frontend".split(" "), check=True)  # noqa: S603
        subprocess.run("npm run build --prefix frontend".split(" "), check=True)  # noqa: S603
