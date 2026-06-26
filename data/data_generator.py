"""Generate Brunnstein's synthetic data and load it into DSQL.

Run as a script:
    uv run python -m data.data_generator
"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from data.erp.generators.customers import generate_customers
from data.erp.generators.goods_receipts import generate_goods_receipts
from data.erp.generators.plants import generate_plants
from data.erp.generators.production import generate_production
from data.erp.generators.products import generate_products
from data.erp.generators.purchase_orders import generate_purchase_orders
from data.erp.generators.raw_materials import generate_raw_materials
from data.erp.generators.sales import generate_sales
from data.erp.generators.supplier_invoices import generate_supplier_invoices
from data.erp.generators.suppliers import generate_suppliers
from data.erp.load_to_dsql import get_engine, load_table, strip_foreign_keys
from data.erp.models import Base
from data.hr.load import generate_hr, load_hr
from data.webshop.orders import (
    generate_online_orders,
    generate_webshop_customers,
)

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
    invoices = generate_supplier_invoices(grs, seed=seed)

    # Master data spine for the sales/production side (Phase 0).
    plants, lines = generate_plants()
    products, components = generate_products(materials)
    customers = generate_customers(seed=seed)

    # Sales and accounts-receivable document flow (Phase 2).
    sales_orders, deliveries, cust_invoices, payments = generate_sales(
        customers, products, plants, year_range=year_range, seed=seed
    )

    # Webshop B2C master data and online orders (Phase 3).
    webshop_customers = generate_webshop_customers(year_range=year_range, seed=seed)
    online_orders = generate_online_orders(
        webshop_customers, products, year_range=year_range, seed=seed
    )

    # Production, quality and maintenance (Phase 4). Driven by realised demand.
    production_runs, maintenance_orders = generate_production(
        products, lines, sales_orders, online_orders, year_range=year_range, seed=seed
    )

    # HR (separate source system, same plants). Org, people, time and payroll.
    hr = generate_hr(plants, lines, year_range=year_range, seed=seed)

    # Snapshot child counts before the session commits and the instances detach.
    n_po_lines = sum(len(p.lines) for p in pos)
    n_gr_lines = sum(len(g.lines) for g in grs)
    n_inv_lines = sum(len(i.lines) for i in invoices)
    n_so_lines = sum(len(o.lines) for o in sales_orders)
    n_dn_lines = sum(len(d.lines) for d in deliveries)
    n_ci_lines = sum(len(i.lines) for i in cust_invoices)
    n_oo_lines = sum(len(o.lines) for o in online_orders)
    n_quality_checks = sum(len(r.quality_checks) for r in production_runs)
    n_employments = sum(len(e.employments) for e in hr["employees"])
    n_payroll_items = sum(len(r.items) for r in hr["payroll_runs"])

    with Session(engine) as session:
        load_table(session, suppliers)
        load_table(session, materials)
        load_table(session, pos)  # cascades to purchase_order_line
        load_table(session, grs)  # cascades to goods_receipt_line
        load_table(session, invoices)  # cascades to supplier_invoice_line
        load_table(session, plants)
        load_table(session, lines)
        load_table(session, products)
        load_table(session, components)
        load_table(session, customers)
        load_table(session, sales_orders)  # cascades to sales_order_line
        load_table(session, deliveries)  # cascades to delivery_line
        load_table(session, cust_invoices)  # cascades to customer_invoice_line
        load_table(session, payments)
        load_table(session, webshop_customers)
        load_table(session, online_orders)  # cascades to online_order_line
        load_table(session, production_runs)  # cascades to quality_check
        load_table(session, maintenance_orders)
        load_hr(session, hr)
        session.commit()

    return {
        "url": str(engine.url),
        "suppliers": len(suppliers),
        "raw_materials": len(materials),
        "purchase_orders": len(pos),
        "purchase_order_lines": n_po_lines,
        "goods_receipts": len(grs),
        "goods_receipt_lines": n_gr_lines,
        "supplier_invoices": len(invoices),
        "supplier_invoice_lines": n_inv_lines,
        "plants": len(plants),
        "production_lines": len(lines),
        "products": len(products),
        "product_components": len(components),
        "customers": len(customers),
        "sales_orders": len(sales_orders),
        "sales_order_lines": n_so_lines,
        "deliveries": len(deliveries),
        "delivery_lines": n_dn_lines,
        "customer_invoices": len(cust_invoices),
        "customer_invoice_lines": n_ci_lines,
        "payments_received": len(payments),
        "webshop_customers": len(webshop_customers),
        "online_orders": len(online_orders),
        "online_order_lines": n_oo_lines,
        "production_runs": len(production_runs),
        "quality_checks": n_quality_checks,
        "maintenance_orders": len(maintenance_orders),
        "org_units": len(hr["org_units"]),
        "positions": len(hr["positions"]),
        "employees": len(hr["employees"]),
        "employments": n_employments,
        "absences": len(hr["absences"]),
        "payroll_runs": len(hr["payroll_runs"]),
        "payroll_items": n_payroll_items,
    }


if __name__ == "__main__":
    counts = main()
    print("loaded into", counts.pop("url"))
    for k, v in counts.items():
        print(f"  {k}: {v}")
