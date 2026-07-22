#
# This file is part of DataM8.
#
# DataM8 is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# DataM8 is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
"""Registry and loader for DataM8 data source plugins."""

# along with this program. If not, see <https://www.gnu.org/licenses/>.

import importlib
from collections.abc import Callable
from pathlib import Path

from datam8 import config, logging, utils
from datam8.utils import importer
from datam8_model.data_source import DataSource, DataSourceType
from datam8_model.plugin import PluginManifest
from datam8_model.solution import Solution

from .base import Plugin

logger = logging.getLogger(__name__)

type PluginInstantiator = Callable[[DataSource, DataSourceType], Plugin]


def _create_plugin_instantiator(cls: type[Plugin], manifest: PluginManifest) -> PluginInstantiator:
    logger.debug(f"Creating plugin instantiator for {manifest.id}")

    def instantiator(ds: DataSource, dst: DataSourceType, /) -> Plugin:
        return cls(manifest, ds, dst)

    return instantiator


class PluginManager:
    """Manage plugin registration, lazy loading, and instantiation for a DataM8 session."""

    __builtin_plugins: dict[str, PluginManifest] = {}

    def __init__(self, solution: Solution | None = None) -> None:
        """Set up empty plugin registries and optionally load plugins from a solution."""
        self.__solution_plugins: dict[str, PluginManifest] = {}
        self.__plugins_dir_path: Path | None = None
        self.__loaded_plugins: dict[str, type[Plugin]] = {}

        if solution is not None:
            self.load_plugins_from_solution(solution)

    @classmethod
    def register_builtin_plugin(cls, name: str, /, plugin: PluginManifest) -> None:
        """Add a built-in plugin manifest to the class-level registry; silently skip if already present."""
        if name not in cls.__builtin_plugins:
            cls.__builtin_plugins[name] = plugin

    def register_plugin(self, name: str, /, plugin: PluginManifest) -> None:
        """Add a solution-level plugin manifest under `name`; the plugin class is loaded lazily on demand."""
        if name is self.__solution_plugins:
            utils.create_error(f"Plugin is already registered: {name}")

        self.__solution_plugins[name] = plugin

    def reload(self, solution: Solution) -> list[PluginManifest]:
        """Clear cached plugin classes, reload plugins from the solution, and return the updated list."""
        self.reset_plugins()
        self.load_plugins_from_solution(solution)

        return self.get_plugins()

    def reset_plugins(self) -> None:
        """Evict all cached plugin classes so they are re-imported on next use."""
        self.__loaded_plugins = {}

    def remove_plugin(self, plugin_id: str, /) -> None:
        """Unregister a solution-level plugin; built-in plugins are unaffected."""
        if plugin_id in self.__solution_plugins:
            del self.__solution_plugins[plugin_id]

    def get_plugin_manifest(self, plugin_id: str, /) -> PluginManifest:
        """Look up and return the manifest for `plugin_id`, checking solution plugins before built-ins.

        Raises
        ------
        Exception
            If no plugin with `plugin_id` is registered.

        """
        manifest: PluginManifest | None = None

        match plugin_id:
            case _ if plugin_id in self.__solution_plugins:
                manifest = self.__solution_plugins[plugin_id]
            case _ if plugin_id in PluginManager.__builtin_plugins:
                manifest = PluginManager.__builtin_plugins[plugin_id]
            case _:
                raise utils.create_error(f"Plugin `{plugin_id}` is not registered.")

        return manifest

    def get_plugin_instantiator(self, data_source_type: DataSourceType, /) -> PluginInstantiator:
        """Return a callable that creates a `Plugin` instance for `data_source_type`.

        The plugin class is loaded once and cached; subsequent calls reuse the cached class.
        """
        manifest = self.get_plugin_manifest(data_source_type.name)
        PluginClass = self.get_plugin(data_source_type.name)

        return _create_plugin_instantiator(PluginClass, manifest)

    def get_plugin(self, plugin_id_: str, /) -> type[Plugin]:
        """Load and return the `Plugin` class for `plugin_id_`, importing from disk or module path as needed."""
        plugin_id = plugin_id_.removeprefix("builtin:")

        if plugin_id in self.__loaded_plugins:
            return self.__loaded_plugins[plugin_id]

        manifest = self.get_plugin_manifest(plugin_id)

        if ":" not in manifest.entryPoint:
            raise utils.create_error(
                "Plugin entrypoint needs to be in the format of `<module>:<ClassName>`"
            )

        module_name, class_name = manifest.entryPoint.split(":")

        match self.__plugins_dir_path:
            case Path() if (self.__plugins_dir_path / module_name).exists():
                file_path = self.__plugins_dir_path / module_name
                module = importer.load_module(file_path, module_name.removesuffix(".py"))
            case _:
                module = importlib.import_module(module_name)

        PluginClass = getattr(module, class_name)
        self.__loaded_plugins[plugin_id] = PluginClass

        return PluginClass

    def get_plugins(self) -> list[PluginManifest]:
        """Return manifests for all registered plugins; solution plugins shadow built-ins of the same name."""
        return list({**PluginManager.__builtin_plugins, **self.__solution_plugins}.values())

    def load_plugins_from_solution(self, solution: Solution, /) -> None:
        """Scan the solution's plugin directory for `*.json` manifests and register each one."""
        plugins_path = config.solution_folder_path / solution.pluginsPath
        self.__plugins_dir_path = plugins_path

        logger.debug("Plugins directory: %s", plugins_path.as_posix())

        for file in plugins_path.glob("**/*.json"):
            logger.debug("Register plugin from %s", file.as_posix())
            manifest = PluginManifest.from_json_file(file)
            self.register_plugin(manifest.id, manifest)

        logger.info("Currently loaded %s plugins from solution", len(self.__solution_plugins))
