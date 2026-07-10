#!/usr/bin/env python3
"""Demo: run the full ReverseDB pipeline against a sample in-memory dataset.

No Oracle connection is required.  The script bypasses the DB layer entirely
and feeds hand-crafted :class:`~reversedb.extractors.metadata.TableInfo` /
:class:`~reversedb.extractors.source_objects.TriggerInfo` /
:class:`~reversedb.extractors.source_objects.ProcedureInfo` objects directly
into the classifier, document builder, and Markdown writer.

Usage
-----
    python demo.py                        # writes demo_report.md
    python demo.py --out /tmp/report.md   # custom output path
"""

from __future__ import annotations

import argparse

from reversedb.classifiers.table_classifier import TableClassifier
from reversedb.config import AnalysisConfig
from reversedb.extractors.metadata import ColumnInfo, ConstraintInfo, TableInfo
from reversedb.extractors.source_objects import ProcedureInfo, TriggerInfo
from reversedb.reporters.document import DocumentBuilder
from reversedb.reporters.markdown_writer import MarkdownWriter

SCHEMA = "LEGACY_ERP"


# ---------------------------------------------------------------------------
# Sample tables
# ---------------------------------------------------------------------------

def _build_tables() -> list[TableInfo]:
    # ORDERS – high-volume transaction table
    orders = TableInfo(
        name="ORDERS",
        num_rows=5_200_000,
        last_analyzed="2025-06-01",
        columns=[
            ColumnInfo("ORDER_ID",        "NUMBER",   10,   False, 1),
            ColumnInfo("CUSTOMER_ID",     "NUMBER",   10,   False, 2),
            ColumnInfo("ORDER_DATE",      "DATE",     None, False, 3),
            ColumnInfo("STATUS",          "VARCHAR2", 20,   False, 4),
            ColumnInfo("TOTAL_AMOUNT",    "NUMBER",   None, True,  5),
            ColumnInfo("CREATED_DATE",    "DATE",     None, True,  6),
            ColumnInfo("LAST_UPDATED",    "TIMESTAMP",None, True,  7),
        ],
        constraints=[
            ConstraintInfo("PK_ORDERS",    "P", ["ORDER_ID"]),
            ConstraintInfo("FK_ORD_CUST",  "R", ["CUSTOMER_ID"], ref_table="CUSTOMERS"),
            ConstraintInfo("FK_ORD_PROD",  "R", ["PRODUCT_ID"],  ref_table="PRODUCT_CATALOG"),
        ],
    )

    # ORDER_ITEMS – line-item transaction table
    order_items = TableInfo(
        name="ORDER_ITEMS",
        num_rows=18_400_000,
        last_analyzed="2025-06-01",
        columns=[
            ColumnInfo("ITEM_ID",         "NUMBER",   10,  False, 1),
            ColumnInfo("ORDER_ID",        "NUMBER",   10,  False, 2),
            ColumnInfo("PRODUCT_ID",      "NUMBER",   10,  False, 3),
            ColumnInfo("QUANTITY",        "NUMBER",   None,False, 4),
            ColumnInfo("UNIT_PRICE",      "NUMBER",   None,False, 5),
            ColumnInfo("APPROVAL_STATUS", "VARCHAR2", 20,  True,  6),
        ],
        constraints=[
            ConstraintInfo("PK_ITEMS",     "P", ["ITEM_ID"]),
            ConstraintInfo("FK_ITEMS_ORD", "R", ["ORDER_ID"],   ref_table="ORDERS"),
            ConstraintInfo("FK_ITEMS_PRD", "R", ["PRODUCT_ID"], ref_table="PRODUCT_CATALOG"),
        ],
    )

    # CUSTOMERS – core business entity (master / high-volume)
    customers = TableInfo(
        name="CUSTOMERS",
        num_rows=950_000,
        last_analyzed="2025-06-01",
        columns=[
            ColumnInfo("CUSTOMER_ID",  "NUMBER",   10,  False, 1),
            ColumnInfo("FULL_NAME",    "VARCHAR2", 200, False, 2),
            ColumnInfo("EMAIL",        "VARCHAR2", 200, True,  3),
            ColumnInfo("COUNTRY_CODE", "CHAR",     2,   False, 4),
            ColumnInfo("CREATED_DATE", "DATE",     None,True,  5),
            ColumnInfo("SEGMENT",      "VARCHAR2", 50,  True,  6),
        ],
        constraints=[
            ConstraintInfo("PK_CUSTOMERS", "P", ["CUSTOMER_ID"]),
        ],
    )

    # PRODUCT_CATALOG – master data, referenced by orders and items
    products = TableInfo(
        name="PRODUCT_CATALOG",
        num_rows=85_000,
        last_analyzed="2025-06-01",
        columns=[
            ColumnInfo("PRODUCT_ID",   "NUMBER",   10,  False, 1),
            ColumnInfo("PRODUCT_CODE", "VARCHAR2", 50,  False, 2),
            ColumnInfo("DESCRIPTION",  "VARCHAR2", 500, True,  3),
            ColumnInfo("CATEGORY_ID",  "NUMBER",   10,  False, 4),
            ColumnInfo("UNIT_PRICE",   "NUMBER",   None,False, 5),
            ColumnInfo("IS_ACTIVE",    "CHAR",     1,   False, 6),
        ],
        constraints=[
            ConstraintInfo("PK_PRODUCTS", "P", ["PRODUCT_ID"]),
            ConstraintInfo("FK_PROD_CAT", "R", ["CATEGORY_ID"], ref_table="CATEGORIES"),
        ],
    )

    # CURRENCIES – small, stable reference table
    currencies = TableInfo(
        name="CURRENCIES",
        num_rows=150,
        last_analyzed="2025-06-01",
        columns=[
            ColumnInfo("CURRENCY_CODE", "CHAR",     3,   False, 1),
            ColumnInfo("CURRENCY_NAME", "VARCHAR2", 100, False, 2),
            ColumnInfo("SYMBOL",        "VARCHAR2", 10,  True,  3),
        ],
        constraints=[
            ConstraintInfo("PK_CURRENCIES", "P", ["CURRENCY_CODE"]),
        ],
    )

    # CATEGORIES – small lookup table for products
    categories = TableInfo(
        name="CATEGORIES",
        num_rows=42,
        last_analyzed="2025-06-01",
        columns=[
            ColumnInfo("CATEGORY_ID",   "NUMBER",   10,  False, 1),
            ColumnInfo("CATEGORY_CODE", "VARCHAR2", 20,  False, 2),
            ColumnInfo("DESCRIPTION",   "VARCHAR2", 200, True,  3),
        ],
        constraints=[
            ConstraintInfo("PK_CATEGORIES", "P", ["CATEGORY_ID"]),
        ],
    )

    # APP_CONFIG – system parameter table (key/value pairs)
    app_config = TableInfo(
        name="APP_CONFIG",
        num_rows=320,
        last_analyzed="2025-06-01",
        columns=[
            ColumnInfo("PARAM_NAME",   "VARCHAR2", 100, False, 1),
            ColumnInfo("PARAM_VALUE",  "VARCHAR2", 500, True,  2),
            ColumnInfo("DESCRIPTION",  "VARCHAR2", 500, True,  3),
            ColumnInfo("LAST_MODIFIED","DATE",      None,True,  4),
        ],
        constraints=[
            ConstraintInfo("PK_APP_CONFIG", "P", ["PARAM_NAME"]),
        ],
    )

    # FEATURE_FLAGS – runtime feature toggles (system parameters)
    feature_flags = TableInfo(
        name="FEATURE_FLAGS",
        num_rows=88,
        last_analyzed="2025-06-01",
        columns=[
            ColumnInfo("FLAG_KEY", "VARCHAR2", 100, False, 1),
            ColumnInfo("VALUE",    "VARCHAR2", 20,  False, 2),
            ColumnInfo("MODULE",   "VARCHAR2", 50,  True,  3),
        ],
        constraints=[
            ConstraintInfo("PK_FLAGS", "P", ["FLAG_KEY"]),
        ],
    )

    return [orders, order_items, customers, products, currencies, categories, app_config, feature_flags]


# ---------------------------------------------------------------------------
# Sample triggers
# ---------------------------------------------------------------------------

def _build_triggers() -> list[TriggerInfo]:
    return [
        TriggerInfo("TRG_ORDERS_AUDIT",  "ORDERS",      "AFTER",  "INSERT OR UPDATE OR DELETE", "ENABLED"),
        TriggerInfo("TRG_ORDERS_STATUS", "ORDERS",      "BEFORE", "UPDATE",                     "ENABLED"),
        TriggerInfo("TRG_ITEMS_CALC",    "ORDER_ITEMS", "BEFORE", "INSERT OR UPDATE",            "ENABLED"),
    ]


# ---------------------------------------------------------------------------
# Sample procedures / packages
# ---------------------------------------------------------------------------

def _build_procedures() -> list[ProcedureInfo]:
    return [
        ProcedureInfo("PKG_ORDER_MGMT",    "PACKAGE",      referenced_tables=["ORDERS", "ORDER_ITEMS", "CUSTOMERS"]),
        ProcedureInfo("PKG_ORDER_MGMT",    "PACKAGE BODY", referenced_tables=[]),
        ProcedureInfo("PROC_CLOSE_ORDER",  "PROCEDURE",    referenced_tables=["ORDERS"]),
        ProcedureInfo("FN_GET_TOTAL",      "FUNCTION",     referenced_tables=["ORDER_ITEMS"]),
        ProcedureInfo("PKG_PRODUCT_UTILS", "PACKAGE",      referenced_tables=["PRODUCT_CATALOG", "CATEGORIES"]),
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(output_path: str) -> None:
    tables = _build_tables()
    triggers = _build_triggers()
    procedures = _build_procedures()

    # Build table → procedure map
    table_proc_map: dict[str, list[str]] = {}
    for proc in procedures:
        for tbl in proc.referenced_tables:
            table_proc_map.setdefault(tbl, [])
            if proc.name not in table_proc_map[tbl]:
                table_proc_map[tbl].append(proc.name)

    # Classify
    cfg = AnalysisConfig(schema=SCHEMA, ref_data_max_rows=10_000, param_table_max_rows=1_000)
    classifier = TableClassifier(cfg)
    classifications = classifier.classify(tables)

    print("Classification results:")
    for result in classifications:
        print(f"  {result.table_name:<25} → {result.category.value}")

    # Build document and write report
    builder = DocumentBuilder(
        schema=SCHEMA,
        tables=tables,
        triggers=triggers,
        procedures=procedures,
        classifications=classifications,
        table_proc_map=table_proc_map,
    )
    document = builder.build()

    writer = MarkdownWriter(output_path)
    writer.write(document)
    print(f"\nReport written to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ReverseDB demo with sample in-memory dataset.")
    parser.add_argument("--out", default="demo_report.md", help="Output Markdown file path.")
    args = parser.parse_args()
    run(args.out)


if __name__ == "__main__":
    main()
