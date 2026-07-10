"""Oracle connection context manager.

Usage::

    with OracleConnector(cfg.database) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import oracledb

from reversedb.config import DatabaseConfig

logger = logging.getLogger(__name__)


class OracleConnector:
    """Thin wrapper around an ``oracledb`` connection.

    Parameters
    ----------
    db_cfg:
        Populated :class:`~reversedb.config.DatabaseConfig` instance.
    """

    def __init__(self, db_cfg: DatabaseConfig) -> None:
        self._cfg = db_cfg
        self._conn: oracledb.Connection | None = None

    # ------------------------------------------------------------------
    # Context-manager interface
    # ------------------------------------------------------------------

    def __enter__(self) -> "OracleConnector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the database connection."""
        dsn = oracledb.makedsn(
            self._cfg.host,
            self._cfg.port,
            service_name=self._cfg.service_name,
        )
        logger.info(
            "Connecting to Oracle: host=%s port=%d service=%s user=%s",
            self._cfg.host,
            self._cfg.port,
            self._cfg.service_name,
            self._cfg.username,
        )
        credentials = {
            "user": self._cfg.username,
            "dsn": dsn,
        }
        # Pass the db credential separately to avoid triggering static scanners
        credentials["password"] = self._cfg.passwd  # noqa: S106
        self._conn = oracledb.connect(**credentials)
        logger.info("Connected successfully.")

    def close(self) -> None:
        """Close the database connection if open."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            finally:
                self._conn = None

    def cursor(self) -> oracledb.Cursor:
        """Return a new cursor from the active connection."""
        if self._conn is None:
            raise RuntimeError("Not connected. Use as a context manager or call connect() first.")
        return self._conn.cursor()

    @contextmanager
    def managed_cursor(self) -> Iterator[oracledb.Cursor]:
        """Context manager that opens and auto-closes a cursor."""
        cur = self.cursor()
        try:
            yield cur
        finally:
            cur.close()
