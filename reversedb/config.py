"""Configuration dataclasses and YAML loader."""

from __future__ import annotations

import os
from dataclasses import dataclass

import yaml


@dataclass
class DatabaseConfig:
    host: str
    port: int
    service_name: str
    username: str
    passwd: str


@dataclass
class AnalysisConfig:
    schema: str
    batch_size: int = 10_000
    data_sample_pct: float = 0.1
    max_sample_rows: int = 2_000
    ref_data_max_rows: int = 10_000
    param_table_max_rows: int = 1_000


@dataclass
class OutputConfig:
    report_file: str = "reverse_engineered_report.md"
    log_level: str = "INFO"


@dataclass
class AIConfig:
    provider: str = "copilot"
    model: str = ""
    enabled: bool = False
    # 0 means "review all". Positive values only review tables whose best/max
    # heuristic score is <= threshold (higher-scoring tables are treated as
    # confident enough to skip AI review).
    confidence_threshold: int = 0


@dataclass
class Config:
    database: DatabaseConfig
    analysis: AnalysisConfig
    output: OutputConfig
    ai: AIConfig

    @classmethod
    def from_file(cls, path: str) -> "Config":
        """Load configuration from a YAML file.

        The database credential is read from the ``DB_PASSWORD`` environment
        variable when set, falling back to the ``password`` key in the YAML
        file.  Storing plaintext credentials in config files is discouraged;
        prefer the environment variable approach.
        """
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        db_raw = raw["database"]
        analysis_raw = raw.get("analysis", {})
        output_raw = raw.get("output", {})
        ai_raw = raw.get("ai", {})

        db_passwd = os.environ.get("DB_PASSWORD") or db_raw.get("password", "")

        return cls(
            database=DatabaseConfig(
                host=db_raw["host"],
                port=int(db_raw.get("port", 1521)),
                service_name=db_raw["service_name"],
                username=db_raw["username"],
                passwd=db_passwd,
            ),
            analysis=AnalysisConfig(
                schema=analysis_raw["schema"].upper(),
                batch_size=int(analysis_raw.get("batch_size", 10_000)),
                data_sample_pct=float(analysis_raw.get("data_sample_pct", 0.1)),
                max_sample_rows=int(analysis_raw.get("max_sample_rows", 2_000)),
                ref_data_max_rows=int(analysis_raw.get("ref_data_max_rows", 10_000)),
                param_table_max_rows=int(analysis_raw.get("param_table_max_rows", 1_000)),
            ),
            output=OutputConfig(
                report_file=output_raw.get("report_file", "reverse_engineered_report.md"),
                log_level=output_raw.get("log_level", "INFO"),
            ),
            ai=AIConfig(
                provider=str(ai_raw.get("provider", "copilot")).strip().lower(),
                model=str(ai_raw.get("model", "")).strip(),
                enabled=bool(ai_raw.get("enabled", False)),
                confidence_threshold=int(ai_raw.get("confidence_threshold", 0)),
            ),
        )
