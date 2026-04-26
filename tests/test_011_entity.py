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

import pytest

from datam8 import errors
from datam8.model import Model, PropertyReference


def test_ensure_locator(model: Model):
    # actual locator
    case_1 = next(model.modelEntities.iter())
    assert model.modelEntities.get(case_1)

    # string without type
    case_2 = case_1.without_type()
    assert model.modelEntities.get(case_2)

    # string with type
    case_3 = str(case_1)
    assert model.modelEntities.get(case_3)

    # dictionary syntax
    assert model["modelEntities"][case_2]


def test_get_raises(model: Model):
    with pytest.raises(errors.EntityNotFoundError):
        model.modelEntities.get("modelEntities/dummy")


def test_get_all(model: Model):
    wrappers = model.modelEntities.get_all()

    assert len(wrappers) == len(model.modelEntities)


def test_get_where(model: Model):
    loc = next(model.modelEntities.iter())

    assert model.modelEntities.get_many_where(
        lambda w: w.entity.name == loc.entityName,
        locator=f"{loc.folders[0]}/",
    ), f"{loc}"


def test_get_where_raises(model: Model):
    with pytest.raises(Exception):
        model.modelEntities.get_where(lambda w: type(w.entity.name) is str)


def test_add_raises(model: Model):
    loc, wrapper = next(model.modelEntities.items())
    with pytest.raises(Exception):
        model.modelEntities.add(loc, wrapper)


def test_remove_raises(model: Model):
    with pytest.raises(errors.EntityNotFoundError):
        model.modelEntities.remove("modelEntities/dummy")


def test_remove(model: Model):
    loc = next(model.modelEntities.iter())
    model.modelEntities.remove(loc)


def test_delitem(model: Model):
    loc = next(model.modelEntities.iter())
    del model.modelEntities[loc]


def test_property_reference_comparisons(model: Model):
    # get any wrapper that has properties
    wrapper = model.modelEntities.get_many_where(lambda w: len(w.entity.properties or []) > 1).pop()
    # just for type hinting
    assert wrapper.entity.properties is not None and len(wrapper.entity.properties) > 0

    original_ref = wrapper.entity.properties[0]
    prop_ref = PropertyReference.from_model_ref(original_ref)
    prop_ref_2 = PropertyReference.from_model_ref(original_ref)

    # equal operations
    assert prop_ref == original_ref
    assert prop_ref != ""
    assert prop_ref == prop_ref_2

    # hashing
    dummy_dict = {
        prop_ref: True,
    }
    _ = dummy_dict[prop_ref]


def test_entity_wrapper_comparison(model: Model):
    wrapper = next(model.modelEntities.values())
    assert wrapper == wrapper
    assert wrapper != ""
