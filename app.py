"""ReverseDB — Streamlit interface for the demo pipeline.

Launch with:
    streamlit run app.py

No Oracle connection is required.  The app runs the same self-contained
pipeline that is documented in ReverseDB_Demo.ipynb, using a built-in
sample schema (LEGACY_ERP) so you can explore the tool immediately.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import streamlit as st

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ReverseDB – Demo",
    page_icon="🔍",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# Data-transfer objects  (mirrors reversedb/config.py and extractors/)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisConfig:
    schema: str
    batch_size: int = 10_000
    data_sample_pct: float = 0.1
    max_sample_rows: int = 2_000
    ref_data_max_rows: int = 10_000
    param_table_max_rows: int = 1_000


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
    constraint_type: str
    columns: list[str] = field(default_factory=list)
    ref_owner: str | None = None
    ref_table: str | None = None
    ref_columns: list[str] = field(default_factory=list)


@dataclass
class TableInfo:
    name: str
    num_rows: int | None
    last_analyzed: Any | None
    columns: list[ColumnInfo] = field(default_factory=list)
    constraints: list[ConstraintInfo] = field(default_factory=list)


@dataclass
class TriggerInfo:
    name: str
    table_name: str
    trigger_type: str
    event: str
    status: str
    source: str = ""


@dataclass
class ProcedureInfo:
    name: str
    obj_type: str
    source: str = ""
    referenced_tables: list[str] = field(default_factory=list)


@dataclass
class DependencyEdge:
    from_name: str
    from_type: str
    to_name: str
    to_type: str
    to_owner: str


# ─────────────────────────────────────────────────────────────────────────────
# Classification rules  (mirrors reversedb/classifiers/rules.py)
# ─────────────────────────────────────────────────────────────────────────────

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
_TXN_COLUMN_HINTS = {
    "STATUS", "STATE", "TXN_DATE", "TRANS_DATE", "CREATED_DATE",
    "POSTED_DATE", "EFFECTIVE_DATE", "VALUE_DATE", "PROCESS_DATE",
    "APPROVAL", "REFERENCE_NO", "DOC_NO", "VOUCHER",
}
_REF_COLUMN_HINTS = {"CODE", "DESCR", "DESCRIPTION", "SHORT_CODE", "LONG_DESC"}
_PARAM_COLUMN_HINTS = {
    "PARAM_VALUE", "PARAM_NAME", "CONFIG_VALUE", "CONFIG_KEY",
    "SETTING_VALUE", "SETTING_NAME", "PROP_VALUE", "PROP_NAME",
}


def _name_score(table_name: str, kw: set) -> int:
    return 2 if set(re.split(r"[_\s]", table_name.upper())) & kw else 0


def _column_score(table: TableInfo, hints: set) -> int:
    parts: set[str] = set()
    for c in table.columns:
        parts.update(re.split(r"[_\s]", c.name.upper()))
    return len(parts & hints)


def _row_count_score_txn(n):
    if n is None:
        return 0
    if n >= 1_000_000:
        return 4
    if n >= 100_000:
        return 2
    if n >= 10_000:
        return 1
    return 0


def _row_count_score_ref(n, threshold):
    if n is None:
        return 1
    return 3 if n <= threshold else 0


def _row_count_score_param(n, threshold):
    if n is None:
        return 0
    return 3 if n <= threshold else 0


def _fk_referenced_score(name, fk_counts):
    c = fk_counts.get(name, 0)
    if c >= 10:
        return 4
    if c >= 5:
        return 2
    if c >= 2:
        return 1
    return 0


def _has_date_column(table: TableInfo) -> int:
    return 1 if any(
        c.data_type in ("DATE", "TIMESTAMP") or "DATE" in c.name.upper()
        for c in table.columns
    ) else 0


def score_transaction(table, fk_counts):
    return (
        _name_score(table.name, _TXN_NAME_KEYWORDS)
        + _column_score(table, _TXN_COLUMN_HINTS)
        + _row_count_score_txn(table.num_rows)
        + _has_date_column(table)
    )


def score_reference(table, ref_max):
    return (
        _name_score(table.name, _REF_NAME_KEYWORDS)
        + _column_score(table, _REF_COLUMN_HINTS)
        + _row_count_score_ref(table.num_rows, ref_max)
    )


def score_master(table, fk_counts):
    return (
        _name_score(table.name, _MASTER_NAME_KEYWORDS)
        + _fk_referenced_score(table.name, fk_counts)
    )


def score_system_param(table, param_max):
    return (
        _name_score(table.name, _PARAM_NAME_KEYWORDS)
        + _column_score(table, _PARAM_COLUMN_HINTS)
        + _row_count_score_param(table.num_rows, param_max)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Table classifier  (mirrors reversedb/classifiers/table_classifier.py)
# ─────────────────────────────────────────────────────────────────────────────

class TableCategory(str, Enum):
    TRANSACTION  = "Transaction"
    REFERENCE    = "Reference Data"
    MASTER       = "Master Data"
    SYSTEM_PARAM = "System Parameter"
    UNKNOWN      = "Unknown"


@dataclass
class ClassificationResult:
    table_name: str
    category: TableCategory
    scores: dict
    ai_confirmed: bool = False
    ai_override: "TableCategory | None" = None


_PRIORITY = {
    TableCategory.SYSTEM_PARAM.value: 4,
    TableCategory.REFERENCE.value:    3,
    TableCategory.MASTER.value:       2,
    TableCategory.TRANSACTION.value:  1,
}


def _build_fk_ref_counts(tables):
    counts: dict[str, int] = {}
    for tbl in tables:
        for con in tbl.constraints:
            if con.constraint_type == "R" and con.ref_table:
                counts[con.ref_table] = counts.get(con.ref_table, 0) + 1
    return counts


def classify_tables(tables: list, cfg: AnalysisConfig) -> list:
    fk_counts = _build_fk_ref_counts(tables)
    results = []
    for tbl in tables:
        scores = {
            TableCategory.TRANSACTION.value:  score_transaction(tbl, fk_counts),
            TableCategory.REFERENCE.value:    score_reference(tbl, cfg.ref_data_max_rows),
            TableCategory.MASTER.value:       score_master(tbl, fk_counts),
            TableCategory.SYSTEM_PARAM.value: score_system_param(tbl, cfg.param_table_max_rows),
        }
        best = max(scores.values())
        if best == 0:
            category = TableCategory.UNKNOWN
        else:
            best_name = max(
                (k for k, v in scores.items() if v == best),
                key=lambda k: _PRIORITY.get(k, 0),
            )
            category = TableCategory(best_name)
        results.append(
            ClassificationResult(table_name=tbl.name, category=category, scores=scores)
        )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Report builder + Markdown writer  (mirrors reversedb/reporters/)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ColumnEntry:
    name: str
    data_type: str
    nullable: bool


@dataclass
class TransactionEntry:
    table_name: str
    num_rows: "int | None"
    ai_confirmed: bool = False
    ai_note: "str | None" = None
    columns: list = field(default_factory=list)
    status_columns: list = field(default_factory=list)
    date_columns: list = field(default_factory=list)
    fk_refs: list = field(default_factory=list)
    triggers: list = field(default_factory=list)
    procedures: list = field(default_factory=list)


@dataclass
class ReferenceEntry:
    table_name: str
    num_rows: "int | None"
    ai_confirmed: bool = False
    ai_note: "str | None" = None
    columns: list = field(default_factory=list)
    fk_consumers: list = field(default_factory=list)
    owner: str = "Admin / System"


@dataclass
class MasterEntry:
    table_name: str
    num_rows: "int | None"
    ai_confirmed: bool = False
    ai_note: "str | None" = None
    primary_key: list = field(default_factory=list)
    columns: list = field(default_factory=list)
    fk_consumers: list = field(default_factory=list)
    procedures: list = field(default_factory=list)


@dataclass
class SystemParamEntry:
    table_name: str
    num_rows: "int | None"
    ai_confirmed: bool = False
    ai_note: "str | None" = None
    key_columns: list = field(default_factory=list)
    value_columns: list = field(default_factory=list)
    procedures: list = field(default_factory=list)


@dataclass
class ReportDocument:
    schema: str
    generated_at: str
    total_tables: int
    total_triggers: int
    total_procedures: int
    transactions: list = field(default_factory=list)
    references: list = field(default_factory=list)
    masters: list = field(default_factory=list)
    system_params: list = field(default_factory=list)
    unknown_tables: list = field(default_factory=list)


def build_document(schema, tables, triggers, procedures, classifications, table_proc_map):
    tables_idx = {t.name: t for t in tables}
    triggers_by: dict[str, list] = {}
    for trg in triggers:
        triggers_by.setdefault(trg.table_name, []).append(trg.name)
    fk_consumers: dict[str, list] = {}
    for tbl in tables:
        for con in tbl.constraints:
            if con.constraint_type == "R" and con.ref_table:
                fk_consumers.setdefault(con.ref_table, []).append(tbl.name)

    doc = ReportDocument(
        schema=schema,
        generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        total_tables=len(tables),
        total_triggers=len(triggers),
        total_procedures=len(procedures),
    )

    def _cols(tbl):
        return [ColumnEntry(c.name, c.data_type, c.nullable) for c in tbl.columns]

    def _ai_note(clf):
        if clf.ai_override:
            return (
                f"AI override: heuristic `{clf.category.value}` → AI `{clf.ai_override.value}`"
            )
        return None

    for clf in classifications:
        tbl = tables_idx.get(clf.table_name)
        if tbl is None:
            continue
        cat = clf.ai_override or clf.category
        note = _ai_note(clf)

        if cat == TableCategory.TRANSACTION:
            status_cols = [
                c.name for c in tbl.columns
                if any(k in c.name.upper() for k in ("STATUS", "STATE", "APPROVAL"))
            ]
            date_cols = [
                c.name for c in tbl.columns
                if c.data_type in ("DATE", "TIMESTAMP") or "DATE" in c.name.upper()
            ]
            fk_refs = list(dict.fromkeys(
                con.ref_table for con in tbl.constraints
                if con.constraint_type == "R" and con.ref_table
            ))
            doc.transactions.append(TransactionEntry(
                table_name=tbl.name, num_rows=tbl.num_rows,
                ai_confirmed=clf.ai_confirmed, ai_note=note,
                columns=_cols(tbl), status_columns=status_cols,
                date_columns=date_cols, fk_refs=fk_refs,
                triggers=triggers_by.get(tbl.name, []),
                procedures=table_proc_map.get(tbl.name, []),
            ))
        elif cat == TableCategory.REFERENCE:
            doc.references.append(ReferenceEntry(
                table_name=tbl.name, num_rows=tbl.num_rows,
                ai_confirmed=clf.ai_confirmed, ai_note=note,
                columns=_cols(tbl),
                fk_consumers=list(dict.fromkeys(fk_consumers.get(tbl.name, []))),
            ))
        elif cat == TableCategory.MASTER:
            pk = next((con.columns for con in tbl.constraints if con.constraint_type == "P"), [])
            doc.masters.append(MasterEntry(
                table_name=tbl.name, num_rows=tbl.num_rows,
                ai_confirmed=clf.ai_confirmed, ai_note=note,
                primary_key=pk, columns=_cols(tbl),
                fk_consumers=list(dict.fromkeys(fk_consumers.get(tbl.name, []))),
                procedures=table_proc_map.get(tbl.name, []),
            ))
        elif cat == TableCategory.SYSTEM_PARAM:
            key_hints = {"PARAM_NAME", "CONFIG_KEY", "SETTING_NAME", "PROP_NAME", "NAME", "KEY"}
            val_hints = {"PARAM_VALUE", "CONFIG_VALUE", "SETTING_VALUE", "PROP_VALUE", "VALUE", "DATA"}
            doc.system_params.append(SystemParamEntry(
                table_name=tbl.name, num_rows=tbl.num_rows,
                ai_confirmed=clf.ai_confirmed, ai_note=note,
                key_columns=[c.name for c in tbl.columns if c.name.upper() in key_hints],
                value_columns=[c.name for c in tbl.columns if c.name.upper() in val_hints],
                procedures=table_proc_map.get(tbl.name, []),
            ))
        else:
            doc.unknown_tables.append(tbl.name)

    return doc


_NA = "n/a"


def _fmt_rows(n):
    return (
        f"{n:,}" if n is not None
        else "unknown (run DBMS_STATS.GATHER_SCHEMA_STATS to refresh)"
    )


def _bullet(items, indent=0):
    p = "  " * indent
    return (f"{p}- _(none)_\n") if not items else "".join(f"{p}- `{i}`\n" for i in items)


def render_markdown(doc: ReportDocument) -> str:
    lines: list[str] = []

    def h(lv, txt):
        lines.append(f'{"#" * lv} {txt}\n')

    h(1, f"Reverse-Engineered Database Report – `{doc.schema}`")
    lines += [f"_Generated: {doc.generated_at}_\n", "---\n"]

    h(2, "A. Executive Summary")
    lines.append(
        f"| Item | Count |\n|---|---|\n"
        f"| Schema | `{doc.schema}` |\n"
        f"| Total tables | {doc.total_tables} |\n"
        f"| Triggers | {doc.total_triggers} |\n"
        f"| Procedures / Functions / Packages | {doc.total_procedures} |\n"
        f"| Transaction tables | {len(doc.transactions)} |\n"
        f"| Reference-data tables | {len(doc.references)} |\n"
        f"| Master-data tables | {len(doc.masters)} |\n"
        f"| System-parameter tables | {len(doc.system_params)} |\n"
        f"| Unclassified tables | {len(doc.unknown_tables)} |\n"
    )
    lines.append("\n")

    h(2, "B. Transaction Types")
    if not doc.transactions:
        lines.append("_No transaction tables identified._\n\n")
    for e in sorted(doc.transactions, key=lambda x: x.table_name):
        h(3, f"`{e.table_name}`")
        lines.append(f"- **Estimated rows:** {_fmt_rows(e.num_rows)}\n")
        if e.ai_confirmed:
            lines.append("- **AI review:** ✅ Confirmed\n")
        elif e.ai_note:
            lines.append(f"- **AI review:** {e.ai_note}\n")
        lines.append("- **Columns:**\n")
        for c in e.columns:
            nf = " _(nullable)_" if c.nullable else ""
            lines.append(f"  - `{c.name}` ({c.data_type}){nf}\n")
        lines.append(
            f"- **Status / state columns:** "
            f"{', '.join(f'`{c}`' for c in e.status_columns) or _NA}\n"
        )
        lines.append(
            f"- **Date / timestamp columns:** "
            f"{', '.join(f'`{c}`' for c in e.date_columns) or _NA}\n"
        )
        lines.append(
            f"- **References (FK targets):** "
            f"{', '.join(f'`{t}`' for t in e.fk_refs) or _NA}\n"
        )
        lines.append(f"- **Triggers:**\n{_bullet(e.triggers, 1)}")
        lines.append(f"- **Procedures / packages:**\n{_bullet(e.procedures, 1)}")
        lines.append("\n")

    h(2, "C. Reference Data")
    if not doc.references:
        lines.append("_No reference-data tables identified._\n\n")
    for e in sorted(doc.references, key=lambda x: x.table_name):
        h(3, f"`{e.table_name}`")
        lines.append(f"- **Estimated rows:** {_fmt_rows(e.num_rows)}\n")
        if e.ai_confirmed:
            lines.append("- **AI review:** ✅ Confirmed\n")
        elif e.ai_note:
            lines.append(f"- **AI review:** {e.ai_note}\n")
        lines.append(f"- **Update ownership:** {e.owner}\n")
        lines.append(f"- **Consumed by (FK):**\n{_bullet(e.fk_consumers, 1)}")
        lines.append("- **Columns:**\n")
        for c in e.columns:
            lines.append(f"  - `{c.name}` ({c.data_type})\n")
        lines.append("\n")

    h(2, "D. Master Data")
    if not doc.masters:
        lines.append("_No master-data tables identified._\n\n")
    for e in sorted(doc.masters, key=lambda x: x.table_name):
        h(3, f"`{e.table_name}`")
        lines.append(f"- **Estimated rows:** {_fmt_rows(e.num_rows)}\n")
        if e.ai_confirmed:
            lines.append("- **AI review:** ✅ Confirmed\n")
        elif e.ai_note:
            lines.append(f"- **AI review:** {e.ai_note}\n")
        lines.append(
            f"- **Primary key:** "
            f"{', '.join(f'`{c}`' for c in e.primary_key) or _NA}\n"
        )
        lines.append(f"- **Referenced by (FK):**\n{_bullet(e.fk_consumers, 1)}")
        lines.append(f"- **Procedures / packages:**\n{_bullet(e.procedures, 1)}")
        lines.append("- **Columns:**\n")
        for c in e.columns:
            nf = " _(nullable)_" if c.nullable else ""
            lines.append(f"  - `{c.name}` ({c.data_type}){nf}\n")
        lines.append("\n")

    h(2, "E. System Parameters")
    if not doc.system_params:
        lines.append("_No system-parameter tables identified._\n\n")
    for e in sorted(doc.system_params, key=lambda x: x.table_name):
        h(3, f"`{e.table_name}`")
        lines.append(f"- **Estimated rows:** {_fmt_rows(e.num_rows)}\n")
        if e.ai_confirmed:
            lines.append("- **AI review:** ✅ Confirmed\n")
        elif e.ai_note:
            lines.append(f"- **AI review:** {e.ai_note}\n")
        lines.append(
            f"- **Key columns:** "
            f"{', '.join(f'`{c}`' for c in e.key_columns) or _NA}\n"
        )
        lines.append(
            f"- **Value columns:** "
            f"{', '.join(f'`{c}`' for c in e.value_columns) or _NA}\n"
        )
        lines.append(f"- **Procedures / packages:**\n{_bullet(e.procedures, 1)}")
        lines.append("\n")

    h(2, "F. Unclassified Tables")
    if not doc.unknown_tables:
        lines.append("_All tables were classified._\n\n")
    else:
        lines.append("The following tables did not match any classification heuristic.\n\n")
        for name in sorted(doc.unknown_tables):
            lines.append(f"- `{name}`\n")
        lines.append("\n")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Built-in sample dataset  (LEGACY_ERP schema)
# ─────────────────────────────────────────────────────────────────────────────

def _build_sample_schema():
    orders = TableInfo("ORDERS", 5_200_000, "2025-06-01",
        columns=[
            ColumnInfo("ORDER_ID",     "NUMBER",    10,   False, 1),
            ColumnInfo("CUSTOMER_ID",  "NUMBER",    10,   False, 2),
            ColumnInfo("ORDER_DATE",   "DATE",      None, False, 3),
            ColumnInfo("STATUS",       "VARCHAR2",  20,   False, 4),
            ColumnInfo("TOTAL_AMOUNT", "NUMBER",    None, True,  5),
            ColumnInfo("CREATED_DATE", "DATE",      None, True,  6),
            ColumnInfo("LAST_UPDATED", "TIMESTAMP", None, True,  7),
        ],
        constraints=[
            ConstraintInfo("PK_ORDERS",   "P", ["ORDER_ID"]),
            ConstraintInfo("FK_ORD_CUST", "R", ["CUSTOMER_ID"], ref_table="CUSTOMERS"),
            ConstraintInfo("FK_ORD_PROD", "R", ["PRODUCT_ID"],  ref_table="PRODUCT_CATALOG"),
        ])

    order_items = TableInfo("ORDER_ITEMS", 18_400_000, "2025-06-01",
        columns=[
            ColumnInfo("ITEM_ID",         "NUMBER",   10,  False, 1),
            ColumnInfo("ORDER_ID",        "NUMBER",   10,  False, 2),
            ColumnInfo("PRODUCT_ID",      "NUMBER",   10,  False, 3),
            ColumnInfo("QUANTITY",        "NUMBER",   None, False, 4),
            ColumnInfo("UNIT_PRICE",      "NUMBER",   None, False, 5),
            ColumnInfo("APPROVAL_STATUS", "VARCHAR2", 20,  True,  6),
        ],
        constraints=[
            ConstraintInfo("PK_ITEMS",     "P", ["ITEM_ID"]),
            ConstraintInfo("FK_ITEMS_ORD", "R", ["ORDER_ID"],   ref_table="ORDERS"),
            ConstraintInfo("FK_ITEMS_PRD", "R", ["PRODUCT_ID"], ref_table="PRODUCT_CATALOG"),
        ])

    customers = TableInfo("CUSTOMERS", 950_000, "2025-06-01",
        columns=[
            ColumnInfo("CUSTOMER_ID",  "NUMBER",   10,  False, 1),
            ColumnInfo("FULL_NAME",    "VARCHAR2", 200, False, 2),
            ColumnInfo("EMAIL",        "VARCHAR2", 200, True,  3),
            ColumnInfo("COUNTRY_CODE", "CHAR",     2,   False, 4),
            ColumnInfo("CREATED_DATE", "DATE",     None, True,  5),
            ColumnInfo("SEGMENT",      "VARCHAR2", 50,  True,  6),
        ],
        constraints=[ConstraintInfo("PK_CUSTOMERS", "P", ["CUSTOMER_ID"])])

    products = TableInfo("PRODUCT_CATALOG", 85_000, "2025-06-01",
        columns=[
            ColumnInfo("PRODUCT_ID",   "NUMBER",   10,  False, 1),
            ColumnInfo("PRODUCT_CODE", "VARCHAR2", 50,  False, 2),
            ColumnInfo("DESCRIPTION",  "VARCHAR2", 500, True,  3),
            ColumnInfo("CATEGORY_ID",  "NUMBER",   10,  False, 4),
            ColumnInfo("UNIT_PRICE",   "NUMBER",   None, False, 5),
            ColumnInfo("IS_ACTIVE",    "CHAR",     1,   False, 6),
        ],
        constraints=[
            ConstraintInfo("PK_PRODUCTS", "P", ["PRODUCT_ID"]),
            ConstraintInfo("FK_PROD_CAT", "R", ["CATEGORY_ID"], ref_table="CATEGORIES"),
        ])

    currencies = TableInfo("CURRENCIES", 150, "2025-06-01",
        columns=[
            ColumnInfo("CURRENCY_CODE", "CHAR",    3,   False, 1),
            ColumnInfo("CURRENCY_NAME", "VARCHAR2", 100, False, 2),
            ColumnInfo("SYMBOL",        "VARCHAR2", 10,  True,  3),
        ],
        constraints=[ConstraintInfo("PK_CURRENCIES", "P", ["CURRENCY_CODE"])])

    categories = TableInfo("CATEGORIES", 42, "2025-06-01",
        columns=[
            ColumnInfo("CATEGORY_ID",   "NUMBER",   10,  False, 1),
            ColumnInfo("CATEGORY_CODE", "VARCHAR2", 20,  False, 2),
            ColumnInfo("DESCRIPTION",   "VARCHAR2", 200, True,  3),
        ],
        constraints=[ConstraintInfo("PK_CATEGORIES", "P", ["CATEGORY_ID"])])

    app_config = TableInfo("APP_CONFIG", 320, "2025-06-01",
        columns=[
            ColumnInfo("PARAM_NAME",    "VARCHAR2", 100, False, 1),
            ColumnInfo("PARAM_VALUE",   "VARCHAR2", 500, True,  2),
            ColumnInfo("DESCRIPTION",   "VARCHAR2", 500, True,  3),
            ColumnInfo("LAST_MODIFIED", "DATE",     None, True, 4),
        ],
        constraints=[ConstraintInfo("PK_APP_CONFIG", "P", ["PARAM_NAME"])])

    feature_flags = TableInfo("FEATURE_FLAGS", 88, "2025-06-01",
        columns=[
            ColumnInfo("FLAG_KEY", "VARCHAR2", 100, False, 1),
            ColumnInfo("VALUE",    "VARCHAR2", 20,  False, 2),
            ColumnInfo("MODULE",   "VARCHAR2", 50,  True,  3),
        ],
        constraints=[ConstraintInfo("PK_FLAGS", "P", ["FLAG_KEY"])])

    all_tables = [
        orders, order_items, customers, products,
        currencies, categories, app_config, feature_flags,
    ]

    all_triggers = [
        TriggerInfo("TRG_ORDERS_AUDIT",  "ORDERS",      "AFTER",  "INSERT OR UPDATE OR DELETE", "ENABLED"),
        TriggerInfo("TRG_ORDERS_STATUS", "ORDERS",      "BEFORE", "UPDATE",                     "ENABLED"),
        TriggerInfo("TRG_ITEMS_CALC",    "ORDER_ITEMS", "BEFORE", "INSERT OR UPDATE",            "ENABLED"),
    ]

    all_procedures = [
        ProcedureInfo("PKG_ORDER_MGMT",    "PACKAGE",      referenced_tables=["ORDERS", "ORDER_ITEMS", "CUSTOMERS"]),
        ProcedureInfo("PKG_ORDER_MGMT",    "PACKAGE BODY", referenced_tables=[]),
        ProcedureInfo("PROC_CLOSE_ORDER",  "PROCEDURE",    referenced_tables=["ORDERS"]),
        ProcedureInfo("FN_GET_TOTAL",      "FUNCTION",     referenced_tables=["ORDER_ITEMS"]),
        ProcedureInfo("PKG_PRODUCT_UTILS", "PACKAGE",      referenced_tables=["PRODUCT_CATALOG", "CATEGORIES"]),
    ]

    return all_tables, all_triggers, all_procedures


def _build_table_proc_map(procedures):
    mapping: dict[str, list[str]] = {}
    for proc in procedures:
        for tbl in proc.referenced_tables:
            mapping.setdefault(tbl, [])
            if proc.name not in mapping[tbl]:
                mapping[tbl].append(proc.name)
    return mapping


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────────────────────

_CATEGORY_COLOURS = {
    TableCategory.TRANSACTION.value:  "🔴",
    TableCategory.REFERENCE.value:    "🟡",
    TableCategory.MASTER.value:       "🟢",
    TableCategory.SYSTEM_PARAM.value: "🔵",
    TableCategory.UNKNOWN.value:      "⚪",
}

st.title("🔍 ReverseDB — Demo Interface")
st.caption(
    "Self-contained pipeline demo · no Oracle connection required · "
    "mirrors `ReverseDB_Demo.ipynb`"
)

# ── Sidebar: configuration ────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration")
    schema_name = st.text_input("Schema name", value="LEGACY_ERP")

    st.subheader("Classification thresholds")
    ref_max = st.number_input(
        "Max rows for Reference Data",
        min_value=1, max_value=10_000_000, value=10_000, step=1_000,
    )
    param_max = st.number_input(
        "Max rows for System Parameter",
        min_value=1, max_value=1_000_000, value=1_000, step=100,
    )

    st.divider()
    run_btn = st.button("▶ Run Pipeline", type="primary", use_container_width=True)

# ── Main area ─────────────────────────────────────────────────────────────────
if not run_btn and "report_md" not in st.session_state:
    st.info(
        "Adjust the thresholds in the sidebar if you like, then click **▶ Run Pipeline**."
    )
    st.stop()

if run_btn:
    cfg = AnalysisConfig(
        schema=schema_name,
        ref_data_max_rows=ref_max,
        param_table_max_rows=param_max,
    )

    progress = st.progress(0, text="Loading sample schema …")

    # Step 1 — load sample data
    all_tables, all_triggers, all_procedures = _build_sample_schema()
    progress.progress(20, text="Step 1/5 · Sample schema loaded ✓")

    # Step 2 — build procedure map
    table_proc_map = _build_table_proc_map(all_procedures)
    progress.progress(40, text="Step 2/5 · Dependency map built ✓")

    # Step 3 — classify
    classifications = classify_tables(all_tables, cfg)
    progress.progress(60, text="Step 3/5 · Tables classified ✓")

    # Step 4 — build document
    doc = build_document(
        schema=schema_name,
        tables=all_tables,
        triggers=all_triggers,
        procedures=all_procedures,
        classifications=classifications,
        table_proc_map=table_proc_map,
    )
    progress.progress(80, text="Step 4/5 · Report document assembled ✓")

    # Step 5 — render Markdown
    report_md = render_markdown(doc)
    progress.progress(100, text="Step 5/5 · Markdown rendered ✓")

    # Persist results across re-renders
    st.session_state["doc"] = doc
    st.session_state["classifications"] = classifications
    st.session_state["report_md"] = report_md

# ── Results ───────────────────────────────────────────────────────────────────
doc: ReportDocument = st.session_state["doc"]
classifications: list[ClassificationResult] = st.session_state["classifications"]
report_md: str = st.session_state["report_md"]

# Summary metrics
st.subheader("📊 Pipeline Results")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total tables",      doc.total_tables)
col2.metric("Transaction",       len(doc.transactions))
col3.metric("Reference Data",    len(doc.references))
col4.metric("Master Data",       len(doc.masters))
col5.metric("System Parameters", len(doc.system_params))

# Classification table
st.subheader("🗂 Classification Results")

table_data = []
for r in classifications:
    icon = _CATEGORY_COLOURS.get(r.category.value, "⚪")
    best_score = max(r.scores.values())
    table_data.append({
        "Table": r.table_name,
        "Category": f"{icon} {r.category.value}",
        "TXN": r.scores[TableCategory.TRANSACTION.value],
        "REF": r.scores[TableCategory.REFERENCE.value],
        "MASTER": r.scores[TableCategory.MASTER.value],
        "PARAM": r.scores[TableCategory.SYSTEM_PARAM.value],
        "Winning score": best_score,
    })

st.dataframe(table_data, use_container_width=True, hide_index=True)

# Full report
with st.expander("📄 Full Markdown Report", expanded=True):
    tab_rendered, tab_raw = st.tabs(["Rendered", "Raw Markdown"])
    with tab_rendered:
        st.markdown(report_md)
    with tab_raw:
        st.code(report_md, language="markdown")

# Download
st.download_button(
    label="⬇ Download report (.md)",
    data=report_md,
    file_name=f"{doc.schema.lower()}_report.md",
    mime="text/markdown",
)
