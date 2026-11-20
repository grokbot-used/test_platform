"""Normalize and hash case description/steps for review staleness.

Only description, preconditions, steps, and expected participate in the
fingerprint. Title, module, priority, client, and timestamps do not.
The same normalizer is used when writing a review and when comparing later.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

FINGERPRINT_FIELDS = ("description", "preconditions", "steps", "expected")
FINGERPRINT_PREFIX = "sha256:"

# Map CJK / typographic punctuation to a small ASCII set so "。" and "." match.
_PUNCT_MAP = str.maketrans({
    "。": ".",
    "．": ".",
    "﹒": ".",
    "。": ".",
    "，": ",",
    "、": ",",
    "﹐": ",",
    "；": ";",
    "﹔": ";",
    "：": ":",
    "﹕": ":",
    "？": "?",
    "！": "!",
    "“": '"',
    "”": '"',
    "„": '"',
    "«": '"',
    "»": '"',
    "「": '"',
    "」": '"',
    "『": '"',
    "』": '"',
    "‘": "'",
    "’": "'",
    "‚": "'",
    "′": "'",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "〔": "[",
    "〕": "]",
    "［": "[",
    "］": "]",
    "—": "-",
    "–": "-",
    "‑": "-",
    "－": "-",
    "─": "-",
    "━": "-",
    "—": "-",
    "…": ".",
    "⋯": ".",
    "·": ".",
    "•": ".",
    "　": " ",
})

# Punctuation class after mapping / NFKC. Spaces around these are dropped.
_PUNCT_CHARS = r".,;:?!\"'()\[\]\-"
_SPACE_BEFORE_PUNCT = re.compile(r"\s+(?=[" + _PUNCT_CHARS + r"])")
_SPACE_AFTER_PUNCT = re.compile(r"(?<=[" + _PUNCT_CHARS + r"])\s+")
_WHITESPACE = re.compile(r"\s+")


def normalize_case_text(value: str | None) -> str:
    """Collapse whitespace and treat equivalent punctuation as the same character."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("…", "...").replace("⋯", "...")
    text = text.translate(_PUNCT_MAP)
    text = unicodedata.normalize("NFKC", text)
    text = _SPACE_BEFORE_PUNCT.sub("", text)
    text = _SPACE_AFTER_PUNCT.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    return text.strip()


def case_content_payload(
    description: str | None = "",
    preconditions: str | None = "",
    steps: str | None = "",
    expected: str | None = "",
) -> str:
    parts = [
        normalize_case_text(description),
        normalize_case_text(preconditions),
        normalize_case_text(steps),
        normalize_case_text(expected),
    ]
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def case_content_fingerprint(
    description: str | None = "",
    preconditions: str | None = "",
    steps: str | None = "",
    expected: str | None = "",
) -> str:
    payload = case_content_payload(description, preconditions, steps, expected)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return FINGERPRINT_PREFIX + digest


def fingerprint_from_version(version) -> str:
    if version is None:
        return ""
    return case_content_fingerprint(
        description=getattr(version, "description", "") or "",
        preconditions=getattr(version, "preconditions", "") or "",
        steps=getattr(version, "steps", "") or "",
        expected=getattr(version, "expected", "") or "",
    )
