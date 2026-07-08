"""Heuristic scoring rules used to classify Oracle tables.

Each rule is a simple function that receives a ``TableInfo`` and returns an
integer score (0 = no evidence, positive = evidence for that category).
The ``TableClassifier`` sums scores from all rules to decide the most likely
category.

Rules are deliberately kept separate so they can be unit-tested and tuned
independently of the classifier orchestration logic.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reversedb.extractors.metadata import TableInfo

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_TXN_NAME_KEYWORDS = {
    "TXN", "TRANSACTION", "TRANS", "ORDER", "PAYMENT", "INVOICE",
    "RECEIPT", "JOURNAL", "LEDGER", "POSTING", "SETTLEMENT", "CLEARING",
    "EVENT", "LOG", "AUDIT", "HISTORY", "ACTIVITY", "ENTRY", "MOVEMENT",
    "TRANSFER", "DISPATCH", "SHIPMENT", "BOOKING",
}

_REF_NAME_KEYWORDS = {
    "TYPE", "CODE", "LOOKUP", "REF", "REFERENCE", "STATUS", "STATE",
    "CATEGORY", "CLASS", "GROUP", "ENUM", "LIST", "REASON", "FLAG",
    "MODE", "PRIORITY", "LEVEL", "GRADE", "CURRENCY", "COUNTRY",
    "LANGUAGE", "REGION", "ZONE",
}

_MASTER_NAME_KEYWORDS = {
    "MASTER", "CUSTOMER", "CLIENT", "ACCOUNT", "PRODUCT", "ITEM",
    "SUPPLIER", "VENDOR", "EMPLOYEE", "STAFF", "PARTY", "PERSON",
    "ENTITY", "ASSET", "LOCATION", "SITE", "BRANCH", "DEPARTMENT",
    "ORGANISATION", "ORGANIZATION", "CONTACT", "PROFILE", "MEMBER",
}

_PARAM_NAME_KEYWORDS = {
    "PARAM", "PARAMETER", "CONFIG", "CONFIGURATION", "SETTING",
    "CONTROL", "OPTION", "PROPERTY", "PREFERENCE", "SYSTEM",
    "GLOBAL", "RUNTIME", "RULE", "POLICY",
}

# Column name substrings that indicate a transaction table
_TXN_COLUMN_HINTS = {
    "STATUS", "STATE", "TXN_DATE", "TRANS_DATE", "CREATED_DATE",
    "POSTED_DATE", "EFFECTIVE_DATE", "VALUE_DATE", "PROCESS_DATE",
    "APPROVAL", "REFERENCE_NO", "DOC_NO", "VOUCHER",
}

# Column name patterns that indicate a reference / code table
_REF_COLUMN_HINTS = {"CODE", "DESCR", "DESCRIPTION", "SHORT_CODE", "LONG_DESC"}

# Column name patterns that indicate a system parameter table
_PARAM_COLUMN_HINTS = {
    "PARAM_VALUE", "PARAM_NAME", "CONFIG_VALUE", "CONFIG_KEY",
    "SETTING_VALUE", "SETTING_NAME", "PROP_VALUE", "PROP_NAME",
}

# ---------------------------------------------------------------------------
# Individual scoring functions
# ---------------------------------------------------------------------------


def _name_score(table_name: str, keyword_set: set[str]) -> int:
    """Return 2 if any keyword appears as a word segment in the table name."""
    parts = set(re.split(r"[_\s]", table_name.upper()))
    return 2 if parts & keyword_set else 0


def _column_score(table: "TableInfo", column_hints: set[str]) -> int:
    """Return 1 for each column whose name (or a segment of it) matches a hint."""
    col_names = {c.name.upper() for c in table.columns}
    col_parts: set[str] = set()
    for name in col_names:
        col_parts.update(re.split(r"[_\s]", name))
    return len(col_parts & column_hints)


def _row_count_score_txn(num_rows: int | None) -> int:
    """High row count is strong evidence of a transaction table."""
    if num_rows is None:
        return 0
    if num_rows >= 1_000_000:
        return 4
    if num_rows >= 100_000:
        return 2
    if num_rows >= 10_000:
        return 1
    return 0


def _row_count_score_ref(num_rows: int | None, threshold: int) -> int:
    """Very low row count is evidence of reference/lookup data."""
    if num_rows is None:
        return 1  # unknown – slight lean toward ref
    if num_rows <= threshold:
        return 3
    return 0


def _row_count_score_param(num_rows: int | None, threshold: int) -> int:
    """Tiny row count is evidence of a system-parameter table."""
    if num_rows is None:
        return 0
    if num_rows <= threshold:
        return 3
    return 0


def _fk_referenced_score(table_name: str, fk_ref_counts: dict[str, int]) -> int:
    """Tables referenced by many FK constraints are likely master data."""
    count = fk_ref_counts.get(table_name, 0)
    if count >= 10:
        return 4
    if count >= 5:
        return 2
    if count >= 2:
        return 1
    return 0


def _has_date_column(table: "TableInfo") -> int:
    """Date/timestamp columns are common in transaction tables."""
    for col in table.columns:
        if col.data_type in ("DATE", "TIMESTAMP") or "DATE" in col.name.upper():
            return 1
    return 0


# ---------------------------------------------------------------------------
# Public composite scorers
# ---------------------------------------------------------------------------


def score_transaction(
    table: "TableInfo",
    fk_ref_counts: dict[str, int],
) -> int:
    return (
        _name_score(table.name, _TXN_NAME_KEYWORDS)
        + _column_score(table, _TXN_COLUMN_HINTS)
        + _row_count_score_txn(table.num_rows)
        + _has_date_column(table)
    )


def score_reference(
    table: "TableInfo",
    ref_data_max_rows: int,
) -> int:
    return (
        _name_score(table.name, _REF_NAME_KEYWORDS)
        + _column_score(table, _REF_COLUMN_HINTS)
        + _row_count_score_ref(table.num_rows, ref_data_max_rows)
    )


def score_master(
    table: "TableInfo",
    fk_ref_counts: dict[str, int],
) -> int:
    return (
        _name_score(table.name, _MASTER_NAME_KEYWORDS)
        + _fk_referenced_score(table.name, fk_ref_counts)
    )


def score_system_param(
    table: "TableInfo",
    param_table_max_rows: int,
) -> int:
    return (
        _name_score(table.name, _PARAM_NAME_KEYWORDS)
        + _column_score(table, _PARAM_COLUMN_HINTS)
        + _row_count_score_param(table.num_rows, param_table_max_rows)
    )
