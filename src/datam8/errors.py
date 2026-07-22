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
"""Custom exception types and error utility helpers for DataM8."""

# along with this program. If not, see <https://www.gnu.org/licenses/>.

from collections.abc import Sequence
from pathlib import Path
from traceback import StackSummary, extract_tb
from typing import Any

from pydantic import BaseModel

from datam8 import config


def extract_details(err: Exception) -> tuple[Path, str, int | None, StackSummary]:
    """Extract the innermost traceback frame details from an exception.

    Returns
    -------
    tuple[Path, str, int | None, StackSummary]
        File path, function name, line number, and remaining stack summary.
        Returns empty/unknown values when no traceback is available.

    """
    if err.__traceback__ is None:
        return Path(), "unknown", None, StackSummary()

    stack_summary = extract_tb(err.__traceback__)

    if len(stack_summary) < 1:
        return Path(), "unknown", None, stack_summary

    details = stack_summary.pop(-1)
    file_path = Path(details.filename)

    if file_path.is_relative_to(config.solution_folder_path):
        file_path.relative_to(config.solution_folder_path)

    return file_path, details.name, details.lineno, stack_summary


class PayloadRegisteredMultipleTimesError(Exception):
    """Raised when the same payload function name is registered more than once."""

    def __init__(self, payload_name, /):
        """Initialize with the duplicate payload name."""
        super().__init__(f"Payload [{payload_name}] already registered.")


class ErrorEnvelope(BaseModel):
    """Stable JSON envelope for API error responses."""

    code: str
    message: str
    details: Any = None
    hint: str | None = None
    traceId: str | None = None


class Datam8Error(Exception):
    """Base exception for all structured DataM8 errors carrying a code, message, and optional details."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Any = None,
        hint: str | None = None,
        exit_code: int = 10,
    ) -> None:
        """Initialize the error with a structured code and optional contextual information."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.hint = hint
        self.exit_code = exit_code

    def to_envelope(self, *, trace_id: str | None = None) -> ErrorEnvelope:
        """Serialise this error into a stable :class:`ErrorEnvelope` for API responses."""
        return ErrorEnvelope(
            code=self.code,
            message=self.message,
            details=self.details,
            hint=self.hint,
            traceId=trace_id,
        )


class Datam8NotFoundError(Datam8Error):
    """Raised when a requested DataM8 resource cannot be located; maps to HTTP 404."""

    def __init__(
        self, *, code: str = "not_found", message: str, details: Any = None, hint: str | None = None
    ):
        """Initialize with exit code 3 and default code `not_found`."""
        super().__init__(code=code, message=message, details=details, hint=hint, exit_code=3)


class Datam8ValidationError(Datam8Error):
    """Raised when user-supplied data fails validation; maps to HTTP 422."""

    def __init__(
        self,
        *,
        code: str = "validation_error",
        message: str,
        details: Any = None,
        hint: str | None = None,
    ):
        """Initialize with exit code 2 and default code `validation_error`."""
        super().__init__(code=code, message=message, details=details, hint=hint, exit_code=2)


class ModelParseError(Exception):
    """Raised when one or more model JSON files cannot be parsed; aggregates inner exceptions."""

    def __init__(
        self,
        msg="Error(s) occured during model files parsing.",
        inner_exceptions: Sequence[Exception] = [],
    ):
        """Initialize, optionally collecting multiple inner parse exceptions."""
        Exception.__init__(self, msg)

        self.inner_exceptions = inner_exceptions
        self.message = msg

    def __str__(self) -> str:
        """Return string representation."""
        if not self.inner_exceptions:
            return self.message
        details = "\n".join(str(err) for err in self.inner_exceptions)
        return f"{self.message}\n{details}"


class NotSupportedModelVersionError(Exception):
    """Raised when a solution file declares a schema version that this generator does not support."""

    def __init__(self, version: str):
        """Initialize with the unsupported version string."""
        super().__init__(f"Tried to parse an unsupported model version: {version}")


class EntityNotFoundError(Exception):
    """Raised when a model entity cannot be found by locator, name, or ID."""

    def __init__(
        self,
        entity: str,
        msg: str = "Entity was not found in model: {}",
        inner_exceptions: list[Exception] | None = None,
    ):
        """Initialize with the missing entity identifier and an optional formatted message."""
        Exception.__init__(self, msg.format(entity))

        self.inner_exceptions = inner_exceptions
        self.message = msg.format(entity)


class InvalidLocatorError(Exception):
    """Raised when a locator string does not conform to the expected format."""

    def __init__(self, locator: str):
        """Initialize with the invalid locator value."""
        super().__init__(f"Not a valid locator: {locator}")


class PropertiesNotResolvedError(Exception):
    """Raised when properties of a model entity are accessed before they have been resolved."""

    def __init__(self, locator):
        """Initialize with the locator of the unresolved entity."""
        super().__init__(f"Tried to access properties of unresolved entity '{locator}' yet")


class InvalidGeneratorTargetError(Exception):
    """Raised when the requested generator target name is not declared in the solution file."""

    def __init__(self, target_name: str):
        """Initialize with the name of the missing generator target."""
        super().__init__(f"Generator target '{target_name}' is not defined")
