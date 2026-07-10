"""Chunked and sampled data reader for large Oracle tables.

Design goals
------------
* For tables with **billions of rows**, never load more data than needed.
* Use Oracle's built-in ``SAMPLE`` clause to get a statistically random
  subset of rows without a full table scan.
* Provide a generic ``stream_query`` generator for any bounded query that
  must be consumed in batches (e.g. iterating over thousands of source-code
  lines stored in ``ALL_SOURCE``).

Oracle SAMPLE clause recap
--------------------------
``SELECT … FROM t SAMPLE(p)`` returns approximately ``p`` percent of rows
from the table using block sampling.  Valid range: 0.000001 – 99.999999.

For a 1-billion-row table:
* ``SAMPLE(0.01)`` ≈ 100,000 rows  (fast, no full scan)
* ``SAMPLE(0.001)`` ≈ 10,000 rows  (even faster)

We further limit with ``FETCH FIRST n ROWS ONLY`` to cap memory usage.
"""

from __future__ import annotations

import logging
from typing import Any, Generator, Sequence

import oracledb

logger = logging.getLogger(__name__)


class ChunkedReader:
    """Provides chunked / sampled reads against an open Oracle connection.

    Parameters
    ----------
    connector:
        An already-connected :class:`~reversedb.db.connector.OracleConnector`
        instance (used as a context manager in the caller).
    batch_size:
        Number of rows to fetch per ``fetchmany`` call (default 10 000).
    """

    def __init__(self, connector: Any, batch_size: int = 10_000) -> None:
        self._connector = connector
        self.batch_size = batch_size

    # ------------------------------------------------------------------
    # Sampled read (preferred for large tables)
    # ------------------------------------------------------------------

    def sample_table(
        self,
        table: str,
        columns: Sequence[str],
        sample_pct: float = 0.1,
        max_rows: int = 2_000,
        where_clause: str = "",
        bind_vars: dict | None = None,
    ) -> list[dict]:
        """Return a statistical sample of rows from *table*.

        Parameters
        ----------
        table:
            Fully-qualified table name, e.g. ``"MYSCHEMA.ORDERS"``.
        columns:
            Column names to select.  Pass ``["*"]`` for all columns.
        sample_pct:
            Percentage of rows to include via ``SAMPLE(sample_pct)``.
            Must be in the range 0.000001 – 99.999999.
        max_rows:
            Hard upper limit on returned rows (applied via
            ``FETCH FIRST … ROWS ONLY``).
        where_clause:
            Optional ``WHERE …`` clause (without the ``WHERE`` keyword).
        bind_vars:
            Bind variables dictionary matching the where_clause.
        """
        sample_pct = max(0.000001, min(99.999999, sample_pct))
        col_list = ", ".join(columns)
        where_sql = f"WHERE {where_clause}" if where_clause else ""
        sql = (
            f"SELECT {col_list} FROM {table} SAMPLE({sample_pct:.6f}) "
            f"{where_sql} "
            f"FETCH FIRST :max_rows ROWS ONLY"
        )
        params = dict(bind_vars or {})
        params["max_rows"] = max_rows

        logger.debug("sample_table: %s (pct=%.6f, max_rows=%d)", table, sample_pct, max_rows)
        with self._connector.managed_cursor() as cur:
            cur.execute(sql, params)
            col_names = [d[0].lower() for d in cur.description]
            rows = cur.fetchall()

        logger.debug("  → %d rows sampled from %s", len(rows), table)
        return [dict(zip(col_names, row)) for row in rows]

    # ------------------------------------------------------------------
    # Chunked full-read (for smaller / bounded queries)
    # ------------------------------------------------------------------

    def stream_query(
        self,
        sql: str,
        bind_vars: dict | None = None,
    ) -> Generator[list[dict], None, None]:
        """Execute *sql* and yield results as batches of dictionaries.

        Each yielded batch contains at most ``self.batch_size`` rows.
        The generator is lazy: the next batch is only fetched when the
        caller advances the iterator.

        Parameters
        ----------
        sql:
            A complete SELECT statement.
        bind_vars:
            Optional named bind-variable dictionary.

        Yields
        ------
        list[dict]
            A batch of rows represented as column-name → value mappings.
        """
        with self._connector.managed_cursor() as cur:
            cur.arraysize = self.batch_size
            cur.execute(sql, bind_vars or {})
            col_names = [d[0].lower() for d in cur.description]
            total = 0
            while True:
                rows = cur.fetchmany(self.batch_size)
                if not rows:
                    break
                total += len(rows)
                yield [dict(zip(col_names, row)) for row in rows]
        logger.debug("stream_query: %d total rows fetched", total)

    def fetch_all(
        self,
        sql: str,
        bind_vars: dict | None = None,
    ) -> list[dict]:
        """Convenience wrapper: consume :meth:`stream_query` into a list.

        Use only for queries that are guaranteed to return a bounded
        result set (e.g. data-dictionary queries on ``ALL_TABLES``).
        """
        result: list[dict] = []
        for batch in self.stream_query(sql, bind_vars):
            result.extend(batch)
        return result
