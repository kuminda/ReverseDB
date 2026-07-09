"""Write a :class:`~reversedb.reporters.document.ReportDocument` to Markdown.

The output follows the structure defined in the project README:

  A. Executive Summary
  B. Transaction Types
  C. Reference Data
  D. Master Data
  E. System Parameters
  F. Unknown / Unclassified Tables
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reversedb.reporters.document import ReportDocument

logger = logging.getLogger(__name__)

_NA = "n/a"


def _fmt_rows(num: int | None) -> str:
    if num is None:
        return "unknown (run DBMS_STATS.GATHER_SCHEMA_STATS to refresh)"
    return f"{num:,}"


def _bullet_list(items: list[str], indent: int = 0) -> str:
    prefix = "  " * indent
    if not items:
        return f"{prefix}- _(none)_\n"
    return "".join(f"{prefix}- `{item}`\n" for item in items)


class MarkdownWriter:
    """Render a :class:`~reversedb.reporters.document.ReportDocument` to a
    Markdown file.

    Parameters
    ----------
    output_path:
        Destination file path.
    """

    def __init__(self, output_path: str) -> None:
        self._path = output_path

    def write(self, doc: "ReportDocument") -> None:
        """Serialise *doc* to Markdown and write to disk."""
        lines: list[str] = []
        self._section_title(lines, doc)
        self._section_executive_summary(lines, doc)
        self._section_transactions(lines, doc)
        self._section_references(lines, doc)
        self._section_masters(lines, doc)
        self._section_params(lines, doc)
        self._section_unknown(lines, doc)

        content = "\n".join(lines)
        with open(self._path, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.info("Report written to %s", self._path)

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    @staticmethod
    def _h(level: int, text: str) -> str:
        return f"{'#' * level} {text}\n"

    def _section_title(self, lines: list[str], doc: "ReportDocument") -> None:
        lines += [
            self._h(1, f"Reverse-Engineered Database Report – `{doc.schema}`"),
            f"_Generated: {doc.generated_at}_\n",
            "---\n",
        ]

    def _section_executive_summary(self, lines: list[str], doc: "ReportDocument") -> None:
        lines.append(self._h(2, "A. Executive Summary"))
        lines.append(
            f"| Item | Count |\n"
            f"|---|---|\n"
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

    def _section_transactions(self, lines: list[str], doc: "ReportDocument") -> None:
        lines.append(self._h(2, "B. Transaction Types"))
        if not doc.transactions:
            lines.append("_No transaction tables identified._\n\n")
            return
        for entry in sorted(doc.transactions, key=lambda e: e.table_name):
            lines.append(self._h(3, f"`{entry.table_name}`"))
            lines.append(f"- **Estimated rows:** {_fmt_rows(entry.num_rows)}\n")
            if entry.ai_confirmed:
                lines.append("- **AI review:** ✅ Confirmed\n")
            elif entry.ai_note:
                lines.append(f"- **AI review:** {entry.ai_note}\n")

            lines.append("- **Columns:**\n")
            for col in entry.columns:
                null_flag = "" if not col.nullable else " _(nullable)_"
                lines.append(f"  - `{col.name}` ({col.data_type}){null_flag}\n")

            lines.append(f"- **Status / state columns:** {', '.join(f'`{c}`' for c in entry.status_columns) or _NA}\n")
            lines.append(f"- **Date / timestamp columns:** {', '.join(f'`{c}`' for c in entry.date_columns) or _NA}\n")
            lines.append(f"- **References (FK targets):** {', '.join(f'`{t}`' for t in entry.fk_refs) or _NA}\n")
            lines.append(f"- **Triggers:**\n{_bullet_list(entry.triggers, 1)}")
            lines.append(f"- **Procedures / packages referencing this table:**\n{_bullet_list(entry.procedures, 1)}")
            lines.append("\n")

    def _section_references(self, lines: list[str], doc: "ReportDocument") -> None:
        lines.append(self._h(2, "C. Reference Data"))
        if not doc.references:
            lines.append("_No reference-data tables identified._\n\n")
            return
        for entry in sorted(doc.references, key=lambda e: e.table_name):
            lines.append(self._h(3, f"`{entry.table_name}`"))
            lines.append(f"- **Estimated rows:** {_fmt_rows(entry.num_rows)}\n")
            if entry.ai_confirmed:
                lines.append("- **AI review:** ✅ Confirmed\n")
            elif entry.ai_note:
                lines.append(f"- **AI review:** {entry.ai_note}\n")
            lines.append(f"- **Update ownership:** {entry.owner}\n")
            lines.append(f"- **Consumed by (FK):**\n{_bullet_list(entry.fk_consumers, 1)}")
            lines.append("- **Columns:**\n")
            for col in entry.columns:
                lines.append(f"  - `{col.name}` ({col.data_type})\n")
            lines.append("\n")

    def _section_masters(self, lines: list[str], doc: "ReportDocument") -> None:
        lines.append(self._h(2, "D. Master Data"))
        if not doc.masters:
            lines.append("_No master-data tables identified._\n\n")
            return
        for entry in sorted(doc.masters, key=lambda e: e.table_name):
            lines.append(self._h(3, f"`{entry.table_name}`"))
            lines.append(f"- **Estimated rows:** {_fmt_rows(entry.num_rows)}\n")
            if entry.ai_confirmed:
                lines.append("- **AI review:** ✅ Confirmed\n")
            elif entry.ai_note:
                lines.append(f"- **AI review:** {entry.ai_note}\n")
            lines.append(f"- **Primary key:** {', '.join(f'`{c}`' for c in entry.primary_key) or _NA}\n")
            lines.append(f"- **Referenced by (FK):**\n{_bullet_list(entry.fk_consumers, 1)}")
            lines.append(f"- **Procedures / packages:**\n{_bullet_list(entry.procedures, 1)}")
            lines.append("- **Columns:**\n")
            for col in entry.columns:
                null_flag = "" if not col.nullable else " _(nullable)_"
                lines.append(f"  - `{col.name}` ({col.data_type}){null_flag}\n")
            lines.append("\n")

    def _section_params(self, lines: list[str], doc: "ReportDocument") -> None:
        lines.append(self._h(2, "E. System Parameters"))
        if not doc.system_params:
            lines.append("_No system-parameter tables identified._\n\n")
            return
        for entry in sorted(doc.system_params, key=lambda e: e.table_name):
            lines.append(self._h(3, f"`{entry.table_name}`"))
            lines.append(f"- **Estimated rows:** {_fmt_rows(entry.num_rows)}\n")
            if entry.ai_confirmed:
                lines.append("- **AI review:** ✅ Confirmed\n")
            elif entry.ai_note:
                lines.append(f"- **AI review:** {entry.ai_note}\n")
            lines.append(f"- **Key columns:** {', '.join(f'`{c}`' for c in entry.key_columns) or _NA}\n")
            lines.append(f"- **Value columns:** {', '.join(f'`{c}`' for c in entry.value_columns) or _NA}\n")
            lines.append(f"- **Procedures / packages:**\n{_bullet_list(entry.procedures, 1)}")
            lines.append("\n")

    def _section_unknown(self, lines: list[str], doc: "ReportDocument") -> None:
        lines.append(self._h(2, "F. Unclassified Tables"))
        if not doc.unknown_tables:
            lines.append("_All tables were classified._\n\n")
            return
        lines.append(
            "The following tables did not match any classification heuristic.  "
            "They may require manual review.\n\n"
        )
        for name in sorted(doc.unknown_tables):
            lines.append(f"- `{name}`\n")
        lines.append("\n")
