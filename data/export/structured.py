"""Export the full relational model to local Parquet + CSV (no database, no AWS).

The ERP, HR and CRM generators normally load straight into Aurora DSQL. This
module runs the same generators in-memory from the canonical seed, then flattens
every table to ``data/export/structured/parquet/<system>/<table>.parquet`` and a CSV
twin under ``data/export/structured/csv/``. The result is a self-contained data package
that can be handed to someone else for analytics / ML / GenAI use cases without
provisioning any AWS.

It also wires the three generators the DSQL loader does not yet run -- customer
returns + credit notes, the inventory ledger, and the GL journal -- so the
export is the complete 45-table model.

Run as a script:
    uv run python -m data.export.structured
"""

from __future__ import annotations

import enum
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import sqlalchemy as sa

from data.crm.load import generate_crm
from data.crm.models import Lead, Opportunity, SalesActivity
from data.erp.generators.customers import generate_customers
from data.erp.generators.gl import generate_gl
from data.erp.generators.goods_receipts import generate_goods_receipts
from data.erp.generators.inventory import generate_inventory
from data.erp.generators.plants import generate_plants
from data.erp.generators.production import generate_production
from data.erp.generators.products import generate_products
from data.erp.generators.purchase_orders import generate_purchase_orders
from data.erp.generators.raw_materials import generate_raw_materials
from data.erp.generators.returns import generate_returns
from data.erp.generators.sales import generate_sales
from data.erp.generators.supplier_invoices import generate_supplier_invoices
from data.erp.generators.suppliers import generate_suppliers
from data.erp.models import (
    CostCenter,
    CreditNote,
    Customer,
    CustomerInvoice,
    CustomerInvoiceLine,
    CustomerReturn,
    CustomerReturnLine,
    Delivery,
    DeliveryLine,
    GLAccount,
    GoodsReceipt,
    GoodsReceiptLine,
    JournalEntry,
    JournalEntryLine,
    MaintenanceOrder,
    OnlineOrder,
    OnlineOrderLine,
    PaymentReceived,
    Plant,
    Product,
    ProductComponent,
    ProductionLine,
    ProductionRun,
    PurchaseOrder,
    PurchaseOrderLine,
    QualityCheck,
    RawMaterial,
    SalesOrder,
    SalesOrderLine,
    StockLevel,
    StockMovement,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
    WebshopCustomer,
)
from data.hr.load import generate_hr
from data.hr.models import (
    Absence,
    Employee,
    Employment,
    OrgUnit,
    PayrollItem,
    PayrollRun,
    Position,
)
from data.webshop.orders import generate_online_orders, generate_webshop_customers

_ROOT = Path(__file__).resolve().parent / "structured"
_TODAY = date(2026, 1, 15)


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, enum.Enum):
        return str(value.value)
    return str(value)


def _arrow_array(column: sa.Column, values: list[Any]) -> pa.Array:
    """Build a typed Arrow array for one SQLAlchemy column, falling back to text."""
    col_type = column.type
    try:
        if isinstance(col_type, sa.Boolean):
            return pa.array([None if v is None else bool(v) for v in values], type=pa.bool_())
        # Float subclasses Numeric, so it has to be checked first.
        if isinstance(col_type, sa.Float):
            return pa.array([None if v is None else float(v) for v in values], type=pa.float64())
        if isinstance(col_type, sa.Numeric):
            precision, scale = col_type.precision, col_type.scale
            if precision is None or scale is None:
                return pa.array(
                    [None if v is None else float(v) for v in values], type=pa.float64()
                )
            quant = Decimal(1).scaleb(-scale)
            normalised = [None if v is None else Decimal(v).quantize(quant) for v in values]
            return pa.array(normalised, type=pa.decimal128(precision, scale))
        if isinstance(col_type, sa.Integer):  # covers BigInteger / SmallInteger
            return pa.array([None if v is None else int(v) for v in values], type=pa.int64())
        if isinstance(col_type, sa.DateTime):
            return pa.array(values, type=pa.timestamp("us"))
        if isinstance(col_type, sa.Date):
            return pa.array(values, type=pa.date32())
        # String, Text, Enum-as-VARCHAR, Uuid -> text.
        return pa.array([_to_str(v) for v in values], type=pa.string())
    except (pa.ArrowInvalid, pa.ArrowTypeError, ValueError, TypeError):
        return pa.array([_to_str(v) for v in values], type=pa.string())


def _table_for(model: type, instances: list[Any]) -> pa.Table:
    columns = {
        col.name: _arrow_array(col, [getattr(inst, col.name) for inst in instances])
        for col in model.__table__.columns
    }
    return pa.table(columns)


def _flatten(parents: list[Any], attr: str) -> list[Any]:
    return [child for parent in parents for child in getattr(parent, attr)]


def main(
    seed: int = 42,
    year_range: tuple[int, int] = (2023, 2025),
    out_dir: Path = _ROOT,
    formats: tuple[str, ...] = ("parquet", "csv"),
) -> dict[str, Any]:
    # --- Procurement (P2P) -------------------------------------------------
    suppliers = generate_suppliers(seed=seed)
    materials = generate_raw_materials(seed=seed)
    pos = generate_purchase_orders(suppliers, materials, year_range=year_range, seed=seed)
    grs = generate_goods_receipts(pos, seed=seed)
    supplier_invoices = generate_supplier_invoices(grs, seed=seed)

    # --- Master data -------------------------------------------------------
    plants, lines = generate_plants()
    products, components = generate_products(materials)
    customers = generate_customers(seed=seed)

    # --- Sales & accounts receivable (O2C) --------------------------------
    sales_orders, deliveries, cust_invoices, payments = generate_sales(
        customers, products, plants, year_range=year_range, seed=seed
    )

    # --- Webshop (B2C) -----------------------------------------------------
    webshop_customers = generate_webshop_customers(year_range=year_range, seed=seed)
    online_orders = generate_online_orders(
        webshop_customers, products, year_range=year_range, seed=seed
    )

    # --- Production, quality, maintenance ---------------------------------
    production_runs, maintenance_orders = generate_production(
        products, lines, sales_orders, online_orders, year_range=year_range, seed=seed
    )

    # --- HR (org, people, time, payroll) ----------------------------------
    hr = generate_hr(plants, lines, year_range=year_range, seed=seed)

    # --- CRM (pipeline) ----------------------------------------------------
    crm = generate_crm(customers, hr["employees"], year_range=year_range, seed=seed)

    # --- Returns + credit notes (not wired into the DSQL loader) ----------
    returns, credit_notes = generate_returns(
        cust_invoices, production_runs, today=_TODAY, seed=seed
    )

    # --- Inventory ledger + snapshot (not wired into the DSQL loader) -----
    movements, stock_levels = generate_inventory(
        grs,
        production_runs,
        deliveries,
        products,
        materials,
        components,
        plants,
        customer_returns=returns,
        today=_TODAY,
        seed=seed,
    )

    # --- General ledger (not wired into the DSQL loader) ------------------
    gl_accounts, cost_centers, journal_entries = generate_gl(
        cust_invoices,
        payments,
        supplier_invoices,
        hr["payroll_runs"],
        credit_notes,
        plants,
        today=_TODAY,
        seed=seed,
    )

    # (system, model, instances) for every table in the model.
    datasets: list[tuple[str, type, list[Any]]] = [
        ("erp", Supplier, suppliers),
        ("erp", RawMaterial, materials),
        ("erp", PurchaseOrder, pos),
        ("erp", PurchaseOrderLine, _flatten(pos, "lines")),
        ("erp", GoodsReceipt, grs),
        ("erp", GoodsReceiptLine, _flatten(grs, "lines")),
        ("erp", SupplierInvoice, supplier_invoices),
        ("erp", SupplierInvoiceLine, _flatten(supplier_invoices, "lines")),
        ("erp", Plant, plants),
        ("erp", ProductionLine, lines),
        ("erp", Product, products),
        ("erp", ProductComponent, components),
        ("erp", Customer, customers),
        ("erp", SalesOrder, sales_orders),
        ("erp", SalesOrderLine, _flatten(sales_orders, "lines")),
        ("erp", Delivery, deliveries),
        ("erp", DeliveryLine, _flatten(deliveries, "lines")),
        ("erp", CustomerInvoice, cust_invoices),
        ("erp", CustomerInvoiceLine, _flatten(cust_invoices, "lines")),
        ("erp", PaymentReceived, payments),
        ("erp", WebshopCustomer, webshop_customers),
        ("erp", OnlineOrder, online_orders),
        ("erp", OnlineOrderLine, _flatten(online_orders, "lines")),
        ("erp", ProductionRun, production_runs),
        ("erp", QualityCheck, _flatten(production_runs, "quality_checks")),
        ("erp", MaintenanceOrder, maintenance_orders),
        ("erp", CustomerReturn, returns),
        ("erp", CustomerReturnLine, _flatten(returns, "lines")),
        ("erp", CreditNote, credit_notes),
        ("erp", StockMovement, movements),
        ("erp", StockLevel, stock_levels),
        ("erp", CostCenter, cost_centers),
        ("erp", GLAccount, gl_accounts),
        ("erp", JournalEntry, journal_entries),
        ("erp", JournalEntryLine, _flatten(journal_entries, "lines")),
        ("hr", OrgUnit, hr["org_units"]),
        ("hr", Position, hr["positions"]),
        ("hr", Employee, hr["employees"]),
        ("hr", Employment, _flatten(hr["employees"], "employments")),
        ("hr", Absence, hr["absences"]),
        ("hr", PayrollRun, hr["payroll_runs"]),
        ("hr", PayrollItem, _flatten(hr["payroll_runs"], "items")),
        ("crm", Lead, crm["leads"]),
        ("crm", Opportunity, crm["opportunities"]),
        ("crm", SalesActivity, crm["activities"]),
    ]

    parquet_root = out_dir / "parquet"
    csv_root = out_dir / "csv"
    manifest: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for system, model, instances in datasets:
        name = model.__tablename__
        table = _table_for(model, instances)
        if "parquet" in formats:
            target = parquet_root / system / f"{name}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, target, compression="snappy")
        if "csv" in formats:
            target = csv_root / system / f"{name}.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            pacsv.write_csv(table, target)
        counts[f"{system}.{name}"] = table.num_rows
        manifest.append(
            {
                "system": system,
                "table": name,
                "rows": table.num_rows,
                "columns": [
                    {"name": col.name, "type": str(col.type)} for col in model.__table__.columns
                ],
            }
        )

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_data_dictionary(out_dir / "data_dictionary.md", manifest, formats)

    return counts


def _write_data_dictionary(
    path: Path, manifest: list[dict[str, Any]], formats: tuple[str, ...]
) -> None:
    """Emit a machine-generated table/column listing for the handoff package."""
    total_rows = sum(t["rows"] for t in manifest)
    lines = [
        "# Brunnstein Beverages -- structured data export",
        "",
        f"{len(manifest)} tables, {total_rows:,} rows total. "
        f"Formats: {', '.join(formats)}. Synthetic, deterministic (seed 42, 2023-2025).",
        "",
    ]
    for system in ("erp", "hr", "crm"):
        tables = [t for t in manifest if t["system"] == system]
        if not tables:
            continue
        lines.append(f"## {system.upper()}")
        lines.append("")
        lines.append("| table | rows | columns |")
        lines.append("|---|---:|---|")
        for t in tables:
            cols = ", ".join(c["name"] for c in t["columns"])
            lines.append(f"| {t['table']} | {t['rows']:,} | {cols} |")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    written = main()
    total = sum(written.values())
    for key, rows in written.items():
        print(f"  {key}: {rows}")
    print(f"total rows: {total}")
