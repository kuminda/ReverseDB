"""Extract inter-object dependencies from ALL_DEPENDENCIES.

This produces a directed graph (as an edge list) that shows which
procedures/functions/packages reference which tables, views, and other
stored objects.  The graph is later used by the reporter to build the
dependency section of the reverse-engineered document.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DependencyEdge:
    from_name: str
    from_type: str   # PROCEDURE | FUNCTION | PACKAGE | TRIGGER | …
    to_name: str
    to_type: str     # TABLE | VIEW | PROCEDURE | …
    to_owner: str


class DependencyExtractor:
    """Extract all dependency edges for the configured schema.

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

    def get_dependencies(self) -> list[DependencyEdge]:
        """Return every dependency edge originating from the schema."""
        logger.info("Extracting object dependencies for schema %s …", self._schema)
        sql = """
            SELECT name,
                   type,
                   referenced_owner,
                   referenced_name,
                   referenced_type
            FROM   all_dependencies
            WHERE  owner = :schema
            ORDER  BY name, referenced_name
        """
        edges: list[DependencyEdge] = []
        for batch in self._reader.stream_query(sql, {"schema": self._schema}):
            for r in batch:
                edges.append(
                    DependencyEdge(
                        from_name=r["name"],
                        from_type=r["type"],
                        to_name=r["referenced_name"],
                        to_type=r["referenced_type"],
                        to_owner=r["referenced_owner"],
                    )
                )
        logger.info("  Found %d dependency edges.", len(edges))
        return edges

    def build_table_procedure_map(
        self, edges: list[DependencyEdge]
    ) -> dict[str, list[str]]:
        """Return a mapping of table_name → [procedure/function/package names].

        Useful for the report section that lists which code objects reference
        each table.
        """
        mapping: dict[str, list[str]] = {}
        for edge in edges:
            if edge.to_type == "TABLE" and edge.from_type in (
                "PROCEDURE", "FUNCTION", "PACKAGE", "PACKAGE BODY", "TRIGGER"
            ):
                mapping.setdefault(edge.to_name, []).append(edge.from_name)
        # Deduplicate while preserving order
        return {tbl: list(dict.fromkeys(objs)) for tbl, objs in mapping.items()}
