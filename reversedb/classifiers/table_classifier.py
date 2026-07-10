"""Table classifier: assigns each table to the most likely data category.

Categories
----------
TRANSACTION
    High-volume event/journal/order tables that record business activity.
REFERENCE
    Small, stable code/lookup tables (currency codes, status codes, etc.).
MASTER
    Core business entities referenced by many other tables (customer,
    product, account, …).
SYSTEM_PARAM
    Configuration / parameter tables that govern application behaviour.
UNKNOWN
    Tables that did not score clearly in any category.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from reversedb.classifiers.rules import (
    score_master,
    score_reference,
    score_system_param,
    score_transaction,
)

if TYPE_CHECKING:
    from reversedb.config import AnalysisConfig
    from reversedb.extractors.metadata import ConstraintInfo, TableInfo

logger = logging.getLogger(__name__)


class TableCategory(str, Enum):
    TRANSACTION = "Transaction"
    REFERENCE = "Reference Data"
    MASTER = "Master Data"
    SYSTEM_PARAM = "System Parameter"
    UNKNOWN = "Unknown"


@dataclass
class ClassificationResult:
    table_name: str
    category: TableCategory
    scores: dict[str, int]
    ai_confirmed: bool = False
    ai_override: TableCategory | None = None


class TableClassifier:
    """Classify every table in the schema using heuristic scoring rules.

    Parameters
    ----------
    analysis_cfg:
        The :class:`~reversedb.config.AnalysisConfig` section of the global
        config (provides row-count thresholds).
    """

    def __init__(self, analysis_cfg: "AnalysisConfig") -> None:
        self._cfg = analysis_cfg

    def classify(
        self,
        tables: list["TableInfo"],
    ) -> list[ClassificationResult]:
        """Return a :class:`ClassificationResult` for every table.

        Parameters
        ----------
        tables:
            Fully populated :class:`~reversedb.extractors.metadata.TableInfo`
            list (columns and constraints already attached).
        """
        # Pre-compute how many FK constraints reference each table
        fk_ref_counts = self._build_fk_ref_counts(tables)

        results: list[ClassificationResult] = []
        for tbl in tables:
            result = self._classify_one(tbl, fk_ref_counts)
            results.append(result)
            logger.debug(
                "  %-40s → %-18s  scores=%s",
                tbl.name,
                result.category.value,
                result.scores,
            )

        summary = {cat.value: 0 for cat in TableCategory}
        for r in results:
            summary[r.category.value] += 1
        logger.info("Classification summary: %s", summary)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    # Tiebreaker priority (highest priority wins when scores are equal).
    # More specific / smaller categories are preferred over broad ones.
    _PRIORITY: dict[str, int] = {
        TableCategory.SYSTEM_PARAM.value: 4,
        TableCategory.REFERENCE.value: 3,
        TableCategory.MASTER.value: 2,
        TableCategory.TRANSACTION.value: 1,
    }

    def _classify_one(
        self,
        table: "TableInfo",
        fk_ref_counts: dict[str, int],
    ) -> ClassificationResult:
        scores = {
            TableCategory.TRANSACTION.value: score_transaction(table, fk_ref_counts),
            TableCategory.REFERENCE.value: score_reference(table, self._cfg.ref_data_max_rows),
            TableCategory.MASTER.value: score_master(table, fk_ref_counts),
            TableCategory.SYSTEM_PARAM.value: score_system_param(table, self._cfg.param_table_max_rows),
        }

        best_score = max(scores.values())
        if best_score == 0:
            category = TableCategory.UNKNOWN
        else:
            # When scores are tied, prefer the more specific category
            best_name = max(
                (k for k, v in scores.items() if v == best_score),
                key=lambda k: self._PRIORITY.get(k, 0),
            )
            category = TableCategory(best_name)

        return ClassificationResult(
            table_name=table.name,
            category=category,
            scores=scores,
        )

    @staticmethod
    def _build_fk_ref_counts(tables: list["TableInfo"]) -> dict[str, int]:
        """Count how many FK constraints in the schema reference each table."""
        counts: dict[str, int] = {}
        for tbl in tables:
            for con in tbl.constraints:
                if con.constraint_type == "R" and con.ref_table:
                    counts[con.ref_table] = counts.get(con.ref_table, 0) + 1
        return counts
