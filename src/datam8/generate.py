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
"""Jinja2-based code generation engine: payload registration, rendering, and output writing."""

# along with this program. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
from collections.abc import Callable, Sequence
from concurrent import futures
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import jinja2

from datam8 import config, errors, logging, model, utils
from datam8.utils import cache, importer
from datam8_model.solution import GeneratorTarget

logger = logging.getLogger(__name__)
payload_functions: dict[PayloadOrder, list[PayloadDefinition]] = {}

type PayloadFunction = Callable[[model.Model, cache.Cache], Sequence[IPayload]]
type PayloadOrder = int


def _get_function_name(callable: Callable[..., Any], /) -> str:
    return callable.__name__  # type: ignore


def generate_output(
    model: model.Model,
    /,
    target: str,
    payloads: Sequence[str],
    *,
    generate_all: bool,
    clean_output: bool,
) -> Path:
    """Run output generation in a CLI context, exiting the process on known errors.

    Wraps :func:`__generate_output_unsafe` so that :class:`~errors.InvalidGeneratorTargetError`
    and :class:`RenderError` cause `sys.exit` rather than propagating as exceptions.
    When running via the API a different error path is taken instead.
    """
    try:
        result = __generate_output_unsafe(
            model,
            _config=GeneratorConfig(
                target=model.get_generator_target(target),
                payloads=payloads,
                generate_all=generate_all,
                clean_output=clean_output,
            ),
        )
    except errors.InvalidGeneratorTargetError as err:
        logger.error(err)
        sys.exit(1)
    except RenderError as _:
        sys.exit(1)

    return result


def __generate_output_unsafe(
    model: model.Model,
    /,
    _config: GeneratorConfig,
) -> Path:
    payload_cache = cache.Cache()

    importer.enable_target_modules(_config.module_path)
    modules = importer.load_modules(_config.module_path)

    logger.info(f"Loaded {len(modules)} modules with {len(payload_functions)} payload(s)")

    if _config.clean_output and _config.output_path.exists():
        logger.warning("Cleaning output...")
        utils.delete_path(_config.output_path, recursive=True)

    if not _config.output_path.exists():
        utils.mkdir(_config.output_path, recursive=True)

    selected_payloads = {
        order: [
            payload
            for payload in payload_functions[order]
            if payload.name in _config.payloads or len(_config.payloads) == 0
        ]
        for order in sorted(payload_functions)
    }

    for order in selected_payloads:
        executor = futures.ThreadPoolExecutor()

        def render_payload_for_order(payload: PayloadDefinition) -> Exception | None:
            return asyncio.run(render_payload(payload, model, payload_cache, _config=_config))

        results = executor.map(render_payload_for_order, selected_payloads[order])
        executor.shutdown()
        errors = [_result for _result in results if _result]
        if errors:
            raise RenderError()

    return _config.output_path


def register_payload(
    template: Path | str, /, *, order: int = 1
) -> Callable[[PayloadFunction], PayloadFunction]:
    """Register a payload function with its Jinja2 template and execution order.

    Parameters
    ----------
    template : Path | str
        Relative path to the Jinja2 template file used to render this payload.
    order : int
        Execution order group; lower numbers run first, allowing payloads to depend
        on outputs from earlier groups.

    Raises
    ------
    PayloadRegisteredMultipleTimesError
        When a payload function with the same name has already been registered.

    """

    def register_payload(func: PayloadFunction) -> PayloadFunction:
        func_name = _get_function_name(func)
        logger.debug(f"Registering payload {func.__module__}:{func_name}")

        if func.__name__ in [  # type: ignore
            payload.name for payloads in payload_functions.values() for payload in payloads
        ]:
            raise errors.PayloadRegisteredMultipleTimesError(func_name)

        if order not in payload_functions:
            payload_functions[order] = []

        payload_functions[order].append(
            PayloadDefinition(
                name=func_name,
                _function=func,
                template_path=template if isinstance(template, Path) else Path(template),
                order=order,
            )
        )
        return func

    return register_payload


async def render_payload(
    payload: PayloadDefinition,
    /,
    model: model.Model,
    cache: cache.Cache,
    *,
    _config: GeneratorConfig,
) -> Exception | None:
    """Execute a payload function and render its Jinja2 template for every produced item.

    Return `None` on success or the first :class:`Exception` encountered so that the
    caller can collect errors across concurrent payloads.
    """
    logger.debug(f"Render payload: {payload.name}")

    try:
        payloads: Sequence[IPayload] = payload._function(model, cache)
    except Exception as err:
        file_path, func_name, line_no, summary = errors.extract_details(err)
        logger.error(
            "payload '%s' threw errors during payload creation in '%s' at line %s: %s",
            payload.name,
            file_path,
            line_no,
            err,
            exc_info=err if logger.getEffectiveLevel() <= logging.INFO else None,
        )
        return err

    template_loader = jinja2.FileSystemLoader([_config.template_path, config.solution_folder_path])
    template_env = jinja2.Environment(loader=template_loader, undefined=jinja2.StrictUndefined)
    template_path = _config.target.sourcePath / payload.template_path

    try:
        template = template_env.get_template(template_path.as_posix())
    except jinja2.TemplateNotFound as err:
        logger.error(f"{payload.name}: {err}")
        return err
    except jinja2.TemplateSyntaxError as err:
        file_path, func_name, line_no, _ = errors.extract_details(err)
        logger.error(
            "Template '%s' contains errors at line %s: %s",
            file_path,
            line_no,
            err,
        )
        return err

    coros = [
        render_template(
            payload.name, _p.get_data(), template, _p.get_output_path(), _config=_config
        )
        for _p in payloads
    ]
    results = [
        result
        for result in await asyncio.gather(*coros, return_exceptions=True)
        if result is not None
    ]

    if len(results) > 0:
        return Exception(results)

    logger.info(f"Rendered template {payload.template_path} from payload {payload.name}")
    return None


async def render_template(
    payload_name: str,
    /,
    data: object,
    template: jinja2.Template,
    output_path: Path,
    *,
    _config: GeneratorConfig,
) -> None | Exception:
    """Render a single Jinja2 template with the given data and write the result to disk.

    Return `None` on success or the caught :class:`Exception` if template rendering fails.
    """
    _output_path = _config.output_path / output_path
    logger.debug(f"[{payload_name}] Write output {template.filename} -> {_output_path}")

    try:
        output = template.render(data=data)
    except Exception as err:
        file_name, _, line_no, _ = errors.extract_details(err)
        logger.error(
            "Template '%s' threw error during rendering at line %s: %s",
            Path(file_name).relative_to(config.solution_folder_path),
            line_no,
            err,
        )
        return err

    if not _output_path.exists():
        os.makedirs(_output_path.parent, exist_ok=True)

    with open(_output_path, "w") as file:
        file.write(output)

    return None


@dataclasses.dataclass
class PayloadDefinition:
    """Associates a registered payload function with its template path and execution order."""

    name: str
    _function: PayloadFunction
    template_path: Path
    order: int


@dataclasses.dataclass
class BasePayload:
    """Concrete :class:`IPayload` implementation holding data and its intended output path."""

    data: object
    output_path: Path

    def get_data(self) -> object:
        """Return the payload data passed to the Jinja2 template."""
        return self.data

    def get_output_path(self) -> Path:
        """Return the relative path where the rendered file will be written."""
        return self.output_path


@dataclasses.dataclass
class GeneratorConfig:
    """Resolved runtime configuration for a single generation run."""

    target: GeneratorTarget
    payloads: Sequence[str]
    generate_all: bool
    clean_output: bool

    @property
    def module_path(self) -> Path:
        """Return the `__modules` directory path for this generator target."""
        return config.solution_folder_path / self.target.sourcePath / "__modules"

    @property
    def template_path(self) -> Path:
        """Return the root directory used to locate Jinja2 templates."""
        return config.solution_folder_path / self.target.sourcePath

    @property
    def output_path(self) -> Path:
        """Return the directory where generated files will be written."""
        return config.solution_folder_path / self.target.outputPath


class GenerateStatus(Enum):
    """Outcome of a generation run."""

    SUCCESS = 0
    FAILURE = 1


class GenerateResult(Protocol):
    """Protocol describing the result object returned by a generation run."""

    status: GenerateStatus
    target: str | None
    output_path: str | None = None
    message: str | None = None


class IPayload(Protocol):
    """Protocol that every payload object must satisfy to participate in template rendering."""

    def get_data(self) -> object:
        """Return payload data."""
        ...

    def get_output_path(self) -> Path:
        """Return output path for rendered template."""
        ...


class RenderError(Exception):
    """Raised when one or more payloads fail during a generation run."""

    def __init__(self):
        """Initialize with a fixed error message."""
        super().__init__("Error during payload rendering")
