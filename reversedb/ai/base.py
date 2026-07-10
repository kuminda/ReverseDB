"""Base interfaces for AI-assisted classification review."""

from __future__ import annotations

from abc import ABC, abstractmethod

from reversedb.classifiers.table_classifier import ClassificationResult
from reversedb.config import AIConfig


class AIReviewer(ABC):
    """Abstract base class for providers that review table classifications."""

    def __init__(self, config: AIConfig) -> None:
        self._config = config

    @abstractmethod
    def review(self, classifications: list[ClassificationResult]) -> list[ClassificationResult]:
        """Return reviewed classification results."""

