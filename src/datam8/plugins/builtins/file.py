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
"""Built-in plugin for reading local CSV files as a DataM8 data source."""

# along with this program. If not, see <https://www.gnu.org/licenses/>.

import functools
from pathlib import Path
from typing import Final

import polars as pl

from datam8 import config, logging, utils
from datam8.plugins.base import Plugin, TableMetadata
from datam8_model.data_source import (
    AuthMode,
    ConnectionProperty,
    ConnectionPropertyValueType,
    SourceDataTypeMapping,
    SourceObject,
)
from datam8_model.plugin import Capability, PluginManifest

logger = logging.getLogger(__name__)

DATA_TYPE_MAPPINGS: Final[dict[str, str]] = {
    "string": "string",
    "number": "decimal",
}
"Mapping from source type to DataM8 internal type"


manifest_csv = PluginManifest(
    id="builtin:CsvFile",
    displayName="Local CSV File (builtin)",
    version=config.get_version(),
    entryPoint="datam8.plugins.builtins.file:CsvFile",
    capabilities=[
        Capability.METADATA,
        Capability.UI_SCHEMA,
        Capability.VALIDATION_CONNECTION,
    ],
)


class CsvFile(Plugin):
    """Built-in plugin that reads local CSV files using Polars."""

    __manifest: PluginManifest = manifest_csv

    def _get_path(self) -> Path:
        protocol = self.extended_properties.pop("protocol")
        file_path = self.extended_properties.pop("path")

        match [protocol, file_path]:
            case ["file", path]:
                path = Path(path)
            case [unknown, _]:
                raise utils.create_error(f"Protocol '{unknown}' is not implemented for CsvFiles")
            case _:
                raise utils.create_error("Should not be reached, is a bug...")

        return path

    def test_connection(self) -> Exception | None:
        """Verify that the configured base directory exists on the local filesystem."""
        path = self._get_path()
        if not path.exists():
            raise utils.create_error(
                FileNotFoundError(
                    f"Directory '{path}' for data source '{self._data_source.name}' not found"
                )
            )

    def list_source(self, source_location: str | None = None, /) -> pl.DataFrame:
        """Return a DataFrame of CSV files and subdirectories under the configured path.

        Parameters
        ----------
        source_location : str | None
            Sub-path relative to the data source root to list; lists root when `None`.

        """
        if source_location is not None:
            _, path = self.parse_source_location(source_location)
            path = self._get_path() / path
        else:
            path = self._get_path()

        objects: list[str] = []
        types: list[str] = []

        for p in path.iterdir():
            if p.is_dir() or p.name.endswith(".csv"):
                objects.append(p.name)
                types.append("DIRECTORY" if p.is_dir() else "FILE")

        data = {"schema": path, "object": objects, "type": types}
        return pl.DataFrame(data)

    def preview_data(self, source_location: str, *, limit: int = 10) -> pl.LazyFrame:
        """Read up to `limit` rows from the CSV file at `source_location`."""
        _, path = self.parse_source_location(source_location)
        path = self._get_path() / path

        try:
            df = pl.read_csv(path, sample_size=limit, **self.extended_properties)
        except Exception as err:
            raise utils.create_error(f"Could not read csv file: {err}") from err

        return df.lazy()

    def get_table_metadata(self, source_location: str, /) -> TableMetadata:
        """Infer column names and types from the CSV schema without reading all rows."""
        _, table = self.parse_source_location(source_location)
        path = self._get_path()
        lf = pl.scan_csv(path / table, **self.extended_properties)
        polars_schema = lf.collect_schema()
        metadata = pl.DataFrame(
            {
                "ordinal": list(range(1, len(polars_schema) + 1)),
                "name": polars_schema.names(),
                "dataType": [
                    "number" if dtype.base_type().is_numeric() else "string"
                    for dtype in polars_schema.values()
                ],
                "numericPrecision": [
                    dtype.precision if isinstance(dtype, pl.Decimal) else None
                    for dtype in polars_schema.values()
                ],
                "numericScale": [
                    dtype.scale if isinstance(dtype, pl.Decimal) else None
                    for dtype in polars_schema.values()
                ],
                "maxLength": [None for _ in range(len(polars_schema))],
            },
            schema_overrides={
                "numericPrecision": pl.Int64,
                "numericScale": pl.Int64,
                "maxLength": pl.Int64,
            },
        )
        return TableMetadata(metadata, SourceObject(schema=None, name=table, type="FILE"))

    @classmethod
    def manifest(cls) -> PluginManifest:
        """Return the manifest for the built-in CsvFile plugin."""
        return cls.__manifest

    @staticmethod
    def create_source_location(table: str, schema: str | None = None) -> str:
        """Return a source location string for the given file path; schema is ignored for CSV files."""
        return table

    @staticmethod
    def parse_source_location(source_location: str) -> tuple[str, str]:
        """Return `("", source_location)` — CSV files have no schema component."""
        return "", source_location

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def get_auth_modes() -> list[AuthMode]:
        """Return the single anonymous/no-auth mode that requires only `path` and `protocol`."""
        auth_modes = [
            AuthMode(
                name="no_auth", displayName="No Auth / Anonymous", required=["path", "protocol"]
            ),
        ]
        return auth_modes

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def get_data_type_mappings() -> list[SourceDataTypeMapping]:
        """Return mappings from CSV inferred types (`string`, `number`) to DataM8 canonical types."""
        global DATA_TYPE_MAPPINGS

        return [
            SourceDataTypeMapping(sourceType=src, targetType=trg)
            for src, trg in DATA_TYPE_MAPPINGS.items()
        ]

    @classmethod
    def resolve_source_type(cls, source_type: str, /) -> str:
        """Map a CSV source type to its DataM8 canonical type, raising `ValueError` for unknown types."""
        global DATA_TYPE_MAPPINGS

        if source_type not in DATA_TYPE_MAPPINGS:
            raise ValueError(f"'{source_type}' is not a configured type for '{cls.manifest().id}'")

        return DATA_TYPE_MAPPINGS[source_type]

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def get_connection_properties() -> list[ConnectionProperty]:
        """Return connection properties: required `path`, optional `protocol` and `has_header`."""
        cps = [
            ConnectionProperty(name="path", required=True, type=ConnectionPropertyValueType.STRING),
            ConnectionProperty(
                name="protocol",
                required=False,
                type=ConnectionPropertyValueType.STRING,
                default="file",
            ),
            ConnectionProperty(
                name="has_header",
                required=False,
                type=ConnectionPropertyValueType.BOOLEAN,
                default=True,
            ),
        ]
        return cps
