"""Small shared helper for building text-heavy PDFs with reportlab Platypus.

The supplier-invoice generator draws on a low-level canvas; contracts and spec
sheets are flowing prose and tables, so they use Platypus instead. This module
centralises the document setup and a reusable stylesheet.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

_BRAND = colors.HexColor("#1f3a5f")


def styles() -> dict:
    """A small stylesheet shared across the document generators."""
    base = getSampleStyleSheet()
    out = {
        "title": ParagraphStyle(
            "BBTitle", parent=base["Title"], fontSize=18, textColor=_BRAND, spaceAfter=4
        ),
        "subtitle": ParagraphStyle(
            "BBSub", parent=base["Normal"], fontSize=9, textColor=colors.grey, spaceAfter=12
        ),
        "heading": ParagraphStyle(
            "BBHeading",
            parent=base["Heading2"],
            fontSize=11,
            textColor=_BRAND,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "BBBody", parent=base["Normal"], fontSize=9.5, leading=13, spaceAfter=4
        ),
        "small": ParagraphStyle(
            "BBSmall", parent=base["Normal"], fontSize=8, textColor=colors.grey
        ),
    }
    return out


def build(path: Path, story: list, title: str) -> Path:
    """Render a Platypus story to ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=title,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
    )
    doc.build(story)
    return path
