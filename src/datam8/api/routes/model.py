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
"""HTTP routes for code generation, model persistence, and reload operations."""

# along with this program. If not, see <https://www.gnu.org/licenses/>.

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from datam8 import config, factory, generate, model, opts

model_router = APIRouter(prefix="/model", tags=["model"])


class GenerateBody(BaseModel):
    """Optional request body controlling a code generation run."""

    model_config = ConfigDict(populate_by_name=True)
    target: str | None = None
    clean_output: Annotated[bool | None, Field(alias="cleanOutput")] = None
    payloads: list[str] | None = None


class GenerateResponse(BaseModel):
    """Result of a completed code generation run, including the output path."""

    target: str | None
    output_path: Annotated[str | None, Field(alias="outputPath")] = None
    message: str | None = None


@model_router.post("/generate")
async def generator_run(body: GenerateBody | None = None) -> GenerateResponse:
    """Run code generation synchronously against the loaded model.

    Clears previously registered payload functions before each run to prevent
    duplicate registration errors in a long-lived server process.
    """
    # The API server is long-lived; decorators in target modules would otherwise
    # re-register payloads on subsequent runs and fail with "already registered".
    generate.payload_functions.clear()

    target = body.target if body is not None else None
    payloads = body.payloads if body is not None else None
    clean_output = body.clean_output if body is not None else None

    output_path = generate.generate_output(
        factory.get_model(),
        target=target or opts.default_target,
        payloads=payloads or [],
        clean_output=clean_output or False,
        generate_all=False,
    )

    response = GenerateResponse(
        target=target or opts.default_target,
        outputPath=output_path.as_posix(),
    )

    return response


class SaveBody(BaseModel):
    """Optional request body specifying a locator to limit which entities are persisted to disk."""

    locator: str | None = None


@model_router.post("/save")
async def model_save(body: SaveBody | None = None) -> None:
    """Persist in-memory model state to disk, optionally scoped to the locator supplied in the body."""
    factory.get_model().save(body.locator if body is not None else None)


class RealoadResponse(BaseModel):
    """Timestamp of the most recent model reload returned by `POST /model/reload`."""

    model_config = ConfigDict(populate_by_name=True)
    reloaded_at: Annotated[datetime, Field(alias="reloadedAt")]


@model_router.post("/reload")
async def model_reload(force: bool = False) -> RealoadResponse:
    """Reload the model from disk, discarding all in-memory changes.

    Raises a 409 when there are unsaved changes unless `force` is `True`.
    """
    pending_changes, pending_deletions = factory.get_model().get_unsaved_entities()
    if (len(pending_changes) > 0 or len(pending_deletions) > 0) and not force:
        pending = len(pending_changes) + len(pending_deletions)
        raise HTTPException(
            status_code=409, detail=f"Pending changes ({pending}) - save model or use force"
        )

    factory._model = await factory.load_model(config.solution_path)
    response = RealoadResponse(reloaded_at=datetime.now(UTC))

    return response


class UnsavedResponse(BaseModel):
    """Summary of entities with unsaved in-memory changes returned by `GET /model/unsaved`."""

    count: int
    changed: list[model.Locator]
    deleted: list[model.Locator]


@model_router.get("/unsaved")
async def get_unsaved() -> UnsavedResponse:
    """Return the count and locators of entities that have been modified or deleted but not yet saved."""
    changed, deleted = factory.get_model().get_unsaved_entities()
    response = UnsavedResponse(
        count=len(changed) + len(deleted),
        changed=changed,
        deleted=deleted,
    )
    return response
