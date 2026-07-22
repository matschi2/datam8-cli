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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Shared utility functions and decorators used across CLI commands, the API, and Jinja2 templates."""

import functools
import os
import platform
from collections.abc import Callable
from logging import FileHandler, StreamHandler
from pathlib import Path
from typing import Any

import rich
import typer
from pydantic import BaseModel
from rich.progress import Progress, SpinnerColumn, TextColumn

from datam8 import config, logging, opts

logger = logging.getLogger(__name__)


def create_error(err: Exception | str, /, status_code: int = 500, exit_code: int = 1) -> Exception:
    """Create a mode-aware error: raise an HTTP exception in API mode or exit in CLI mode."""
    if config.mode == config.RunMode.API:
        import fastapi

        return fastapi.HTTPException(status_code=status_code, detail=str(err).splitlines())

    if isinstance(err, str):
        err = Exception(err)

    if logger.getEffectiveLevel() <= logging.DEBUG or config.mode == config.RunMode.TEST:
        return err

    typer.echo(err)
    return typer.Exit(exit_code).with_traceback(err.__traceback__)


def is_wsl() -> bool:
    """Return True if the current process is running inside Windows Subsystem for Linux."""
    # if no running on linux, it cannot be wsl
    if platform.system() != "Linux":
        return False

    # get kernel release information and check if if contains wsl or microsoft
    rel = platform.release().lower()
    if "wsl" in rel or "microsoft" in rel:
        return True

    return False


def emit_result(
    *messages: Any,
    models: list[BaseModel] | None = None,
    json: bool = False,
    pretty: bool = False,
) -> None:
    """Print command output to stdout, serialising Pydantic models as JSON when requested."""
    if json and models:
        typer.echo("\n".join([model.model_dump_json(indent=4) for model in models]))
        return

    for msg in messages:
        if pretty:
            rich.print(msg)
        else:
            typer.echo(msg)


def none_if[T](input: T | None, value: T) -> T | None:
    """Return None when `input` equals `value`, otherwise return `input` unchanged."""
    if input == value:
        return None
    return input


def pascal_to_snake_case(text: str) -> str:
    """Convert a pascal or camel case string to snake case.

    Example:
    -------
    * `AttributeTypes.json` to `attribute_types.json`
    * `dataSources.json` to `data_sources.json`
    * `data_types.json` to `data_types.json`

    """
    result: list[str] = []

    for idx in range(0, len(text)):
        if text[idx].isupper() and idx != 0:
            result.append("_")

        result.append(text[idx].lower())

    return "".join(result)


def delete_path(path: Path, recursive: bool = False) -> None:
    """Delete a file or directory, optionally removing all nested contents first."""
    if not path.exists():
        return

    if path.is_file():
        os.remove(path)
        return

    if not recursive and path.is_dir():
        path.rmdir()
        return

    for child in path.iterdir():
        delete_path(child, recursive)

    path.rmdir()


def mkdir(path: Path, recursive: bool = False) -> None:
    """Create `path`, silently skipping directories that already exist.

    Parameters
    ----------
    path : Path
        Directory path to create.
    recursive : bool
        When True, create missing parent directories before creating `path`.

    Raises
    ------
    FileNotFoundError
        If a parent directory does not exist and `recursive` is False.

    """
    if not path.parent.exists() and recursive:
        mkdir(path.parent, recursive=recursive)

    if not path.exists():
        os.mkdir(path)


def print_progress_async(msg: str):
    """Return a decorator that shows a Rich spinner with `msg` while the wrapped async function runs."""

    def decorator_print_progress_async(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Callable:
            result = func(*args, **kwargs)

            if config.log_level in [
                opts.LogLevels.WARNING,
                opts.LogLevels.ERROR,
            ]:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    transient=True,
                ) as progress:
                    progress.add_task(description=msg, total=None)
                    # time.sleep(3)

            return await result

        return wrapper

    return decorator_print_progress_async


def get_logger(func):
    """Return a decorator that re-initialises the module logger before each call to pick up CLI log-level changes."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Callable[..., Any]:
        start_logger(func.__module__)
        return func(*args, **kwargs)

    return wrapper


def start_logger(
    log_name: str = "template log",
    log_directory: str = f"{Path(__file__).parents[1]}\\Logs",
    enable_write_log: bool = False,
) -> logging.Logger:
    r"""Return a configured logger, optionally writing output to a file under `log_directory`.

    Parameters
    ----------
    log_name : str, optional
        Logger name and base name of the log file.
    log_directory : str, optional
        Directory for the log file when `enable_write_log` is True.
    enable_write_log : bool, optional
        When True, attach a `FileHandler` that writes to `log_directory`.

    """
    log_path = f"{log_directory}\\{log_name}.log"

    logger = logging.getLogger(log_name)
    logger.setLevel(config.log_level.value.upper())

    if enable_write_log and not logger.hasHandlers():
        # Create Log
        if not os.path.exists(log_directory):
            os.makedirs(log_directory)

        # Remove Old Log file
        if os.path.exists(log_path):
            os.remove(log_path)

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s: %(message)s")
        file_handler = FileHandler(log_path)
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

    # Adding Stream handler to print out logs additionally to the console
    stream_handler = StreamHandler()
    stream_handler.setFormatter(logging.ColorFormatter())

    if not logger.hasHandlers():
        logger.addHandler(stream_handler)

    return logger
