"""Text helpers shared across the entity generators."""

from __future__ import annotations

import re


def slugify_company_name(name: str) -> str:
    """Lowercase, German-umlaut-folded, dash-separated slug.

    Used for domain-style identifiers (email addresses, S3 keys) where the
    canonical supplier name needs an ASCII representation that's stable
    across runs.
    """
    s = name.lower()
    s = s.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s
