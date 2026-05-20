"""Generate Brunnstein's synthetic data and load it into DSQL.

Run as a script:
    uv run python -m data.data_generator
"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from data.generators.goods_receipts import generate_goods_receipts
from data.generators.purchase_orders import generate_purchase_orders
from data.generators.raw_materials import generate_raw_materials
from data.generators.supplier_invoices import generate_supplier_invoices
from data.generators.suppliers import generate_suppliers
from data.load_to_dsql import get_engine, load_table, strip_foreign_keys
from data.models import Base

load_dotenv()


def main(
    seed: int = 42,
    year_range: tuple[int, int] = (2023, 2025),
    reset: bool = True,
) -> dict[str, Any]:
    engine = get_engine()
    strip_foreign_keys(Base.metadata)

    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    suppliers = generate_suppliers(seed=seed)
    materials = generate_raw_materials(seed=seed)
    pos = generate_purchase_orders(suppliers, materials, year_range=year_range, seed=seed)
    grs = generate_goods_receipts(pos, seed=seed)
    documents, invoices = generate_supplier_invoices(grs, seed=seed)

    # Snapshot child counts before the session commits and the instances detach.
    n_po_lines = sum(len(p.lines) for p in pos)
    n_gr_lines = sum(len(g.lines) for g in grs)
    n_inv_lines = sum(len(i.lines) for i in invoices)

    with Session(engine) as session:
        load_table(session, suppliers)
        load_table(session, materials)
        load_table(session, pos)        # cascades to purchase_order_line
        load_table(session, grs)        # cascades to goods_receipt_line
        load_table(session, documents)
        load_table(session, invoices)   # cascades to supplier_invoice_line
        session.commit()

    return {
        "url": str(engine.url),
        "suppliers": len(suppliers),
        "raw_materials": len(materials),
        "purchase_orders": len(pos),
        "purchase_order_lines": n_po_lines,
        "goods_receipts": len(grs),
        "goods_receipt_lines": n_gr_lines,
        "documents": len(documents),
        "supplier_invoices": len(invoices),
        "supplier_invoice_lines": n_inv_lines,
    }


if __name__ == "__main__":
    counts = main()
    print("loaded into", counts.pop("url"))
    for k, v in counts.items():
        print(f"  {k}: {v}")
