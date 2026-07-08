"""Extract trigger and stored procedure / function / package source code.

Source text from ``ALL_SOURCE`` is stored line-by-line and is assembled
into a single string per object.  The extractor streams it in batches to
handle schemas with thousands of large packages without running out of
memory.
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
class TriggerInfo:
    name: str
    table_name: str
    trigger_type: str       # BEFORE / AFTER / INSTEAD OF
    event: str              # INSERT, UPDATE, DELETE, or combinations
    status: str             # ENABLED / DISABLED
    source: str = ""        # Full PL/SQL source


@dataclass
class ProcedureInfo:
    name: str
    obj_type: str           # PROCEDURE | FUNCTION | PACKAGE | PACKAGE BODY
    source: str = ""        # Full PL/SQL source
    referenced_tables: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class SourceExtractor:
    """Extract trigger and procedure/function/package metadata and source.

    Parameters
    ----------
    reader:
        A :class:`~reversedb.db.chunked_reader.ChunkedReader` instance.
    schema:
        Oracle schema name (upper-case).
    """

    def __init__(self, reader: Any, schema: str) -> None:
        self._reader = reader
        self._schema = schema.upper()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_triggers(self) -> list[TriggerInfo]:
        """Return all triggers defined in the schema with their PL/SQL source."""
        logger.info("Extracting triggers for schema %s …", self._schema)
        sql = """
            SELECT trigger_name,
                   table_name,
                   trigger_type,
                   triggering_event,
                   status
            FROM   all_triggers
            WHERE  owner = :schema
            ORDER  BY trigger_name
        """
        rows = self._reader.fetch_all(sql, {"schema": self._schema})
        logger.info("  Found %d triggers.", len(rows))

        trigger_map = {
            r["trigger_name"]: TriggerInfo(
                name=r["trigger_name"],
                table_name=r["table_name"],
                trigger_type=r["trigger_type"],
                event=r["triggering_event"],
                status=r["status"],
            )
            for r in rows
        }

        self._attach_source(trigger_map, obj_type="TRIGGER")
        return list(trigger_map.values())

    def get_procedures(self) -> list[ProcedureInfo]:
        """Return procedures, functions, packages, and package bodies with source."""
        logger.info("Extracting procedures/functions/packages for schema %s …", self._schema)
        sql = """
            SELECT DISTINCT name, type
            FROM   all_source
            WHERE  owner = :schema
              AND  type IN ('PROCEDURE', 'FUNCTION', 'PACKAGE', 'PACKAGE BODY')
            ORDER  BY type, name
        """
        rows = self._reader.fetch_all(sql, {"schema": self._schema})
        logger.info("  Found %d source objects.", len(rows))

        proc_map: dict[str, ProcedureInfo] = {
            f"{r['type']}:{r['name']}": ProcedureInfo(name=r["name"], obj_type=r["type"])
            for r in rows
        }

        self._attach_procedure_source(proc_map)
        return list(proc_map.values())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _attach_source(self, obj_map: dict[str, Any], obj_type: str) -> None:
        """Fetch and assemble source lines for objects in *obj_map*."""
        sql = """
            SELECT name, line, text
            FROM   all_source
            WHERE  owner = :schema
              AND  type  = :obj_type
            ORDER  BY name, line
        """
        source_lines: dict[str, list[str]] = {}
        for batch in self._reader.stream_query(sql, {"schema": self._schema, "obj_type": obj_type}):
            for r in batch:
                source_lines.setdefault(r["name"], []).append(r["text"] or "")

        for name, lines in source_lines.items():
            if name in obj_map:
                obj_map[name].source = "".join(lines)

    def _attach_procedure_source(self, proc_map: dict[str, "ProcedureInfo"]) -> None:
        """Fetch source for procedures, functions, and packages."""
        sql = """
            SELECT type, name, line, text
            FROM   all_source
            WHERE  owner = :schema
              AND  type IN ('PROCEDURE', 'FUNCTION', 'PACKAGE', 'PACKAGE BODY')
            ORDER  BY type, name, line
        """
        source_lines: dict[str, list[str]] = {}
        for batch in self._reader.stream_query(sql, {"schema": self._schema}):
            for r in batch:
                key = f"{r['type']}:{r['name']}"
                source_lines.setdefault(key, []).append(r["text"] or "")

        for key, lines in source_lines.items():
            if key in proc_map:
                proc_map[key].source = "".join(lines)
