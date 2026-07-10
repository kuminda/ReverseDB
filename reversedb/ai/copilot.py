"""Copilot-backed AI reviewer implementation."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from reversedb.ai.base import AIReviewer
from reversedb.classifiers.table_classifier import ClassificationResult, TableCategory

logger = logging.getLogger(__name__)


class CopilotReviewer(AIReviewer):
    """Review table classifications using GitHub Copilot chat completions API."""

    _DEFAULT_ENDPOINT = "https://api.githubcopilot.com/chat/completions"
    _DEFAULT_MODEL = "gpt-4.1"

    def review(self, classifications: list[ClassificationResult]) -> list[ClassificationResult]:
        to_review = self._select_for_review(classifications)
        if not to_review:
            logger.info("AI review skipped: no tables met review criteria.")
            return classifications

        token = (
            os.environ.get("COPILOT_API_KEY")
            or os.environ.get("GITHUB_TOKEN")
            or os.environ.get("GH_TOKEN")
        )
        if not token:
            raise RuntimeError(
                "Copilot API token missing. Set COPILOT_API_KEY, GITHUB_TOKEN, or GH_TOKEN."
            )

        prompt = self._build_prompt(to_review)
        raw_text = self._call_copilot(prompt, token)
        reviews = self._parse_response(raw_text)
        return self._apply_reviews(classifications, reviews)

    def _select_for_review(self, classifications: list[ClassificationResult]) -> list[ClassificationResult]:
        threshold = self._config.confidence_threshold
        if threshold <= 0:
            return classifications
        return [c for c in classifications if max(c.scores.values()) <= threshold]

    def _build_prompt(self, classifications: list[ClassificationResult]) -> str:
        payload = [
            {
                "table_name": c.table_name,
                "heuristic_category": c.category.value,
                "scores": c.scores,
            }
            for c in classifications
        ]
        return (
            "You are reviewing Oracle table classification results.\n"
            "For each table, either confirm the heuristic category or override it.\n"
            "Allowed categories: Transaction, Reference Data, Master Data, System Parameter, Unknown.\n"
            "Return STRICT JSON only using this schema:\n"
            "{"
            '"reviews":[{"table_name":"...", "confirmed":<boolean>, "override_category":"<allowed or null>"}]'
            "}\n"
            "Rules:\n"
            "- confirmed=true means keep heuristic category and override_category must be null.\n"
            "- confirmed=false means override_category must be one allowed category.\n"
            "- Include every provided table exactly once.\n\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _call_copilot(self, prompt: str, token: str) -> str:
        endpoint = os.environ.get("COPILOT_CHAT_COMPLETIONS_URL", self._DEFAULT_ENDPOINT)
        model = self._config.model or self._DEFAULT_MODEL
        body = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a strict JSON-only classifier reviewer."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                response_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Copilot API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Copilot API request failed: {exc}") from exc

        try:
            data = json.loads(response_body)
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Copilot API response: {response_body}") from exc

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        raw = text.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].lstrip(":").strip()
        return json.loads(raw)

    def _parse_response(self, raw_text: str) -> dict[str, dict[str, Any]]:
        payload = self._extract_json(raw_text)
        rows = payload.get("reviews", [])
        parsed: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            table_name = str(row.get("table_name", "")).strip()
            if not table_name:
                continue
            confirmed = bool(row.get("confirmed", False))
            override_raw = row.get("override_category")
            override = str(override_raw).strip() if override_raw is not None else None
            parsed[table_name] = {"confirmed": confirmed, "override": override}
        return parsed

    @staticmethod
    def _to_category(name: str | None) -> TableCategory | None:
        if not name:
            return None
        valid = {cat.value: cat for cat in TableCategory}
        return valid.get(name)

    def _apply_reviews(
        self,
        classifications: list[ClassificationResult],
        reviews: dict[str, dict[str, Any]],
    ) -> list[ClassificationResult]:
        out: list[ClassificationResult] = []
        for row in classifications:
            review = reviews.get(row.table_name)
            if not review:
                out.append(row)
                continue

            confirmed = bool(review.get("confirmed", False))
            override = self._to_category(review.get("override"))
            if confirmed:
                out.append(
                    ClassificationResult(
                        table_name=row.table_name,
                        category=row.category,
                        scores=row.scores,
                        ai_confirmed=True,
                        ai_override=None,
                    )
                )
                continue

            if override is None:
                out.append(row)
                continue

            out.append(
                ClassificationResult(
                    table_name=row.table_name,
                    category=row.category,
                    scores=row.scores,
                    ai_confirmed=False,
                    ai_override=override,
                )
            )
        return out
