"""Extract table, column, and constraint metadata from Oracle data dictionary.

All queries target the ``ALL_*`` views so the tool works whether the
connecting user owns the schema or has been granted SELECT on those views.
The owner is filtered by the configured schema name.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    data_length: int | None
    nullable: bool
    position: int


@dataclass
class ConstraintInfo:
    name: str
    constraint_type: str          # P, U, R, C
    columns: list[str] = field(default_factory=list)
    ref_owner: str | None = None
    ref_table: str | None = None  # resolved from r_constraint_name
    ref_columns: list[str] = field(default_factory=list)


@dataclass
class TableInfo:
    name: str
    num_rows: int | None          # from ALL_TABLES stats (may be None if stale)
    last_analyzed: Any | None
    columns: list[ColumnInfo] = field(default_factory=list)
    constraints: list[ConstraintInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class MetadataExtractor:
    """Extract table, column, and constraint metadata for a given schema.

    Parameters
    ----------
    reader:
        A :class:`~reversedb.db.chunked_reader.ChunkedReader` instance
        backed by an open connection.
    schema:
        Oracle schema name (upper-case).
    """

    def __init__(self, reader: Any, schema: str) -> None:
        self._reader = reader
        self._schema = schema.upper()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self) -> list[TableInfo]:
        """Return fully populated :class:`TableInfo` objects for every table
        in the configured schema."""
        logger.info("Extracting table list for schema %s …", self._schema)
        tables = self._get_tables()
        logger.info("  Found %d tables.", len(tables))

        logger.info("Extracting columns …")
        columns_by_table = self._get_columns()

        logger.info("Extracting constraints …")
        constraints_by_table = self._get_constraints()

        for tbl in tables:
            tbl.columns = columns_by_table.get(tbl.name, [])
            tbl.constraints = constraints_by_table.get(tbl.name, [])

        return tables

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_tables(self) -> list[TableInfo]:
        sql = """
            SELECT table_name,
                   num_rows,
                   last_analyzed
            FROM   all_tables
            WHERE  owner = :schema
            ORDER  BY table_name
        """
        rows = self._reader.fetch_all(sql, {"schema": self._schema})
        return [
            TableInfo(
                name=r["table_name"],
                num_rows=r["num_rows"],
                last_analyzed=r["last_analyzed"],
            )
            for r in rows
        ]

    def _get_columns(self) -> dict[str, list[ColumnInfo]]:
        sql = """
            SELECT table_name,
                   column_name,
                   data_type,
                   data_length,
                   nullable,
                   column_id
            FROM   all_tab_columns
            WHERE  owner = :schema
            ORDER  BY table_name, column_id
        """
        result: dict[str, list[ColumnInfo]] = {}
        for batch in self._reader.stream_query(sql, {"schema": self._schema}):
            for r in batch:
                tbl = r["table_name"]
                result.setdefault(tbl, []).append(
                    ColumnInfo(
                        name=r["column_name"],
                        data_type=r["data_type"],
                        data_length=r["data_length"],
                        nullable=(r["nullable"] == "Y"),
                        position=r["column_id"],
                    )
                )
        return result

    def _get_constraints(self) -> dict[str, list[ConstraintInfo]]:
        """Fetch PK, UK, FK, and CHECK constraints with their column lists."""
        # Step 1: constraint headers
        sql_hdr = """
            SELECT c.table_name,
                   c.constraint_name,
                   c.constraint_type,
                   c.r_owner,
                   c.r_constraint_name
            FROM   all_constraints c
            WHERE  c.owner = :schema
              AND  c.constraint_type IN ('P', 'U', 'R', 'C')
            ORDER  BY c.table_name, c.constraint_type, c.constraint_name
        """
        headers = self._reader.fetch_all(sql_hdr, {"schema": self._schema})

        # Collect FK r_constraint_names so we can resolve the referenced table
        r_names = {
            r["r_constraint_name"]
            for r in headers
            if r["r_constraint_name"] is not None
        }

        # Step 2: resolve referenced constraint → table name
        ref_table_map: dict[str, str] = {}
        if r_names:
            # Oracle doesn't support IN(:list) for bind vars; build literal
            quoted = ", ".join(f"'{n}'" for n in r_names)
            sql_ref = f"""
                SELECT constraint_name, table_name
                FROM   all_constraints
                WHERE  constraint_name IN ({quoted})
            """
            for row in self._reader.fetch_all(sql_ref):
                ref_table_map[row["constraint_name"]] = row["table_name"]

        # Step 3: constraint columns
        sql_cols = """
            SELECT constraint_name, column_name, position
            FROM   all_cons_columns
            WHERE  owner = :schema
            ORDER  BY constraint_name, position
        """
        cols_by_constraint: dict[str, list[str]] = {}
        for batch in self._reader.stream_query(sql_cols, {"schema": self._schema}):
            for r in batch:
                cols_by_constraint.setdefault(r["constraint_name"], []).append(
                    r["column_name"]
                )

        # Step 4: assemble ConstraintInfo objects
        result: dict[str, list[ConstraintInfo]] = {}
        for r in headers:
            r_tbl = None
            if r["r_constraint_name"]:
                r_tbl = ref_table_map.get(r["r_constraint_name"])
            ci = ConstraintInfo(
                name=r["constraint_name"],
                constraint_type=r["constraint_type"],
                columns=cols_by_constraint.get(r["constraint_name"], []),
                ref_owner=r["r_owner"],
                ref_table=r_tbl,
                ref_columns=cols_by_constraint.get(r["r_constraint_name"] or "", []),
            )
            result.setdefault(r["table_name"], []).append(ci)

        return result
