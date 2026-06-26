"""Materialised outputs of the simulated sources (gitignored).

The source packages (erp, hr, crm, webshop, banking, retail, shopfloor) own the
generation logic. Their derived, file-shaped outputs land here, organised by
lake layer rather than by source:

    bronze/      raw, source-shaped landing files (the file-based feeds)
    structured/  the full relational model flattened to parquet + csv

Regenerate with ``data.export.lake`` and ``data.export.structured``.
"""

from __future__ import annotations

from pathlib import Path

EXPORT_ROOT = Path(__file__).resolve().parent
BRONZE_ROOT = EXPORT_ROOT / "bronze"
STRUCTURED_ROOT = EXPORT_ROOT / "structured"
