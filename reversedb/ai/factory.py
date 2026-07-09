"""Factory for AI reviewer providers."""

from __future__ import annotations

from reversedb.ai.base import AIReviewer
from reversedb.ai.copilot import CopilotReviewer
from reversedb.config import AIConfig


def get_reviewer(ai_cfg: AIConfig) -> AIReviewer:
    provider = ai_cfg.provider.strip().lower()
    if provider == "copilot":
        return CopilotReviewer(ai_cfg)
    raise ValueError(
        f"Unsupported AI provider '{ai_cfg.provider}'. "
        "Supported providers: copilot."
    )

