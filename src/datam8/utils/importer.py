# DataM8
# Copyright (C) 2024-2025 ORAYLIS GmbH
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
"""Dynamic module loader that imports Python files from target output directories at runtime."""

# along with this program. If not, see <https://www.gnu.org/licenses/>.
import pathlib
import sys
from importlib import machinery, util
from types import ModuleType

from datam8 import config, errors, logging, utils

logger = logging.getLogger(__name__)


def enable_target_modules(module_path: pathlib.Path) -> None:
    """Register `module_path` with `TargetModuleFinder` so generated Python modules can be imported by name."""
    logger.info(
        "Enable importing from target %s",
        module_path.absolute().relative_to(config.solution_folder_path),
    )

    if module_path not in TargetModuleFinder._path:
        TargetModuleFinder._path.append(module_path.absolute().as_posix())

    if TargetModuleFinder not in sys.meta_path:
        sys.meta_path.append(TargetModuleFinder)

    logger.debug("Configured module paths: %s", TargetModuleFinder._path)


def load_modules(module_path: pathlib.Path) -> dict[str, ModuleType]:
    """Recursively discover and load all Python files under `module_path`, returning them keyed by relative module name."""
    modules: dict[str, ModuleType] = {}
    module_files = list(module_path.glob("**/*.py"))

    for i in range(0, len(module_files)):
        module_name = module_files[i].relative_to(module_path).as_posix().removesuffix(".py")
        try:
            modules[module_name] = load_module(module_files[i], module_name)
        except errors.PayloadRegisteredMultipleTimesError as err:
            logger.error(f"{err}\n{module_files[i]}")
            sys.exit(1)
        except ModuleNotFoundError as err:
            msg = "%s at %s:%s"
            file_name, _, line_no, _ = errors.extract_details(err)

            logger.error(msg, err, file_name, line_no)
            sys.exit(1)

    return modules


def load_module(path: pathlib.Path, module_name: str) -> ModuleType:
    """Load and execute a single Python file as a module, registering it in `sys.modules` under `module_name`."""
    logger.debug(f"Loaded module {path.relative_to(config.solution_folder_path)}")

    if path.is_dir():
        path = path / "__init__.py"

    if not path.exists():
        raise utils.create_error(f"Module to be loaded does not exist: {path}")

    spec = util.spec_from_file_location(module_name, path)
    if spec is None:
        # TODO: raise a better error
        raise Exception("spec is none")

    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader = spec.loader

    if loader is None:
        # TODO: raise a better error
        raise Exception("loader is none")

    loader.exec_module(module)

    return module


class TargetModuleFinder(machinery.PathFinder):
    """A meta path finder that resolves imports from the registered target output directories.

    Paths are accumulated in `_path` via `enable_target_modules` and searched before
    the standard `sys.path` entries.
    """

    _path = []

    @classmethod
    def find_spec(cls, fullname: str, path=None, target=None):
        """Search `cls._path` for a module spec matching `fullname`."""
        return super().find_spec(fullname, cls._path, target)
