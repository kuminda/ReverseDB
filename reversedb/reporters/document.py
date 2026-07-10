"""Report data model and builder.

The :class:`DocumentBuilder` takes all extracted and classified artefacts
and assembles them into a :class:`ReportDocument` that is a plain Python
object graph with no formatting concerns.  Rendering to Markdown (or any
other format) is handled by a separate writer.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reversedb.classifiers.table_classifier import ClassificationResult, TableCategory
    from reversedb.extractors.dependencies import DependencyEdge
    from reversedb.extractors.metadata import TableInfo
    from reversedb.extractors.source_objects import ProcedureInfo, TriggerInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report data model
# ---------------------------------------------------------------------------


@dataclass
class ColumnEntry:
    name: str
    data_type: str
    nullable: bool


@dataclass
class TransactionEntry:
    table_name: str
    num_rows: int | None
    ai_confirmed: bool = False
    ai_note: str | None = None
    columns: list[ColumnEntry] = field(default_factory=list)
    status_columns: list[str] = field(default_factory=list)
    date_columns: list[str] = field(default_factory=list)
    fk_refs: list[str] = field(default_factory=list)          # tables this table FKs into
    triggers: list[str] = field(default_factory=list)         # trigger names on this table
    procedures: list[str] = field(default_factory=list)       # procs/pkgs that reference this table


@dataclass
class ReferenceEntry:
    table_name: str
    num_rows: int | None
    ai_confirmed: bool = False
    ai_note: str | None = None
    columns: list[ColumnEntry] = field(default_factory=list)
    fk_consumers: list[str] = field(default_factory=list)     # tables that FK into this one
    owner: str = "Admin / System"


@dataclass
class MasterEntry:
    table_name: str
    num_rows: int | None
    ai_confirmed: bool = False
    ai_note: str | None = None
    primary_key: list[str] = field(default_factory=list)
    columns: list[ColumnEntry] = field(default_factory=list)
    fk_consumers: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)


@dataclass
class SystemParamEntry:
    table_name: str
    num_rows: int | None
    ai_confirmed: bool = False
    ai_note: str | None = None
    key_columns: list[str] = field(default_factory=list)
    value_columns: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)


@dataclass
class ReportDocument:
    schema: str
    generated_at: str
    total_tables: int
    total_triggers: int
    total_procedures: int
    transactions: list[TransactionEntry] = field(default_factory=list)
    references: list[ReferenceEntry] = field(default_factory=list)
    masters: list[MasterEntry] = field(default_factory=list)
    system_params: list[SystemParamEntry] = field(default_factory=list)
    unknown_tables: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class DocumentBuilder:
    """Assemble a :class:`ReportDocument` from extracted artefacts.

    Parameters
    ----------
    schema:
        The analysed Oracle schema name.
    tables:
        Fully populated :class:`~reversedb.extractors.metadata.TableInfo` list.
    triggers:
        List of :class:`~reversedb.extractors.source_objects.TriggerInfo`.
    procedures:
        List of :class:`~reversedb.extractors.source_objects.ProcedureInfo`.
    classifications:
        Output of :meth:`~reversedb.classifiers.table_classifier.TableClassifier.classify`.
    table_proc_map:
        Mapping of table_name → [procedure names] from
        :meth:`~reversedb.extractors.dependencies.DependencyExtractor.build_table_procedure_map`.
    """

    def __init__(
        self,
        schema: str,
        tables: list["TableInfo"],
        triggers: list["TriggerInfo"],
        procedures: list["ProcedureInfo"],
        classifications: list["ClassificationResult"],
        table_proc_map: dict[str, list[str]],
    ) -> None:
        self._schema = schema
        self._tables = {t.name: t for t in tables}
        self._triggers = triggers
        self._procedures = procedures
        self._classifications = classifications
        self._table_proc_map = table_proc_map

        # Pre-index triggers by table name
        self._triggers_by_table: dict[str, list[str]] = {}
        for trg in triggers:
            self._triggers_by_table.setdefault(trg.table_name, []).append(trg.name)

        # Pre-index FK consumers (tables that FK into each table)
        self._fk_consumers: dict[str, list[str]] = {}
        for tbl in tables:
            for con in tbl.constraints:
                if con.constraint_type == "R" and con.ref_table:
                    self._fk_consumers.setdefault(con.ref_table, []).append(tbl.name)

    def build(self) -> ReportDocument:
        """Return the assembled :class:`ReportDocument`."""
        from reversedb.classifiers.table_classifier import TableCategory

        doc = ReportDocument(
            schema=self._schema,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            total_tables=len(self._tables),
            total_triggers=len(self._triggers),
            total_procedures=len(self._procedures),
        )

        for clf in self._classifications:
            tbl = self._tables.get(clf.table_name)
            if tbl is None:
                continue

            final_category = clf.ai_override or clf.category
            ai_note = self._ai_note(clf)
            if final_category == TableCategory.TRANSACTION:
                doc.transactions.append(self._build_txn(tbl, clf.ai_confirmed, ai_note))
            elif final_category == TableCategory.REFERENCE:
                doc.references.append(self._build_ref(tbl, clf.ai_confirmed, ai_note))
            elif final_category == TableCategory.MASTER:
                doc.masters.append(self._build_master(tbl, clf.ai_confirmed, ai_note))
            elif final_category == TableCategory.SYSTEM_PARAM:
                doc.system_params.append(self._build_param(tbl, clf.ai_confirmed, ai_note))
            else:
                doc.unknown_tables.append(tbl.name)

        return doc

    # ------------------------------------------------------------------
    # Per-category builders
    # ------------------------------------------------------------------

    def _col_entries(self, tbl: "TableInfo") -> list[ColumnEntry]:
        return [ColumnEntry(c.name, c.data_type, c.nullable) for c in tbl.columns]

    @staticmethod
    def _ai_note(clf: "ClassificationResult") -> str | None:
        override = clf.ai_override
        if override is not None:
            return f"AI override: heuristic `{clf.category.value}` → AI `{override.value}`"
        return None

    def _build_txn(
        self,
        tbl: "TableInfo",
        ai_confirmed: bool,
        ai_note: str | None,
    ) -> TransactionEntry:
        status_cols = [
            c.name for c in tbl.columns
            if any(kw in c.name.upper() for kw in ("STATUS", "STATE", "APPROVAL"))
        ]
        date_cols = [
            c.name for c in tbl.columns
            if c.data_type in ("DATE", "TIMESTAMP") or "DATE" in c.name.upper()
        ]
        fk_refs = [
            con.ref_table
            for con in tbl.constraints
            if con.constraint_type == "R" and con.ref_table
        ]
        return TransactionEntry(
            table_name=tbl.name,
            num_rows=tbl.num_rows,
            ai_confirmed=ai_confirmed,
            ai_note=ai_note,
            columns=self._col_entries(tbl),
            status_columns=status_cols,
            date_columns=date_cols,
            fk_refs=list(dict.fromkeys(fk_refs)),
            triggers=self._triggers_by_table.get(tbl.name, []),
            procedures=self._table_proc_map.get(tbl.name, []),
        )

    def _build_ref(
        self,
        tbl: "TableInfo",
        ai_confirmed: bool,
        ai_note: str | None,
    ) -> ReferenceEntry:
        return ReferenceEntry(
            table_name=tbl.name,
            num_rows=tbl.num_rows,
            ai_confirmed=ai_confirmed,
            ai_note=ai_note,
            columns=self._col_entries(tbl),
            fk_consumers=list(dict.fromkeys(self._fk_consumers.get(tbl.name, []))),
        )

    def _build_master(
        self,
        tbl: "TableInfo",
        ai_confirmed: bool,
        ai_note: str | None,
    ) -> MasterEntry:
        pk = next(
            (con.columns for con in tbl.constraints if con.constraint_type == "P"),
            [],
        )
        return MasterEntry(
            table_name=tbl.name,
            num_rows=tbl.num_rows,
            ai_confirmed=ai_confirmed,
            ai_note=ai_note,
            primary_key=pk,
            columns=self._col_entries(tbl),
            fk_consumers=list(dict.fromkeys(self._fk_consumers.get(tbl.name, []))),
            procedures=self._table_proc_map.get(tbl.name, []),
        )

    def _build_param(
        self,
        tbl: "TableInfo",
        ai_confirmed: bool,
        ai_note: str | None,
    ) -> SystemParamEntry:
        key_hints = {"PARAM_NAME", "CONFIG_KEY", "SETTING_NAME", "PROP_NAME", "NAME", "KEY"}
        val_hints = {"PARAM_VALUE", "CONFIG_VALUE", "SETTING_VALUE", "PROP_VALUE", "VALUE", "DATA"}
        key_cols = [c.name for c in tbl.columns if c.name.upper() in key_hints]
        val_cols = [c.name for c in tbl.columns if c.name.upper() in val_hints]
        return SystemParamEntry(
            table_name=tbl.name,
            num_rows=tbl.num_rows,
            ai_confirmed=ai_confirmed,
            ai_note=ai_note,
            key_columns=key_cols,
            value_columns=val_cols,
            procedures=self._table_proc_map.get(tbl.name, []),
        )
