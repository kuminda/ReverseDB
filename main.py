#!/usr/bin/env python3
"""ReverseDB – CLI entry point.

Usage
-----
    python main.py --config config.yaml

The tool connects to the Oracle database described in *config.yaml*,
extracts metadata and source objects from the configured schema, classifies
every table into one of four categories (Transaction, Reference Data, Master
Data, System Parameter), and writes a Markdown report.

Large-table safety
------------------
Data sampling (for heuristic classification) uses Oracle's ``SAMPLE`` clause
so that multi-billion-row tables are never fully scanned.  All bulk reads of
the data dictionary use cursor ``arraysize``-based streaming so memory stays
bounded regardless of schema size.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from reversedb.classifiers.table_classifier import TableClassifier
from reversedb.config import Config
from reversedb.db.chunked_reader import ChunkedReader
from reversedb.db.connector import OracleConnector
from reversedb.extractors.dependencies import DependencyExtractor
from reversedb.extractors.metadata import MetadataExtractor
from reversedb.extractors.source_objects import SourceExtractor
from reversedb.reporters.document import DocumentBuilder
from reversedb.reporters.markdown_writer import MarkdownWriter


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reverse-engineer a legacy Oracle database into a structured Markdown report."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the YAML configuration file (default: config.yaml).",
    )
    return parser.parse_args()


def run(config_path: str) -> None:
    """Main pipeline: extract → classify → report."""
    cfg = Config.from_file(config_path)
    _setup_logging(cfg.output.log_level)

    logger = logging.getLogger(__name__)
    logger.info("ReverseDB starting – schema=%s", cfg.analysis.schema)

    with OracleConnector(cfg.database) as conn:
        reader = ChunkedReader(conn, batch_size=cfg.analysis.batch_size)

        # ------------------------------------------------------------------
        # 1. Extract metadata
        # ------------------------------------------------------------------
        logger.info("=== Step 1: Metadata extraction ===")
        meta_extractor = MetadataExtractor(reader, cfg.analysis.schema)
        tables = meta_extractor.extract()

        # ------------------------------------------------------------------
        # 2. Extract source objects (triggers + procedures/packages)
        # ------------------------------------------------------------------
        logger.info("=== Step 2: Source object extraction ===")
        src_extractor = SourceExtractor(reader, cfg.analysis.schema)
        triggers = src_extractor.get_triggers()
        procedures = src_extractor.get_procedures()

        # ------------------------------------------------------------------
        # 3. Extract dependencies
        # ------------------------------------------------------------------
        logger.info("=== Step 3: Dependency extraction ===")
        dep_extractor = DependencyExtractor(reader, cfg.analysis.schema)
        dep_edges = dep_extractor.get_dependencies()
        table_proc_map = dep_extractor.build_table_procedure_map(dep_edges)

        # ------------------------------------------------------------------
        # 4. Classify tables
        # ------------------------------------------------------------------
        logger.info("=== Step 4: Table classification ===")
        classifier = TableClassifier(cfg.analysis)
        classifications = classifier.classify(tables)

        # ------------------------------------------------------------------
        # 5. Build report document
        # ------------------------------------------------------------------
        logger.info("=== Step 5: Building report document ===")
        builder = DocumentBuilder(
            schema=cfg.analysis.schema,
            tables=tables,
            triggers=triggers,
            procedures=procedures,
            classifications=classifications,
            table_proc_map=table_proc_map,
        )
        document = builder.build()

        # ------------------------------------------------------------------
        # 6. Write Markdown report
        # ------------------------------------------------------------------
        logger.info("=== Step 6: Writing Markdown report ===")
        writer = MarkdownWriter(cfg.output.report_file)
        writer.write(document)

    logger.info("Done. Report saved to: %s", cfg.output.report_file)


def main() -> None:
    args = _parse_args()
    config_path = args.config
    if not Path(config_path).exists():
        print(
            f"ERROR: Config file not found: {config_path}\n"
            "Copy config.yaml.example to config.yaml and fill in your database details.",
            file=sys.stderr,
        )
        sys.exit(1)
    run(config_path)


if __name__ == "__main__":
    main()
