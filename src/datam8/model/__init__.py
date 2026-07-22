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
"""Public API for the DataM8 model package, re-exporting core types and helper functions."""

# along with this program. If not, see <https://www.gnu.org/licenses/>.

# ruff: noqa: F401

from __future__ import annotations

from pathlib import Path

from datam8_model import base as b

from .entity_wrapper import (
    EntityDict,
    EntityRepository,
    EntityWrapper,
    EntityWrapperVariant,
    PropertyReference,
)
from .locator import ROOT_LOCATOR, Locator
from .model import MODEL_DUMP_OPTIONS, Model


def wrap_base_entity[T: b.BaseEntityType](
    entity_type: b.EntityType, locator_path: Path, entity: T, source_file: Path
) -> EntityWrapper[T]:
    """Wrap a parsed solution entity into an `EntityWrapper` with a resolved `Locator`.

    Derive the locator from `locator_path` by splitting the POSIX path into
    folders (stripping the leading and trailing segments) and reading the
    entity name directly from `entity.name`.

    Parameters
    ----------
    entity_type : EntityType
        The entity type used as the locator's `entityType` segment.
    locator_path : Path
        File-system path whose intermediate segments become the locator folders.
        The first and last segments are stripped.
    entity : T
        The parsed entity whose `name` attribute becomes the locator's entity name.
    source_file : Path
        Absolute path to the JSON file this entity was read from.

    """
    locator = Locator(
        entityType=entity_type.value,
        folders=locator_path.as_posix().split("/")[1:-1],
        entityName=getattr(entity, "name"),  # noqa: B009
    )

    new_wrapper = EntityWrapper[T](
        locator=locator,
        entity=entity,
        source_file=source_file,
    )

    return new_wrapper


def new_empty_entity_type_dict() -> dict[b.EntityType, list[EntityWrapper[b.BaseEntityType]]]:
    """Create a dictionary with one empty list per `EntityType` member.

    The item type of each list is intentionally unspecified; callers should
    narrow the type themselves once they start populating a specific key.

    """
    return {_type: [] for _type in b.EntityType}
